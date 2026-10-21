"""security.principal.log_retention_mcq — mcq_concept (Principal, короткое): минимальный срок хранения журналов,
чтобы расследовать заданную долю вторжений от самого начала.

Время от вторжения до обнаружения — экспоненциальное со средним D дней (по истории инцидентов). Расследование
начинается через L дней после обнаружения (внешние криминалисты, согласования) и требует журналов с момента
вторжения. Журналы старше R дней удаляются. Доля расследуемых: P(T ≤ R − L) = 1 − e^{−(R − L)/D}. Ключ —
минимальное целое R, при котором доля ≥ X.

Ловушки: ниже ключа — ``ignore_lag`` (без задержки начала расследования), ``mean_only`` (D + L — «в среднем
обнаруживаем за D»), ``quantile_wrong`` (D·ln(1/X) + L — перепутан хвост), ``linear`` (X·D + L); выше ключа —
``markov`` (D / (1 − X) + L — грубая оценка «в худшем случае»), ``log2`` (двоичный логарифм вместо натурального).
Сколько ловушек меньше ключа — 1–3 равновероятно. Ключ проверяется исполнением: программа перебирает R по дням и
считает долю через численное интегрирование плотности (иной путь, чем обратная функция в генераторе).
"""
from __future__ import annotations

import math

from assessment_bank.families._principal_c_utils import formatter, numeric_mcq, pick_traps
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.principal.log_retention_mcq"

CONTEXTS = ["банк", "оператор связи", "маркетплейс", "страховая компания", "сеть клиник", "служба доставки",
            "облачный провайдер", "платёжный сервис", "региональный портал услуг"]

PROGRAM = """import math

{fmt}
D, L, X = {D}, {L}, {X}

def share(R):                      # доля вторжений, у которых журналы с начала ещё есть к началу расследования
    T = R - L
    if T <= 0:
        return 0.0
    n = 400                        # интеграл плотности 1/D·e^(−t/D) от 0 до T методом Симпсона
    h = T / n
    f = lambda t: math.exp(-t / D) / D
    s = f(0) + f(T) + sum((4 if i % 2 else 2) * f(i * h) for i in range(1, n))
    return s * h / 3

R = L
while share(R) < X - 1e-12:
    R += 1
print(fmt(R))
"""


def _min_r(D, L, X):
    return L + math.ceil(D * math.log(1 / (1 - X)) - 1e-9)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    n_below = rng.choice([0, 1, 2, 3])  # ранг ключа равномерный; недостающие — контрольные значения
    fmt, fmt_src = formatter("int", "дн.")
    for _ in range(4000):
        D = rng.choice([20, 25, 30, 35, 40, 45, 50, 60, 70, 75, 80, 90, 100, 120])
        L = rng.choice([5, 7, 10, 14, 15, 20, 21, 28, 30])
        X = rng.choice([0.9, 0.95, 0.97, 0.98, 0.99])
        exact = D * math.log(1 / (1 - X))
        if abs(exact - round(exact)) < 0.05:          # не у границы целого дня
            continue
        good = _min_r(D, L, X)
        pool = {"ignore_lag": math.ceil(exact), "mean_only": D + L, "quantile_wrong": math.ceil(D * math.log(1 / X)) + L,
                "linear": math.ceil(X * D) + L, "markov": math.ceil(D / (1 - X)) + L,
                "log2": math.ceil(D * math.log2(1 / (1 - X))) + L}
        traps = pick_traps(good, pool, n_below, rng, fmt, "int", rel=0.08, lo=100, hi=1000)
        if traps:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    x_txt = f"{round(100 * X)} %"
    stem = (f"{ctx.capitalize()}: по истории инцидентов время от вторжения до обнаружения распределено "
            f"экспоненциально, в среднем {D} дн. Расследование начинается через {L} дн. после обнаружения и требует "
            f"журналов с самого начала вторжения. Журналы старше срока хранения удаляются. Каков минимальный срок "
            f"хранения журналов (целое число дней), чтобы от начала можно было расследовать не меньше {x_txt} "
            f"вторжений?")
    exact_txt = f"{exact:.1f}".replace(".", ",")
    why = (f"Журналы с начала вторжения есть, если время до обнаружения T ≤ R − {L}. P(T ≤ t) = 1 − e^(−t/{D}) ≥ "
           f"{x_txt} ⇔ t ≥ {D}·ln(1/(1 − {x_txt})) ≈ {exact_txt} дн.; R = {good} дн. "
           f"Ошибки: без задержки расследования — {pool['ignore_lag']}; «среднее + задержка» — {pool['mean_only']}; "
           f"перепутан хвост (ln(1/X)) — {pool['quantile_wrong']}; оценка «D / (1 − X)» — {pool['markov']}; "
           f"двоичный логарифм — {pool['log2']}. Вывод: срок хранения журналов задаётся хвостом распределения "
           f"времени обнаружения и задержкой расследования, а не средним временем.")
    program = PROGRAM.format(fmt=fmt_src, D=D, L=L, X=X)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=good, pool=pool, traps=traps, fmt=fmt,
                       program=program, why=why, params={"D": D, "L": L, "X": X},
                       note="Программа перебирает срок по дням и интегрирует плотность численно (метод Симпсона).")
