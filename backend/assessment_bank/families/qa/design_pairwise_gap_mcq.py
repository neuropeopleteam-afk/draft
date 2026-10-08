"""qa.design.pairwise_gap_mcq — mcq_concept: какая пара значений не покрыта набором тестов.

Попарное тестирование (all-pairs): каждая пара значений любых двух параметров должна
встретиться хотя бы в одном тесте. Генератор строит жадное покрытие всех пар, затем убирает
или меняет один тест так, чтобы часть пар осталась непокрытой, и перемешивает строки.
Вопрос: какая из четырёх пар не встречается ни в одном тесте (остальные три встречаются,
по возможности ровно один раз — «трудные» дистракторы). Ключ проверяется исполнением:
программа по показанной таблице считает покрытие пар и печатает непокрытую пару из вариантов.
"""
from __future__ import annotations

import itertools

from assessment_bank.gen_utils import build_variant, make_rng, plural, text_table
from assessment_bank.schema import AnswerKey, Check

from ._qa_utils import balanced_options, check_lengths

FAMILY_ID = "qa.design.pairwise_gap_mcq"

CONTEXTS = [
    ("веб-приложение банка", [("Браузер", ["Chrome", "Firefox", "Safari"]),
                              ("ОС", ["Windows", "macOS", "Linux"]),
                              ("Язык", ["ru", "en"]),
                              ("Вход", ["пароль", "VK ID", "Госуслуги"])]),
    ("форма оплаты", [("Способ", ["карта", "СБП", "баланс"]),
                      ("Валюта", ["RUB", "USD", "CNY"]),
                      ("Устройство", ["десктоп", "телефон"]),
                      ("Клиент", ["новый", "постоянный"])]),
    ("мобильное приложение доставки", [("ОС", ["Android", "iOS"]),
                                       ("Сеть", ["Wi-Fi", "4G", "3G"]),
                                       ("Тема", ["светлая", "тёмная"]),
                                       ("Адрес", ["дом", "офис", "пункт"])]),
    ("личный кабинет кандидата", [("Роль", ["кандидат", "работодатель", "жюри"]),
                                  ("Браузер", ["Chrome", "Яндекс", "Safari"]),
                                  ("Экран", ["узкий", "широкий"]),
                                  ("ФСП ID", ["есть", "нет"])]),
    ("сервис бронирования", [("Тариф", ["эконом", "стандарт", "бизнес"]),
                             ("Оплата", ["сразу", "при заезде"]),
                             ("Гостей", ["1", "2", "4"]),
                             ("Отмена", ["платная", "бесплатная"])]),
]


def _pairs_of(row):
    return {((i, row[i]), (j, row[j])) for i, j in itertools.combinations(range(len(row)), 2)}


def _all_pairs(params):
    out = set()
    for i, j in itertools.combinations(range(len(params)), 2):
        for a in params[i][1]:
            for b in params[j][1]:
                out.add(((i, a), (j, b)))
    return out


def _greedy(rng, params):
    need = _all_pairs(params)
    rows = []
    combos = list(itertools.product(*[p[1] for p in params]))
    while need:
        best = max(len(_pairs_of(c) & need) for c in combos)
        cands = [c for c in combos if len(_pairs_of(c) & need) == best]
        row = rng.choice(cands)
        rows.append(list(row))
        need -= _pairs_of(row)
    return rows


PROGRAM = '''import itertools

HEADER = {header!r}
ROWS = {rows!r}
OPTIONS = {options!r}   # (текст, (параметр1, значение1), (параметр2, значение2))
covered = set()
for r in ROWS:
    for i, j in itertools.combinations(range(len(HEADER)), 2):
        covered.add(((HEADER[i], r[i]), (HEADER[j], r[j])))
        covered.add(((HEADER[j], r[j]), (HEADER[i], r[i])))
gaps = [text for text, a, b in OPTIONS if (tuple(a), tuple(b)) not in covered]
print(" | ".join(gaps))
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, all_params = rng.choice(CONTEXTS)
    k = rng.choice([3, 4])
    params = rng.sample(all_params, k) if k == 3 else list(all_params)
    params = [(n, rng.sample(vals, len(vals))) for n, vals in params]
    for _ in range(300):
        rows = _greedy(rng, params)
        mode = rng.choice(["drop", "change"])
        victim = rng.randrange(len(rows))
        if mode == "drop":
            rows = rows[:victim] + rows[victim + 1:]
        else:
            col = rng.randrange(k)
            vals = [v for v in params[col][1] if v != rows[victim][col]]
            rows[victim] = rows[victim][:col] + [rng.choice(vals)] + rows[victim][col + 1:]
        cnt: dict = {}
        for r in rows:
            for p in _pairs_of(r):
                cnt[p] = cnt.get(p, 0) + 1
        gaps = sorted(_all_pairs(params) - set(cnt))
        once = sorted(p for p, c in cnt.items() if c == 1)
        if gaps and len(once) >= 3 and len(set(map(tuple, rows))) == len(rows):
            break
    else:
        raise RuntimeError("не удалось построить набор")
    rng.shuffle(rows)
    gap = rng.choice(gaps)
    distract = rng.sample(once, 3)

    def txt(p):
        (i, a), (j, b) = p
        return f"{params[i][0]} = {a}, {params[j][0]} = {b}"

    texts = [txt(gap)] + [txt(p) for p in distract]
    check_lengths(texts, max_ratio=1.5, slack=8)
    opts, key = balanced_options(FAMILY_ID, seed, rng, (texts[0], None), [(t, None) for t in texts[1:]])
    header = [p[0] for p in params]
    table = text_table(["№"] + header, [[n + 1] + r for n, r in enumerate(rows)])
    by_text = {txt(p): p for p in [gap] + distract}
    options = [(o.text, (header[by_text[o.text][0][0]], by_text[o.text][0][1]),
                (header[by_text[o.text][1][0]], by_text[o.text][1][1])) for o in opts]
    program = PROGRAM.format(header=header, rows=rows, options=options)
    total = 1
    for p in params:
        total *= len(p[1])
    sizes = " × ".join(str(len(p[1])) for p in params) + f" = {total}"
    stem = (f"Тестируется {ctx}. Параметры конфигурации и их значения: "
            + "; ".join(f"{n} — {', '.join(v)}" for n, v in params)
            + f" (полный перебор — {sizes} {plural(total, "комбинация", "комбинации", "комбинаций")}). Тестировщик составил набор из {len(rows)} "
            f"тестов и утверждает, что он покрывает все пары значений (pairwise). Какая из пар "
            f"значений не встречается ни в одном тесте набора?")
    ak = AnswerKey(kind="option", value=key,
                   explanation=(f"Пара «{texts[0]}» не встречается ни в одной строке таблицы. "
                                f"Остальные пары из вариантов встречаются ровно в одном тесте "
                                f"(их легко принять за непокрытые). Всего непокрытых пар: "
                                f"{len(gaps)}."))
    checks = [Check(name="pairs", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=texts[0], embeds_display_code=False)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=table, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks, language="text",
                         display_code_note="Показана таблица тестов; программа считает покрытие "
                                           "пар по тем же строкам.",
                         params={"k": k, "n_rows": len(rows), "n_gaps": len(gaps), "mode": mode})
