"""backend.arch.single_flight_fix — choose_fix (Lead): объединение одинаковых загрузок в асинхронном кэше.

Показан асинхронный кэш с TTL: при промахе каждый запрос сам вызывает загрузчик — при всплеске (холодный
кэш после выкладки) сотни одинаковых запросов идут в источник. Нужно выбрать замену метода чтения, которая
выполняет четыре требования: одна загрузка на ключ при любом числе ожидающих; разные ключи грузятся
параллельно; ошибка загрузки доходит до всех ожидающих и не запоминается; по истечении TTL — новая загрузка.

Варианты (большие фрагменты, каждый исполняется):
  * good — Future «в полёте» на ключ, удаляется в finally, ошибка — через set_exception;
  * global_lock — одна блокировка на все ключи с повторной проверкой: дубли убраны, но разные ключи
    грузятся по очереди;
  * no_double_check — блокировка на ключ без повторной проверки кэша после её получения: ожидающие
    по очереди грузят снова;
  * sticky_error — Future удаляется только при успехе: после ошибки ключ «залипает» в ошибке навсегда.
Состав дистракторов фиксирован. Ключ проверяется исполнением: asyncio-тест (однопоточный цикл событий —
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
    "global_lock": '''
    async def {meth}(self, {arg}):
        hit = self._data.get({arg})
        if hit and hit[1] > self.now:
            return hit[0]
        lock = self.__dict__.setdefault("_lock", asyncio.Lock())
        async with lock:
            hit = self._data.get({arg})
            if hit and hit[1] > self.now:
                return hit[0]
            value = await self._loader({arg})
            self._data[{arg}] = (value, self.now + self._ttl)
            return value
''',
    "no_double_check": '''
    async def {meth}(self, {arg}):
        hit = self._data.get({arg})
        if hit and hit[1] > self.now:
            return hit[0]
        lock = self._inflight.setdefault({arg}, asyncio.Lock())
        async with lock:
            value = await self._loader({arg})
            self._data[{arg}] = (value, self.now + self._ttl)
            return value
''',
    "sticky_error": '''
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
            except Exception as exc:
                fut.set_exception(exc)
            else:
                self._data[{arg}] = (value, self.now + self._ttl)
                fut.set_result(value)
                del self._inflight[{arg}]
        return await fut
''',
}

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
    names = {"_data": rng.choice(["_data", "_store", "_entries"]), "_inflight": rng.choice(["_inflight", "_loading"]),
             "hit": rng.choice(["hit", "entry", "cached"]), "fut": rng.choice(["fut", "waiter", "task"]),
             "value": rng.choice(["value", "val", "result"]), "exc": rng.choice(["exc", "err", "e"])}

    def ren(src: str) -> str:   # поверхностные имена; порядок обращений к rng не зависит от текста
        return re.sub(r"\b(_data|_inflight|hit|fut|value|exc)\b", lambda m: names[m.group(1)], src)

    head = ren(HEAD.format(**f))
    code = {k: dedent(head) + "\n" + ren(GET[k].format(**f)).rstrip() + "\n" for k in GET}
    test = TEST.format(cls=cls, meth=meth, ttl=ttl, n=n, k1=k1, k2=k2, k3=k3, k4=k4)
    chosen = ["global_lock", "no_double_check", "sticky_error"]
    opt_code = {k: dedent(ren(GET[k].format(**f))) for k in ["good"] + chosen}
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
    why = {"global_lock": "одна блокировка на все ключи убирает дубли, но разные ключи грузятся по очереди (требование 2)",
           "no_double_check": "после получения блокировки кэш не перепроверяется — ожидающие по очереди грузят снова "
                              "(требование 1)",
           "sticky_error": "загрузка «в полёте» удаляется только при успехе — после ошибки ключ навсегда отдаёт ту же "
                           "ошибку (требование 3)"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=("Верна загрузка «в полёте» на ключ: первый запрос создаёт Future и грузит, остальные "
                                "ждут тот же Future; результат или ошибка передаются всем, а запись о загрузке "
                                "удаляется в finally — ошибка не запоминается. Остальные: " +
                                "; ".join(why[d] for d in chosen) + "."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=code["buggy"], options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="cache_stampede",
                         language="python", params={"cls": cls, "meth": meth, "ttl": ttl, "n": n})
