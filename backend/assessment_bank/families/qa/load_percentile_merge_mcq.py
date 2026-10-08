"""qa.load.percentile_merge_mcq — mcq_concept: перцентиль по сервису из гистограмм узлов.

Нагрузочный тест идёт на несколько узлов за балансировщиком; каждый узел отдаёт гистограмму
времени ответа (число запросов по интервалам, как бакеты Prometheus). На дашборде p95
сервиса считается как среднее p95 узлов. Нужно найти p95 по всем запросам сервиса так же,
как histogram_quantile: сначала сложить гистограммы узлов, затем найти интервал, где
находится 95-й перцентиль, и линейно интерполировать внутри него. Перцентили нельзя
усреднять: у маленького медленного узла такой же вес, как у большого быстрого.
Версия 2: варианты ответа — методы, а не числа (панель 06.10: числовой вариант требовал
многошаговой арифметики по 8 интервалам, b ≈ 1,9–2,5 при слабой дискриминации, а состав
дистракторов 3 из 4 делал варианты неизоморфными). Состав фиксирован: среднее p95 узлов,
взвешенное по числу запросов среднее, максимум. Ключ проверяется исполнением: по показанной
таблице считается перцентиль общей выборки, и только метод ключа с ним совпадает, остальные
отличаются не меньше чем на 15 %.
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
METHODS = {methods!r}   # буква варианта -> метод


def quantile(counts, p):
    total = sum(counts)
    rank, cum = p * total, 0
    for i, c in enumerate(counts):
        if c and cum + c >= rank:
            lo = BOUNDS[i - 1] if i else 0
            return lo + (BOUNDS[i] - lo) * (rank - cum) / c
        cum += c
    raise ValueError("перцентиль в последнем интервале")


# эталон: перцентиль общей выборки — по общей гистограмме всех запросов
merged = [sum(col) for col in zip(*NODES.values())]
truth = quantile(merged, P)
per = {{n: quantile(c, P) for n, c in NODES.items()}}
tot = {{n: sum(c) for n, c in NODES.items()}}
value = {{"merge": truth,
         "mean": sum(per.values()) / len(per),
         "weighted": sum(per[n] * tot[n] for n in per) / sum(tot.values()),
         "max": max(per.values())}}
ok = [letter for letter, m in METHODS.items() if abs(value[m] - truth) / truth < 0.01]
print(ok[0] if len(ok) == 1 else "AMBIGUOUS")
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
        cand = {"mean": sum(vals) / k, "max": max(vals),
                "weighted": sum(per[n] * tot[n] for n in names) / sum(tot.values())}
        # все три метода-дистрактора должны давать заметно иной результат, чем перцентиль общей выборки
        if all(abs(v - good) / good >= 0.15 for v in cand.values()):
            break
    else:
        raise RuntimeError("не удалось подобрать гистограммы")
    pct = int(p * 100)
    chosen = ["mean", "weighted", "max"]
    label = {"good": f"Сложить гистограммы узлов по интервалам и взять p{pct} по суммарной гистограмме",
             "mean": f"Взять среднее арифметическое p{pct} узлов",
             "weighted": f"Взять среднее p{pct} узлов, взвешенное по числу запросов узла",
             "max": f"Взять максимальный p{pct} среди узлов"}
    opts, key = balanced_options(FAMILY_ID, seed, rng, (label["good"], None),
                                 [(label[c], None) for c in chosen])
    by_text = {o.text: o.id for o in opts}
    methods = {by_text[label["good"]]: "merge", **{by_text[label[c]]: c for c in chosen}}
    head = ["Узел"] + ["≤50"] + [f"{a}–{b}" for a, b in zip(BOUNDS, BOUNDS[1:])] + ["Всего", f"p{pct}, мс"]
    rows = [[nm] + [ru_num(x) for x in nodes[nm]] + [ru_num(sum(nodes[nm])), ru_num(int(round(per[nm])))]
            for nm in names]
    table = text_table(head, rows)
    shown = round(sum(per.values()) / k)
    stem = (f"Нагрузочный тест: {svc} работает на {k} узлах за балансировщиком. Каждый узел "
            f"отдаёт гистограмму времени ответа — число запросов по интервалам, мс (таблица ниже, "
            f"запросов дольше 2000 мс нет); p{pct} узла посчитан по его гистограмме с линейной "
            f"интерполяцией внутри интервала, как в histogram_quantile. На дашборде p{pct} "
            f"сервиса показан как среднее p{pct} узлов — {ru_num(shown)} мс. Как получить p{pct} по "
            f"всем запросам сервиса (тем же методом интерполяции)?")
    why = {"mean": f"среднее p{pct} узлов — перцентили нельзя усреднять: маленький медленный узел весит "
                   f"столько же, сколько большой быстрый",
           "max": f"максимум p{pct} узлов — это хвост одного маленького узла, а не {pct}-й перцентиль всех запросов",
           "weighted": f"взвешенное среднее p{pct} — всё равно усреднение перцентилей, а не перцентиль общей выборки"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=(f"Перцентиль общей выборки получается только из общей гистограммы: гистограммы "
                                f"узлов складываются по интервалам (sum by (le)), затем по сумме находится интервал "
                                f"с {pct}-м перцентилем и выполняется интерполяция — здесь ≈ {good:.0f} мс. "
                                f"Дистракторы: " + "; ".join(why[c] for c in chosen) + "."))
    checks = [Check(name="merge", runner="python", expect="stdout_equals", expected_stdout=key,
                    program=PROGRAM.format(bounds=BOUNDS, nodes=nodes, p=p, methods=methods),
                    embeds_display_code=False)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=table, options=opts, answer_key=ak,
                         context=svc, verification="execution", checks=checks, language="text",
                         display_code_note="Программа складывает те же гистограммы, считает перцентиль общей "
                                           "выборки и сверяет с ним каждый метод из вариантов: верный совпадает, "
                                           "остальные отличаются не меньше чем на 15 %.",
                         params={"k": k, "p": p, "distractors": chosen, "good": round(good)})
