"""analyst.sql.t21_int_division_conv_output — predict_output (набор t21, порог Middle): конверсия в процентах —
целочисленное деление в SQLite и ROUND с 100.0.

Таблица дневной статистики по каналам / платформам / лендингам / кампаниям (визиты и заказы — целые) и запрос с
GROUP BY: одна колонка конверсии считается в целых числах (`SUM(o) * 100 / SUM(v)` — дробная часть отбрасывается,
или `SUM(o) / SUM(v) * 100` — сначала деление нацело, почти всегда 0), вторая — `ROUND(100.0 * SUM(o) / SUM(v), 1)`
(вещественное деление, печатается с точкой, например 12.0). Данные подобраны без «половинок» на втором знаке.
Ключ — независимый расчёт в генераторе (точные дроби); проверка — исполнение запроса в sqlite.
"""
from __future__ import annotations

from fractions import Fraction

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "analyst.sql.t21_int_division_conv_output"

# (таблица, сюжет, группа, группы, визиты, целевые действия)
CTX = [
    ("daily_stats", "Конверсия визитов в заказы по каналам", "channel", ["ads", "email", "seo", "social"],
     "visits", "orders"),
    ("app_stats", "Конверсия установок в подписку по платформам", "platform", ["android", "ios", "web"],
     "installs", "subs"),
    ("landing_stats", "Конверсия лендингов в заявки", "landing", ["promo", "main", "sale", "blog"], "views",
     "leads"),
    ("campaign_stats", "Конверсия рассылок в клики по кампаниям", "campaign", ["autumn", "black", "spring", "vip"],
     "sent", "clicks"),
]


def _round1(q: Fraction) -> float | None:
    """ROUND(q, 1) для q >= 0; None, если q·10 — ровно половинка (такие данные не используем)."""
    t = q * 10
    fl = t.numerator // t.denominator
    frac = t - fl
    if frac == Fraction(1, 2):
        return None
    r = fl + (1 if frac > Fraction(1, 2) else 0)
    return float(Fraction(r, 10))


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, plot, g, groups, v, o = rng.choice(CTX)
    form = rng.choice(["mul_first", "mul_first", "div_first"])
    for _ in range(2000):
        gs = sorted(rng.sample(groups, 3))
        rows, stats, ok = [], [], True
        for x in gs:
            days = rng.randint(1, 2)
            vs = [rng.randint(15, 140) for _ in range(days)]
            os_ = [rng.randint(0, max(1, vv // 4)) for vv in vs]
            for d, (vv, oo) in enumerate(zip(vs, os_), start=1):
                rows.append((x, d, vv, oo))
            sv, so = sum(vs), sum(os_)
            q = Fraction(100 * so, sv)
            r1 = _round1(q)
            if r1 is None or so == 0:
                ok = False
                break
            iv = (100 * so) // sv if form == "mul_first" else (so // sv) * 100
            stats.append((x, sv, so, iv, r1, q))
        if not ok:
            continue
        # дробная часть есть хотя бы у одной группы (иначе целое деление ничего не теряет)
        if all(s[5].denominator == 1 for s in stats):
            continue
        if len({s[4] for s in stats}) < 3:
            continue
        break
    else:
        raise RuntimeError("t21_int_division_conv: не собрались данные")
    expr = f"SUM({o}) * 100 / SUM({v})" if form == "mul_first" else f"SUM({o}) / SUM({v}) * 100"
    code = (f"SELECT {g},\n"
            f"       {expr} AS conv_int,\n"
            f"       ROUND(100.0 * SUM({o}) / SUM({v}), 1) AS conv\n"
            f"FROM {T}\n"
            f"GROUP BY {g}\n"
            f"ORDER BY {g};")
    out = "\n".join(f"{x}|{iv}|{r1!r}" for x, _sv, _so, iv, r1, _q in stats)
    setup = (f"CREATE TABLE {T} ({g} TEXT NOT NULL, day INTEGER NOT NULL, {v} INTEGER NOT NULL, "
             f"{o} INTEGER NOT NULL);\n" + sql_inserts(T, [g, "day", v, o], rows) + "\n")
    stem = (f"{plot}: запрос считает конверсию {o} / {v} в процентах двумя способами. Столбцы {v} и {o} — "
            f"целые числа (INTEGER).\n\n{T}\n{text_table([g, 'day', v, o], rows)}")
    per = "; ".join(f"{x}: {so}/{sv}" for x, sv, so, _iv, _r1, _q in stats)
    if form == "mul_first":
        why = (f"{expr}: сначала умножение, затем деление целых — дробная часть отбрасывается "
               f"(например, {stats[0][2]} * 100 / {stats[0][1]} = {stats[0][3]})")
    else:
        why = (f"{expr}: деление целых выполняется первым и даёт 0 ({o} везде меньше {v}), умножение на 100 его "
               f"не спасает")
    expl = (f"Суммы по группам: {per}. {why[0].upper() + why[1:]}. В conv литерал 100.0 делает деление "
            f"вещественным, ROUND(…, 1) оставляет один знак, и результат печатается с точкой. Ответ: "
            + "; ".join(out.splitlines()) + ".")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"rows": rows, "form": form}, language="sql", files={"setup.sql": setup})
