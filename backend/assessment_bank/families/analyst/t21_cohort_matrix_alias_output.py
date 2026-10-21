"""analyst.python.t21_cohort_matrix_alias_output — predict_output (набор t21, порог Middle): матрица когорт из
списков — общий объект-строка вместо отдельных строк.

Программа строит матрицу «когорта × неделя» нулями и раскладывает в неё события `(когорта, неделя)`, затем печатает
одну строку матрицы и общую сумму. В большинстве вариантов матрица собрана так, что все строки — ОДИН и тот же
список (`[[0] * w] * n` или `[row for _ in range(n)]`): каждое `+= 1` видно во всех строках, а общая сумма равна
n × число событий. В части вариантов строки независимы (`[[0] * w for _ in range(n)]` или `row[:]`). Ключ —
независимая модель в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "analyst.python.t21_cohort_matrix_alias_output"

# (сюжет, имя матрицы, имя списка событий, что за событие)
CTX = [
    ("удержание: когорта — неделя регистрации, столбец — неделя активности", "retention", "events"),
    ("повторные покупки: когорта — месяц первой покупки, столбец — месяц повтора", "repeat", "purchases"),
    ("активность учеников: поток курса × неделя обучения", "activity", "visits"),
    ("возвраты в приложение: неделя установки × неделя после установки", "returns", "sessions"),
]

FORMS = ["mul_outer", "same_row", "mul_outer", "same_row", "comprehension", "copy_row"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    plot, mat, ev = rng.choice(CTX)
    form = rng.choice(FORMS)
    n = rng.randint(3, 4)
    w = rng.randint(3, 5)
    for _ in range(500):
        k = rng.randint(4, 6)
        events = [(rng.randrange(n), rng.randrange(w)) for _ in range(k)]
        if len({c for c, _w in events}) < 2:
            continue
        show = rng.randrange(n)
        if not any(c == show for c, _w in events) or all(c == show for c, _w in events):
            continue
        break
    else:
        raise RuntimeError("t21_cohort_matrix_alias: не собрались события")
    alias = form in ("mul_outer", "same_row")
    if form == "mul_outer":
        build = f"{mat} = [[0] * weeks] * cohorts\n"
    elif form == "same_row":
        build = f"row = [0] * weeks\n{mat} = [row for _ in range(cohorts)]\n"
    elif form == "copy_row":
        build = f"row = [0] * weeks\n{mat} = [row[:] for _ in range(cohorts)]\n"
    else:
        build = f"{mat} = [[0] * weeks for _ in range(cohorts)]\n"
    code = (f"cohorts = {n}\n"
            f"weeks = {w}\n"
            f"{build}"
            f"{ev} = {events}\n"
            f"for c, wk in {ev}:\n"
            f"    {mat}[c][wk] += 1\n"
            f"print(*{mat}[{show}])\n"
            f"print(sum(sum(r) for r in {mat}))")
    if alias:
        shared = [0] * w
        for _c, wk in events:
            shared[wk] += 1
        line = shared
        total = n * len(events)
    else:
        m = [[0] * w for _ in range(n)]
        for c, wk in events:
            m[c][wk] += 1
        line = m[show]
        total = len(events)
    out = " ".join(str(x) for x in line) + "\n" + str(total)
    stem = (f"Аналитик собирает матрицу когорт ({plot}) из списка событий «(когорта, неделя)» и проверяет одну "
            f"строку и общую сумму.")
    if alias:
        why = ("все строки матрицы — один и тот же список (умножение внешнего списка или генератор, который каждый "
               "раз кладёт тот же объект row), поэтому каждое += 1 видно во всех строках. Любая строка — счётчики по "
               f"неделям по ВСЕМ событиям: {' '.join(map(str, line))}; общая сумма — "
               f"{n} {plural(n, 'строка', 'строки', 'строк')} × {len(events)} "
               f"{plural(len(events), 'событие', 'события', 'событий')} = {total}")
    else:
        why = ("строки матрицы — независимые списки (новый список на каждой итерации или копия row[:]), поэтому "
               f"событие меняет только свою когорту: строка {show} — {' '.join(map(str, line))}, общая сумма "
               f"равна числу событий, {total}")
    expl = f"Здесь {why}. Вывод: «{' '.join(map(str, line))}», «{total}»."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"form": form, "events": events, "show": show}, language="python")
