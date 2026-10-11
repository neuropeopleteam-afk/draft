"""backend.arch.single_flight_fix — choose_fix (Lead): объединение одинаковых загрузок в асинхронном кэше.

Показан асинхронный кэш с TTL: при промахе каждый запрос сам вызывает загрузчик — при всплеске (холодный
кэш после выкладки) сотни одинаковых запросов идут в источник. Нужно выбрать замену метода чтения, которая
выполняет четыре требования: одна загрузка на ключ при любом числе ожидающих; разные ключи грузятся
параллельно; ошибка загрузки доходит до всех ожидающих и не запоминается; по истечении TTL — новая загрузка.

Варианты (каждый исполняется) построены по схеме 2×2 от верного (Future «в полёте» на ключ, удаляется в
finally, ошибка — через set_exception): из пула правил выбираются два (a, b), варианты — верный, нарушено a,
нарушено b, нарушены оба. Пул:
  * sticky_error — запись «в полёте» удаляется только при успехе (else вместо finally): после ошибки ключ
    «залипает» в ошибке;
  * cache_error — ошибка кэшируется на TTL как значение: следующий запрос не пробует снова и получает объект
    исключения;
  * register_late — Future регистрируется «в полёте» только после загрузки: одновременные запросы его не видят
    и грузят каждый сам.
Каждый вариант отличается от двух других на одно правило и от третьего — на два; у каждого варианта свои
локальные имена и необязательный комментарий, поэтому ни длина, ни сходство вариантов не выдают ключ.
Ключ проверяется исполнением: asyncio-тест (однопоточный цикл событий —
детерминированный порядок) на показанном коде (падает) и на каждом варианте.
"""
from __future__ import annotations

import re

from assessment_bank.gen_utils import build_variant, dedent, make_options, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.arch.single_flight_fix"

CONTEXTS = [
    ("курсы валют", "RatesCache", "currency"),
    ("профили кандидатов", "ProfileCache", "user_id"),
    ("тарифы доставки", "TariffCache", "zone"),
    ("права доступа", "AclCache", "subject"),
    ("карточки товаров", "ProductCache", "sku"),
    ("расписание врачей", "ScheduleCache", "doctor_id"),
]

HEAD = '''import asyncio


class {cls}:
    def __init__(self, loader, ttl):
        self._loader = loader          # async def loader({arg}) -> значение
        self._ttl = ttl
        self._data = {{}}                # {arg} -> (значение, истекает_в)
        self._inflight = {{}}            # {arg} -> загрузка «в полёте»
        self.now = 0.0                 # текущее время (подставляется снаружи)
'''

GET = {
    "buggy": '''
    async def {meth}(self, {arg}):
        hit = self._data.get({arg})
        if hit and hit[1] > self.now:
            return hit[0]
        value = await self._loader({arg})
        self._data[{arg}] = (value, self.now + self._ttl)
        return value
''',
    "good": '''
    async def {meth}(self, {arg}):
        hit = self._data.get({arg})
        if hit and hit[1] > self.now:
            return hit[0]
        fut = self._inflight.get({arg})
        if fut is None:
            fut = asyncio.get_running_loop().create_future()
            self._inflight[{arg}] = fut
            try:
                value = await self._loader({arg})
                self._data[{arg}] = (value, self.now + self._ttl)
                fut.set_result(value)
            except Exception as exc:
                fut.set_exception(exc)
            finally:
                del self._inflight[{arg}]
        return await fut
''',
}

# правило -> (фрагмент верного шаблона, замена); фрагменты разных правил не пересекаются
MUTATIONS = {
    "sticky_error": ("            finally:\n                del self._inflight[{arg}]\n",
                     "            else:\n                del self._inflight[{arg}]\n"),
    "cache_error": ("                fut.set_exception(exc)\n",
                    "                self._data[{arg}] = (exc, self.now + self._ttl)\n                fut.set_exception(exc)\n"),
    "register_late": ("            self._inflight[{arg}] = fut\n            try:\n                value = await self._loader({arg})\n",
                      "            try:\n                value = await self._loader({arg})\n                self._inflight[{arg}] = fut\n"),
}
PAIRS = [("sticky_error", "cache_error"), ("sticky_error", "register_late"), ("cache_error", "register_late")]
WHY = {"sticky_error": "запись «в полёте» удаляется только при успехе — после ошибки ключ навсегда отдаёт ту же ошибку "
                       "(требование 3)",
       "cache_error": "ошибка кэшируется на TTL как значение — следующий запрос не пробует снова и получает объект "
                      "исключения (требование 3)",
       "register_late": "Future попадает в «в полёте» только после загрузки — одновременные запросы его не видят и "
                        "грузят каждый сам (требование 1)"}
NOTES = ["# одна загрузка на ключ, остальные ждут её результат", "# промах: грузим один раз, остальные ждут",
         "# холодный кэш: защищаем источник от дублей"]

TEST = '''
import asyncio as _aio
calls, active, peak = [], [0], [0]

async def loader(k):
    calls.append(k)
    active[0] += 1
    peak[0] = max(peak[0], active[0])
    await _aio.sleep(0)
    await _aio.sleep(0)
    active[0] -= 1
    if str(k).startswith("bad"):
        raise ValueError(k)
    return f"v:{{k}}"

async def scenario():
    c = {cls}(loader, ttl={ttl})
    got = await _aio.gather(*[c.{meth}("{k1}") for _ in range({n})])
    assert got == ["v:{k1}"] * {n}, "значения"
    assert calls.count("{k1}") == 1, "одна загрузка на ключ"
    peak[0] = 0
    await _aio.gather(c.{meth}("{k2}"), c.{meth}("{k3}"), c.{meth}("{k4}"))
    assert peak[0] >= 2, "разные ключи грузятся параллельно"
    res = await _aio.gather(*[c.{meth}("bad{k1}") for _ in range(5)], return_exceptions=True)
    assert all(isinstance(e, ValueError) for e in res), "ошибка доходит до всех"
    assert calls.count("bad{k1}") == 1, "одна загрузка и при ошибке"
    await _aio.gather(c.{meth}("bad{k1}"), return_exceptions=True)
    assert calls.count("bad{k1}") == 2, "ошибка не запоминается"
    c.now = {ttl} + 1
    assert await c.{meth}("{k1}") == "v:{k1}" and calls.count("{k1}") == 2, "TTL"

_aio.run(scenario())
'''

KEYS = {"currency": ["USD", "EUR", "CNY", "TRY"], "user_id": ["u17", "u23", "u42", "u58"],
        "zone": ["msk", "spb", "kzn", "ekb"], "subject": ["alice", "bob", "carol", "dave"],
        "sku": ["A100", "B200", "C300", "D400"], "doctor_id": ["d7", "d8", "d9", "d11"]}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, cls, arg = rng.choice(CONTEXTS)
    meth = rng.choice(["get", "fetch", "get_or_load"])
    ttl = rng.choice([30, 60, 300, 600])
    n = rng.choice([20, 50, 100])
    keys = list(KEYS[arg])
    rng.shuffle(keys)
    k1, k2, k3, k4 = keys
    f = dict(cls=cls, arg=arg, meth=meth)
    a, b = rng.choice(PAIRS)
    sets = {"good": [], a: [a], b: [b], f"{a}+{b}": [a, b]}
    note = rng.choice(NOTES)
    head_names = {"_data": rng.choice(["_data", "_store", "_entries"]), "_inflight": rng.choice(["_inflight", "_loading"])}
    fields = lambda src: re.sub(r"\b(_data|_inflight)\b", lambda m: head_names[m.group(1)], src)  # noqa: E731
    head = fields(HEAD.format(**f))
    code = {"buggy": dedent(head) + "\n" + fields(GET["buggy"].format(**f)).rstrip() + "\n"}
    opt_code = {}
    # у каждого варианта — свои локальные имена и необязательный комментарий; порядок обращений к rng не зависит
    # от текста
    for k, muts in sets.items():
        tpl = GET["good"]
        for mname in muts:
            old, new = MUTATIONS[mname]
            if tpl.count(old) != 1:
                raise ValueError(f"фрагмент правила {mname} не найден ровно один раз")
            tpl = tpl.replace(old, new)
        names = {"hit": rng.choice(["hit", "entry", "cached"]), "fut": rng.choice(["fut", "waiter", "pending"]),
                 "value": rng.choice(["value", "val", "result"]), "exc": rng.choice(["exc", "err", "e"])}
        add_note = rng.random() < 0.5
        src = re.sub(r"\b(hit|fut|value|exc)\b", lambda m: names[m.group(1)], fields(tpl.format(**f)))
        if add_note:
            src = src.replace("        if " + names["fut"] + " is None:\n",
                              "        " + note + "\n        if " + names["fut"] + " is None:\n", 1)
        opt_code[k] = dedent(src).strip() + "\n"
        code[k] = dedent(head) + "\n" + src.rstrip() + "\n"
    if len(set(opt_code.values())) != 4:
        raise ValueError("варианты 2×2 совпадают")
    test = TEST.format(cls=cls, meth=meth, ttl=ttl, n=n, k1=k1, k2=k2, k3=k3, k4=k4)
    chosen = [a, b, f"{a}+{b}"]
    opts, key = make_options(rng, ("Заменить метод на:", opt_code["good"]),
                             [("Заменить метод на:", opt_code[d]) for d in chosen])
    by_code = {c: k for k, c in opt_code.items()}
    checks = [Check(name="buggy_fails", runner="python", program=py_harness(code["buggy"], test), expect="fail")]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="python",
                            program=py_harness(code[by_code[o.code]], test), embeds_display_code=False,
                            expect="pass" if o.id == key else "fail"))
    lead = rng.choice([
        f"Кэш «{ctx}» (класс `{cls}`) стоит перед медленным источником. После выкладки кэш пуст, и при всплеске "
        f"{n} одновременных запросов одного ключа каждый вызывает загрузчик — источник ложится.",
        f"Источник данных «{ctx}» медленный, перед ним — асинхронный кэш `{cls}`. Разбор инцидента: после "
        f"выкладки кэш был пуст, {n} одновременных запросов одного ключа вызвали {n} загрузок, и источник упал.",
        f"`{cls}` кэширует «{ctx}» с TTL. Под нагрузкой с холодным кэшем каждый из {n} одновременных запросов "
        f"одного ключа сам идёт в источник — нагрузка на него растёт в {n} раз."])
    stem = (f"{lead} "
            f"Нужна замена метода `{meth}`, при которой: (1) при промахе загрузчик вызывается один раз на ключ, "
            f"сколько бы запросов ни ждали; (2) разные ключи грузятся параллельно; (3) ошибка загрузки доходит до "
            f"всех ожидающих и не запоминается — следующий запрос пробует снова; (4) по истечении TTL ({ttl} с) "
            f"значение загружается заново. Какая замена выполняет все четыре требования?")
    ak = AnswerKey(kind="option", value=key,
                   explanation=("Верна загрузка «в полёте» на ключ: первый запрос создаёт Future и грузит, остальные "
                                "ждут тот же Future; результат или ошибка передаются всем, а запись о загрузке "
                                "удаляется в finally — ошибка не запоминается. Остальные нарушают правила: " +
                                f"{WHY[a]}; {WHY[b]}; третий вариант нарушает оба."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=code["buggy"], options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="cache_stampede",
                         language="python", params={"cls": cls, "meth": meth, "ttl": ttl, "n": n,
                                                    "distractors": chosen})
