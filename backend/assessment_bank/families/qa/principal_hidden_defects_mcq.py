"""qa.principal.hidden_defects_mcq — mcq_concept (Principal, короткое): сколько дефектов ещё не найдено, если две
команды тестировали независимо, а находимость дефектов разных классов разная.

Для каждого класса дефектов (слоя) известны: нашла команда 1 — n1, команда 2 — n2, обе — m. Оценка числа
дефектов слоя по двум независимым «уловам» — n1·n2 / m (Линкольн — Петерсен), ненайденных в слое — n1·n2 / m −
(n1 + n2 − m). Ключ — сумма по слоям (округлённая): внутри слоя находимость одинакова, между слоями — нет.

Ловушки: ниже ключа — ``pooled`` (одна оценка по сумме слоёв: при разной находимости занижает), ``minus_sum``
(вычитают n1 + n2, дважды считая общие); выше — ``total`` (вся оценка вместо ненайденных), ``minus_max``
(вычитают только улов лучшей команды); ``unique_only`` (n1 + n2 − 2m: «найденные одной командой» вместо
ненайденных) — с любой стороны. Сколько ловушек меньше ключа — 0–2 равновероятно. Ключ проверяется исполнением:
программа строит списки найденных дефектов по слоям как множества идентификаторов и считает оценку по ним точными
дробями.
"""
from __future__ import annotations

from assessment_bank.families._principal_c_utils import formatter, numeric_mcq, pick_traps
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.principal.hidden_defects_mcq"

CONTEXTS = [("мобильный банк", "интерфейс и тексты", "расчёты и интеграции"),
            ("портал госуслуг", "формы и навигация", "проверки данных и статусы заявлений"),
            ("система бронирования", "экраны поиска", "тарифы и отмены"),
            ("платёжный шлюз", "кабинет мерчанта", "клиринг и возвраты"),
            ("складская система", "экраны операторов", "резервирование и остатки"),
            ("CRM для продаж", "карточки и списки", "права доступа и синхронизация")]

PROGRAM = """from fractions import Fraction as F

{fmt}
LAYERS = {layers!r}         # слой -> (только команда 1, только команда 2, обе)
total_hidden = F(0)
for name, (only1, only2, both) in LAYERS.items():
    ids = iter(range(10**6))
    common = {{next(ids) for _ in range(both)}}
    team1 = common | {{next(ids) for _ in range(only1)}}
    team2 = common | {{next(ids) for _ in range(only2)}}
    estimate = F(len(team1) * len(team2), len(team1 & team2))   # оценка числа дефектов слоя
    total_hidden += estimate - len(team1 | team2)
print(fmt(float(total_hidden)))
"""


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, l1, l2 = rng.choice(CONTEXTS)
    n_below = rng.choice([0, 1, 2])
    fmt, fmt_src = formatter("int", "деф.")
    for _ in range(8000):
        # слой 1 — легко находимые: высокая доля общих; слой 2 — трудные: общих мало
        a1, b1, m1 = rng.choice([40, 50, 60, 80]), rng.choice([40, 50, 60, 70]), 0
        m1 = rng.choice([25, 30, 35, 40])
        a2, b2 = rng.choice([10, 12, 15, 18, 20]), rng.choice([8, 10, 12, 15, 18])
        m2 = rng.choice([2, 3, 4, 5])
        if m1 >= min(a1, b1) or m2 >= min(a2, b2):
            continue
        hid = lambda n1, n2, m: n1 * n2 / m - (n1 + n2 - m)  # noqa: E731
        good = hid(a1, b1, m1) + hid(a2, b2, m2)
        N1, N2, M = a1 + a2, b1 + b2, m1 + m2
        est = lambda n1, n2, m: n1 * n2 / m  # noqa: E731
        pool = {"pooled": hid(N1, N2, M), "minus_sum": est(a1, b1, m1) + est(a2, b2, m2) - N1 - N2,
                "total": est(a1, b1, m1) + est(a2, b2, m2),
                "minus_max": est(a1, b1, m1) + est(a2, b2, m2) - max(N1, N2),
                "unique_only": N1 + N2 - 2 * M}
        traps = pick_traps(good, pool, n_below, rng, fmt, "int", rel=0.08, lo=10, hi=100)
        if traps:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    code = "\n".join(["Слой | нашла команда 1 | нашла команда 2 | нашли обе",
                      f"«{l1}» | {a1} | {b1} | {m1}",
                      f"«{l2}» | {a2} | {b2} | {m2}",
                      "Команды тестировали независимо; внутри слоя дефекты находятся одинаково легко."])
    stem = (f"{ctx[0].upper() + ctx[1:]}: перед выпуском две команды независимо тестировали одну сборку. Руководитель "
            f"программы качества спрашивает, сколько дефектов в сборке ещё не найдено. Какова оценка?")
    why = (f"В каждом слое оценка числа дефектов — n1·n2 / m, ненайденных — n1·n2 / m − (n1 + n2 − m); сумма по "
           f"слоям — {fmt(good)}. Ошибки: одна оценка по сумме слоёв — {fmt(pool['pooled'])} (трудные дефекты "
           f"разбавляются лёгкими); вычли n1 + n2 — {fmt(pool['minus_sum'])}; вся оценка — {fmt(pool['total'])}; "
           f"вычли улов лучшей команды — {fmt(pool['minus_max'])}; найденные одной командой — "
           f"{fmt(pool['unique_only'])}. Вывод: остаточные дефекты оценивают по слоям с одинаковой находимостью — "
           f"общая оценка занижает хвост трудных дефектов.")
    why = why.replace("деф..", "деф.")
    program = PROGRAM.format(fmt=fmt_src, layers={l1: (a1 - m1, b1 - m1, m1), l2: (a2 - m2, b2 - m2, m2)})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=good, pool=pool, traps=traps, fmt=fmt,
                       program=program, why=why, code=code,
                       params={"layer1": [a1, b1, m1], "layer2": [a2, b2, m2]},
                       note="Программа строит множества найденных дефектов по слоям и считает оценку точными дробями.")
