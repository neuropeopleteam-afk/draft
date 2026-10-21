"""frontend.http.lp3_swr_requests_output — predict_output: сколько запросов уйдёт в сеть при max-age и SWR.

Ответ API кэшируется браузером: Cache-Control: max-age=M, stale-while-revalidate=S. Свежий ответ (возраст ≤ M)
отдаётся из кэша без сети; устаревший в пределах M + S отдаётся из кэша и запускает фоновую перепроверку (один
сетевой запрос, после него возраст = 0); старше M + S — запрос ждёт сеть. Перепроверка завершается мгновенно.
Ловушки: забыть фоновые перепроверки (они тоже сеть); считать, что SWR-ответ не обновляет кэш; считать возраст от
первого запроса. Ответ — число сетевых запросов, включая самый первый.
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import num_accept, typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.http.lp3_swr_requests_output"
EPS = ["/api/cart", "/api/feed", "/api/profile", "/api/prices", "/api/notifications/count", "/api/rates"]

CALC = r'''
import re
M = S = None
ts = []
for l in DATA.splitlines():
    if l.startswith("Cache-Control"):
        M = int(re.search(r"max-age=(\d+)", l).group(1))
        S = int(re.search(r"stale-while-revalidate=(\d+)", l).group(1))
    elif l.startswith("обращения"):
        ts = [int(x) for x in l.split(":", 1)[1].split(";")]
net, fetched = 0, None
for t in ts:
    if fetched is None or t - fetched > M + S:
        net += 1
        fetched = t
    elif t - fetched > M:
        net += 1
        fetched = t
print(net)
'''


def _sim(ts, M, S):
    net, fetched = 0, None
    for t in ts:
        if fetched is None or t - fetched > M + S or t - fetched > M:
            net += 1
            fetched = t
    return net


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ep = rng.choice(EPS)
    for _ in range(3000):
        M = rng.choice([10, 30, 60, 120])
        S = rng.choice([30, 60, 120, 300])
        n = rng.randint(10, 16)
        t, ts = 0, []
        for _ in range(n):
            ts.append(t)
            t += rng.choice([2, 5, 8, 15, 20, 40, 70, 150, 400])
        good = _sim(ts, M, S)
        # ошибка: фоновые перепроверки не считаются сетью
        fg, fetched = 0, None
        for x in ts:
            if fetched is None or x - fetched > M + S:
                fg += 1
                fetched = x
            elif x - fetched > M:
                fetched = x
        # ошибка: возраст от первого запроса, кэш не обновляется
        first = sum(1 for x in ts if x == 0 or x - ts[0] > M)
        if good in (fg, first) or good < 3:
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    block = "\n".join([f"Cache-Control: max-age={M}, stale-while-revalidate={S}",
                       "обращения страницы к API (секунды от первого): " + "; ".join(str(x) for x in ts)])
    stem = (f"Страница обращается к {ep}; ответ кэшируется браузером с заголовком из блока ниже. В кэше одна запись; "
            "сетевой ответ (и обычный, и фоновая перепроверка) делает возраст записи нулевым. Фоновая перепроверка "
            "завершается мгновенно. Сколько сетевых запросов к API будет за все обращения, включая первый? "
            "Ответ — целое число.")
    expl = (f"Свежо, пока возраст ≤ {M} с; до {M + S} с — ответ из кэша и фоновая перепроверка (это сетевой запрос, "
            f"возраст обнуляется); старше — ожидание сети. Итого {good}. Без учёта фоновых перепроверок — {fg}; "
            f"с возрастом от первого запроса — {first}.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(good), expl=expl, ctx=ep,
                         accept=num_accept(good, ("запросов", "запроса")), params={"M": M, "S": S, "ts": ts})
