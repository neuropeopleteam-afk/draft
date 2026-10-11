"""data_ml.metrics.pooled_rate_bug — find_bug: общая конверсия как среднее долей сегментов.

Порог Junior/Middle. Отчёт по сегментам считает итоговую долю как невзвешенное среднее долей сегментов, а не как
отношение сумм; при сегментах разного размера итог искажается (малый сегмент с высокой долей тянет вверх).
Один подтип. Ловушки — пропуск сегментов без наблюдений, округление, суммирование. В условии — симптом с
числами, без названия меры. Проверка исполнением: итог равен отношению сумм на сегментах разного размера.
"""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from assessment_bank.families.common._plus_utils import line_bug_variant

FAMILY_ID = "data_ml.metrics.pooled_rate_bug"

# (контекст, знаменатель, числитель, название доли, сегмент)
CONTEXTS = [("конверсия интернет-магазина", "visits", "orders", "conversion", "каналам"),
            ("кликабельность рекламы", "shows", "clicks", "ctr", "площадкам"),
            ("брак на производстве", "produced", "defects", "defect_rate", "линиям"),
            ("отток клиентов", "clients", "churned", "churn_rate", "регионам"),
            ("доставка вовремя", "deliveries", "on_time", "on_time_share", "складам"),
            ("ответы поддержки", "tickets", "solved", "solve_rate", "очередям")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, den, num, rate, seg = rng.choice(CONTEXTS)
    fn = rng.choice(["summary", "build_report", "totals", "aggregate"])
    rows = rng.choice(["segments", "rows", "groups"])
    digits = rng.choice([3, 4])
    with_min = rng.random() < 0.5
    order = ["den", "num", "rate"] + (["n"] if rng.random() < 0.5 else [])
    rng.shuffle(order)
    sizes = [rng.randint(3000, 9000), rng.randint(100, 400), rng.randint(1500, 4000)]
    rates = [rng.randint(1, 4) / 100, rng.randint(15, 30) / 100, rng.randint(2, 6) / 100]
    data = [(s, round(s * r)) for s, r in zip(sizes, rates)] + [(0, 0)]
    rng.shuffle(data)

    def assemble(ret: str) -> str:
        sig = f"def {fn}({rows}, min_{den}=1):" if with_min else f"def {fn}({rows}):"
        cond = f"{den} < min_{den}" if with_min else f"{den} == 0"
        lines = [sig, f"    total_{den} = 0", f"    total_{num} = 0", "    shares = []",
                 f"    for {den}, {num} in {rows}:", f"        if {cond}:", "            continue",
                 f"        shares.append({num} / {den})", f"        total_{den} += {den}",
                 f"        total_{num} += {num}", "    return {"]
        entries = {"den": f'        "{den}": total_{den},', "num": f'        "{num}": total_{num},', "rate": ret,
                   "n": '        "n_segments": len(shares),'}
        lines += [entries[e] for e in order] + ["    }"]
        return "\n".join(lines) + "\n"

    buggy = assemble(f'        "{rate}": round(sum(shares) / len(shares), {digits}),')
    fixed = assemble(f'        "{rate}": round(total_{num} / total_{den}, {digits}),')
    tot_d = sum(d for d, _ in data)
    tot_n = sum(n for _, n in data)
    exp = round(tot_n / tot_d, digits)
    bad = round(sum(n / d for d, n in data if d) / 3, digits)
    test = (f"r = {fn}({data!r})\n"
            f"assert r[{den!r}] == {tot_d} and r[{num!r}] == {tot_n}\n"
            f"assert r[{rate!r}] == {exp!r}, r\n")
    stem = (f"Аналитика ({ctx}). `{fn}` сводит данные по {seg}: всего {tot_d} ({den}) и {tot_n} ({num}), а в поле "
            f"`{rate}` отчёт показывает {bad:.{digits}f} — заметно больше, чем ожидали по общим числам. "
            f"Укажите номер строки с ошибкой.")
    why = (f"Итоговая доля — отношение сумм: {tot_n} / {tot_d} ≈ {exp:.{digits}f}. Среднее долей сегментов "
           f"({bad:.{digits}f}) даёт каждому сегменту одинаковый вес, и маленький сегмент с высокой долей тянет итог "
           f"вверх. Пропуск сегментов без наблюдений и округление верны.")
    return line_bug_variant(FAMILY_ID, seed, stem=stem, buggy=buggy, fixed=fixed, test=test, context=ctx,
                            defect="unweighted_mean_of_ratios", why=why,
                            display_note="После показанного кода функция вызывается на сегментах из условия и "
                                         "сверяется с отношением сумм.",
                            params={"data": data, "expected": exp})
