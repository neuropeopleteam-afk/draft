"""common.dist.fencing_token_bug — find_bug: fencing-токен не меняется при перехвате истёкшей аренды.

Сценарий из практики распределённых блокировок (аренда с TTL + fencing-токены): воркер A
взял аренду, ушёл в долгую паузу (GC, swap), аренда истекла, её взял воркер B и записал
данные; A проснулся и перезаписал данные B. Хранилище отклоняет запись с токеном меньше уже
виденного, но сервис аренды при выдаче аренды поверх истёкшей чужой переиспользует старый
токен (продление «по наличию записи», а не «тем же клиентом»), поэтому токены A и B равны.

Подтип дефекта один (урок калибровки 05.10: один подтип на семейство); варьируется только
поверхность — предметная область, имена, порядок классов, служебные строки, данные теста.
Дистракторы для внимания: строгое `<` в хранилище верно (тот же держатель пишет повторно),
проверка занятости аренды верна. Ключ проверяется исполнением: дефектный код пропускает
устаревшую запись, исправленный — отклоняет и сохраняет повторные записи держателя.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.dist.fencing_token_bug"

# (контекст, ресурс-пример, клиенты, имя сервиса, имя хранилища, метод выдачи, метод записи)
CONTEXTS = [
    ("планировщик ночных отчётов", ("report:2026-10", "report:weekly", "report:audit"),
     ("worker-a", "worker-b", "worker-c"), "LeaseService",
     "ReportStore", "acquire", "write"),
    ("обработка платёжных реестров", ("registry:117", "registry:204", "registry:outbound"),
     ("node-1", "node-2", "node-3"), "LockService",
     "LedgerStore", "grant", "put"),
    ("синхронизация каталога", ("catalog:shard-3", "catalog:shard-7", "catalog:prices"),
     ("sync-east", "sync-west", "sync-north"), "LeaseManager",
     "CatalogStore", "lock", "save"),
    ("пересчёт рейтингов", ("ratings:daily", "ratings:sellers", "ratings:reviews"),
     ("job-17", "job-18", "job-19"), "LeaseBroker",
     "RatingStore", "take", "store"),
]


def _lease(svc, acq, ttl_name, buggy: bool, doc: bool):
    reuse = ("        token = cur[2] if cur else next(self._seq)" if buggy else
             "        token = cur[2] if cur and cur[0] == client else next(self._seq)")
    lines = [f"class {svc}:"]
    if doc:
        lines.append('    """Аренда ресурса с TTL; каждый новый держатель получает больший токен."""')
    lines += [f"    def __init__(self, {ttl_name}):",
              f"        self.ttl = {ttl_name}",
              "        self.leases = {}  # resource -> (client, until, token)",
              "        self._seq = itertools.count(1)",
              "",
              f"    def {acq}(self, resource, client, now):",
              "        cur = self.leases.get(resource)",
              "        if cur and cur[1] > now and cur[0] != client:",
              "            return None",
              reuse,
              "        self.leases[resource] = (client, now + self.ttl, token)",
              "        return token",
              "",
              "    def release(self, resource, client):",
              "        cur = self.leases.get(resource)",
              "        if cur and cur[0] == client:",
              "            del self.leases[resource]"]
    return lines


def _store(st, wr, doc: bool):
    lines = [f"class {st}:"]
    if doc:
        lines.append('    """Хранилище отклоняет запись с токеном меньше уже виденного."""')
    lines += ["    def __init__(self):",
              "        self.data, self.max_token = {}, {}",
              "",
              f"    def {wr}(self, resource, value, token):",
              "        if token < self.max_token.get(resource, 0):",
              "            raise PermissionError('stale fencing token')",
              "        self.max_token[resource] = token",
              "        self.data[resource] = value"]
    return lines


def _code(c, buggy, order, docs, ttl_name):
    _, _, _, svc, st, acq, wr = c
    a, b = _lease(svc, acq, ttl_name, buggy, docs[0]), _store(st, wr, docs[1])
    parts = [a, b] if order == "lease_first" else [b, a]
    return "\n".join(["import itertools", "", ""] + parts[0] + ["", ""] + parts[1])


def _test(c, ttl, pause, res, ca, cb):
    _, _, _, svc, st, acq, wr = c
    return f"""
svc, st = {svc}({ttl}), {st}()
r = {res!r}
t1 = svc.{acq}(r, {ca!r}, now=0)
st.{wr}(r, 'from-a-1', t1)
assert svc.{acq}(r, {cb!r}, now={ttl - 1}) is None, 'действующая аренда должна блокировать'
t2 = svc.{acq}(r, {cb!r}, now={pause})
assert t2 is not None
st.{wr}(r, 'from-b-1', t2)
st.{wr}(r, 'from-b-2', t2)
try:
    st.{wr}(r, 'from-a-2', t1)
except PermissionError:
    pass
else:
    raise AssertionError('устаревший держатель перезаписал данные')
assert st.data[r] == 'from-b-2'
t3 = svc.{acq}(r, {cb!r}, now={pause + 1})
st.{wr}(r, 'from-b-3', t3)
svc.release(r, {cb!r})
t4 = svc.{acq}(r, {ca!r}, now={pause + 2})
st.{wr}(r, 'from-a-3', t4)
try:
    st.{wr}(r, 'from-b-4', t3)
except PermissionError:
    pass
else:
    raise AssertionError('после смены держателя принят старый токен')
assert st.data[r] == 'from-a-3'
"""


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    c = rng.choice(CONTEXTS)
    ctx, resources, clients, svc, st, acq, wr = c
    res = rng.choice(resources)
    ca, cb = rng.sample(clients, 2)
    order = rng.choice(["lease_first", "store_first"])
    docs = (rng.random() < 0.5, rng.random() < 0.5)
    ttl_name = rng.choice(["ttl", "ttl_s", "lease_s"])
    ttl = rng.choice([10, 15, 20, 30])
    pause = ttl + rng.randint(2, 25)
    buggy = _code(c, True, order, docs, ttl_name)
    fixed = _code(c, False, order, docs, ttl_name)
    diff = changed_lines(buggy, fixed)
    assert len(diff) == 1
    key_line = next(iter(diff))
    test = _test(c, ttl, pause, res, ca, cb)
    checks = [Check(name="buggy_fails", runner="python", program=py_harness(buggy, test), expect="fail"),
              Check(name="fixed_passes", runner="python", program=py_harness(fixed, test),
                    expect="pass", embeds_display_code=False)]
    stem = (f"Сервис «{ctx}»: несколько экземпляров обрабатывают ресурс `{res}`, взаимное "
            f"исключение — через аренду с TTL {ttl} с и fencing-токены: `{svc}.{acq}` выдаёт "
            f"токен, `{st}.{wr}` должен отклонять запись с токеном меньше уже виденного для "
            f"ресурса. Инцидент: `{ca}` взял аренду и записал данные, затем завис на {pause} с "
            f"(пауза сборщика мусора); аренду взял `{cb}` и записал свои данные; проснувшийся "
            f"`{ca}` записал ещё раз — и хранилище приняло запись, данные `{cb}` потеряны. "
            f"Время `now` передаётся в секундах. В коде ровно одна ошибка. Укажите номер строки.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=(f"Строка {key_line}: токен переиспользуется, если для ресурса есть "
                                f"запись аренды, даже истёкшая и чужая. `{cb}` получает тот же токен, "
                                f"что и `{ca}`, и проверка «токен меньше виденного» не отличает "
                                f"устаревшего держателя. Новый токен нужен при каждой выдаче новому "
                                f"клиенту (продление тем же клиентом может сохранить токен). Строгое "
                                f"«<» в хранилище верно: держатель вправе писать повторно."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="fencing_token_reuse",
                         params={"fixed_code": fixed, "order": order, "ttl": ttl, "pause": pause})
