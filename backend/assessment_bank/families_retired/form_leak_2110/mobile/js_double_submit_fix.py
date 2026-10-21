"""mobile.js.double_submit_fix — choose_fix: двойное нажатие «Оплатить» отправляет два платежа.

Обработчик нажатия асинхронный; флаг «идёт отправка» должен ставиться ДО первого await и сниматься в finally.
Состав дистракторов фиксирован:
  * flag_after_await — флаг ставится после запроса: второе нажатие успевает пройти проверку;
  * no_finally — флаг снимается только при успехе: после ошибки сети кнопка больше не работает;
  * check_no_set — проверка флага есть, но флаг нигде не ставится.
Ключ проверяется исполнением в Node: два нажатия подряд, затем ошибка сети и повторное нажатие.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, js_harness, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._mob_utils import balanced_options

FAMILY_ID = "mobile.js.double_submit_fix"

CTX = [("оплата заказа", "onPayPress", "pay", "Оплатить"), ("перевод между счетами", "onTransferPress",
                                                           "transfer", "Перевести"),
       ("бронирование столика", "onBookPress", "book", "Забронировать"),
       ("отправка отзыва", "onSendPress", "sendReview", "Отправить"),
       ("покупка билета", "onBuyPress", "buyTicket", "Купить"), ("запись к врачу", "onConfirmPress",
                                                                  "confirmVisit", "Записаться")]

PRELUDE = """function makeApi(method) {
  const api = { calls: 0, failNext: false };
  api[method] = async (form) => {
    api.calls += 1;
    for (let k = 0; k < 3; k++) await null;
    if (api.failNext) { api.failNext = false; throw new Error('network'); }
    return { ok: true };
  };
  return api;
}"""


def _handler(kind, fn, method, flag):
    head = f"let {flag} = false;\n\nasync function {fn}(form, api, ui) {{\n"
    if kind == "buggy":
        body = (f"  const res = await api.{method}(form);\n  ui.showDone(res);\n")
    elif kind == "good":
        body = (f"  if ({flag}) return;\n  {flag} = true;\n  try {{\n    const res = await api.{method}(form);\n"
                f"    ui.showDone(res);\n  }} catch (e) {{\n    ui.showError(e);\n  }} finally {{\n    {flag} = false;\n  }}\n")
    elif kind == "flag_after_await":
        body = (f"  if ({flag}) return;\n  try {{\n    const res = await api.{method}(form);\n    {flag} = true;\n"
                f"    ui.showDone(res);\n  }} catch (e) {{\n    ui.showError(e);\n  }} finally {{\n    {flag} = false;\n  }}\n")
    elif kind == "no_finally":
        body = (f"  if ({flag}) return;\n  {flag} = true;\n  try {{\n    const res = await api.{method}(form);\n"
                f"    ui.showDone(res);\n    {flag} = false;\n  }} catch (e) {{\n    ui.showError(e);\n  }}\n")
    elif kind == "check_no_set":
        body = (f"  if ({flag}) return;\n  try {{\n    const res = await api.{method}(form);\n"
                f"    ui.showDone(res);\n  }} catch (e) {{\n    ui.showError(e);\n  }} finally {{\n    {flag} = false;\n  }}\n")
    else:
        raise ValueError(kind)
    return head + body + "}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, fn, method, label = rng.choice(CTX)
    flag = rng.choice(["submitting", "inFlight", "busy", "isSending"])
    code = _handler("buggy", fn, method, flag)
    dist = ["flag_after_await", "no_finally", "check_no_set"]
    opts, key = balanced_options(FAMILY_ID, seed, rng, ("Заменить код на:", _handler("good", fn, method, flag)),
                                 [("Заменить код на:", _handler(d, fn, method, flag)) for d in dist])
    amount = rng.randint(3, 90) * 100
    test = (f"const api = makeApi({method!r});\nconst ui = {{ showDone() {{}}, showError() {{}} }};\n"
            f"const form = {{ amount: {amount} }};\n"
            f"await Promise.all([{fn}(form, api, ui), {fn}(form, api, ui)]);\n"
            f"__assert(api.calls === 1, 'двойное нажатие: запросов ' + api.calls);\n"
            f"api.failNext = true;\nawait {fn}(form, api, ui);\nawait {fn}(form, api, ui);\n"
            f"__assert(api.calls === 3, 'после ошибки сети: запросов ' + api.calls);")
    checks = [Check(name=f"option:{o.id}", runner="node", embeds_display_code=False,
                    program=js_harness(o.code, test, PRELUDE), expect="pass" if o.id == key else "fail")
              for o in opts]
    checks.append(Check(name="buggy_fails", runner="node", program=js_harness(code, test, PRELUDE), expect="fail"))
    stem = (f"Мобильное приложение, экран «{ctx}»: кнопка «{label}» вызывает `{fn}`. Жалоба: при быстром двойном "
            f"касании иногда уходят два запроса, и с карты списывается дважды по {amount} ₽. Нужно, чтобы во время "
            f"отправки повторные нажатия игнорировались, а после ошибки сети пользователь мог нажать кнопку снова. "
            f"Какая замена кода верна?")
    why = {"flag_after_await": "флаг ставится только после ответа сервера — второе касание проходит проверку раньше",
           "no_finally": "флаг снимается только при успехе — после ошибки сети кнопка перестаёт работать",
           "check_no_set": "проверка флага есть, но флаг нигде не ставится в true"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=("Верно: флаг ставится синхронно до первого await, снимается в finally. Дистракторы: "
                                + "; ".join(why[d] for d in dist) + "."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="double_submit",
                         params={"amount": amount, "distractors": dist})
