"""common.perf.fanout_tail_mcq — mcq_concept: усиление хвоста задержки при fan-out («The Tail at Scale»).

Запрос параллельно опрашивает N независимых бэкендов и ждёт всех; у каждого доля ответов
медленнее порога L равна q (L — его p99 / p99,5 / p99,9). Какая доля пользовательских
запросов медленнее L? Ответ: 1 − (1 − q)^N — для Senior это базовая оценка при
проектировании fan-out (почему p99 бэкенда становится медианой фронта).

Дистракторы — содержательные ошибки проектирования fan-out с обеих сторон от верного ответа
(все двузначные проценты одной строковой длины; ранг ключа задаётся по seed до подбора чисел):
  * half_fanout — учтена только половина шардов: 1 − (1 − q)^(N/2);
  * sqrt_fanout — корень из числа бэкендов вместо степени N;
  * q_half — взята половинная вероятность хвоста (q/2);
  * harmonic — отношение N·q / (1 + N·q) вместо 1 − (1 − q)^N;
  * complement — (1 − q)^N, доля запросов, где медленных нет (перепутано дополнение);
  * union_bound — линейная оценка N·q (верхняя граница Буля без вычета пересечений);
  * double_fanout — двойной учёт числа шардов: 1 − (1 − q)^(2N);
  * q_double — удвоенная вероятность хвоста (2q).

Ключ проверяется исполнением: программа на Python перемножает вероятности «бэкенд уложился»
по каждому из N бэкендов точной арифметикой (Fraction) и печатает букву совпавшего варианта.
"""
from __future__ import annotations

import math
from fractions import Fraction

from assessment_bank.gen_utils import build_variant, make_options, make_rng, spread_pick
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.perf.fanout_tail_mcq"

CONTEXTS = [
    ("поиск по каталогу", "шардов индекса", "шард", "поисковый запрос"),
    ("лента рекомендаций", "сервисов-источников", "источник", "запрос ленты"),
    ("агрегатор цен", "поставщиков", "поставщик", "запрос цены"),
    ("BFF мобильного приложения", "микросервисов", "микросервис", "запрос экрана"),
    ("аналитический дашборд", "партиций хранилища", "партиция", "запрос виджета"),
]

PCTS = [("99", Fraction(1, 100)), ("99,5", Fraction(1, 200)), ("99,9", Fraction(1, 1000))]

PROGRAM = """from fractions import Fraction
N, q = {n}, Fraction({qn}, {qd})
ok_all = Fraction(1)
for _ in range(N):          # бэкенды независимы, запрос ждёт всех
    ok_all *= 1 - q
slow = 1 - ok_all
options = {opts!r}
hit = [k for k, v in options.items() if abs(Fraction(v) - 100 * slow) <= Fraction(15, 100)]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""

WHY = {
    "half_fanout": "учтена только половина опрашиваемых бэкендов",
    "sqrt_fanout": "взята степень √N вместо N (ошибка из формулы стандартного отклонения)",
    "q_half": "взята половинная доля хвоста q/2",
    "harmonic": "оценка по формуле N·q / (1 + N·q) вместо 1 − (1 − q)^N",
    "complement": "доля быстрых запросов (1 − q)^N вместо медленных (перепутано дополнение)",
    "union_bound": "линейная сумма N·q (верхняя оценка Буля без вычета пересечений)",
    "double_fanout": "двойной учёт числа бэкендов (2N)",
    "q_double": "удвоенная доля хвоста одного бэкенда (2q)",
}


def _pct(x: Fraction | float) -> str:
    return f"{float(100 * x):.1f}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, many, one, req = rng.choice(CONTEXTS)
    n_below = make_rng(FAMILY_ID, seed // 4, "rank").sample(range(4), 4)[seed % 4]
    for _ in range(1500):
        pname, q = rng.choice(PCTS)
        n = rng.choice([20, 25, 30, 40, 50, 60, 80, 100, 120, 150, 200, 250, 300, 400, 500, 600, 800])
        nq = float(n * q)
        if not (0.22 <= nq <= 0.92):
            continue
        good = float(1 - (1 - q) ** n)
        good_p = round(100 * good, 1)
        if not (18.0 <= good_p <= 62.0):
            continue
        sqrt_n = max(4, round(math.sqrt(n)))
        raw = {
            "half_fanout": float(1 - (1 - q) ** (n // 2)),
            "sqrt_fanout": float(1 - (1 - q) ** sqrt_n),
            "q_half": float(1 - (1 - q / 2) ** n),
            "harmonic": nq / (1.0 + nq),
            "complement": float((1 - q) ** n),
            "union_bound": nq,
            "double_fanout": float(1 - (1 - q) ** (2 * n)),
            "q_double": float(1 - (1 - 2 * q) ** n),
        }
        cand = {k: round(100 * v, 1) for k, v in raw.items() if 10.5 <= round(100 * v, 1) <= 95.0}
        below = [k for k, v in cand.items() if v < good_p - 2.5]
        above = [k for k, v in cand.items() if v > good_p + 2.5]
        if len(below) < n_below or len(above) < 3 - n_below:
            continue

        def fits(tvals: list[float]) -> bool:
            all_v = sorted([good_p, *tvals])
            if len(set(all_v)) != 4 or any(not (10.0 <= x <= 99.9) for x in all_v):
                return False
            return all(b - a >= 3.0 for a, b in zip(all_v, all_v[1:]))

        rng.shuffle(below)
        rng.shuffle(above)
        picked = spread_pick(rng, good_p, below, above, n_below, 3 - n_below, cand.__getitem__, fits, min_step=0.10)
        if picked is not None:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")

    chosen = [k for k, _ in picked]
    shown = {"good": f"{good_p:.1f}", **{k: f"{cand[k]:.1f}" for k in chosen}}
    text = {k: f"≈ {v.replace('.', ',')} % запросов" for k, v in shown.items()}
    opts, key = make_options(rng, (text["good"], None), [(text[d], None) for d in chosen])
    opt_vals = {o.id: o.text.split("≈ ")[1].split(" %")[0].replace(",", ".") for o in opts}
    lead = rng.choice([
        f"{ctx.capitalize()}: каждый {req} параллельно отправляется на {n} {many}, ответ "
        f"собирается, когда ответили все.",
        f"Сервис «{ctx}» обслуживает {req} так: запрос рассылается сразу на все {n} {many} и "
        f"ждёт ответа каждого.",
        f"В архитектуре «{ctx}» {req} — это fan-out на {n} {many} с ожиданием всех ответов."])
    lat = rng.choice([80, 120, 150, 200, 250, 300])
    stem = (f"{lead} У каждого бэкенда (тип «{one}») p{pname} задержки — {lat} мс, задержки разных "
            f"бэкендов независимы, сеть и сборка ответа пренебрежимо быстрые. Какая доля "
            f"пользовательских запросов будет медленнее {lat} мс?")
    checks = [Check(name="tail", runner="python",
                    program=PROGRAM.format(n=n, qn=q.numerator, qd=q.denominator, opts=opt_vals),
                    expect="stdout_equals", expected_stdout=key)]
    why_str = "; ".join(f"{shown[k].replace('.', ',')} % — {WHY[k]}" for k in chosen)
    ak = AnswerKey(kind="option", value=key,
                   explanation=(f"Запрос быстрый, только если быстрыми оказались все {n} бэкендов: "
                                f"(1 − {str(float(q)).replace('.', ',')})^{n} ≈ {_pct((1 - q) ** n).replace('.', ',')} %; "
                                f"медленных — дополнение, ≈ {shown['good'].replace('.', ',')} %. "
                                f"Дистракторы: {why_str}."))
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Ответ проверяется программой: точный расчёт "
                                           "вероятности по N независимым бэкендам.",
                         params={"n": n, "q": str(q), "percentile": pname, "latency_ms": lat,
                                 "shown": shown, "n_below": n_below})
