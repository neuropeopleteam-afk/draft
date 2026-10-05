"""common.http.retry_idempotent_mcq — mcq_concept: какой запрос безопасно повторять после таймаута.

Ключ проверяется исполнением: модель сервера применяет каждый запрос один и два раза и
сравнивает состояние (идемпотентность по RFC 9110 §9.2.2 — эффект повтора равен эффекту
одного запроса). Ручная разметка «идемпотентен / нет» сверяется с симуляцией.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.http.retry_idempotent_mcq"

IDEMPOTENT = {"put_set": True, "delete": True, "patch_set": True, "get": True, "post_key": True,
              "post_append": False, "patch_incr": False, "post_action": False, "post_newkey": False}

CONTEXTS = {
    "магазин": {
        "put_set": "PUT /carts/{a}/items/{b} с телом {{\"qty\": {n}}}",
        "delete": "DELETE /carts/{a}/items/{b} без тела запроса",
        "patch_set": "PATCH /carts/{a} с телом {{\"coupon\": \"AUTUMN{n}\"}}",
        "get": "GET /carts/{a}?expand=items без тела запроса",
        "post_key": "POST /carts/{a}/items, Idempotency-Key общий для всех попыток",
        "post_append": "POST /carts/{a}/items с телом {{\"sku\": {b}, \"qty\": {n}}}",
        "patch_incr": "PATCH /carts/{a}/items/{b} с телом {{\"op\": \"add\", \"qty\": {n}}}",
        "post_action": "POST /carts/{a}/checkout — оформить заказ из корзины",
        "post_newkey": "POST /carts/{a}/items, новый Idempotency-Key на каждую попытку",
    },
    "трекер задач": {
        "put_set": "PUT /tasks/{a}/assignee с телом {{\"user_id\": {b}}}",
        "delete": "DELETE /tasks/{a}/labels/urgent без тела запроса",
        "patch_set": "PATCH /tasks/{a} с телом {{\"status\": \"done\"}}",
        "get": "GET /tasks/{a}/comments?limit={n}0 без тела запроса",
        "post_key": "POST /tasks/{a}/comments, Idempotency-Key общий для всех попыток",
        "post_append": "POST /tasks/{a}/comments с телом {{\"text\": \"Готово\"}}",
        "patch_incr": "PATCH /tasks/{a} с телом {{\"op\": \"add\", \"spent_hours\": {n}}}",
        "post_action": "POST /tasks/{a}/duplicate — создать копию задачи",
        "post_newkey": "POST /tasks/{a}/comments, новый Idempotency-Key на каждую попытку",
    },
    "онлайн-банк": {
        "put_set": "PUT /accounts/{a}/limits/daily с телом {{\"amount\": {n}000}}",
        "delete": "DELETE /accounts/{a}/templates/{b} без тела запроса",
        "patch_set": "PATCH /accounts/{a} с телом {{\"alias\": \"Копилка {n}\"}}",
        "get": "GET /accounts/{a}/balance без тела запроса",
        "post_key": "POST /accounts/{a}/transfers, Idempotency-Key общий для всех попыток",
        "post_append": "POST /accounts/{a}/transfers с телом {{\"to\": {b}, \"amount\": {n}00}}",
        "patch_incr": "PATCH /accounts/{a}/limits/daily с телом {{\"op\": \"add\", \"amount\": {n}00}}",
        "post_action": "POST /accounts/{a}/statements — заказать выписку на почту",
        "post_newkey": "POST /accounts/{a}/transfers, новый Idempotency-Key на каждую попытку",
    },
    "SaaS-подписки": {
        "put_set": "PUT /subscriptions/{a}/plan с телом {{\"plan\": \"pro\", \"seats\": {n}}}",
        "delete": "DELETE /subscriptions/{a}/addons/{b} без тела запроса",
        "patch_set": "PATCH /subscriptions/{a} с телом {{\"auto_renew\": false}}",
        "get": "GET /subscriptions/{a}/invoices?page=1 без тела запроса",
        "post_key": "POST /subscriptions/{a}/invoices, Idempotency-Key общий для всех попыток",
        "post_append": "POST /subscriptions/{a}/invoices с телом {{\"amount\": {n}900}}",
        "patch_incr": "PATCH /subscriptions/{a} с телом {{\"op\": \"add\", \"seats\": {n}}}",
        "post_action": "POST /subscriptions/{a}/renew — продлить на месяц",
        "post_newkey": "POST /subscriptions/{a}/invoices, новый Idempotency-Key на каждую попытку",
    },
}

MODEL = '''import copy


def apply(state, kind, attempt):
    if kind == "put_set":
        state["items"]["x"] = {"value": 3}
    elif kind == "delete":
        state["items"].pop("x", None)
    elif kind == "patch_set":
        state["attrs"]["field"] = "new"
    elif kind == "get":
        pass
    elif kind == "post_key":
        if "key-1" not in state["seen"]:
            state["seen"].add("key-1")
            state["list"].append(len(state["list"]) + 1)
    elif kind == "post_append":
        state["list"].append(len(state["list"]) + 1)
    elif kind == "patch_incr":
        state["items"]["x"]["value"] += 1
    elif kind == "post_action":
        state["created"].append("obj-%d" % (len(state["created"]) + 1))
    elif kind == "post_newkey":
        key = "key-%d" % attempt
        if key not in state["seen"]:
            state["seen"].add(key)
            state["list"].append(len(state["list"]) + 1)


def idempotent(kind):
    base = {"items": {"x": {"value": 1}}, "attrs": {"field": "old"}, "list": [], "seen": set(),
            "created": []}
    once, twice = copy.deepcopy(base), copy.deepcopy(base)
    apply(once, kind, 1)
    apply(twice, kind, 1)
    apply(twice, kind, 2)
    return once == twice
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(sorted(CONTEXTS))
    texts = CONTEXTS[ctx]
    vals = dict(a=rng.randint(10, 999), b=rng.randint(2, 99), n=rng.randint(2, 9))
    safe_q = rng.random() < 0.5
    idem = [k for k, v in IDEMPOTENT.items() if v]
    non = [k for k, v in IDEMPOTENT.items() if not v]
    if safe_q:
        correct, distr = rng.choice(idem), rng.sample(non, 3)
    else:
        correct, distr = rng.choice(non), rng.sample(idem, 3)
    fmt = lambda k: texts[k].format(**vals)
    opts, key = make_options(rng, (fmt(correct), None), [(fmt(d), None) for d in distr])
    kind_of = {fmt(k): k for k in [correct] + distr}
    pairs = [(o.id, kind_of[o.text]) for o in opts]
    want = "True" if safe_q else "False"
    program = (MODEL + f"\n\nfor letter, kind in {pairs!r}:\n"
               f"    if str(idempotent(kind)) == {want!r}:\n        print(letter)\n")
    q = ("Какой из запросов клиент может безопасно повторить автоматически — повтор не изменит "
         "результат на сервере?" if safe_q else
         "Какой из запросов НЕЛЬЗЯ автоматически повторять без дополнительной защиты — повтор "
         "может изменить результат на сервере?")
    stem = (f"Мобильное приложение ({ctx}) работает с REST API. Если ответ не пришёл за 10 с, "
            f"клиент не знает, выполнен ли запрос: ответ мог потеряться уже после обработки. "
            f"Сервер реализует методы по семантике RFC 9110, а запросы с одинаковым "
            f"`Idempotency-Key` выполняет один раз. {q}")
    why = {"put_set": "PUT заменяет состояние ресурса целиком — повтор даёт то же состояние",
           "delete": "DELETE: после первого удаления повтор ничего не меняет (код ответа может быть 404)",
           "patch_set": "PATCH, который присваивает значение полю, повторять безопасно",
           "get": "GET — безопасный метод, не меняет состояние",
           "post_key": "сервер дедуплицирует запросы с тем же Idempotency-Key",
           "post_append": "каждый POST в коллекцию создаёт новый элемент",
           "patch_incr": "PATCH с операцией «прибавить» при повторе прибавит ещё раз",
           "post_action": "каждый вызов действия создаёт новый объект или новое списание",
           "post_newkey": "новый ключ на каждую попытку делает защиту бесполезной"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=f"{why[correct]}. Остальные: " + "; ".join(why[d] for d in distr) + ".")
    checks = [Check(name="simulate", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=key, embeds_display_code=False)]
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Показанного кода нет; исполняется модель сервера, "
                                           "сравнивающая состояние после одного и двух запросов.",
                         params={"correct": correct, "distractors": distr, "safe_question": safe_q})
