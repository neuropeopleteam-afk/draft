"""devops.slo.lp3_error_budget_releases_output — predict_output: сколько релизов ещё позволяет бюджет ошибок.

SLO доступности за 30-дневное окно → бюджет в «минутах полного простоя» = 30·24·60·(1 − SLO). Инциденты месяца
расходуют бюджет пропорционально доле затронутых запросов (частичная деградация — не полный простой). Часть
бюджета держится в резерве на непредвиденные инциденты. Плохой релиз ловится на канарейке: канарейка получает
c % трафика и откатывается автоматически через t минут, плохой релиз — с вероятностью q. Ожидаемый расход на
релиз = q · c · t. Ловушки (в условии не названы): считать инциденты полным простоем; забыть резерв; забыть, что
бюджет расходует только плохой релиз и только на доле канарейки. Ответ — целое число релизов (целая часть).
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import num_accept, typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.slo.lp3_error_budget_releases_output"
SERVICES = ["API платежей", "поиск по каталогу", "личный кабинет", "сервис уведомлений", "API доставки",
            "авторизация", "корзина", "биллинг"]
CAUSES = ["ошибка конфигурации балансировщика", "исчерпание диска на узле БД", "деградация внешнего DNS",
          "утечка памяти после релиза", "падение зоны облака", "истёкший сертификат", "перегрузка очереди",
          "неудачная миграция схемы"]

CALC = r'''
import re
cfg, inc = {}, []
for l in DATA.splitlines():
    m = re.match(r"^([^|:]+):\s*([\d,]+)", l)
    if m:
        cfg[m.group(1).strip()] = float(m.group(2).replace(",", "."))
    elif l.count("|") == 2 and not l.startswith("инцидент"):
        p = [x.strip() for x in l.split("|")]
        inc.append((float(p[1].split()[0]), float(p[2].rstrip(" %"))))
slo = cfg["SLO доступности, %"] / 100
budget = 30 * 24 * 60 * (1 - slo)
spent = sum(d * s / 100 for d, s in inc)
free = budget - spent - budget * cfg["резерв бюджета, %"] / 100
per = cfg["вероятность плохого релиза, %"] / 100 * cfg["трафик на канарейку, %"] / 100 * cfg["откат канарейки через, мин"]
print(int(free / per + 1e-9))
'''


def _n(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    svc = rng.choice(SERVICES)
    for _ in range(4000):
        slo = rng.choice([99.5, 99.9, 99.95])
        budget = 30 * 24 * 60 * (1 - slo / 100)
        n = rng.randint(3, 5)
        causes = rng.sample(CAUSES, n)
        inc = []
        for i in range(n):
            share = 100 if i == 0 and rng.random() < 0.5 else rng.choice([2, 5, 10, 15, 20, 25, 40, 50])
            dur = rng.choice([3, 4, 5, 6, 8, 10, 12, 15, 20, 30, 45, 60, 90])
            inc.append((causes[i], dur, share))
        rng.shuffle(inc)
        spent = sum(d * s / 100 for _, d, s in inc)
        reserve = rng.choice([10, 20, 25, 30])
        q = rng.choice([2, 3, 5, 8, 10])
        c = rng.choice([1, 2, 5, 10])
        t = rng.choice([5, 10, 15, 20])
        free = budget - spent - budget * reserve / 100
        per = q / 100 * c / 100 * t
        if free <= 0:
            continue
        good = int(free / per + 1e-9)
        naive_full = budget - sum(d for _, d, _ in inc) - budget * reserve / 100   # инциденты как полный простой
        n2 = int((budget - spent) / per + 1e-9)                                   # резерв забыт
        if not (5 <= good <= 3000) or naive_full > 0 and int(naive_full / per) == good or n2 == good:
            continue
        if abs(free / per - round(free / per)) < 0.02:
            continue  # ответ не у границы округления
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    lines = [f"SLO доступности, %: {_n(slo)}", "окно SLO: 30 дней", f"резерв бюджета, %: {reserve}",
             f"трафик на канарейку, %: {c}", f"откат канарейки через, мин: {t}",
             f"вероятность плохого релиза, %: {q}", "", "инцидент | длительность | доля затронутых запросов"]
    for cause, d, s in inc:
        lines.append(f"{cause} | {d} мин | {s} %")
    block = "\n".join(lines)
    stem = (f"Сервис «{svc}». С начала 30-дневного окна SLO уже были инциденты (таблица ниже, доля — сколько "
            "запросов получали ошибки в это время). Политика команды: часть бюджета ошибок держать в резерве, "
            "релизы катить через канарейку с автоматическим откатом; плохой релиз отдаёт ошибки на всю долю "
            "канарейки до отката, хороший бюджет не тратит. Сколько релизов ещё можно выкатить до конца окна, "
            "чтобы ожидаемый расход бюджета не залез в резерв? Ответ — целое число.")
    expl = (f"Бюджет = 30·24·60·(1 − {_n(slo)} %) = {budget:.1f} мин полного простоя. Израсходовано: "
            + " + ".join(f"{d}·{s} %" for _, d, s in inc) + f" = {spent:.2f} мин. Резерв {reserve} % = "
            f"{budget * reserve / 100:.1f} мин; свободно {free:.2f} мин. Ожидаемый расход на релиз = {q} % · {c} % · "
            f"{t} мин = {per:.4f} мин → {free:.2f} / {per:.4f} = {good}. Ошибки: инциденты как полный простой, "
            "резерв не учтён, расход релиза без вероятности или без доли канарейки.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(good), expl=expl, ctx=svc,
                         accept=num_accept(good, ("релизов", "релиза")),
                         params={"slo": slo, "reserve": reserve, "q": q, "c": c, "t": t, "inc": [list(x) for x in inc]})
