"""data_ml.mlops.principal_retrain_cadence_mcq — mcq_concept (Principal, у границы Lead): как часто переобучать модель.

Модель деградирует из-за дрейфа: метрика теряет d п. п. за каждую неделю с момента среза данных, один п. п. стоит
V млн ₽ в неделю. Переобучение стоит C (вычисления и разметка) плюс обязательная проверка модельного риска W;
выкатка новой модели с вероятностью r неудачна и обходится в X (откат, разбор). Разметка запаздывает на lag недель —
новая модель уже на lag недель «старше» данных (это сдвигает потери на постоянную и на выбор периода не влияет).
Какой период переобучения из четырёх даёт минимальную среднюю цену в неделю?

Ловушки: без риска неудачной выкатки, без цены проверки модельного риска, «потери всего цикла — по концу цикла»
(V·d·T вместо среднего V·d·(T − 1)/2) — эти три сдвигают ответ к коротким периодам; «потери только от
опоздания разметки, без роста внутри цикла» — к длинным. Период-ответ выбирается по seed до подбора чисел — ключ равновероятен
среди четырёх показанных периодов (и по месту числа); ответ отличается от двух ловушек (если ответ — крайний
период, хотя бы от одной). Ключ проверяется исполнением: программа понедельно имитирует 1248 недель (кратно всем
периодам) с переобучением в начале каждого цикла и печатает период с минимальной средней ценой.
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import ru_num
from assessment_bank.families._principal_b_kit import argmin_sep, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "data_ml.mlops.principal_retrain_cadence_mcq"

CONTEXTS = [("модель оттока абонентов", "полнота среди уходящих в следующем месяце", "удержание абонентов"),
            ("модель антифрода платежей", "доля пойманного мошенничества при фиксированной доле проверок",
             "возвраты по спорным платежам"),
            ("рекомендации товаров", "доля кликов по рекомендациям", "выручка с рекомендательной полки"),
            ("прогноз спроса для закупок", "точность прогноза по товарам", "списания и упущенные продажи"),
            ("скоринг откликов на вакансии", "доля приглашённых среди первых десяти откликов",
             "время рекрутеров на ручной разбор"),
            ("модель цены поездки", "доля поездок с ценой в допустимом коридоре", "отмены и недополученная маржа"),
            ("модель кредитного скоринга", "коэффициент Джини на новых заявках", "дефолты и отказы хорошим заёмщикам"),
            ("поисковое ранжирование каталога", "доля сессий с покупкой из первой страницы выдачи",
             "оборот из поиска"),
            ("модель маршрутизации обращений", "доля обращений, попавших в нужную очередь с первого раза",
             "повторные переводы и время операторов")]
RISK = ["Выкатка новой модели неудачна примерно в {r} % случаев, откат и разбор обходятся в {x} млн ₽.",
        "Примерно {r} % выкаток новой модели оказываются неудачными; откат, разбор и компенсации — {x} млн ₽."]
VALID = ["плюс обязательная проверка модельного риска перед выкаткой — {w} млн ₽.",
         "и перед каждой выкаткой обязательна независимая проверка модельного риска — ещё {w} млн ₽."]
PERIOD_SETS = [(1, 2, 4, 8), (2, 4, 8, 13), (1, 3, 6, 12), (2, 4, 6, 13), (1, 2, 6, 12), (3, 6, 12, 26)]
HORIZON = 624 * 2  # кратно 1, 2, 3, 4, 6, 8, 12, 13, 26

PROGRAM = """V, d, lag, C, W, r, X = {V}, {d}, {lag}, {C}, {W}, {r}, {X}
periods = {periods!r}
H = {H}
avg = {{}}
for T in periods:
    total = 0.0
    for week in range(H):
        age = week % T                      # недель с последнего переобучения
        if age == 0:
            total += C + W + r * X          # переобучение, проверка, ожидаемая цена неудачной выкатки
        total += V * d * (age + lag)        # потери от дрейфа в эту неделю
    avg[T] = total / H
best = min(avg, key=avg.get)
opts = __OPTS__
hit = [k for k, t in opts.items() if int(t.split(" ")[2]) == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _avg(p, T, *, risk=True, valid=True, end=False, grow=True):
    c = p["C"] + (p["W"] if valid else 0) + (p["r"] * p["X"] if risk else 0)
    drift = p["V"] * p["d"] * (((T if end else (T - 1) / 2) if grow else 0) + p["lag"])
    return c / T + drift


def _sample(rng):
    return {"periods": rng.choice(PERIOD_SETS), "V": rng.choice([0.2, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0]),
            "d": rng.choice([0.05, 0.1, 0.2, 0.3, 0.5]), "lag": rng.choice([1, 2, 3]),
            "C": rng.choice([0.3, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0]), "W": rng.choice([0.2, 0.3, 0.5, 1.0, 1.5]),
            "r": rng.choice([0.05, 0.1, 0.2]), "X": rng.choice([2, 5, 10, 20])}


def _week(T: int) -> str:
    return f"раз в {T} {plural(T, 'неделю', 'недели', 'недель')}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, metric, money = rng.choice(CONTEXTS)
    pos = rng.choice([0, 1, 2, 3])

    def accept(p):
        per = p["periods"]
        full = {str(T): _avg(p, T) for T in per}
        good = argmin_sep(full, 0.03)
        if good != str(per[pos]):
            return None
        traps = {name: argmin_sep({str(T): _avg(p, T, **kw) for T in per}, 0.01)
                 for name, kw in (("no_risk", {"risk": False}), ("no_valid", {"valid": False}),
                                  ("end_loss", {"end": True}), ("no_growth", {"grow": False}))}
        if None in traps.values():
            return None
        need = 1 if pos in (0, 3) else 2
        if sum(1 for v in traps.values() if v != good) < need:
            return None
        return int(good), full, traps

    p, (good, full, traps) = search(rng, _sample, accept)
    per = p["periods"]
    risk_t, valid_t = rng.choice(RISK), rng.choice(VALID)
    stem = (f"{ctx.capitalize()}: из-за дрейфа метрика ({metric}) теряет ≈ {ru_num(p['d'])} п. п. за каждую неделю с "
            f"момента среза обучающих данных; один п. п. стоит ≈ {ru_num(p['V'])} млн ₽ в неделю ({money}). Одно переобучение "
            f"(вычисления и разметка) стоит {ru_num(p['C'])} млн ₽, " + valid_t.format(w=ru_num(p["W"])) + " " +
            risk_t.format(r=fmt_num(100 * p["r"], 0), x=ru_num(p["X"])) + f" Разметка приходит с опозданием на "
            f"{p['lag']} {plural(p['lag'], 'неделю', 'недели', 'недель')}, поэтому новая модель в день выкатки уже "
            f"отстаёт от данных на это время. Какой период переобучения даёт минимальную среднюю цену в неделю "
            f"(переобучение, проверка, риск выкатки и потери от дрейфа)?")
    ce = p["C"] + p["W"] + p["r"] * p["X"]
    expl = (f"Цена в неделю при периоде T = (C + W + r·X) / T + V·d·((T − 1)/2 + lag), где C + W + r·X = "
            f"{fmt_num(ce, 2)} млн ₽, V·d = {fmt_num(p['V'] * p['d'], 3)}. По периодам: " +
            "; ".join(f"{T} — {fmt_num(full[str(T)], 3)}" for T in per) +
            f" млн ₽. Минимум — {_week(good)}. Опоздание разметки добавляет одинаковую величину V·d·lag ко всем "
            f"периодам и выбор не меняет. Ловушки: без риска выкатки — {_week(int(traps['no_risk']))}; без проверки "
            f"модельного риска — {_week(int(traps['no_valid']))}; потери цикла по его концу (V·d·T) — "
            f"{_week(int(traps['end_loss']))}; потери только от опоздания разметки, без роста внутри цикла — "
            f"{_week(int(traps['no_growth']))}.")
    program = PROGRAM.format(V=p["V"], d=p["d"], lag=p["lag"], C=p["C"], W=p["W"], r=p["r"], X=p["X"],
                             periods=list(per), H=HORIZON)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=_week(good),
                       distractors=[_week(T) for T in per if T != good], program=program, explanation=expl,
                       params={**{k: v for k, v in p.items() if k != "periods"}, "periods": list(per),
                               "good": good, **{f"trap_{k}": int(v) for k, v in traps.items()}},
                       note="Ответ проверяется программой: понедельная имитация 1248 недель для каждого периода.")
