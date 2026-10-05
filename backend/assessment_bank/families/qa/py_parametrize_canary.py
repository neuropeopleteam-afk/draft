"""qa.pytest.parametrize_canary — predict_output (канарейка): сколько тестов pytest пройдёт и упадёт.

Функция из 2–4 строк, тест с parametrize на 4–5 случаев (часть ожиданий неверна) и тест с
двумя декораторами parametrize (декартово произведение). Ключ считает независимая модель на
Python, он сверяется с исполнением показанного кода под обвязкой pytest.
"""
from __future__ import annotations

from assessment_bank.families.qa._shims import PYTEST_SUMMARY_TAIL, pytest_program
from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "qa.pytest.parametrize_canary"


def _password(rng):
    n = rng.choice([6, 8, 10])
    pool = ["qwerty12", "Sunrise2026", "abc1", "letmein", "P4ssword", "zx9", "kotik_2010",
            "LongPassphrase", "12345678", "a1b2c3d4e5"]
    real = lambda p: len(p) >= n and any(ch.isdigit() for ch in p)
    fn = ["def is_strong(password):",
          f"    return len(password) >= {n} and any(ch.isdigit() for ch in password)"]
    cases = rng.sample(pool, rng.randint(4, 5))
    bases = rng.sample(["abcdefg", "Pass", "qwertyuiop", "sun", "Moscow"], rng.choice([2, 3]))
    digits = rng.sample(["1", "7", "9", "0"], 2)
    t2 = ([f"@pytest.mark.parametrize(\"digit\", {digits!r})",
           f"@pytest.mark.parametrize(\"base\", {bases!r})",
           "def test_word_with_digit_is_strong(base, digit):",
           "    assert is_strong(base + digit)"],
          [real(b + d) for b in bases for d in digits])
    return dict(fn=fn, name="is_strong", arg="password", real=real, cases=cases, t2=t2,
                ctx="регистрация", rule=f"не короче {n} символов и содержит цифру")


def _delivery(rng):
    th = rng.choice([1000, 2000, 3000])
    base = rng.choice([199, 249, 299])
    real = lambda t: 0 if t >= th else base
    fn = ["def delivery_price(total):", f"    if total >= {th}:", "        return 0",
          f"    return {base}"]
    cases = rng.sample([th - 1, th, th + 1, th // 2, 2 * th, 1], rng.randint(4, 5))
    totals = rng.sample([th - 10, th - 1, th, th + 5, th + 500], rng.choice([2, 3]))
    extras = rng.sample([0, 1, 10, 50], 2)
    t2 = ([f"@pytest.mark.parametrize(\"extra\", {extras!r})",
           f"@pytest.mark.parametrize(\"total\", {totals!r})",
           "def test_free_delivery_from_threshold(total, extra):",
           "    assert delivery_price(total + extra) == 0"],
          [real(t + e) == 0 for t in totals for e in extras])
    return dict(fn=fn, name="delivery_price", arg="total", real=real, cases=cases, t2=t2,
                ctx="доставка", rule=f"бесплатно от {th} ₽, иначе {base} ₽")


def _slug(rng):
    real = lambda s: "-".join(s.lower().split())
    fn = ["def make_slug(title):", "    return \"-\".join(title.lower().split())"]
    pool = ["Hello World", "  Новости  дня ", "QA_Team", "Release 2.0", "Тест-план", "A  B\tC"]
    cases = rng.sample(pool, rng.randint(4, 5))
    words = rng.sample(["Новости", "QA", "Отчёт", "Docs"], 2)
    seps = rng.sample([" ", "  ", "_", "\t", "-"], rng.choice([2, 3]))
    t2 = ([f"@pytest.mark.parametrize(\"sep\", {seps!r})",
           f"@pytest.mark.parametrize(\"word\", {words!r})",
           "def test_words_joined_by_dash(word, sep):",
           "    assert make_slug(word + sep + word) == word.lower() + \"-\" + word.lower()"],
          [real(w + s + w) == w.lower() + "-" + w.lower() for w in words for s in seps])
    return dict(fn=fn, name="make_slug", arg="title", real=real, cases=cases, t2=t2,
                ctx="блог", rule="нижний регистр, слова через дефис")


SCENARIOS = [_password, _delivery, _slug]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    sc = rng.choice(SCENARIOS)(rng)
    pairs = []
    for c in sc["cases"]:
        exp = sc["real"](c)
        if rng.random() < 0.4:  # автор теста ошибся в ожидании
            if isinstance(exp, bool):
                exp = not exp
            elif isinstance(exp, int):
                exp = 0 if exp else 1
            else:
                exp = exp.replace("-", "_", 1) if "-" in exp else exp + "-"
        pairs.append((c, exp))
    t1 = ([f"@pytest.mark.parametrize(\"{sc['arg']}, expected\", ["]
          + [f"    ({c!r}, {e!r})," for c, e in pairs] + ["])",
          f"def test_{sc['name']}({sc['arg']}, expected):",
          f"    assert {sc['name']}({sc['arg']}) == expected"])
    t2_lines, t2_res = sc["t2"]
    code = "\n".join(["import pytest", "", ""] + sc["fn"] + ["", ""] + t1 + ["", ""] + t2_lines)
    passed = sum(sc["real"](c) == e for c, e in pairs) + sum(t2_res)
    total = len(pairs) + len(t2_res)
    out = f"passed={passed} failed={total - passed}"
    stem = (f"Тесты функции `{sc['name']}` ({sc['ctx']}: {sc['rule']}). Сколько тестов pytest "
            f"пройдёт и сколько упадёт? Запишите ответ в виде `passed=N failed=M`.")
    ak = AnswerKey(kind="output", value=out,
                   explanation=f"Первый тест — {len(pairs)} случаев, второй — "
                               f"{len(t2_res)} (декартово произведение двух parametrize). "
                               "Падают случаи, где ожидание не совпадает с поведением функции.")
    checks = [Check(name="stdout", runner="python", expect="stdout_equals", expected_stdout=out,
                    program=pytest_program(code, PYTEST_SUMMARY_TAIL))]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=sc["ctx"],
                         verification="execution", checks=checks,
                         display_code_note="pytest заменён минимальной совместимой обвязкой "
                                           "(parametrize); совпадение с pytest 8.3.3 проверено.",
                         params={"scenario": sc["name"], "n_cases": total})
