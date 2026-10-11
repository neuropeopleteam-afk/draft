"""devops.mon.histogram_quantile_mcq — mcq_concept: что вернёт histogram_quantile по корзинам гистограммы.

Алгоритм Prometheus (функция histogram_quantile, promql/quantile.go): корзины кумулятивные (`le` — верхняя
граница, `+Inf` — всего наблюдений), ранг = q × total; берётся первая корзина, где накопленное число ≥ ранга;
результат — линейная интерполяция внутри неё: нижняя граница + (верхняя − нижняя) × (ранг − накоплено до
корзины) / (число в корзине); нижняя граница первой корзины — 0. Подтип один: ответ внутри конечной корзины
(не в +Inf). Дистракторы — фиксированный состав: верхняя граница найденной корзины, нижняя граница и середина
корзины. Ключ — исполнение модели алгоритма в песочнице Python над показанными значениями корзин.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "devops.mon.histogram_quantile_mcq"

CTX = [("API заказов", "http_request_duration_seconds"), ("шлюз платежей", "gateway_latency_seconds"),
       ("поиск", "search_query_duration_seconds"), ("очередь фоновых задач", "job_duration_seconds"),
       ("сервис профилей", "rpc_latency_seconds")]
BOUNDS = [[0.05, 0.1, 0.25, 0.5, 1.0, 2.5], [0.1, 0.2, 0.4, 0.8, 1.6], [0.025, 0.05, 0.1, 0.2, 0.4, 0.8],
          [0.25, 0.5, 1.0, 2.0, 4.0]]

MODEL = '''
bounds = {bounds!r}
counts = {counts!r}          # кумулятивные, последняя — +Inf
q = {q!r}
rank = q * counts[-1]
b = next(i for i, c in enumerate(counts) if c >= rank)
assert b < len(bounds), "ответ попал в +Inf"
start = 0.0 if b == 0 else bounds[b - 1]
below = 0 if b == 0 else counts[b - 1]
v = start + (bounds[b] - start) * (rank - below) / (counts[b] - below)
print(f"≈ {{v * 1000:.0f}} мс")
'''


def ms(x: float) -> str:
    return f"≈ {x * 1000:.0f} мс"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, metric = rng.choice(CTX)
    for _ in range(2000):
        bounds = rng.choice(BOUNDS)
        q = rng.choice([0.5, 0.9, 0.95, 0.99])
        per = [rng.randint(5, 400) for _ in bounds] + [rng.randint(0, 30)]
        counts, acc = [], 0
        for c in per:
            acc += c
            counts.append(acc)
        rank = q * counts[-1]
        b = next(i for i, c in enumerate(counts) if c >= rank)
        if b >= len(bounds) or b == 0:
            continue
        start, end = bounds[b - 1], bounds[b]
        v = start + (end - start) * (rank - counts[b - 1]) / (counts[b] - counts[b - 1])
        texts = [ms(v), ms(end), ms(start), ms((start + end) / 2)]
        if len(set(texts)) == 4 and abs(v - (start + end) / 2) > 0.08 * (end - start):
            break
    correct, wrong = texts[0], texts[1:]
    opts, key = make_options(rng, (correct, None), [(w, None) for w in wrong])
    rows = [f'{metric}_bucket{{le="{bd:g}"}}  {c}' for bd, c in zip(bounds, counts)]
    rows.append(f'{metric}_bucket{{le="+Inf"}}  {counts[-1]}')
    code = (f"histogram_quantile({q:g}, sum by (le) (increase({metric}_bucket[5m])))\n\n"
            "# increase(...) за последние 5 минут по корзинам:\n" + "\n".join(rows))
    dec = lambda x: f"{x:g}".replace(".", ",")  # noqa: E731
    expl = (f"Всего {counts[-1]} наблюдений, ранг = {dec(q)} × {counts[-1]} = {dec(round(rank, 2))}. Первая корзина с "
            f"накопленным ≥ ранга — le={dec(end)} ({counts[b]}); до неё {counts[b - 1]}. Интерполяция: {dec(start)} + "
            f"({dec(end)} − {dec(start)}) × ({dec(round(rank, 2))} − {counts[b - 1]}) / {counts[b] - counts[b - 1]} = "
            f"{dec(round(v, 4))} с, то есть {correct}.")
    stem = (f"Сервис «{ctx}». Что вернёт запрос PromQL ниже по показанным приростам корзин гистограммы "
            "(округлите до миллисекунд)?")
    checks = [Check(name="quantile_model", runner="python",
                    program=MODEL.format(bounds=bounds, counts=counts, q=q), expect="stdout_equals",
                    expected_stdout=correct, embeds_display_code=False)]
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Исполняется модель histogram_quantile над показанными значениями корзин",
                         params={"q": q, "bucket": b})
