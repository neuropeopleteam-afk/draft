"""qa.principal.scaleout_nodes_mcq — mcq_concept (Principal, короткое): сколько узлов нужно под прогноз пиковой
нагрузки, если нагрузочный тест показал неполное масштабирование.

Нагрузочный тест: на 1 узле — X1 запросов/с, на n1 узлах — Xn. Модель Амдала: X(N) = X1·N / (1 + s(N − 1)), доля
последовательной работы s находится по измерению: s = (n1·X1 / Xn − 1) / (n1 − 1). Ключ — минимальное N, при
котором X(N) ≥ X_t (цель ниже предела X1 / s с запасом).

Ловушки: ниже ключа — ``linear`` (⌈X_t / X1⌉), ``per_node`` (⌈X_t / (Xn / n1)⌉: производительность узла как при
n1), ``power`` (каждое увеличение в n1 раз даёт тот же множитель Xn / X1), ``gustafson`` (закон Густафсона
вместо Амдала); выше ключа — ``wrong_s`` (s = 1 − Xn / (n1·X1): неверная формула доли), ``linear_eff`` (эффективность
узла падает линейно с числом узлов, как между 1 и n1). Сколько ловушек меньше ключа — 1–3 равновероятно. Ключ
проверяется исполнением: программа находит s бисекцией по измерению и перебирает N.
"""
from __future__ import annotations

import math

from assessment_bank.families._principal_c_utils import formatter, numeric_mcq, pick_traps
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.principal.scaleout_nodes_mcq"

CONTEXTS = ["поиск по каталогу", "оформление заказа", "расчёт тарифа", "проверка платежа", "выдача ленты",
            "построение маршрута", "приём показаний счётчиков", "запись к врачу"]

PROGRAM = """{fmt}
X1, n1, Xn, target = {X1}, {n1}, {Xn}, {target}
def amdahl(N, s):
    return X1 * N / (1 + s * (N - 1))
lo, hi = 0.0, 1.0                       # s по измерению: amdahl(n1, s) = Xn, функция убывает по s
for _ in range(200):
    mid = (lo + hi) / 2
    if amdahl(n1, mid) > Xn:
        lo = mid
    else:
        hi = mid
s = (lo + hi) / 2
N = 1
while amdahl(N, s) < target:
    N += 1
print(fmt(N))
"""


def _min_n(f, target, limit=300):
    for n in range(1, limit):
        if f(n) >= target - 1e-9:
            return n
    return None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    n_below = rng.choice([0, 1, 2, 3])  # ранг ключа равномерный; недостающие — контрольные значения
    fmt, fmt_src = formatter("int", "узлов")
    for _ in range(6000):
        X1 = rng.choice([200, 250, 300, 400, 500, 600, 800])
        n1 = rng.choice([4, 8])
        eff = rng.choice([0.9, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98])
        Xn = int(round(X1 * n1 * eff / 10) * 10)
        s = (n1 * X1 / Xn - 1) / (n1 - 1)
        if s <= 0:
            continue
        amd = lambda N, ss=s: X1 * N / (1 + ss * (N - 1))  # noqa: E731
        limit = X1 / s
        target = int(round(limit * rng.choice([0.2, 0.25, 0.3, 0.35, 0.4, 0.45]) / 100) * 100)
        good = _min_n(amd, target)
        if good is None:
            continue
        # запас: на N − 1 и N пропускная способность не у самой цели
        if abs(amd(good) - target) < 0.003 * target or abs(amd(good - 1) - target) < 0.003 * target:
            continue
        S = Xn / X1
        s_bad = 1 - Xn / (n1 * X1)
        eff_at = lambda N: 1 - (1 - Xn / (n1 * X1)) * (N - 1) / (n1 - 1)  # noqa: E731
        pool = {"linear": math.ceil(target / X1), "per_node": math.ceil(target / (Xn / n1)),
                "power": _min_n(lambda N: X1 * S ** (math.log(N) / math.log(n1)), target),
                "gustafson": _min_n(lambda N: X1 * (N - s * (N - 1)), target),
                "wrong_s": _min_n(lambda N: X1 * N / (1 + s_bad * (N - 1)), target),
                "linear_eff": _min_n(lambda N: X1 * N * eff_at(N), target)}
        traps = pick_traps(good, pool, n_below, rng, fmt, "int", rel=0.08, lo=10, hi=100)
        if traps:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    stem = (f"Сценарий «{ctx}»: нагрузочный тест на узлах той же конфигурации, что в эксплуатации, дал {X1} запросов/с "
            f"на 1 узле и {Xn} запросов/с на {n1} узлах (узкое место — общий ресурс, доля последовательной работы "
            f"постоянна). Прогноз пика — {target} запросов/с. Сколько узлов минимально нужно по модели Амдала?")
    why = (f"Из измерения: {n1}·{X1} / {Xn} = 1 + s·({n1} − 1), s ≈ {s:.4f}".replace(".", ",") +
           f" — предел {round(limit)} запросов/с. Минимальное N с X1·N / (1 + s(N − 1)) ≥ {target} — {good}. Ошибки: "
           f"линейно — {pool['linear']}; производительность узла как при {n1} узлах — {pool['per_node']}; тот же "
           f"множитель на каждое увеличение в {n1} {'раза' if n1 < 5 else 'раз'} — {pool['power']}; закон Густафсона — {pool['gustafson']}; "
           f"неверная доля s = 1 − Xn/(n1·X1) — {pool['wrong_s'] or 'цель недостижима'}; эффективность узла падает "
           f"линейно с числом узлов — {pool['linear_eff'] or 'цель недостижима'}. Вывод: план ёмкости по нагрузочному тесту строится по модели "
           f"масштабирования, восстановленной из измерений, и её пределу, а не линейной экстраполяцией.")
    program = PROGRAM.format(fmt=fmt_src, X1=X1, n1=n1, Xn=Xn, target=target)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=good, pool=pool, traps=traps, fmt=fmt,
                       program=program, why=why, params={"X1": X1, "n1": n1, "Xn": Xn, "target": target},
                       note="Программа находит долю s бисекцией по измерению и перебирает число узлов.")
