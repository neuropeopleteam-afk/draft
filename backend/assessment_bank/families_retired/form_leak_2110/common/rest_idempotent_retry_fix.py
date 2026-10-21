"""common.api.rest_idempotent_retry_fix — choose_fix (Senior/Lead, REST API): повтор POST с ключом идемпотентности.

Клиент создаёт платёж POST-запросом и при таймауте повторяет его. Сервер поддерживает заголовок Idempotency-Key:
повтор с тем же ключом возвращает сохранённый ответ, а не создаёт новый платёж. Показанный код генерирует новый ключ
на каждую попытку — при таймауте после фактической обработки создаётся второй платёж. Верно: один ключ на
логическую операцию, повторы — с ним. Неверные: повтор только на 5xx (таймаут не повторяется — операция не
завершена), ключ из суммы и времени попытки, повтор без ключа. Проверка — исполнением: тестовый сервер
обрабатывает запрос и «теряет» ответ на первых попытках; печатается число платежей и итог клиента.
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import codefix_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "common.api.rest_idempotent_retry_fix"
SCEN = [("create_payment", "платёж", "amount", "payments"), ("create_order", "заказ", "total", "orders"),
        ("create_transfer", "перевод", "sum", "transfers"), ("create_refund", "возврат", "amount", "refunds"),
        ("create_booking", "бронь", "price", "bookings"), ("create_invoice", "счёт", "amount", "invoices"),
        ("create_payout", "выплату", "amount", "payouts"), ("create_subscription", "подписку", "plan_price", "subscriptions")]
EXC = ["Timeout", "ReadTimeout", "GatewayTimeout", "UpstreamTimeout"]
KEYV = ["key", "idem_key", "op_key", "request_key"]
RESV = ["resp", "result", "answer", "reply"]
SRC = ["mobile", "web", "partner-api", "backoffice"]

SERVER = '''import itertools

class {exc}(Exception):
    pass

class FakeServer:
    """POST /{res}: обрабатывает запрос, но ответ на первых {lost} попытках теряется (таймаут у клиента)."""
    def __init__(self, lost):
        self.lost, self.calls, self.created, self.saved = lost, 0, [], {{}}
        self.ids = itertools.count(1)

    def post(self, path, body, headers):
        self.calls += 1
        key = headers.get("Idempotency-Key")
        if key is not None and key in self.saved:
            resp = self.saved[key]
        else:
            resp = {{"status": 201, "id": next(self.ids)}}
            self.created.append(body)
            if key is not None:
                self.saved[key] = resp
        if self.calls <= self.lost:
            raise {exc}()
        return resp

_counter = itertools.count(1)
log = []

def new_key():
    return f"k-{{next(_counter)}}"
'''

TEST = '''
srv = FakeServer(lost={lost})
res = {fn}(srv, {{"{field}": {amount}, "currency": "{cur}"}}, attempts={attempts})
print(len(srv.created), res)
'''


TAILS = ["    return None\n", "    return None  # попытки исчерпаны\n", "    return None  # ответа так и не было\n",
         "    log.append(\"no response\")\n    return None\n"]


def _body(kind, exc, kv, rv, path, src, loop, tail="    return None\n"):
    hdr = lambda k: f'{{"Idempotency-Key": {k}, "X-Source": "{src}"}}' if k else f'{{"X-Source": "{src}"}}'
    pre, key_expr = "", None
    if kind in ("good", "only_5xx"):
        pre, key_expr = f"    {kv} = new_key()\n", kv
    elif kind == "buggy":
        key_expr = "new_key()"
    elif kind in ("key_from_attempt", "attempt_no_retry"):
        key_expr = f'f"{{payload}}-{{i}}"'
    head = "    for i in range(attempts):\n" if loop == "for" else "    i = 0\n    while i < attempts:\n"
    step = "" if loop == "for" else "        i += 1\n"
    call = f'server.post("/{path}", payload, {hdr(key_expr)})'
    if kind in ("only_5xx", "attempt_no_retry"):
        inner = (f"        try:\n            {rv} = {call}\n        except {exc}:\n            return None\n{step}"
                 f"        if {rv}[\"status\"] < 500:\n            return {rv}\n")
    else:
        inner = (f"{step}        try:\n            {rv} = {call}\n        except {exc}:\n            continue\n"
                 f"        return {rv}\n")
    return pre + head + inner + tail


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    fn, what, field, path = SCEN[seed % len(SCEN)]
    exc, kv, rv, src = rng.choice(EXC), rng.choice(KEYV), rng.choice(RESV), rng.choice(SRC)
    loop = rng.choice(["for", "while"])
    lost = rng.choice([1, 2])
    attempts = lost + rng.choice([1, 2])
    amount = rng.choice([990, 1500, 2490, 5000, 12000])
    cur = rng.choice(["RUB", "KZT", "BYN"])
    kinds = ["buggy", "good", "only_5xx", "key_from_attempt", "attempt_no_retry"]
    code = {k: f"def {fn}(server, payload, attempts):\n" + _body(k, exc, kv, rv, path, src, loop, rng.choice(TAILS))
            for k in kinds}
    # 2×2: ключ на операцию / на попытку × повтор на таймауте / отказ — все варианты одинаково «центральны»
    wrong_names = rng.sample(["only_5xx", "key_from_attempt", "attempt_no_retry"], 3)
    pre = SERVER.format(res=path, lost=lost, exc=exc)
    test = TEST.format(lost=lost, fn=fn, field=field, amount=amount, attempts=attempts, cur=cur)

    def harness(c):
        return pre + "\n" + c + "\n" + test
    lead = rng.choice([
        f"Мобильный клиент создаёт {what} запросом `POST /{path}` и при таймауте (`{exc}`) повторяет его до `attempts` раз.",
        f"Сервис-оркестратор создаёт {what} через `POST /{path}` партнёрского API; при `{exc}` вызов повторяется до `attempts` раз.",
        f"Клиентская библиотека отправляет `POST /{path}` (создать {what}) и на `{exc}` делает повтор, всего до `attempts` попыток."])
    tail = rng.choice([
        "В инциденте ответ сервера терялся по таймауту, хотя запрос был обработан, — у части клиентов появились дубли.",
        "После сетевого сбоя поддержка нашла двойные списания: сервер успевал обработать запрос, а ответ до клиента не доходил.",
        "На нагрузочном тесте с потерей ответов число созданных объектов оказалось больше числа операций."])
    stem = (f"{lead} Сервер поддерживает заголовок `Idempotency-Key`: повтор с уже виденным ключом возвращает "
            f"сохранённый ответ и ничего не создаёт. {tail} `new_key()` возвращает новый уникальный ключ. "
            f"Какая замена функции `{fn}` верна?")
    expl = ("Ключ идемпотентности относится к логической операции, а не к попытке: его создают один раз и повторяют "
            "с ним — сервер вернёт сохранённый ответ, второй объект не появится. Ключ из номера попытки разный у "
            "попыток — дубли, как и в показанном коде; отказ от повтора на таймауте оставляет клиента без ответа, "
            "хотя объект создан.")
    return codefix_variant(FAMILY_ID, seed, rng, ctx=what, stem=stem, runner="python", buggy=code["buggy"],
                           good=code["good"], wrongs=[(n, code[n]) for n in wrong_names], label=f"Заменить {fn} на:",
                           harness=harness, explanation=expl, defect_type="idempotency",
                           params={"lost": lost, "attempts": attempts, "fn": fn, "loop": loop, "exc": exc},
                           language="python")
