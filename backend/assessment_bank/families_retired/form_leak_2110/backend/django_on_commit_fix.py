"""backend.django.on_commit_fix — choose_fix: побочный эффект внутри transaction.atomic.

Исходный код отправляет уведомление внутри atomic до проверки, которая может откатить транзакцию:
при откате письмо уже ушло. Нужно выбрать исправление, верное и при вызове функции внутри внешней
транзакции (импорт пакетом, ATOMIC_REQUESTS). Состав вариантов фиксирован (урок калибровки 05.10):
  * верный — transaction.on_commit(lambda: notify(obj.id)): вызов после коммита внешней транзакции;
  * after_block — уведомление сразу после блока with: верно в автокоммите, но при внешней транзакции
    выход из вложенного atomic — это только savepoint, а внешняя может откатиться;
  * after_check — уведомление внутри блока после проверки: тот же дефект при внешнем откате;
  * eager_call — transaction.on_commit(notify(obj.id)): функция вызывается сразу, в on_commit
    передаётся None (TypeError, откат, письмо уже ушло).
Проверка исполнением настоящего Django (SQLite в памяти): успешный вызов, откат по проверке и откат
внешней транзакции после успешного вызова.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.django.on_commit_fix"

# (контекст, модель, функция, уведомление, поле суммы, причина отказа)
CONTEXTS = [("оформление заказа", "Order", "place_order", "send_receipt", "total", "превышен лимит заказа"),
            ("выплата партнёру", "Payout", "create_payout", "notify_partner", "amount", "превышен дневной лимит"),
            ("бронирование", "Booking", "book_room", "send_confirmation", "nights", "слишком долгая бронь"),
            ("пополнение счёта", "TopUp", "top_up", "push_balance", "amount", "сумма вне лимита"),
            ("заявка на кредит", "LoanRequest", "submit_loan", "notify_scoring", "amount", "сумма вне продукта")]


def _model(model: str, fld: str) -> str:
    return "\n".join(["from django.db import models, transaction", "", "SENT = []", "", "",
                      f"class {model}(models.Model):", "    customer = models.CharField(max_length=40)",
                      f"    {fld} = models.IntegerField()", "", "", ""])


def _fn(c, kind: str, limit: int) -> str:
    _ctx, model, fn, notify, fld, reason = c
    send = f"    {notify}(obj.id)"
    body = {
        "original": [f"    with transaction.atomic():",
                     f"        obj = {model}.objects.create(customer=customer, {fld}={fld})",
                     f"        {notify}(obj.id)",
                     f"        if obj.{fld} > {limit}:",
                     f'            raise ValueError("{reason}")',
                     "    return obj"],
        "correct": [f"    with transaction.atomic():",
                    f"        obj = {model}.objects.create(customer=customer, {fld}={fld})",
                    f"        transaction.on_commit(lambda: {notify}(obj.id))",
                    f"        if obj.{fld} > {limit}:",
                    f'            raise ValueError("{reason}")',
                    "    return obj"],
        "after_block": [f"    with transaction.atomic():",
                        f"        obj = {model}.objects.create(customer=customer, {fld}={fld})",
                        f"        if obj.{fld} > {limit}:",
                        f'            raise ValueError("{reason}")',
                        send,
                        "    return obj"],
        "after_check": [f"    with transaction.atomic():",
                        f"        obj = {model}.objects.create(customer=customer, {fld}={fld})",
                        f"        if obj.{fld} > {limit}:",
                        f'            raise ValueError("{reason}")',
                        f"        {notify}(obj.id)",
                        "    return obj"],
        "eager_call": [f"    with transaction.atomic():",
                       f"        obj = {model}.objects.create(customer=customer, {fld}={fld})",
                       f"        transaction.on_commit({notify}(obj.id))",
                       f"        if obj.{fld} > {limit}:",
                       f'            raise ValueError("{reason}")',
                       "    return obj"],
    }[kind]
    return "\n".join([f"def {notify}(obj_id):", "    SENT.append(obj_id)", "", "",
                      f"def {fn}(customer, {fld}):"] + body)


def _harness(src: str, c, ok_val: int, bad_val: int) -> str:
    _ctx, model, fn, notify, fld, _reason = c
    return src + "\n\n\n" + "\n".join([
        "def __bank_test():",
        "    from django.db import connection as _c",
        "    with _c.schema_editor() as se:",
        f"        se.create_model({model})",
        f"    o1 = {fn}('c1', {ok_val})",
        "    s1 = SENT == [o1.id]",
        "    try:",
        f"        {fn}('c2', {bad_val})",
        "        s2 = False",
        "    except ValueError:",
        f"        s2 = SENT == [o1.id] and {model}.objects.count() == 1",
        "    try:",
        "        with transaction.atomic():",
        f"            {fn}('c3', {ok_val})",
        "            raise RuntimeError('импорт пакета прерван')",
        "    except RuntimeError:",
        "        pass",
        f"    s3 = SENT == [o1.id] and {model}.objects.count() == 1",
        "    return s1 and s2 and s3",
        "",
        "",
        "try:",
        "    __r = __bank_test()",
        "except Exception as __e:",
        "    __r = False",
        "print('RESULT: PASS' if __r else 'RESULT: FAIL')",
    ]) + "\n"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    c = rng.choice(CONTEXTS)
    ctx, model, fn, notify, fld, reason = c
    limit = rng.randint(2, 120) * 50 if fld != "nights" else rng.randint(7, 90)
    ok_val = rng.randint(1, limit)
    bad_val = limit + rng.randint(1, limit)
    head = _model(model, fld)
    original = _fn(c, "original", limit)
    # подписи нейтральные: способ отправки виден только в коде вариантов (подпись не должна подсказывать ответ)
    label = "Заменить функцию на:"
    names = ["correct", "after_block", "after_check", "eager_call"]
    srcs = {n: _fn(c, n, limit) for n in names}
    opts, key = make_options(rng, (label, srcs["correct"]), [(label, srcs[n]) for n in names[1:]])
    by_code = {o.code: o.id for o in opts}
    code = head + original + "\n"
    checks = [Check(name="original_fails", runner="django", program=_harness(code, c, ok_val, bad_val),
                    expect="fail")]
    for n in names:
        checks.append(Check(name=f"option:{by_code[srcs[n]]}", runner="django",
                            program=_harness(head + srcs[n] + "\n", c, ok_val, bad_val),
                            expect="pass" if n == "correct" else "fail", embeds_display_code=False))
    stem = (f"Django, {ctx}: `{fn}` создаёт запись и отправляет уведомление `{notify}`. Если проверка "
            f"не прошла ({reason}), транзакция откатывается, но уведомление уже ушло. Функцию вызывают и "
            f"отдельно, и внутри внешней транзакции (пакетный импорт, ATOMIC_REQUESTS), которая может "
            f"откатиться позже. Какой вариант отправляет уведомление только о реально сохранённых записях?")
    why = (f"Верно transaction.on_commit(lambda: {notify}(obj.id)): Django вызовет функцию после коммита "
           f"самой внешней транзакции и не вызовет при откате. Вызов после блока with или после проверки "
           f"срабатывает до коммита внешней транзакции (вложенный atomic — только savepoint). "
           f"on_commit({notify}(obj.id)) вызывает функцию сразу и передаёт в on_commit None.")
    ak = AnswerKey(kind="option", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="side_effect_in_transaction",
                         params={"limit": limit})
