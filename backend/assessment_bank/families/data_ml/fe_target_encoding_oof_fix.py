"""data_ml.features.target_encoding_oof_fix — choose_fix: кодирование категории средним цели вне своего фолда.

Порог Middle/Senior. Показанная функция считает статистику категории по всем строкам, включая саму строку, —
у редких категорий код почти равен собственной цели (утечка). Нужна схема out-of-fold: для строк фолда f — среднее
цели категории по строкам других фолдов со сглаживанием к среднему этих строк. Варианты (состав фиксирован,
отличаются одной строкой):
* верный — статистика по строкам `j % k != f`, запись — строкам `i % k == f`;
* статистика по своему фолду (`j % k == f`);
* исключена одна строка с номером f (`j != f`), а не фолд;
* статистика верная, но запись — в строки других фолдов (`i % k != f`), последний фолд перезаписывает.
Проверка исполнением: код строки i не меняется при изменении её цели (и цели её фолда); значения совпадают с
независимым расчётом.
"""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from assessment_bank.families.common._plus_utils import fix_options_variant

FAMILY_ID = "data_ml.features.target_encoding_oof_fix"

CONTEXTS = [("скоринг заявок", "город заявителя"), ("отток абонентов", "тарифный план"),
            ("клики по рекламе", "площадка"), ("возвраты товаров", "бренд"),
            ("просрочка платежей", "отрасль клиента"), ("отклики на вакансии", "профессия")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, cat_name = rng.choice(CONTEXTS)
    fn = rng.choice(["target_encode", "oof_encode", "encode_category"])
    k_def = rng.choice([4, 5])
    m_def = rng.choice([5, 10, 20])
    st = rng.choice(["stats", "agg", "sums"])
    ov = rng.choice(["out", "enc", "codes"])
    rv = rng.choice(["rows", "src", "fit_rows"])
    pv = rng.choice(["prior", "base", "global_mean"])

    def func(rows_expr: str, assign_cond: str) -> str:
        return (f"def {fn}(cats, ys, k={k_def}, m={m_def}):\n    n = len(cats)\n    {ov} = [0.0] * n\n"
                f"    for f in range(k):\n        {rv} = {rows_expr}\n"
                f"        {pv} = sum(ys[j] for j in {rv}) / len({rv})\n        {st} = {{}}\n"
                f"        for j in {rv}:\n            s, c = {st}.get(cats[j], (0, 0))\n"
                f"            {st}[cats[j]] = (s + ys[j], c + 1)\n        for i in range(n):\n"
                f"            if {assign_cond}:\n                s, c = {st}.get(cats[i], (0, 0))\n"
                f"                {ov}[i] = (s + m * {pv}) / (c + m)\n    return {ov}\n")

    buggy = func("list(range(n))", "i % k == f")
    correct = func("[j for j in range(n) if j % k != f]", "i % k == f")
    distractors = [func("[j for j in range(n) if j % k == f]", "i % k == f"),
                   func("[j for j in range(n) if j != f]", "i % k == f"),
                   func("[j for j in range(n) if j % k != f]", "i % k != f")]
    n = rng.randint(14, 20)
    cats = [rng.choice("ABCD") for _ in range(n)]
    cats[rng.randrange(n)] = "Z"
    ys = [rng.randint(0, 1) for _ in range(n)]
    test = f"""
cats, ys = {cats!r}, {ys!r}
k, m = 3, 4
def ref(cats, ys, k, m):
    n = len(cats)
    res = []
    for i in range(n):
        other = [j for j in range(n) if j % k != i % k]
        p = sum(ys[j] for j in other) / len(other)
        same = [ys[j] for j in other if cats[j] == cats[i]]
        res.append((sum(same) + m * p) / (len(same) + m))
    return res
a = {fn}(cats, ys, k, m)
assert all(abs(x - y) < 1e-12 for x, y in zip(a, ref(cats, ys, k, m)))
for i in range(len(cats)):
    ys2 = list(ys)
    for j in range(len(cats)):
        if j % k == i % k:
            ys2[j] = 1 - ys2[j]
    assert abs({fn}(cats, ys2, k, m)[i] - a[i]) < 1e-12, i
"""
    stem = (f"ML ({ctx}). Признак «{cat_name}» кодируется средним цели (target encoding) по схеме out-of-fold со "
            f"сглаживанием: для строк фолда f — статистика категории по строкам других фолдов, `m` — сила "
            f"сглаживания к их среднему. На кросс-валидации модель заметно лучше, чем на новых данных, особенно "
            f"на редких категориях. Какая замена функции исправляет кодирование?")
    why = ("Код строки не должен зависеть от её собственной цели: статистика для строк фолда f считается только по "
           "строкам других фолдов (`j % k != f`) и записывается только строкам фолда f. Статистика по всем строкам "
           "или по своему фолду включает цель самой строки (у редкой категории код ≈ её цели); исключение одной строки "
           "с номером f — не исключение фолда; запись в строки других фолдов снова смешивает их с собственной целью.")
    return fix_options_variant(FAMILY_ID, seed, rng, stem=stem, buggy=buggy, correct=correct,
                               distractors=distractors, test=test, context=ctx, defect="target_encoding_in_fold_leak",
                               why=why, params={"n": n})
