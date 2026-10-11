"""mobile.principal.crash_users_mcq — mcq_concept (Principal, короткое): какая доля пользователей проведёт неделю без
единой ошибки при заданной доле сессий с ошибкой и неравномерной активности.

Пользователи делятся на сегменты по числу сессий в неделю (s_i, доля w_i). Сессия с ошибкой — с вероятностью c
независимо. Доля пользователей без ошибок за неделю: Σ w_i · (1 − c)^{s_i}. Ключ — это значение.

Ловушки: ниже ключа — ``mean_sessions`` (все пользователи со средним числом сессий: неравенство Йенсена),
``linear`` (1 − c × среднее число сессий), ``max_sessions`` (все как самый активный сегмент); выше ключа —
``per_session`` (доля пользователей = доля сессий), ``daily`` (за день, а не за неделю), ``min_sessions`` (все как
наименее активный сегмент), ``median_user`` («типичный» пользователь); ``unweighted`` (среднее по сегментам без
весов) — с любой стороны. Сколько ловушек меньше ключа — 0–3 равновероятно. Ключ проверяется исполнением:
программа перебирает сессии каждого сегмента по одной точными дробями.
"""
from __future__ import annotations

from assessment_bank.families._principal_c_utils import formatter, numeric_mcq, pick_traps
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.principal.crash_users_mcq"

CONTEXTS = ["мобильный банк", "приложение доставки еды", "приложение такси", "маркетплейс", "приложение для заметок",
            "фитнес-трекер", "приложение кинотеатра", "мессенджер для работы", "приложение каршеринга"]
SEGMENTS = ["редкие", "обычные", "активные", "очень активные"]

PROGRAM = """from fractions import Fraction as F

{fmt}
c = F({c_n}, 100000)                  # доля сессий со сбоем
SEG = {seg!r}                         # сегмент -> (доля пользователей, %; сессий в неделю)
clean = F(0)
for name, (w, s) in SEG.items():
    survive = F(1)
    for _ in range(s):                # сессии по одной: каждая без ошибки с вероятностью 1 − c
        survive *= 1 - c
    clean += F(w, 100) * survive
print(fmt(float(clean)))
"""


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    n_below = rng.choice([0, 1, 2, 3])
    fmt, fmt_src = formatter("p1")
    for _ in range(20000):
        k = rng.choice([3, 3, 4])
        segs = SEGMENTS[:k] if k == 4 else rng.choice([SEGMENTS[:3], SEGMENTS[1:]])
        sess = sorted([rng.choice([1, 2, 3]), rng.choice([40, 60, 80, 100])]
                      + rng.sample([5, 8, 12, 20, 30], len(segs) - 2))
        w = rng.choice([[50, 30, 20], [60, 30, 10], [40, 40, 20], [70, 20, 10]] if len(segs) == 3 else
                       [[40, 30, 20, 10], [50, 25, 15, 10], [30, 30, 25, 15]])
        c_n = rng.choice([400, 500, 600, 800, 1000, 1200, 1500, 2000])    # c = c_n / 100000 (0,4–2 %)
        c = c_n / 100000
        seg = {n: (wi, si) for n, wi, si in zip(segs, w, sess)}
        mean_s = sum(wi * si for wi, si in zip(w, sess)) / 100
        good = sum(wi / 100 * (1 - c) ** si for wi, si in zip(w, sess))
        med = sess[[i for i in range(len(w)) if sum(w[:i + 1]) >= 50][0]]
        pool = {"mean_sessions": (1 - c) ** mean_s, "linear": 1 - c * mean_s, "max_sessions": (1 - c) ** max(sess),
                "per_session": 1 - c, "daily": sum(wi / 100 * (1 - c) ** (si / 7) for wi, si in zip(w, sess)),
                "min_sessions": (1 - c) ** min(sess), "median_user": (1 - c) ** med,
                "unweighted": sum((1 - c) ** si for si in sess) / len(sess)}
        traps = pick_traps(good, pool, n_below, rng, fmt, "p1", rel=0.03, lo=0.1, hi=1.0)
        if traps:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    c_txt = f"{c_n / 1000:g}".replace(".", ",") + " %"
    rows = [f"  {n}: {wi} % пользователей, {si} сесс. в неделю" for n, (wi, si) in seg.items()]
    code = "\n".join(["Сегменты активности:", *rows, f"Доля сессий с заметной пользователю ошибкой (сбой, зависание): {c_txt}; ошибки независимы"])
    stem = (f"{ctx.capitalize()}: команда отчитывается долей сессий с ошибкой, а цель компании на следующий год — по "
            f"пользователям: доля пользователей, у которых за неделю не было ни одной ошибки. Какова эта доля сейчас?")
    mean_txt = f"{mean_s:.1f}".replace(".", ",")
    why = (f"Для сегмента с s сессиями доля пользователей без ошибок (1 − c)^s; итог — взвешенная сумма по "
           f"сегментам: {fmt(good)}. Ошибки: средний пользователь со средним числом сессий ({mean_txt}) — "
           f"{fmt(pool['mean_sessions'])}; линейно 1 − c × среднее — {fmt(pool['linear'])}; доля пользователей = "
           f"доля сессий без ошибок — {fmt(pool['per_session'])}; за день вместо недели — {fmt(pool['daily'])}; все как самый "
           f"активный сегмент — {fmt(pool['max_sessions'])}; все как наименее активный — {fmt(pool['min_sessions'])}; "
           f"среднее по сегментам без весов — {fmt(pool['unweighted'])}; «типичный» (медианный) пользователь — "
           f"{fmt(pool['median_user'])}. "
           f"Вывод: цель по пользователям при той же доле сессий со сбоем зависит от распределения активности — "
           f"рост вовлечённости снижает её без единой новой ошибки в коде.")
    program = PROGRAM.format(fmt=fmt_src, c_n=c_n, seg=seg)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=good, pool=pool, traps=traps, fmt=fmt,
                       program=program, why=why, code=code, params={"c_n": c_n, "segments": seg},
                       note="Программа перебирает сессии каждого сегмента по одной точными дробями.")
