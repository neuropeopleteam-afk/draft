"""data_ml.fe.onehot_serving_fix — choose_fix: one-hot кодирование на инференсе (training-serving skew).

Исходная функция строит словарь категорий по текущему батчу: при онлайн-инференсе (одна
строка) вектор получается длины 1, порядок признаков не совпадает с обучением. Нужно
выбрать реализацию, которая использует категории из обучения, сохраняет их порядок и
кодирует неизвестную категорию нулевым вектором, не падая. Дистракторы: KeyError на новой
категории, объединение словарей (меняется длина), «последняя категория» для неизвестных,
общий список-вектор на все строки.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, dedent, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

from ._dm_utils import balanced_options

FAMILY_ID = "data_ml.fe.onehot_serving_fix"

# (столбец, значения при обучении, новые значения, контекст)
CONTEXTS = [
    ("city", ["kazan", "moscow", "omsk", "perm", "tula"], ["sochi", "ufa"], "прогноз спроса"),
    ("device", ["android", "ios", "smart_tv", "web"], ["car", "watch"], "рекомендации видео"),
    ("channel", ["ads", "email", "organic", "partner"], ["podcast", "tiktok"], "атрибуция маркетинга"),
    ("payment", ["card", "cash", "sbp", "wallet"], ["bnpl", "crypto"], "антифрод"),
    ("tariff", ["basic", "family", "pro", "start"], ["corp", "student"], "прогноз оттока"),
]
DISTRACTORS = ["keyerror", "union", "last_index", "shared_vec"]


def _impl(kind, fn, col, nm):
    I, V, O, R = nm["index"], nm["vec"], nm["out"], nm["row"]
    if kind == "union":
        return "\n".join([
            f"def {fn}(rows, column, categories):",
            f"    cats = sorted(set(categories) | {{{R}[column] for {R} in rows}})",
            f"    {O} = []",
            f"    for {R} in rows:",
            f"        {V} = [1 if {R}[column] == c else 0 for c in cats]",
            f"        {O}.append({V})",
            f"    return {O}"])
    head = [f"def {fn}(rows, column, categories):",
            f"    {I} = {{c: i for i, c in enumerate(categories)}}",
            f"    {O} = []"]
    if kind == "shared_vec":
        head.append(f"    {V} = [0] * len(categories)")
    body = [f"    for {R} in rows:"]
    if kind != "shared_vec":
        body.append(f"        {V} = [0] * len(categories)")
    if kind in ("good", "shared_vec"):
        body += [f"        if {R}[column] in {I}:", f"            {V}[{I}[{R}[column]]] = 1"]
    elif kind == "keyerror":
        body += [f"        {V}[{I}[{R}[column]]] = 1"]
    else:  # last_index
        body += [f"        {V}[{I}.get({R}[column], len(categories) - 1)] = 1"]
    body += [f"        {O}.append({V})", f"    return {O}"]
    return "\n".join(head + body)


def _expected(rows, col, cats):
    out = []
    for r in rows:
        out.append([1 if r[col] == c else 0 for c in cats])
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    col, train_vals, new_vals, ctx = rng.choice(CONTEXTS)
    fn = rng.choice(["one_hot", "encode_onehot", "to_dummies"])
    fit_fn = rng.choice(["fit_categories", "learn_vocabulary"])
    buggy = dedent(f"""
        def {fit_fn}(rows, column):
            return sorted({{r[column] for r in rows}})


        def {fn}(rows, column, categories):
            batch_categories = sorted({{r[column] for r in rows}})
            return [[1 if r[column] == c else 0 for c in batch_categories] for r in rows]""")
    chosen = rng.sample(DISTRACTORS, 3)
    nm = dict(index=rng.choice(["index", "position", "lookup"]),
              vec=rng.choice(["vec", "features", "one_hot_row"]),
              out=rng.choice(["out", "result", "encoded"]),
              row=rng.choice(["r", "row", "item"]))
    good = _impl("good", fn, col, nm)
    opts, key = balanced_options(FAMILY_ID, seed, rng, (f"Заменить функцию {fn} на:", good),
                             [(f"Заменить функцию {fn} на:", _impl(d, fn, col, nm)) for d in chosen])
    train = [{col: v} for v in rng.sample(train_vals, len(train_vals))] + [{col: rng.choice(train_vals)}]
    cats = sorted(train_vals)
    online = [{col: rng.choice(train_vals)}]
    batch = [{col: rng.choice(train_vals)}, {col: rng.choice(new_vals)}, {col: rng.choice(train_vals)}]
    tests = dedent(f"""
        cats = {fit_fn}({train!r}, {col!r})
        assert cats == {cats!r}
        assert {fn}({online!r}, {col!r}, cats) == {_expected(online, col, cats)!r}
        assert {fn}({batch!r}, {col!r}, cats) == {_expected(batch, col, cats)!r}""")
    fit_src = buggy.split("\n\n\n")[0]
    checks = [Check(name="buggy_fails", runner="python", program=py_harness(buggy, tests), expect="fail")]
    for o in opts:
        prog = py_harness(fit_src + "\n\n\n" + o.code, tests)
        checks.append(Check(name=f"option:{o.id}", runner="python", program=prog,
                            embeds_display_code=False,
                            expect="pass" if o.id == key else "fail"))
    unseen = rng.choice(new_vals)
    stem = (f"Модель ({ctx}) обучена на признаках one-hot по столбцу `{col}`; категории "
            f"запомнены функцией `{fit_fn}` при обучении: {cats!r}. В онлайне сервис получает по одной "
            f"строке, и модель падает с ошибкой размерности; кроме того, в потоке появилась "
            f"новая категория `{unseen}`. Требование: вектор длины len(categories) в порядке "
            f"категорий обучения, неизвестная категория кодируется нулевым вектором, функция не "
            f"падает. Какое исправление функции `{fn}` верно?")
    why = {"keyerror": "обращение index[r[column]] падает с KeyError на новой категории",
           "union": "объединение с категориями батча меняет длину и порядок вектора",
           "last_index": "неизвестная категория молча кодируется как последняя известная",
           "shared_vec": "один список vec на все строки: единицы накапливаются, а все строки "
                         "ссылаются на один и тот же объект"}
    ak = AnswerKey(kind="option", value=key,
                   explanation="Словарь категорий фиксируется при обучении и передаётся на "
                               "инференс; новый объект — новый вектор нулей, единица только для "
                               "известной категории. Ошибки дистракторов: "
                               + "; ".join(why[d] for d in chosen) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="training_serving_skew", params={"distractors": chosen})
