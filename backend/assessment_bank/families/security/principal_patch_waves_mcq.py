"""security.principal.patch_waves_mcq — mcq_concept (Principal, короткое): сколько серверов ожидаемо будет
взломано, пока критическое исправление выкатывается волнами, если время появления эксплойта случайно.

Волна i — n_i серверов, исправленных на день t_i после публикации уязвимости. Эксплойт появляется через случайное
время с экспоненциальным распределением (среднее M дней); если сервер ещё не исправлен к моменту появления
эксплойта, его взламывают с вероятностью q. Ожидаемое число взломанных: q · Σ n_i · (1 − e^(−t_i / M)). Ключ —
это число.

Ловушки: выше ключа — ``mean_day`` (средний день исправления вместо распределения по волнам — неравенство Йенсена),
``last_wave`` (все серверы — как последняя волна), ``linear`` (вероятность t_i / M без экспоненты); ниже —
``first_wave`` (все серверы — как первая волна); ``exploit_at_mean`` (эксплойт появляется ровно через M дней) —
с любой стороны. Сколько ловушек меньше ключа — 0–2 равновероятно. Ключ проверяется исполнением: программа
интегрирует плотность времени появления эксплойта по дням численно (метод Симпсона) для каждой волны.
"""
from __future__ import annotations

import math

from assessment_bank.families._principal_c_utils import formatter, numeric_mcq, pick_traps
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "security.principal.patch_waves_mcq"

CONTEXTS = ["уязвимость в веб-сервере", "уязвимость в VPN-шлюзе", "уязвимость в библиотеке разбора XML",
            "уязвимость в агенте мониторинга", "уязвимость в СУБД", "уязвимость в балансировщике нагрузки"]
WAVES = ["внешний периметр", "сервисы для клиентов", "внутренние сервисы", "тестовые и резервные"]

PROGRAM = """import math

{fmt}
WAVES = {waves!r}           # (серверов, день исправления)
M, q = {M}, {q}
def density(t):                  # плотность времени появления эксплойта, среднее M дней
    return math.exp(-t / M) / M
def prob_before(day, n=2000):    # P(эксплойт раньше дня day) — интеграл плотности методом Симпсона
    h = day / n
    s = density(0) + density(day)
    for k in range(1, n):
        s += (4 if k % 2 else 2) * density(k * h)
    return s * h / 3
print(fmt(q * sum(cnt * prob_before(day) for cnt, day in WAVES)))
"""


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    n_below = rng.choice([0, 1, 2])
    fmt, fmt_src = formatter("int", "серв.")
    k = rng.choice([3, 4])
    for _ in range(6000):
        counts = [rng.choice([20, 40, 60, 80, 120, 160, 200, 300]) for _ in range(k)]
        days = sorted(rng.sample([1, 2, 3, 5, 7, 10, 14, 21, 30, 45], k))
        M = rng.choice([5, 7, 10, 14, 21, 30])
        q = rng.choice([0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5])
        N = sum(counts)
        P = lambda t: 1 - math.exp(-t / M)  # noqa: E731
        good = q * sum(c * P(t) for c, t in zip(counts, days))
        tbar = sum(c * t for c, t in zip(counts, days)) / N
        pool = {"mean_day": q * N * P(tbar), "last_wave": q * N * P(days[-1]),
                "linear": q * sum(c * min(1.0, t / M) for c, t in zip(counts, days)),
                "first_wave": q * N * P(days[0]), "exploit_at_mean": q * sum(c for c, t in zip(counts, days) if t > M)}
        traps = pick_traps(good, pool, n_below, rng, fmt, "int", rel=0.08, lo=10, hi=100)
        if traps:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    names = WAVES[:k]
    rows = [f"  волна {i + 1} «{names[i]}»: {c} {plural(c, 'сервер', 'сервера', 'серверов')}, исправлены на день {t}"
            for i, (c, t) in enumerate(zip(counts, days))]
    q_txt = f"{round(q * 100)} %"
    code = "\n".join(["План выкатки исправления (день — от публикации уязвимости):", *rows,
                      f"Время до появления рабочего эксплойта — экспоненциальное, в среднем {M} дн.",
                      f"Неисправленный сервер после появления эксплойта взламывают с вероятностью {q_txt}."])
    stem = (f"Опубликована критическая {ctx}; затронуты {N} серверов. Совет директоров просит оценить ожидаемое "
            f"число взломанных серверов при текущем плане выкатки. Сколько получится?")
    why = (f"Для волны вероятность «эксплойт раньше исправления» — 1 − e^(−t/M); ожидаемое число — "
           f"q · Σ n_i (1 − e^(−t_i/M)) = {fmt(good)}. Ошибки: средний день исправления для всех — "
           f"{fmt(pool['mean_day'])}; все как последняя волна — {fmt(pool['last_wave'])}; линейно t/M — "
           f"{fmt(pool['linear'])}; все как первая волна — {fmt(pool['first_wave'])}; эксплойт ровно через {M} дн. — "
           f"{fmt(pool['exploit_at_mean'])}. Вывод: риск выкатки волнами считается по каждой волне — вероятность "
           f"нелинейна по времени, и среднее время исправления её завышает.")
    why = why.replace("серв..", "серв.")
    program = PROGRAM.format(fmt=fmt_src, waves=list(zip(counts, days)), M=M, q=q)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=good, pool=pool, traps=traps, fmt=fmt,
                       program=program, why=why, code=code,
                       params={"counts": counts, "days": days, "M": M, "q": q},
                       note="Программа интегрирует плотность времени появления эксплойта методом Симпсона.")
