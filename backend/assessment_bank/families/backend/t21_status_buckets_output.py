"""backend.http.t21_status_buckets_output — predict_output (набор t21, порог Стажёра): разбор кодов ответа по
классам в цикле с if / elif.

Программа проходит по списку кодов ответа HTTP из лога и считает успешные (2xx), ошибки клиента (4xx) и ошибки
сервера (5xx); 3xx не попадает ни в один счётчик. Ловушки чтения: границы диапазонов (`< 300`, `>= 500`), код 3xx
«проваливается» мимо всех веток, порядок elif. Ключ — независимый подсчёт в генераторе; проверка — исполнение
показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.http.t21_status_buckets_output"

CTX = [("API заказов", "orders"), ("шлюз оплаты", "payments"), ("сервис профилей", "profiles"),
       ("поиск по каталогу", "search"), ("загрузка файлов", "uploads")]
CODES = {2: [200, 201, 204], 3: [301, 302, 304], 4: [400, 401, 403, 404, 409, 429], 5: [500, 502, 503, 504]}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, svc = rng.choice(CTX)
    for _ in range(200):
        n = rng.randint(6, 8)
        classes = [rng.choice([2, 2, 3, 4, 4, 5]) for _ in range(n)]
        if not ({3, 4, 5} <= set(classes)) or classes.count(2) == 0:
            continue
        codes = [rng.choice(CODES[c]) for c in classes]
        break
    else:
        raise RuntimeError("t21_status_buckets: не собрался список кодов")
    var = rng.choice(["codes", "statuses", "log"])
    code = (f"{var} = {codes}\n"
            "ok = client = server = 0\n"
            f"for c in {var}:\n"
            "    if c < 300:\n"
            "        ok += 1\n"
            "    elif 400 <= c < 500:\n"
            "        client += 1\n"
            "    elif c >= 500:\n"
            "        server += 1\n"
            "print(ok, client, server)")
    ok = sum(1 for c in codes if c < 300)
    client = sum(1 for c in codes if 400 <= c < 500)
    server = sum(1 for c in codes if c >= 500)
    out = f"{ok} {client} {server}"
    n3 = sum(1 for c in codes if 300 <= c < 400)
    expl = (f"Успешных (код < 300) — {ok}, ошибок клиента (400–499) — {client}, ошибок сервера (≥ 500) — {server}; "
            f"{n3} код(а) 3xx не попадают ни в одну ветку и не считаются. print через пробел: «{out}».")
    stem = f"Сервис «{ctx}» ({svc}): программа разбирает коды ответа из лога за минуту."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"codes": codes}, language="python")
