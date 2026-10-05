"""backend.api.idempotency_key_fix — choose_fix: заголовок Idempotency-Key в POST-эндпоинте.

Код с дефектом хранит ответ по «голому» ключу и не сравнивает тело запроса. Требования:
повтор с тем же ключом и телом — сохранённый ответ без повторного действия; тот же ключ с
другим телом — 422; ключи разных клиентов независимы; если действие упало, ключ не
«сгорает»; тело сравнивается по содержанию (порядок полей JSON не важен). Дистракторы
(одинаковой формы) нарушают ровно одно требование.
"""
from __future__ import annotations

from assessment_bank.gen_utils import (build_variant, dedent, indent, make_options, make_rng,
                                       py_harness)
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.api.idempotency_key_fix"

CONTEXTS = [("create_payment", "charge", "payment_id", "POST /payments", "платёжный шлюз", "списание"),
            ("create_transfer", "send_money", "transfer_id", "POST /transfers", "онлайн-банк", "перевод"),
            ("place_order", "reserve_goods", "order_id", "POST /orders", "интернет-магазин",
             "резервирование товара"),
            ("create_refund", "refund", "refund_id", "POST /refunds", "маркетплейс", "возврат денег"),
            ("issue_invoice", "bill", "invoice_id", "POST /invoices", "B2B-биллинг", "выставление счёта")]

def _option(kind: str, fn: str, act: str, n: dict) -> str:
    st, fp, cl = n["store"], n["fp"], n["client"]
    key = f"key = idem_key" if kind == "global_key" else f"key = ({cl}, idem_key)"
    fpl = {"unsorted": f"{fp} = json.dumps(body)",
           "frozenset_hash": f"{fp} = hash(frozenset(body.items()))"}.get(
        kind, f"{fp} = json.dumps(body, sort_keys=True)")
    lines = ["import json", "", f"{st} = {{}}", "", "",
             f"def {fn}({cl}: str, idem_key: str, body: dict, {act}) -> tuple:",
             f"    {key}", f"    {fpl}", f"    if key in {st}:",
             f"        stored, response = {st}[key]", f"        if stored != {fp}:",
             f'            return 422, {{"error": "{n["err"]}"}}', "        return response"]
    if kind == "reserve_first":
        lines += [f'    {st}[key] = {fp}, (409, {{"error": "in_progress"}})',
                  f"    {st}[key] = {fp}, (201, {act}(body))", f"    return {st}[key][1]"]
    else:
        lines += [f"    response = 201, {act}(body)", f"    {st}[key] = {fp}, response",
                  "    return response"]
    return "\n".join(lines)


def _buggy(fn: str, act: str, n: dict) -> str:
    st, cl = n["store"], n["client"]
    return dedent(f'''
        import json

        {st} = {{}}


        def {fn}({cl}: str, idem_key: str, body: dict, {act}) -> tuple:
            """Idempotency-Key: повтор запроса возвращает сохранённый ответ."""
            if idem_key in {st}:
                return {st}[idem_key]
            response = 201, {act}(body)
            {st}[idem_key] = response
            return response''')


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    fn, act, rid, route, ctx, what = rng.choice(CONTEXTS)
    chosen = rng.sample(["global_key", "unsorted", "frozenset_hash", "reserve_first"], 3)
    n = dict(store=rng.choice(["saved", "responses", "idem_store", "replies"]),
             fp=rng.choice(["fingerprint", "body_hash", "digest", "signature"]),
             client=rng.choice(["client_id", "merchant_id", "account_id", "tenant_id"]),
             err=rng.choice(["idempotency_key_reused", "key_conflict", "body_mismatch"]))
    c1, c2 = rng.sample(["shop-17", "shop-42", "app-3", "crm-8", "bot-11", "pos-5"], 2)
    k1, k2 = rng.sample(["a1f3", "7c2e", "e9b0", "51d4", "0f8a", "c6d7"], 2)
    amt = [rng.randint(1, 90) * 100 for _ in range(3)]
    ref = rng.sample(["o-12", "o-77", "o-305", "o-918"], 3)
    b1 = {"amount": amt[0], "currency": "RUB", "meta": {"ref": ref[0]}}
    b1r = {"meta": {"ref": ref[0]}, "currency": "RUB", "amount": amt[0]}
    b2 = {"amount": amt[1], "currency": "RUB", "meta": {"ref": ref[1]}}
    b3 = {"amount": amt[2], "currency": "RUB", "meta": {"ref": ref[2]}}
    changed = {**b1, "amount": amt[0] + 100}
    r = lambda n, a: (201, {rid: f"p{n}", "amount": a})
    tests = dedent(f"""
        calls = []
        def ok(body):
            calls.append(body["amount"])
            return {{{rid!r}: f"p{{len(calls)}}", "amount": body["amount"]}}
        def flaky(body):
            raise TimeoutError("upstream")
        assert {fn}({c1!r}, {k1!r}, {b1!r}, ok) == {r(1, amt[0])!r}
        assert {fn}({c1!r}, {k1!r}, {b1r!r}, ok) == {r(1, amt[0])!r} and len(calls) == 1
        assert {fn}({c1!r}, {k1!r}, {changed!r}, ok)[0] == 422 and len(calls) == 1
        assert {fn}({c2!r}, {k1!r}, {b2!r}, ok) == {r(2, amt[1])!r}
        try:
            {fn}({c1!r}, {k2!r}, {b3!r}, flaky)
            raise AssertionError("ожидался TimeoutError")
        except TimeoutError:
            pass
        assert {fn}({c1!r}, {k2!r}, {b3!r}, ok) == {r(3, amt[2])!r} and len(calls) == 3
        """)
    code = _buggy(fn, act, n)
    opts, key = make_options(rng, ("Заменить обработчик на:", _option("good", fn, act, n)),
                             [("Заменить обработчик на:", _option(k, fn, act, n)) for k in chosen])
    checks = [Check(name=f"option:{o.id}", runner="python", program=py_harness(o.code, tests),
                    expect="pass" if o.id == key else "fail", embeds_display_code=False)
              for o in opts]
    checks.append(Check(name="buggy_fails", runner="python", program=py_harness(code, tests),
                        expect="fail"))
    stem = (f"Эндпоинт `{route}` ({ctx}) принимает заголовок `Idempotency-Key`; функция "
            f"`{act}(body)` выполняет действие ({what}) и возвращает данные ответа. Требования: "
            f"(1) повтор с тем же ключом и тем же телом от того же клиента возвращает сохранённый "
            f"ответ, а действие не повторяется; (2) тот же ключ с другим телом — ответ 422; "
            f"(3) ключи разных клиентов независимы; (4) если `{act}` выбросил исключение, ключ не "
            f"считается использованным, и повтор выполняет действие; (5) тела сравниваются по "
            f"содержанию, порядок полей JSON не важен. Тело может содержать вложенные объекты. "
            f"Какой обработчик выполняет все требования?")
    why = {"global_key": f"ключ без {n['client']}: одинаковые ключи разных клиентов конфликтуют (3)",
           "unsorted": "json.dumps без sort_keys зависит от порядка полей — повтор с тем же "
                       "телом в другом порядке получает 422 (5)",
           "frozenset_hash": "frozenset(body.items()) не принимает вложенные словари — TypeError",
           "reserve_first": "отметка «in_progress» записывается до действия и остаётся после "
                            "исключения — повтор навсегда получает 409 (4)"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=f"Верно: ключ ({n['client']}, idem_key), отпечаток тела — "
                               "json.dumps(..., sort_keys=True), ответ сохраняется только после "
                               "успешного действия. Дистракторы: "
                               + "; ".join(why[k] for k in chosen) + ". В продакшене ключ и "
                               "ответ хранят в БД с уникальным индексом и сроком жизни.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="idempotency_key_scope", params={"distractors": chosen})
