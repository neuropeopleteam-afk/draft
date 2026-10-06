"""data_ml.repro.rng_split_fix — choose_fix: воспроизводимое разбиение train/test без глобального ГСЧ.

Исходная функция перемешивает индексы глобальным ``random`` (seed задан один раз при импорте
модуля), поэтому любой новый потребитель случайности перед разбиением (аугментация,
инициализация модели, сэмплирование) меняет состав теста — эксперименты перестают быть
сравнимыми. Требования к исправлению: одинаковый результат при одном seed независимо от
обращений к ``random`` в остальном коде; глобальное состояние ``random`` не меняется;
входной список не меняется. Ровно одна из четырёх версий выполняет все три требования
(локальный ``random.Random(seed)``); дистракторы — ``random.seed`` внутри функции (портит
глобальный ГСЧ), то же с сортировкой по ``random.random``, перемешивание самого входного
списка, общий генератор уровня модуля (состояние переходит между вызовами, seed игнорируется).
"""
from __future__ import annotations

import re

from assessment_bank.gen_utils import build_variant, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

from ._dm_utils import balanced_options

FAMILY_ID = "data_ml.repro.rng_split_fix"

CONSUMERS = ["случайную аугментацию (она вызывает `random.random()`)",
             "сэмплирование негативных примеров через `random.sample`",
             "случайную инициализацию весов модели через `random.gauss`",
             "бутстрэп доверительных интервалов через `random.choices`"]
CONTEXTS = [("клиенты банка", "clients", "client"), ("транзакции", "transactions", "tx"),
            ("отзывы покупателей", "reviews", "review"), ("снимки МРТ", "scans", "scan"),
            ("сессии пользователей", "sessions", "session"), ("заявки на кредит", "applications", "app")]
DISTRACTORS = ["global_seed", "global_sort", "shuffle_input", "module_rng"]
NEAR_MISSES = ["near_global_call", "near_unseeded"]


def _tail(rows, share):
    return [f"    n_test = round(len({rows}) * {share})",
            f"    test = [{rows}[i] for i in idx[:n_test]]",
            f"    train = [{rows}[i] for i in idx[n_test:]]",
            "    return train, test"]


def _rename(code, idx, cut):
    return re.sub(r"\bn_test\b", cut, re.sub(r"\bidx\b", idx, code))


def _func(kind, fn, rows, share):
    head = f"def {fn}({rows}, {share}, seed):"
    if kind == "good":
        body = ["    rng = random.Random(seed)", f"    idx = list(range(len({rows})))",
                "    rng.shuffle(idx)"] + _tail(rows, share)
    elif kind == "near_global_call":   # локальный генератор создан, но перемешивает глобальный
        body = ["    rng = random.Random(seed)", f"    idx = list(range(len({rows})))",
                "    random.shuffle(idx)"] + _tail(rows, share)
    elif kind == "near_unseeded":      # локальный генератор без seed
        body = ["    rng = random.Random()", f"    idx = list(range(len({rows})))",
                "    rng.shuffle(idx)"] + _tail(rows, share)
    elif kind == "global_seed":
        body = ["    random.seed(seed)", f"    idx = list(range(len({rows})))",
                "    random.shuffle(idx)"] + _tail(rows, share)
    elif kind == "global_sort":
        body = ["    random.seed(seed)",
                f"    idx = sorted(range(len({rows})), key=lambda _: random.random())"] + _tail(rows, share)
    elif kind == "shuffle_input":
        body = [f"    random.Random(seed).shuffle({rows})",
                f"    n_test = round(len({rows}) * {share})",
                f"    return {rows}[n_test:], {rows}[:n_test]"]
    elif kind == "module_rng":
        return "\n".join(["_RNG = random.Random(42)", "", "", head,
                          f"    idx = list(range(len({rows})))", "    _RNG.shuffle(idx)"]
                         + _tail(rows, share))
    else:
        raise ValueError(kind)
    return "\n".join([head] + body)


def _buggy(fn, rows, share):
    return "\n".join(["import random", "", "random.seed(42)", "", "",
                      f"def {fn}({rows}, {share}):", f"    idx = list(range(len({rows})))",
                      "    random.shuffle(idx)"] + _tail(rows, share))


def _tests(fn, item, n, share, seed, with_seed=True):
    call = (lambda r, s: f"{fn}({r}, {share}, {s})") if with_seed else (lambda r, s: f"{fn}({r}, {share})")
    data = [f"{item}_{i:02d}" for i in range(n)]
    return "\n".join([
        f"data = {data!r}",
        "snapshot = list(data)",
        f"first = {call('data', seed)}",
        "for _ in range(7):",
        "    random.random()",
        f"second = {call('data', seed)}",
        "assert first == second, 'другие потребители random изменили разбиение'",
        "assert data == snapshot, 'входной список изменён'",
        "random.random()",
        "state = random.getstate()",
        f"{call('list(snapshot)', seed)}",
        "assert random.getstate() == state, 'изменено глобальное состояние random'",
        f"train, test = first",
        f"assert len(test) == round({n} * {share}) and sorted(train + test) == sorted(snapshot)",
        f"assert {call('list(snapshot)', seed + 1)} != first, 'seed не влияет на разбиение'",
    ])


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, rows, item = rng.choice(CONTEXTS)
    fn = rng.choice(["split_rows", "train_test_split", "make_split", "holdout_split"])
    share = rng.choice(["test_share", "test_size", "test_frac"])
    n = rng.randint(20, 40)
    frac = rng.choice([0.2, 0.25, 0.3])
    tseed = rng.randint(1, 999)
    # Версия 2 (калибровка 05.10: решалась малыми моделями — все дистракторы явно трогали
    # глобальный random или входной список, верный узнавался по `random.Random(seed)`).
    # Теперь всегда есть «почти верный» вариант, отличающийся от ключа одним токеном.
    chosen = [rng.choice(NEAR_MISSES)] + rng.sample(DISTRACTORS, 2)
    idx_name = rng.choice(["idx", "order", "perm", "positions"])
    cut_name = rng.choice(["n_test", "cut", "k_test", "border"])
    ren = lambda c: _rename(c, idx_name, cut_name)
    buggy = ren(_buggy(fn, rows, share))
    opts, key = balanced_options(FAMILY_ID, seed, rng, ("Заменить функцию на:", ren(_func("good", fn, rows, share))),
                                 [("Заменить функцию на:", ren(_func(d, fn, rows, share))) for d in chosen])
    tests_seed = _tests(fn, item, n, frac, tseed)
    tests_buggy = _tests(fn, item, n, frac, tseed, with_seed=False)
    checks = [Check(name="buggy_fails", runner="python", program=py_harness(buggy, tests_buggy),
                    expect="fail")]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="python",
                            program=py_harness("import random\n\n\n" + o.code, tests_seed),
                            embeds_display_code=False, expect="pass" if o.id == key else "fail"))
    consumer = rng.choice(CONSUMERS)
    intro = rng.choice([
        f"Данные — {ctx}. Функция разбиения на обучение и тест перемешивает индексы глобальным "
        f"генератором `random`, seed задаётся один раз при импорте модуля.",
        f"Пайплайн обучения ({ctx}) делит выборку на обучение и тест функцией `{fn}`; она "
        f"берёт случайность из глобального модуля `random`, а `random.seed(42)` вызывается при "
        f"импорте.",
        f"В проекте ({ctx}) разбиение на обучение и тест делает `{fn}` через глобальный "
        f"`random`; воспроизводимость, как считала команда, обеспечивает `random.seed(42)` в "
        f"начале модуля."])
    stem = (f"{intro} Перед разбиением в пайплайн добавили {consumer} — состав теста изменился, "
            f"и метрики новых экспериментов нельзя сравнить со старыми. Нужна версия с "
            f"параметром `seed`, которая: (1) при одном seed даёт одно и то же разбиение "
            f"независимо от обращений к `random` в остальном коде; (2) не меняет глобальное "
            f"состояние модуля `random` — от него зависят другие этапы; (3) не меняет входной "
            f"список. Какая замена выполняет все три требования?")
    why = {"near_global_call": "локальный генератор создан, но перемешивание вызывает глобальный "
                               "random.shuffle — результат зависит от других потребителей, а "
                               "глобальное состояние меняется (требования 1 и 2)",
           "near_unseeded": "random.Random() без аргумента берёт seed из системной энтропии — "
                            "параметр seed игнорируется, разбиение не воспроизводится (требование 1)",
           "global_seed": "random.seed внутри функции сбрасывает глобальный генератор — "
                          "меняется случайность остальных этапов (нарушено требование 2)",
           "global_sort": "сортировка по random.random после random.seed тоже меняет "
                          "глобальное состояние (требование 2)",
           "shuffle_input": "перемешивается сам входной список — меняются данные вызывающего "
                            "кода, а повторный вызов перемешивает уже перемешанное (требования 1 и 3)",
           "module_rng": "генератор уровня модуля игнорирует seed и продолжает последовательность "
                         "между вызовами — второй вызов даёт другое разбиение (требование 1)"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=("Локальный random.Random(seed) — независимый поток случайности: "
                                "результат зависит только от seed и не затрагивает глобальный "
                                "генератор. Дистракторы: " + "; ".join(why[d] for d in chosen) + "."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="global_rng_state",
                         params={"distractors": chosen, "n": n, "frac": frac, "tseed": tseed})
