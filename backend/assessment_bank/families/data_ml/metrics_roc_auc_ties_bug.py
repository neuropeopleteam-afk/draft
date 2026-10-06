"""data_ml.metrics.roc_auc_ties_bug — find_bug: ROC-AUC вручную неверно учитывает одинаковые скоры.

Скоры модели округлены (корзины калибровки, два знака), поэтому одинаковых значений много.
ROC-AUC = доля пар (позитив, негатив), где позитив получил скор выше, плюс половина пар с
равными скорами (эквивалентно статистике Манна — Уитни со средними рангами). Две реализации:

* попарная — дефект в строке сравнения (``>=`` вместо ``>``: ничья считается победой) или в
  строке веса ничьей (``1.0`` вместо ``0.5``);
* ранговая — дефект в строке присвоения ранга внутри группы равных скоров (порядковый ранг
  ``t + 1`` или минимальный ``i + 1`` вместо среднего ``(i + j) / 2 + 1``).

Ключ проверяется исполнением: показанная функция падает на эталонных значениях (данные с
ничьими), исправленная проходит; пример в условии вычислен независимой моделью и сверяется
с выводом показанного кода.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_ml.metrics.roc_auc_ties_bug"

CONTEXTS = [("антифрод", "is_fraud"), ("прогноз оттока", "churned"), ("кредитный скоринг", "default"),
            ("модерация отзывов", "toxic"), ("рекомендации", "clicked"), ("медицинский скрининг", "sick")]
SUBTYPES = ["pair_ge", "pair_weight", "rank_ordinal", "rank_min"]


def _pairwise(sub, fn, y, s):
    cmp_line = "            if p >= n:" if sub == "pair_ge" else "            if p > n:"
    tie_w = "1.0" if sub == "pair_weight" else "0.5"
    return "\n".join([
        f"def {fn}({y}, {s}):",
        f"    pos = [v for t, v in zip({y}, {s}) if t == 1]",
        f"    neg = [v for t, v in zip({y}, {s}) if t == 0]",
        "    if not pos or not neg:",
        "        raise ValueError(\"нужны оба класса\")",
        "    total = 0.0",
        "    for p in pos:",
        "        for n in neg:",
        cmp_line,
        "                total += 1.0",
        "            elif p == n:",
        f"                total += {tie_w}",
        "    return total / (len(pos) * len(neg))"])


def _rank(sub, fn, y, s):
    rank_expr = {"rank_ordinal": "t + 1", "rank_min": "i + 1"}.get(sub, "(i + j) / 2 + 1")
    return "\n".join([
        f"def {fn}({y}, {s}):",
        f"    order = sorted(range(len({s})), key=lambda k: {s}[k])",
        f"    ranks = [0.0] * len({s})",
        "    i = 0",
        "    while i < len(order):",
        "        j = i",
        f"        while j + 1 < len(order) and {s}[order[j + 1]] == {s}[order[i]]:",
        "            j += 1",
        "        for t in range(i, j + 1):",
        f"            ranks[order[t]] = {rank_expr}",
        "        i = j + 1",
        f"    n_pos = sum(1 for t in {y} if t == 1)",
        f"    n_neg = len({y}) - n_pos",
        f"    r_pos = sum(r for r, t in zip(ranks, {y}) if t == 1)",
        "    return (r_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)"])


def _code(sub, fn, y, s, fixed=False):
    real = ("pair_ok" if sub.startswith("pair") else "rank_ok") if fixed else sub
    return _pairwise(real, fn, y, s) if sub.startswith("pair") else _rank(real, fn, y, s)


def _ref_auc(labels, scores):
    """Независимая модель: попарное сравнение, ничья = 0,5."""
    pos = [v for t, v in zip(labels, scores) if t == 1]
    neg = [v for t, v in zip(labels, scores) if t == 0]
    tot = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return tot / (len(pos) * len(neg))


def _buggy_model(sub, labels, scores):
    """Независимая модель дефектной функции (для примера в условии)."""
    if sub in ("pair_ge", "pair_weight"):
        pos = [v for t, v in zip(labels, scores) if t == 1]
        neg = [v for t, v in zip(labels, scores) if t == 0]
        tot = sum(1.0 if p >= n else 0.0 for p in pos for n in neg)
        return tot / (len(pos) * len(neg))
    order = sorted(range(len(scores)), key=lambda k: scores[k])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        for t in range(i, j + 1):
            ranks[order[t]] = t + 1 if sub == "rank_ordinal" else i + 1
        i = j + 1
    n_pos = sum(labels)
    r_pos = sum(r for r, t in zip(ranks, labels) if t == 1)
    return (r_pos - n_pos * (n_pos + 1) / 2) / (n_pos * (len(labels) - n_pos))


def _dataset(rng, n, grid):
    for _ in range(1000):
        labels = [rng.randint(0, 1) for _ in range(n)]
        if not 2 <= sum(labels) <= n - 2:
            continue
        scores = [round(rng.choice(grid), 2) for _ in range(n)]
        pos = {v for t, v in zip(labels, scores) if t == 1}
        neg = {v for t, v in zip(labels, scores) if t == 0}
        if pos & neg:  # есть хотя бы одна ничья позитив/негатив
            return labels, scores
    raise RuntimeError("не удалось построить данные с ничьими")


# Калибровка 05.10: подтипы pair_ge выделены в data_ml.metrics.auc_pairwise_ties_bug (варианты были неизоморфны).
SUBTYPES_HERE = ('rank_ordinal', 'rank_min')


def _generate(seed: int, family_id: str, subtypes):
    rng = make_rng(family_id, seed)
    ctx, target = rng.choice(CONTEXTS)
    sub = rng.choice(list(subtypes))
    fn = rng.choice(["roc_auc", "auc_score", "manual_auc"])
    y = rng.choice(["y_true", "labels", target])
    s = rng.choice(["y_score", "scores", "proba"])
    buggy, fixed = _code(sub, fn, y, s), _code(sub, fn, y, s, fixed=True)
    # 0–2 строки нейтрального комментария сверху: номер строки дефекта не постоянен
    hdr = rng.choice(["", "# Ручной расчёт метрики для отчёта.\n",
                      "# Метрика качества модели без sklearn.\n# Используется в ночном отчёте.\n"])
    buggy, fixed = hdr + buggy, hdr + fixed
    key_line = min(changed_lines(buggy, fixed))
    assert changed_lines(buggy, fixed) == {key_line}
    grid = [x / 20 for x in range(2, 19)] if rng.random() < 0.5 else [x / 10 for x in range(1, 10)]
    # пример в условии: ничьи есть, и дефект на нём заметен
    for _ in range(200):
        ex_y, ex_s = _dataset(rng, rng.randint(6, 8), grid)
        ref, bad = _ref_auc(ex_y, ex_s), _buggy_model(sub, ex_y, ex_s)
        if abs(ref - bad) > 1e-6:
            break
    else:
        raise RuntimeError("пример не показывает дефект")
    cases = [_dataset(rng, rng.randint(8, 14), grid) for _ in range(3)]
    cases.append(([0, 1, 0, 1, 1, 0], [0.5, 0.5, 0.5, 0.5, 0.5, 0.5]))
    cases.append(([1, 0, 1, 0], [0.9, 0.1, 0.8, 0.3]))  # без ничьих
    tests = "\n".join(f"assert abs({fn}({cy!r}, {cs!r}) - {_ref_auc(cy, cs)!r}) < 1e-9"
                      for cy, cs in cases)
    example_prog = buggy + f"\n\n\nprint(round({fn}({ex_y!r}, {ex_s!r}), 4))\n"
    checks = [
        Check(name="buggy_fails", runner="python", program=py_harness(buggy, tests), expect="fail"),
        Check(name="fixed_passes", runner="python", program=py_harness(fixed, tests),
              embeds_display_code=False, expect="pass"),
        Check(name="stem_example", runner="python", program=example_prog,
              expect="stdout_equals", expected_stdout=str(round(bad, 4))),
    ]
    stem = (f"Задача: {ctx}, целевая переменная `{target}`. Модель выдаёт скоры, округлённые до "
            f"двух знаков, поэтому одинаковых значений много. Аналитик написал собственную "
            f"функцию ROC-AUC, чтобы не тянуть sklearn в сервис мониторинга. На данных "
            f"{y} = {ex_y}, {s} = {ex_s} функция вернула {round(bad, 4)}, а "
            f"`sklearn.metrics.roc_auc_score` — {round(ref, 4)}. ROC-AUC — вероятность того, что "
            f"случайный позитивный объект получит скор выше случайного негативного; пара с "
            f"равными скорами считается за половину. Укажите номер строки с ошибкой.")
    why = {"pair_ge": "условие `p >= n` засчитывает пару с равными скорами как полную победу "
                      "позитива, и ветка `elif p == n` никогда не выполняется; нужно `p > n`",
           "pair_weight": "пара с равными скорами получает вес 1.0, а должна 0.5",
           "rank_ordinal": "внутри группы равных скоров ранги идут подряд (t + 1) в порядке "
                           "исходных индексов — результат зависит от порядка строк; нужен средний "
                           "ранг (i + j) / 2 + 1",
           "rank_min": "всем равным скорам присваивается минимальный ранг группы (i + 1); "
                       "нужен средний ранг (i + j) / 2 + 1"}
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=f"Строка {key_line}: {why[sub]}. На данных без одинаковых скоров "
                               "ошибка не проявляется, поэтому её легко пропустить.")
    return build_variant(family_id, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="tie_handling",
                         params={"fixed_code": fixed, "subtype": sub, "fn": fn})



def generate(seed: int):
    return _generate(seed, FAMILY_ID, SUBTYPES_HERE)
