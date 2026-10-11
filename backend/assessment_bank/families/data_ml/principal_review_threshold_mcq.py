"""data_ml.decision.principal_review_threshold_mcq — mcq_concept (Principal, у границы Lead): порог ручной проверки.

Модель выдаёт скор риска; заявки со скором ≥ t уходят на ручную проверку. Дана таблица по корзинам скора за
сутки: число заявок и доля мошеннических (по разметке прошлого квартала). Проверка одной заявки стоит c_r и ловит
мошенничество с полнотой ρ; честный клиент на проверке — потеря f (задержка, часть клиентов уходит); пропущенное мошенничество — L. Отдел проверки обрабатывает не больше K заявок
в сутки. Какой из четырёх порогов допустим по мощности и даёт минимальную ожидаемую цену суток?

Ловушки: без ограничения мощности, без потерь на честных клиентах, «проверка ловит всё» (ρ = 1), «самый строгий
порог» (наибольший — меньше всего проверок). Порог-ответ выбирается по seed до подбора чисел — равновероятен
среди четырёх по месту; ответ отличается хотя бы от двух ловушек (у крайних — хотя бы от одной), минимум отделён
от второго места ≥ 4 %. Ключ проверяется исполнением: программа проходит корзины, относит каждую к проверке или
автоодобрению, проверяет мощность и складывает цену.
"""
from __future__ import annotations

from assessment_bank.families._principal_b_kit import argmin_sep, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, text_table

FAMILY_ID = "data_ml.decision.principal_review_threshold_mcq"

CONTEXTS = [("заявки на потребительский кредит", "заявок"), ("выводы средств с кошелька", "операций"),
            ("регистрации продавцов на маркетплейсе", "регистраций"), ("заявки на возврат товара", "заявок"),
            ("объявления о вакансиях от новых работодателей", "объявлений"), ("переводы новым получателям", "переводов")]
EDGES = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
THRESHOLDS = [0.5, 0.6, 0.7, 0.8, 0.9]

PROGRAM = """opts = __OPTS__
buckets = {buckets!r}      # (нижняя граница скора, заявок в сутки, доля мошеннических)
c_r, rho, f, L, K = {c_r}, {rho}, {f}, {L}, {K}
thresholds = {thr!r}
best, best_cost = None, None
for t in thresholds:
    reviewed = cost = 0.0
    for low, n, fraud in buckets:
        bad, good = n * fraud, n * (1 - fraud)
        if low >= t - 1e-9:                       # корзина уходит на ручную проверку
            reviewed += n
            cost += n * c_r + good * f + bad * (1 - rho) * L
        else:                                     # автоодобрение
            cost += bad * L
    if reviewed > K:
        continue
    if best_cost is None or cost < best_cost - 1e-9:
        best, best_cost = t, cost
hit = [k for k, txt in opts.items() if abs(float(txt.split(" ")[1].replace(",", ".")) - best) < 1e-9]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _cost(p, t, *, cap=True, friction=True, rho=None):
    rho = p["rho"] if rho is None else rho
    rev = cost = 0.0
    for low, n, fr in p["buckets"]:
        bad, good = n * fr, n * (1 - fr)
        if low >= t - 1e-9:
            rev += n
            cost += n * p["c_r"] + (good * p["f"] if friction else 0) + bad * (1 - rho) * p["L"]
        else:
            cost += bad * p["L"]
    if cap and rev > p["K"]:
        return None
    return cost


def _sample(rng):
    total = rng.choice([20000, 40000, 80000])
    shares = [rng.choice(v) for v in ([0.9, 0.92], [0.03, 0.04], [0.02, 0.025], [0.015, 0.012],
                                      [0.01, 0.008], [0.005, 0.004])]
    counts = [round(total * s / 10) * 10 for s in shares]
    fraud = [rng.choice(v) for v in ([0.0005, 0.001], [0.005, 0.01, 0.02], [0.02, 0.03, 0.05], [0.05, 0.08, 0.1],
                                     [0.12, 0.2], [0.3, 0.45])]
    thr = sorted(rng.sample(THRESHOLDS, 4))
    return {"buckets": [(EDGES[i], counts[i], fraud[i]) for i in range(6)], "thr": thr,
            "c_r": rng.choice([150, 300, 500]), "rho": rng.choice([0.85, 0.9, 0.95]),
            "f": rng.choice([50, 150, 400, 800]), "L": rng.choice([5000, 15000, 40000, 80000, 150000]),
            "K_mult": rng.choice([1.15, 1.4, 1.8, 3.0])}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, unit = rng.choice(CONTEXTS)
    pos = rng.choice([0, 1, 2, 3])

    def accept(p):
        thr = p["thr"]
        vols = {t: sum(n for low, n, _f in p["buckets"] if low >= t - 1e-9) for t in thr}
        p["K"] = int(round(vols[thr[pos]] * p["K_mult"] / 10) * 10)    # мощность — с запасом над объёмом ответа
        if any(abs(v - p["K"]) < 0.03 * p["K"] for v in vols.values()):
            return None
        full = {str(t): c for t in thr if (c := _cost(p, t)) is not None}
        if len(full) < 2:
            return None
        good = argmin_sep(full)
        if good is None or float(good) != thr[pos]:
            return None
        nc = argmin_sep({str(t): _cost(p, t, cap=False) for t in thr}, 0.01)
        nf = argmin_sep({str(t): c for t in thr if (c := _cost(p, t, friction=False)) is not None}, 0.01)
        pr = argmin_sep({str(t): c for t in thr if (c := _cost(p, t, rho=1.0)) is not None}, 0.01)
        if None in (nc, nf, pr):
            return None
        traps = {"no_capacity": float(nc), "no_friction": float(nf), "perfect_review": float(pr), "strictest": thr[-1]}
        need = 1 if pos in (0, 3) else 2
        if sum(1 for v in traps.values() if v != thr[pos]) < need:
            return None
        return thr[pos], full, vols, traps

    p, (good, full, vols, traps) = search(rng, _sample, accept)
    lbl = lambda t: f"порог {fmt_num(t, 1)}"
    rows = []
    for i, (low, n, fr) in enumerate(p["buckets"]):
        hi = EDGES[i + 1]
        rows.append((f"{fmt_num(low, 1)}–{fmt_num(hi, 1)}", fmt_num(n, 0), fmt_num(100 * fr, 2 if fr < 0.01 else 1) + " %"))
    table = text_table(["Скор", f"{unit.capitalize()} в сутки", "Доля мошеннических"], rows)
    stem = (f"Модель риска оценивает {ctx}; всё со скором не ниже порога уходит на ручную проверку, остальное "
            f"одобряется автоматически. Распределение за сутки (разметка прошлого квартала):\n{table}\n"
            f"Ручная проверка одного случая стоит {fmt_num(p['c_r'], 0)} ₽ и ловит мошенничество в "
            f"{fmt_num(100 * p['rho'], 0)} % случаев; честный клиент на проверке — потеря ≈ {fmt_num(p['f'], 0)} ₽ "
            f"(задержка и отток); пропущенное мошенничество — ≈ {fmt_num(p['L'], 0)} ₽. Отдел проверки успевает не "
            f"больше {fmt_num(p['K'], 0)} {unit} в сутки. Какой порог допустим по мощности и даёт минимальную ожидаемую цену "
            f"суток?")
    expl = ("Цена суток = проверки × стоимость + честные на проверке × потеря + мошенничество (пропущенное "
            "автоодобрением и не пойманное проверкой) × ущерб. По порогам: " +
            "; ".join(f"{fmt_num(t, 1)} — {fmt_num(vols[t], 0)} на проверку, " +
                      (f"{fmt_num(full[str(t)], 0)} ₽" if str(t) in full else "сверх мощности") for t in p["thr"]) +
            f". Минимум — {lbl(good)}. Ловушки: без ограничения мощности — {lbl(traps['no_capacity'])}; без потерь на "
            f"честных — {lbl(traps['no_friction'])}; «проверка ловит всё» — {lbl(traps['perfect_review'])}; самый "
            f"строгий — {lbl(traps['strictest'])}.")
    program = PROGRAM.format(buckets=p["buckets"], c_r=p["c_r"], rho=p["rho"], f=p["f"], L=p["L"], K=p["K"],
                             thr=p["thr"])
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=lbl(good),
                       distractors=[lbl(t) for t in p["thr"] if t != good], program=program, explanation=expl,
                       params={**{k: v for k, v in p.items() if k != "buckets"},
                               "buckets": [list(b) for b in p["buckets"]], "good": good,
                               **{f"trap_{k}": v for k, v in traps.items()}},
                       note="Ответ проверяется программой: проход по корзинам скора с проверкой мощности.")
