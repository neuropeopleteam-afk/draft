"""backend.arch.lead_idempotency_fix — choose_fix (Lead у границы Lead/Principal, короткое): ключ идемпотентности.

Приём денежной операции с ключом идемпотентности. Принципы API даны без кода: повтор с тем же ключом в окне повторов
клиента не выполняет операцию второй раз и возвращает тот же ответ; тот же ключ с другим телом — ошибка, а не
чужой ответ; повтор, пришедший, пока первая попытка выполняется, операцию не выполняет. Показанный код нарушает все
три; кандидат выбирает замену функции, выполняющую все.

Правила (из пула выбираются два, варианты — схема 2×2: верный, нарушено первое, второе, оба):
* ``ttl`` — запись ключа хранится окно повторов (KEY_TTL_S), а не время отметки «выполняется» (LOCK_TTL_S);
* ``body`` — отпечаток тела сверяется при повторе;
* ``inflight`` — незавершённая попытка даёт конфликт, а не повторное выполнение.
У вариантов свои локальные имена. Ключ проверяется исполнением: каждая замена исполняется в составе модуля на
четырёх сценариях с подставными часами (повтор через много часов; другое тело; повтор во время выполнения; новый
ключ — новая операция).
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import module_choose_fix
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "backend.arch.lead_idempotency_fix"

CONTEXTS = [("списание с карты", "charge"), ("перевод между счетами", "transfer"), ("возврат покупки", "refund"),
            ("оплата заказа", "pay"), ("выплата продавцу", "payout"), ("пополнение кошелька", "top_up"),
            ("оплата штрафа", "pay_fine")]
FN_NAMES = ["handle_once", "idempotent_call", "accept_payment", "process_request", "run_once"]
LOCALS = {"ROW": ["row", "rec", "entry", "saved"], "RES": ["result", "res", "out", "resp"]}

MODULE = '''"""Приём денежных операций с ключом идемпотентности."""
import hashlib
import json

KEY_TTL_S = @TTL@          # сколько хранится ключ: окно повторов клиента
LOCK_TTL_S = @LOCK@             # сколько держится отметка «выполняется» у зависшей попытки


class Conflict(Exception):
    """Ключ уже использован с другим телом или запрос с этим ключом ещё выполняется."""


class Store:
    """Хранилище ключей: put_if_absent атомарен; записи старше ttl считаются отсутствующими."""

    def __init__(self, clock):
        self.clock, self.rows = clock, {}

    def get(self, key, ttl):
        row = self.rows.get(key)
        if row is None or self.clock.now() - row["at"] > ttl:
            return None
        return row

    def put_if_absent(self, key, row, ttl):
        if self.get(key, ttl) is not None:
            return False
        self.rows[key] = dict(row, at=self.clock.now())
        return True

    def update(self, key, **fields):
        self.rows[key].update(fields)


def fingerprint(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


{FN}
'''

CORRECT = '''def @FN@(store, key, body, @OP@):
    """Выполняет операцию не больше одного раза на ключ."""
    fp = fingerprint(body)
    if store.put_if_absent(key, {"fp": fp, "state": "running"}, KEY_TTL_S):
        @RES@ = @OP@(body)
        store.update(key, state="done", result=@RES@)
        return @RES@
    @ROW@ = store.get(key, KEY_TTL_S)
    if @ROW@["fp"] != fp:
        raise Conflict("ключ использован с другим телом")
    if @ROW@["state"] != "done":
        raise Conflict("запрос с этим ключом ещё выполняется")
    return @ROW@["result"]'''

RULES = {
    "ttl": ('"running"}, KEY_TTL_S):', '"running"}, LOCK_TTL_S):'),
    "body": ('    if @ROW@["fp"] != fp:', '    if @ROW@.get("fp") is None:'),
    "inflight": ('        raise Conflict("запрос с этим ключом ещё выполняется")',
                 '        return @OP@(body)'),
}
RULE_TEXT = {"ttl": "повтор с тем же ключом в окне повторов клиента не выполняет операцию второй раз",
             "body": "тот же ключ с другим телом — ошибка, а не чужой ответ",
             "inflight": "повтор, пришедший во время выполнения первой попытки, операцию не выполняет"}

TESTS = '''
class Clock:
    def __init__(self):
        self.t = 0
    def now(self):
        return self.t

# 1) повтор через много часов (в окне клиента) — тот же ответ без второго выполнения
clock = Clock()
store, done = Store(clock), []
def op(body):
    done.append(body)
    return {"id": len(done), "amount": body["amount"]}
r1 = @FN@(store, "k1", {"amount": 100}, op)
clock.t += @LATE@ * 3600
r2 = @FN@(store, "k1", {"amount": 100}, op)
assert r1 == r2 and len(done) == 1, ("повтор выполнен заново", len(done))

# 2) тот же ключ, другое тело — конфликт, операция не выполняется
try:
    @FN@(store, "k1", {"amount": 999}, op)
    raise AssertionError("чужой ответ на другое тело")
except Conflict:
    pass
assert len(done) == 1

# 3) повтор приходит, пока первая попытка выполняется
clock = Clock()
store, n, inner = Store(clock), [0], []
def slow(body):
    n[0] += 1
    if n[0] == 1:
        clock.t += 5
        try:
            inner.append(@FN@(store, "k2", body, slow))
        except Conflict:
            inner.append("conflict")
    return {"id": n[0]}
@FN@(store, "k2", {"amount": 5}, slow)
assert n[0] == 1 and inner == ["conflict"], ("операция выполнена дважды", n[0], inner)

# 4) новый ключ — новая операция
@FN@(store, "k3", {"amount": 5}, slow)
assert n[0] == 2
'''


def _render(tpl: str, fn: str, op: str, names: dict[str, str]) -> str:
    out = tpl.replace("@FN@", fn).replace("@OP@", op)
    for k, v in names.items():
        out = out.replace(f"@{k}@", v)
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, op = rng.choice(CONTEXTS)
    fn = rng.choice(FN_NAMES)
    win = rng.choice([24, 48, 72])
    late = win - rng.choice([2, 4, 6])
    lock = rng.choice([30, 60, 120])
    a, b = rng.sample(sorted(RULES), 2)

    def variant(broken):
        names = {k: rng.choice(v) for k, v in LOCALS.items()}
        tpl = CORRECT
        for r in broken:
            old, new = RULES[r]
            assert tpl.count(old) == 1, r
            tpl = tpl.replace(old, new)
        return _render(tpl, fn, op, names)

    correct = variant([])
    distractors = [variant([a]), variant([b]), variant([a, b])]
    buggy_tpl = CORRECT
    for r in RULES:
        buggy_tpl = buggy_tpl.replace(*RULES[r])
    buggy = _render(buggy_tpl, fn, op, {k: v[0] for k, v in LOCALS.items()})
    module = MODULE.replace("@TTL@", f"{win} * 3600").replace("@LOCK@", str(lock))
    tests = TESTS.replace("@FN@", fn).replace("@LATE@", str(late))
    hw = plural(win, "час", "часа", "часов")
    intro = rng.choice([
        f"Вы — ведущий инженер бэкенда. Операция «{ctx}» принимается с ключом идемпотентности, клиенты повторяют "
        f"запросы до {win} {hw}; приём делает функция `{fn}` (модуль ниже).",
        f"После двойных списаний в операции «{ctx}» вы как ведущий инженер бэкенда разбираете функцию `{fn}` "
        f"(модуль ниже); клиенты повторяют запросы до {win} {hw}.",
        f"Функция `{fn}` (модуль ниже) принимает операцию «{ctx}» с ключом идемпотентности; окно повторов клиентов — "
        f"{win} {hw}, и вы как ведущий инженер бэкенда утверждаете исправление.",
    ])
    principles = "; ".join(RULE_TEXT[r] for r in ("ttl", "body", "inflight"))
    stem = (f"{intro} Принципы API: {principles}.\n\nКакая замена функции `{fn}` выполняет все три принципа?")
    why = ("Верная замена: ключ записывается на окно повторов (KEY_TTL_S, а не время отметки LOCK_TTL_S), при "
           "повторе сверяется отпечаток тела, незавершённая попытка даёт конфликт. Дистракторы нарушают: "
           f"«{RULE_TEXT[a]}», «{RULE_TEXT[b]}» или оба.")
    return module_choose_fix(FAMILY_ID, seed, rng, stem=stem, module=module, buggy_fn=buggy, correct_fn=correct,
                             distractors=distractors, tests=tests, context=ctx, defect="idempotency", why=why,
                             label="Заменить функцию на:",
                             params={"rules": f"{a}+{b}", "fn": fn, "op": op, "win": win, "late": late,
                                     "lock": lock})
