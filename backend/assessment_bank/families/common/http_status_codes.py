"""common.http.status_codes — mcq_concept: какой код ответа соответствует семантике HTTP."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.http.status_codes"

# (правильный ответ, сценарий, дистракторы, обоснование) — по RFC 9110 / RFC 6585
SCENARIOS = [
    ("201 Created", "POST {path} создал новый {res}; сервер возвращает его представление и "
     "заголовок Location с адресом.", ["200 OK", "202 Accepted", "204 No Content"],
     "RFC 9110 §15.3.2: ресурс создан, Location указывает на него."),
    ("202 Accepted", "POST {path}/export ставит выгрузку в очередь: файл будет готов через "
     "несколько минут, клиенту возвращается ссылка для проверки статуса.",
     ["201 Created", "200 OK", "102 Processing"],
     "RFC 9110 §15.3.3: запрос принят к обработке, но обработка не завершена."),
    ("304 Not Modified", "GET {path}/{id} с заголовком If-None-Match, значение которого совпадает "
     "с текущим ETag этого ресурса ({res}).", ["200 OK", "204 No Content", "412 Precondition Failed"],
     "RFC 9110 §15.4.5: условный GET, представление не изменилось — тело не передаётся."),
    ("412 Precondition Failed", "PUT {path}/{id} с заголовком If-Match, но {res} уже изменил "
     "другой клиент, и ETag больше не совпадает.", ["409 Conflict", "304 Not Modified", "400 Bad Request"],
     "RFC 9110 §15.5.13: предусловие If-Match ложно — защита от потерянного обновления."),
    ("401 Unauthorized", "GET {path} без заголовка Authorization у API, которое требует "
     "аутентификации.", ["403 Forbidden", "400 Bad Request", "404 Not Found"],
     "RFC 9110 §15.5.2: нет действительных учётных данных; ответ содержит WWW-Authenticate."),
    ("403 Forbidden", "DELETE {path}/{id} с действительным токеном пользователя, у которого нет "
     "прав на удаление; API не скрывает, что такой {res} существует.",
     ["401 Unauthorized", "404 Not Found", "405 Method Not Allowed"],
     "RFC 9110 §15.5.4: личность известна, но прав нет; повтор с теми же учётными данными не поможет."),
    ("405 Method Not Allowed", "PATCH {path} — коллекция поддерживает только GET и POST.",
     ["400 Bad Request", "404 Not Found", "501 Not Implemented"],
     "RFC 9110 §15.5.6: метод не поддерживается этим ресурсом; ответ содержит Allow: GET, POST."),
    ("415 Unsupported Media Type", "POST {path} с телом в XML и Content-Type: application/xml, "
     "а API принимает только application/json.",
     ["400 Bad Request", "406 Not Acceptable", "501 Not Implemented"],
     "RFC 9110 §15.5.16: формат тела запроса не поддерживается."),
    ("406 Not Acceptable", "GET {path}/{id} с заголовком Accept: application/xml, а сервер умеет "
     "отдавать только JSON и не отдаёт представление по умолчанию.",
     ["415 Unsupported Media Type", "400 Bad Request", "501 Not Implemented"],
     "RFC 9110 §15.5.7: нет представления, удовлетворяющего заголовку Accept."),
    ("429 Too Many Requests", "Клиент превысил лимит {limit} запросов в минуту к {path}; сервер "
     "сообщает в Retry-After, через сколько секунд можно повторить.",
     ["503 Service Unavailable", "403 Forbidden", "409 Conflict"],
     "RFC 6585 §4: превышен лимит частоты запросов."),
    ("400 Bad Request", "POST {path} с телом, которое не является корректным JSON (обрезано на "
     "середине).", ["422 Unprocessable Content", "415 Unsupported Media Type", "500 Internal Server Error"],
     "RFC 9110 §15.5.1: синтаксически неверный запрос; 422 — для синтаксически корректного содержимого."),
    ("504 Gateway Timeout", "Шлюз API не дождался ответа внутреннего сервиса за отведённые "
     "{sec} секунд при запросе GET {path}/{id}.",
     ["502 Bad Gateway", "503 Service Unavailable", "408 Request Timeout"],
     "RFC 9110 §15.6.5: шлюз не получил своевременного ответа от вышестоящего сервера."),
]
RESOURCES = [("заказ", "orders", "магазин"), ("счёт", "invoices", "биллинг"),
             ("профиль", "profiles", "соцсеть"), ("тикет", "tickets", "поддержка"),
             ("документ", "documents", "документооборот"), ("платёж", "payments", "финтех"),
             ("отчёт", "reports", "аналитика")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    idx = rng.randrange(len(SCENARIOS))
    correct, scen, distr, why = SCENARIOS[idx]
    res, coll, ctx = rng.choice(RESOURCES)
    path = f"/api/v{rng.randint(1, 3)}/{coll}"
    text = scen.format(path=path, res=res, id=rng.randint(10, 9999), limit=rng.choice([60, 100, 300]),
                       sec=rng.choice([10, 30, 60]))
    lead = rng.choice(["Ситуация: ", "Сценарий API: ", "Сервис обрабатывает запрос. "])
    ask = rng.choice(["Какой код ответа наиболее точно соответствует семантике HTTP (RFC 9110)?",
                      "Какой статус должен вернуть сервер по семантике HTTP?"])
    stem = f"{lead}{text}\n\n{ask}"
    opts, key = make_options(rng, (correct, None), [(d, None) for d in distr])
    codes = [int(o.text.split()[0]) for o in opts]
    check = Check(name="codes_exist", runner="python", embeds_display_code=False, expect="pass",
                  program=py_harness("from http import HTTPStatus",
                                     f"for c in {codes!r}:\n    HTTPStatus(c)"))
    ak = AnswerKey(kind="option", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="reference_table", checks=[check],
                         params={"scenario": idx})
