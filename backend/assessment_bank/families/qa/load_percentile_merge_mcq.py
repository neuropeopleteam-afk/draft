"""qa.load.percentile_merge_mcq — mcq_concept: перцентиль по сервису из гистограмм узлов.

Нагрузочный тест идёт на несколько узлов за балансировщиком; каждый узел отдаёт гистограмму
времени ответа (число запросов по интервалам, как бакеты Prometheus). На дашборде p95
сервиса считается как среднее p95 узлов. Нужно найти p95 по всем запросам сервиса так же,
как histogram_quantile: сначала сложить гистограммы узлов, затем найти интервал, где
находится 95-й перцентиль, и линейно интерполировать внутри него. Перцентили нельзя
усреднять: у маленького медленного узла такой же вес, как у большого быстрого.
Дистракторы — среднее p95 узлов, максимум p95 узлов, среднее p95, взвешенное по числу
запросов, медиана p95 узлов. Ключ проверяется исполнением расчёта по показанной таблице.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, text_table
from assessment_bank.schema import AnswerKey, Check

from ._qa_utils import balanced_options, ru_num

FAMILY_ID = "qa.load.percentile_merge_mcq"

BOUNDS = [50, 100, 200, 300, 500, 800, 1200, 2000]
SERVICES = ["API каталога", "сервис авторизации", "API корзины", "сервис поиска",
            "API расчёта тарифа", "сервис профилей", "API откликов", "шлюз платежей"]

PROGRAM = '''BOUNDS = {bounds!r}
NODES = {nodes!r}   # имя -> число запросов по интервалам (0, 50], (50, 100], ...
P = {p!r}


def quantile(counts, p):
    total = sum(counts)
    rank, cum = p * total, 0
    for i, c in enumerate(counts):
        if c and cum + c >= rank:
            lo = BOUNDS[i - 1] if i else 0
            return lo + (BOUNDS[i] - lo) * (rank - cum) / c
        cum += c
    raise ValueError("перцентиль в последнем интервале")


merged = [sum(col) for col in zip(*NODES.values())]
value = quantile(merged, P)
print(f"около {{round(value / 5) * 5}} мс")
'''


def _quantile(counts, p):
    total = sum(counts)
    rank, cum = p * total, 0
    for i, c in enumerate(counts):
        if c and cum + c >= rank:
            lo = BOUNDS[i - 1] if i else 0
            return lo + (BOUNDS[i] - lo) * (rank - cum) / c
        cum += c
    raise ValueError


def _profile(rng, total, center):
    """Распределение запросов по интервалам вокруг индекса center (без последнего «+Inf»)."""
    w = []
    for i in range(len(BOUNDS)):
        d = abs(i - center)
        w.append(rng.uniform(0.8, 1.2) * (0.5 ** (d * 1.6)) * (0.35 if i > center else 1.0))
    s = sum(w)
    counts = [int(total * x / s) for x in w]
    counts[center] += total - sum(counts)
    return counts


def _fmt(v):
    return f"около {round(v / 5) * 5} мс"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    svc = rng.choice(SERVICES)
    p = rng.choice([0.95, 0.95, 0.99])
    for _ in range(500):
        k = rng.choice([3, 4])
        names = [f"node-{i}" for i in range(1, k + 1)]
        slow = rng.randrange(k)
        nodes = {}
        for i, nm in enumerate(names):
            if i == slow:
                nodes[nm] = _profile(rng, rng.randrange(300, 1500, 10), rng.choice([4, 5]))
            else:
                nodes[nm] = _profile(rng, rng.randrange(5000, 14000, 10), rng.choice([1, 2]))
        try:
            per = {nm: _quantile(c, p) for nm, c in nodes.items()}
            merged = [sum(col) for col in zip(*nodes.values())]
            good = _quantile(merged, p)
        except ValueError:
            continue
        vals = list(per.values())
        tot = {nm: sum(c) for nm, c in nodes.items()}
        srt = sorted(vals)
        cand = {"mean": sum(vals) / k, "max": max(vals),
                "weighted": sum(per[n] * tot[n] for n in names) / sum(tot.values()),
                "median": (srt[k // 2] if k % 2 else (srt[k // 2 - 1] + srt[k // 2]) / 2)}
        cand = {n: v for n, v in cand.items()
                if abs(v - good) / good >= 0.15 and _fmt(v) != _fmt(good)}
        if len(cand) < 3:
            continue
        chosen = rng.sample(sorted(cand), 3)
        vs = sorted([good] + [cand[c] for c in chosen])
        if all(b / a >= 1.15 for a, b in zip(vs, vs[1:])):
            break
    else:
        raise RuntimeError("не удалось подобрать гистограммы")
    opts, key = balanced_options(FAMILY_ID, seed, rng, (_fmt(good), None),
                                 [(_fmt(cand[c]), None) for c in chosen])
    head = ["Узел"] + ["≤50"] + [f"{a}–{b}" for a, b in zip(BOUNDS, BOUNDS[1:])] + ["Всего", f"p{int(p * 100)}, мс"]
    rows = [[nm] + [ru_num(x) for x in nodes[nm]] + [ru_num(sum(nodes[nm])), ru_num(int(round(per[nm])))]
            for nm in names]
    table = text_table(head, rows)
    pct = int(p * 100)
    shown = round(sum(per.values()) / k)
    stem = (f"Нагрузочный тест: {svc} работает на {k} узлах за балансировщиком. Каждый узел "
            f"отдаёт гистограмму времени ответа — число запросов по интервалам, мс (таблица ниже, "
            f"запросов дольше 2000 мс нет); p{pct} узла посчитан по его гистограмме с линейной "
            f"интерполяцией внутри интервала, как в histogram_quantile. На дашборде p{pct} "
            f"сервиса показан как среднее p{pct} узлов — {ru_num(shown)} мс. Чему равен p{pct} по "
            f"всем запросам сервиса, если считать тем же методом?")
    why = {"mean": f"среднее p{pct} узлов — перцентили нельзя усреднять",
           "max": f"максимум p{pct} узлов — это хвост маленького медленного узла",
           "weighted": f"взвешенное по числу запросов среднее p{pct} — всё равно усреднение "
                       f"перцентилей, а не перцентиль общей выборки",
           "median": f"медиана p{pct} узлов — тоже не перцентиль общей выборки"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=(f"Сначала гистограммы узлов складываются по интервалам "
                                f"(sum by (le)), затем по общей гистограмме находится интервал с "
                                f"{pct}-м перцентилем и выполняется интерполяция: ≈ {good:.0f} мс. "
                                f"Дистракторы: " + "; ".join(why[c] for c in chosen) + "."))
    checks = [Check(name="merge", runner="python", expect="stdout_equals", expected_stdout=_fmt(good),
                    program=PROGRAM.format(bounds=BOUNDS, nodes=nodes, p=p),
                    embeds_display_code=False)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=table, options=opts, answer_key=ak,
                         context=svc, verification="execution", checks=checks, language="text",
                         display_code_note="Программа складывает те же гистограммы и считает "
                                           "перцентиль с интерполяцией.",
                         params={"k": k, "p": p, "distractors": chosen})
