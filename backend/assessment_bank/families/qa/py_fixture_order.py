"""qa.pytest.fixture_order — predict_output: порядок подготовки и завершения фикстур pytest.

3–4 фикстуры с областями function/module/session, yield и return, зависимостями и (иногда)
autouse-фикстурой; 2–3 теста. Кандидат предсказывает вывод `pytest -s`. Ключ считает
независимая модель в генераторе (правила pytest: фикстуры с большей областью раньше,
autouse раньше запрошенных, зависимости раньше зависимых, завершение в обратном порядке
в конце своей области); он сверяется с исполнением показанного кода под обвязкой pytest,
а обвязка при разработке сверена с настоящим pytest 8.3.3.
"""
from __future__ import annotations

from assessment_bank.families.qa._shims import pytest_program
from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "qa.pytest.fixture_order"

CONTEXTS = [("интернет-магазин", ["db", "user", "cart", "coupon"], ["checkout", "refund", "history"]),
            ("банк", ["config", "ledger", "account", "card"], ["transfer", "statement", "limits"]),
            ("онлайн-школа", ["server", "client", "course", "student"], ["enroll", "grades", "certificate"]),
            ("логистика", ["broker", "warehouse", "parcel", "courier"], ["dispatch", "tracking", "return"])]
RANK = {"session": 3, "module": 2, "function": 0}
TAIL = "_bk_run(dict(globals()))\n"


def _gen_fixtures(rng, names):
    n = rng.choice([3, 4])
    names = names[:n]
    fx = []
    for i, name in enumerate(names):
        allowed = ["session", "module", "function"] if i == 0 else ["module", "function", "function"]
        scope = rng.choice(allowed)
        cand = [f for f in fx if RANK[f["scope"]] >= RANK[scope]]
        deps = []
        if cand and rng.random() < 0.75:
            deps = [rng.choice(cand)["name"]]
        fx.append(dict(name=name, scope=scope, deps=deps, yields=rng.random() < 0.7))
    return fx


def _model(fx, autouse, tests):
    """Независимая модель порядка pytest: список строк вывода."""
    by = {f["name"]: f for f in fx}
    if autouse:
        by[autouse["name"]] = autouse
    out, cache = [], set()
    fins = {3: [], 2: [], 0: []}

    def setup(name):
        if name in cache:
            return
        f = by[name]
        for d in f["deps"]:
            setup(d)
        out.append(f"{name}: setup")
        cache.add(name)
        fins[RANK[f["scope"]]].append(name)

    def teardown(level):
        while fins[level]:
            name = fins[level].pop()
            cache.discard(name)
            if by[name]["yields"]:
                out.append(f"{name}: teardown")

    for tname, args in tests:
        closure = ([autouse["name"]] if autouse else []) + list(args)
        changed = True
        while changed:
            changed = False
            for a in list(closure):
                for d in by[a]["deps"]:
                    if d not in closure:
                        closure.append(d)
                        changed = True
        closure.sort(key=lambda a: RANK[by[a]["scope"]], reverse=True)
        for a in closure:
            setup(a)
        out.append(f"run {tname}")
        teardown(0)
    teardown(2)
    teardown(3)
    return out


def _fixture_code(f):
    deco = "@pytest.fixture" if f["scope"] == "function" else f"@pytest.fixture(scope=\"{f['scope']}\")"
    if f.get("autouse"):
        deco = "@pytest.fixture(autouse=True)"
    lines = [deco, f"def {f['name']}({', '.join(f['deps'])}):", f"    print(\"{f['name']}: setup\")"]
    if f["yields"]:
        lines += [f"    yield \"{f['name']}\"", f"    print(\"{f['name']}: teardown\")"]
    else:
        lines += [f"    return \"{f['name']}\""]
    return lines


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, names, tnames = rng.choice(CONTEXTS)
    for _ in range(500):
        fx = _gen_fixtures(rng, names)
        autouse = (dict(name="log_test", scope="function", deps=[], yields=True, autouse=True)
                   if rng.random() < 0.35 else None)
        # Калибровка 05.10: вывод до 17 строк — канцелярская нагрузка; тестов всегда 2
        n_tests = 2
        tests = []
        for t in rng.sample(tnames, n_tests):
            k = rng.choice([1, 2, 2])
            args = rng.sample([f["name"] for f in fx], k)
            tests.append((f"test_{t}", args))
        has_wide = any(f["scope"] != "function" and f["yields"] for f in fx)
        reorder = any(len(a) == 2 and RANK[{f["name"]: f for f in fx}[a[1]]["scope"]] >
                      RANK[{f["name"]: f for f in fx}[a[0]]["scope"]] for _, a in tests)
        dep_used = any(f["deps"] for f in fx)
        if has_wide and dep_used and (reorder or autouse):
            break
    else:
        raise RuntimeError("не удалось подобрать конфигурацию")
    lines = ["import pytest", ""]
    for f in ([autouse] if autouse else []) + fx:
        lines += [""] + _fixture_code(f) + [""]
    for tname, args in tests:
        lines += ["", f"def {tname}({', '.join(args)}):", f"    print(\"run {tname}\")", ""]
    code = "\n".join(lines).rstrip() + "\n"
    out = "\n".join(_model(fx, autouse, tests))
    stem = (f"Тесты ({ctx}) лежат в одном файле и запускаются командой `pytest -s` (вывод print не "
            f"перехватывается) в порядке следования в файле. Что будет напечатано? Запишите строки "
            f"вывода print по порядку, без служебных строк pytest.")
    ak = AnswerKey(kind="output", value=out,
                   explanation="Фикстуры с большей областью видимости (session, module) готовятся "
                               "раньше function-фикстур, autouse — раньше запрошенных, "
                               "зависимости — раньше зависимых; завершение идёт в обратном "
                               "порядке в конце своей области: function — после каждого теста, "
                               "module и session — после последнего теста файла.")
    checks = [Check(name="stdout", runner="python", expect="stdout_equals", expected_stdout=out,
                    program=pytest_program(code, TAIL))]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code.rstrip(), answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         display_code_note="pytest заменён минимальной совместимой обвязкой; "
                                           "порядок фикстур сверен с pytest 8.3.3.",
                         params={"fixtures": [(f["name"], f["scope"], f["deps"], f["yields"]) for f in fx],
                                 "autouse": bool(autouse), "tests": tests})
