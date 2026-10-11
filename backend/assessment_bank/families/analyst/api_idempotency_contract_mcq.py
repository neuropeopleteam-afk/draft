"""analyst.api.idempotency_contract_mcq — mcq_concept: какая серверная реализация ключа идемпотентности
выполняет требования контракта в показанных сценариях.

Контракт метода, создающего операцию (платёж, перевод, заказ…), требует заголовок с ключом идемпотентности.
Показаны три сценария из четырёх: повтор после таймаута, одновременный дубль (двойное нажатие), тот же ключ с
другим телом, повтор через несколько часов. Требования — только те, что проверяют показанные сценарии.
Варианты ответа — описания реализаций: блокировка ключа до операции с хэшем тела (24 ч или 10 мин), то же без
хэша, «проверить, затем сделать» без уникальности, «проверить, сделать, вставить с уникальностью»,
дедупликация по телу за 60 с без ключа. Верна ровно одна реализация (в зависимости от набора сценариев это
может быть и «неполная» — если показанные сценарии её недостаток не задевают). Ключ проверяется исполнением:
модель на Python проигрывает каждый сценарий по событиям во времени (приход запроса, конец операции через 3 с)
для каждой реализации и проверяет требования.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import balanced_options

FAMILY_ID = "analyst.api.idempotency_contract_mcq"

CTX = [("платёж", "POST /payments", "Idempotency-Key", "сумма"), ("перевод между счетами", "POST /transfers",
        "Idempotency-Key", "сумма перевода"), ("заказ", "POST /orders", "X-Request-Id", "состав заказа"),
       ("начисление бонусов", "POST /bonus-accruals", "Idempotency-Key", "число бонусов"),
       ("бронирование билета", "POST /tickets", "X-Idempotency-Key", "место"),
       ("выплата исполнителю", "POST /payouts", "Idempotency-Key", "сумма выплаты"),
       ("возврат денег", "POST /refunds", "X-Request-Id", "сумма возврата"),
       ("отправка заявки в банк", "POST /loan-requests", "Idempotency-Key", "сумма кредита")]

BEH = {"good": dict(kind="lock_first", ttl=86400, hash=True),
       "no_hash": dict(kind="lock_first", ttl=86400, hash=False),
       "short_ttl": dict(kind="lock_first", ttl=600, hash=True),
       "check_then_act": dict(kind="check_then_act", ttl=86400, hash=False),
       "check_unique": dict(kind="check_unique", ttl=86400, hash=False),
       "dedupe_body": dict(kind="dedupe_body", ttl=60, hash=False)}

DESC = {
    "good": ("До операции атомарно вставить запись «ключ, хэш тела, статус „в работе“» (ключ уникален). Ключ уже "
             "есть: хэш другой — 422; „в работе“ — 409; готово — сохранённый ответ. После операции сохранить "
             "ответ; ключи хранить 24 ч."),
    "no_hash": ("До операции атомарно вставить запись «ключ, статус „в работе“» (ключ уникален). Ключ уже есть: "
                "„в работе“ — 409; готово — сохранённый ответ. После операции сохранить ответ; ключи хранить "
                "24 ч."),
    "short_ttl": ("До операции атомарно вставить запись «ключ, хэш тела, статус „в работе“» (ключ уникален). Ключ "
                  "уже есть: хэш другой — 422; „в работе“ — 409; готово — сохранённый ответ. После операции "
                  "сохранить ответ; ключи хранить 10 мин."),
    "check_then_act": ("Найти ключ в таблице: есть — вернуть сохранённый ответ. Нет — провести операцию, затем "
                       "записать ключ и ответ (запись по ключу перезаписывается). Ключи хранить 24 ч."),
    "check_unique": ("Найти ключ в таблице: есть — вернуть сохранённый ответ. Нет — провести операцию, затем "
                     "вставить ключ и ответ (ключ уникален); вставка упала на уникальности — вернуть ответ, "
                     "сохранённый ранее. Ключи хранить 24 ч."),
    "dedupe_body": ("Ключ не использовать: если за последние 60 с уже была завершённая операция с тем же телом "
                    "от того же клиента — вернуть её ответ, иначе провести новую операцию.")}

SIM = r'''
D = 3.0

def run(beh, events):
    store, ops, out, queue = {}, [], {}, [(t, 0, i) for i, (t, k, b) in enumerate(events)]
    while queue:
        queue.sort()
        t, phase, i = queue.pop(0)
        _, key, body = events[i]
        kind = beh["kind"]
        if phase == 0:
            rec = store.get(key)
            if rec and t - rec["t"] > beh["ttl"]:
                rec = None
            if kind == "dedupe_body":
                prev = [o for o in ops if o[1] == body and t - o[0] <= 60]
                if prev:
                    out[i] = prev[-1][2]
                else:
                    queue.append((t + D, 1, i))
                continue
            if kind == "lock_first":
                if rec:
                    if beh["hash"] and rec["h"] != body:
                        out[i] = "422"
                    elif rec["status"] == "work":
                        out[i] = "409"
                    else:
                        out[i] = rec["resp"]
                    continue
                store[key] = dict(h=body, status="work", resp=None, t=t)
                queue.append((t + D, 1, i))
                continue
            if rec and rec["status"] == "done":
                out[i] = rec["resp"]
            else:
                queue.append((t + D, 1, i))
            continue
        resp = "op%d" % (len(ops) + 1)
        ops.append((t, body, resp))
        if kind == "lock_first":
            store[key].update(status="done", resp=resp)
            out[i] = resp
        elif kind == "check_unique":
            rec = store.get(key)
            if rec and t - rec["t"] <= beh["ttl"]:
                out[i] = rec["resp"]
            else:
                store[key] = dict(h=body, status="done", resp=resp, t=t)
                out[i] = resp
        elif kind == "check_then_act":
            store[key] = dict(h=body, status="done", resp=resp, t=t)
            out[i] = resp
        else:
            out[i] = resp
    return ops, out

def scenario_ok(beh, sc):
    name, delay = sc
    if name == "parallel":
        ops, out = run(beh, [(0.0, "K2", "A"), (0.5, "K2", "A")])
        return len(ops) == 1 and out[1] in ("409", "op1")
    if name == "other_body":
        ops, out = run(beh, [(0.0, "K1", "A"), (delay, "K1", "B")])
        return len(ops) == 1 and out[1] == "422"
    ops, out = run(beh, [(0.0, "K1", "A"), (delay, "K1", "A")])
    return len(ops) == 1 and out[1] == "op1"
'''

CHECK = r'''
hits = [k for k, b in OPTS.items() if all(scenario_ok(b, sc) for sc in SCENARIOS)]
print(hits[0] if len(hits) == 1 else "AMBIGUOUS")
'''

_ns: dict = {}
exec(compile(SIM, FAMILY_ID, "exec"), _ns)  # та же модель, что в проверке, — для подбора состава вариантов


def _sc_text(name, delay, ctx, header, what):
    if name == "timeout_retry":
        return (f"Запрос с ключом K1 обработан, но ответ до клиента не дошёл (таймаут); через {int(delay)} с "
                f"клиент повторяет запрос с тем же ключом K1 и тем же телом.")
    if name == "late_retry":
        return (f"Запрос с ключом K1 обработан, ответ потерян; клиент был без связи и повторяет запрос с K1 и тем "
                f"же телом через {int(delay // 3600)} ч.")
    if name == "parallel":
        return ("Пользователь дважды нажал кнопку: два запроса с одним ключом K2 и одинаковым телом пришли с "
                "разницей 0,5 с (операция занимает около 3 с).")
    return (f"Запрос с ключом K1 обработан; через {int(delay)} с из-за ошибки клиента пришёл запрос с тем же "
            f"ключом K1, но другим полем «{what}».")


REQ = {"timeout_retry": "повтор с тем же ключом и телом в течение 24 ч не проводит операцию второй раз и "
                        "возвращает исходный ответ",
       "late_retry": "повтор с тем же ключом и телом в течение 24 ч не проводит операцию второй раз и "
                     "возвращает исходный ответ",
       "parallel": "одновременный дубль с тем же ключом не проводит вторую операцию (допустим ответ 409 "
                   "«повторите позже»)",
       "other_body": "запрос с уже использованным ключом, но другим телом отклоняется с 422 без операции"}

WHY = {"good": "ключ занимается до операции (дубль получает 409), хэш тела ловит другое тело (422), 24 ч "
               "покрывают поздний повтор",
       "no_hash": "без хэша тела запрос с тем же ключом и другим телом получит старый ответ вместо 422",
       "short_ttl": "через 10 мин ключ удалён — поздний повтор проведёт операцию второй раз",
       "check_then_act": "два одновременных запроса оба не находят ключ и оба проводят операцию; другое тело "
                         "получает старый ответ вместо 422",
       "check_unique": "уникальность проверяется после операции — при одновременном дубле обе операции уже "
                       "проведены; другое тело получает старый ответ",
       "dedupe_body": "без ключа повтор позже 60 с проводит операцию второй раз, а другое тело считается новой "
                      "операцией"}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, endpoint, header, what = rng.choice(CTX)
    for _ in range(200):
        names = rng.sample(["timeout_retry", "late_retry", "parallel", "other_body"], 3)
        delays = {"timeout_retry": float(rng.choice([45, 90, 120, 300])),
                  "late_retry": float(rng.choice([2, 5, 8, 20]) * 3600),
                  "parallel": 0.5, "other_body": float(rng.choice([15, 40, 120]))}
        scs = [(n, delays[n]) for n in names]
        ok = {b: all(_ns["scenario_ok"](BEH[b], sc) for sc in scs) for b in BEH}
        passing = [b for b in BEH if ok[b]]
        failing = [b for b in BEH if not ok[b]]
        if passing and len(failing) >= 3:
            break
    else:
        raise RuntimeError("нет набора сценариев")
    alt = [b for b in passing if b != "good"]
    # верный ответ — не всегда «полная» реализация: так его нельзя узнать по тексту из другого варианта
    key_b = rng.choice(alt) if alt and rng.random() < 0.7 else rng.choice(passing)
    dist_b = rng.sample(failing, 3)
    opts, key = balanced_options(FAMILY_ID, seed, rng, (DESC[key_b], None), [(DESC[b], None) for b in dist_b])
    by_text = {DESC[b]: b for b in BEH}
    opt_beh = {o.id: BEH[by_text[o.text]] for o in opts}
    prog = SIM + f"OPTS = {opt_beh!r}\nSCENARIOS = {scs!r}\n" + CHECK
    checks = [Check(name="idempotency_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=key)]
    reqs = list(dict.fromkeys(REQ[n] for n in names))
    sc_list = "\n".join(f"{i}. {_sc_text(n, delays[n], ctx, header, what)}" for i, n in enumerate(names, 1))
    req_list = "; ".join(reqs)
    stem = (f"Метод `{endpoint}` создаёт операцию «{ctx}». Клиент передаёт заголовок `{header}` — ключ "
            f"идемпотентности, новый для каждой новой операции. Требования контракта: {req_list}. Сценарии, на "
            f"которых их проверяют:\n{sc_list}\n\nКакая реализация на сервере выполняет требования во всех "
            f"трёх сценариях?")
    expl = (f"Верно: {WHY[key_b]}" + (" (недостаток этой реализации показанные сценарии не задевают)"
                                      if key_b != "good" else "") +
            ". Остальные: " + "; ".join(WHY[b] for b in dist_b) + ".")
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note=("Ответ проверяется моделью на Python: каждый сценарий проигрывается "
                                            "по событиям во времени для каждой реализации."),
                         params={"scenarios": names, "key": key_b, "dist": dist_b,
                                 "delays": [delays[n] for n in names]})
