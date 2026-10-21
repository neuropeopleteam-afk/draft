"""Общие помощники генераторов: детерминированный ГСЧ, варианты ответов, тестовые обвязки.

Правила детерминизма для авторов семейств:
* весь случайный выбор — только через ``make_rng(FAMILY_ID, seed)`` (sha256 от id и seed),
  никаких ``random.*`` глобально, ``time``, ``hash()`` строк и обхода ``set`` строк;
* одинаковый seed → байт в байт одинаковый Variant (валидатор проверяет это в отдельном
  процессе с другим PYTHONHASHSEED).
"""
from __future__ import annotations

import difflib
import hashlib
import random
import textwrap
from typing import Any, Callable, Iterable, Sequence

from .metrics import count_code_lines, count_operations
from .schema import AnswerKey, Check, Option, Rubric, StepPrompt, Variant, VariantMeta, make_variant_id

LETTERS = "ABCDEF"


def make_rng(family_id: str, seed: int, salt: str = "") -> random.Random:
    digest = hashlib.sha256(f"{family_id}:{seed}:{salt}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def plural(n: int, one: str, few: str, many: str) -> str:
    """Форма существительного после числительного: plural(2, «партиция», «партиции», «партиций»)."""
    n = abs(int(n))
    if 11 <= n % 100 <= 14:
        return many
    return one if n % 10 == 1 else few if 2 <= n % 10 <= 4 else many


def dedent(s: str) -> str:
    return textwrap.dedent(s).strip("\n")


def indent(s: str, n: int = 4) -> str:
    return textwrap.indent(s, " " * n)


def make_options(rng: random.Random, correct: tuple[str, str | None],
                 distractors: Sequence[tuple[str, str | None]], step: int | None = None,
                 ) -> tuple[list[Option], str]:
    """Перемешать правильный ответ и дистракторы; вернуть (options, id правильного)."""
    items = [(t, c, True) for t, c in [correct]] + [(t, c, False) for t, c in distractors]
    texts = [(t, c) for t, c, _ in items]
    if len(set(texts)) != len(texts):
        raise ValueError("варианты ответа совпадают — генератор должен давать различные")
    rng.shuffle(items)
    options, key = [], ""
    for i, (t, c, ok) in enumerate(items):
        options.append(Option(id=LETTERS[i], text=t, code=c, step=step))
        if ok:
            key = LETTERS[i]
    return options, key


def changed_lines(buggy: str, fixed: str) -> set[int]:
    """Номера строк (с 1) кода с дефектом, которые заменены или удалены в исправлении."""
    a, b = buggy.splitlines(), fixed.splitlines()
    out: set[int] = set()
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            out.update(range(i1 + 1, i2 + 1))
    return out


def py_harness(code: str, test_body: str) -> str:
    """Код + тесты; печатает последней строкой RESULT: PASS / RESULT: FAIL."""
    return (code.rstrip() + "\n\n\ndef __bank_tests__():\n" + indent(dedent(test_body)) +
            "\n\n\ntry:\n    __bank_tests__()\n    print('RESULT: PASS')\n"
            "except Exception as __bank_e:\n    print('RESULT: FAIL', type(__bank_e).__name__)\n")


def js_harness(code: str, test_body: str, prelude: str = "") -> str:
    """Код JS + асинхронные тесты; печатает RESULT: PASS / RESULT: FAIL."""
    return (prelude + "\n" + code.rstrip() + "\n\n;(async () => {\n"
            "  const __assert = (c, m) => { if (!c) throw new Error(m || 'assert'); };\n"
            "  try {\n" + indent(dedent(test_body), 4) + "\n    console.log('RESULT: PASS');\n"
            "  } catch (e) {\n    console.log('RESULT: FAIL ' + (e && e.name));\n  }\n})();\n")


def text_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    rows = [[("NULL" if v is None else str(v)) for v in r] for r in rows]
    widths = [max(len(str(h)), *(len(r[i]) for r in rows)) if rows else len(str(h))
              for i, h in enumerate(headers)]
    line = lambda cells: " | ".join(str(c).ljust(w) for c, w in zip(cells, widths)).rstrip()
    sep = "-+-".join("-" * w for w in widths)
    return "\n".join([line(headers), sep] + [line(r) for r in rows])


def sql_literal(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def sql_inserts(table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    out = []
    for r in rows:
        out.append(f"INSERT INTO {table} ({', '.join(columns)}) VALUES "
                   f"({', '.join(sql_literal(v) for v in r)});")
    return "\n".join(out)


def build_variant(family_id: str, seed: int, *, stem: str, answer_key: AnswerKey,
                  context: str, verification: str, code: str | None = None,
                  options: list[Option] | None = None, rubric: Rubric | None = None,
                  checks: list[Check] | None = None, steps: list[StepPrompt] | None = None,
                  params: dict[str, Any] | None = None, defect_type: str | None = None,
                  display_code_note: str | None = None, language: str | None = None) -> Variant:
    """Собрать Variant; формат/язык берутся из YAML семейства, метрики считаются здесь."""
    from .registry import get_spec  # ленивый импорт: реестр импортирует генераторы

    spec = get_spec(family_id)
    lang = language or spec.language
    meta = VariantMeta(
        family_id=family_id, seed=seed, format=spec.format, language=lang,
        generator_version=spec.version, context=context,
        code_lines=count_code_lines(code, lang) if code else None,
        operations=count_operations(code, lang) if code else None,
        defect_type=defect_type, steps=steps, verification=verification,
        checks=checks or [], display_code_note=display_code_note, params=params or {})
    return Variant(variant_id=make_variant_id(family_id, seed), stem=stem, code=code,
                   options=options, answer_key=answer_key, rubric=rubric, meta=meta)


def ob3_steps(reproduce: str, fix: str, explain: str) -> list[StepPrompt]:
    return [StepPrompt(step=1, kind="reproduce", prompt=reproduce),
            StepPrompt(step=2, kind="fix", prompt=fix),
            StepPrompt(step=3, kind="explain", prompt=explain)]


def rubric_from(spec: dict[str, Any]) -> Rubric:
    """Собрать Rubric из словаря {criteria: [(id, описание, вес)], strong, medium, weak}."""
    from .schema import RubricCriterion

    crit = [RubricCriterion(id=c[0], description=c[1], weight=c[2]) for c in spec["criteria"]]
    return Rubric(criteria=crit, strong=para(spec["strong"]), medium=para(spec["medium"]),
                  weak=para(spec["weak"]), scoring_notes=spec.get("notes", ""))


def para(s: str) -> str:
    """Склеить многострочный текст эталона в один абзац."""
    return " ".join(s.split())


def pick_ranked(rng: random.Random, good: Any, pool: dict[str, Any], n_below: int, k: int = 3,
                fmt: Callable[[Any], str] = str) -> list[str] | None:
    """Выбрать ``k`` ловушек из ``pool`` так, чтобы ровно ``n_below`` были меньше ключа (ранг ключа задан заранее).

    Ранг ключа среди вариантов выбирается ДО подбора параметров (``n_below = rng.randrange(k + 1)``), генератор
    перебирает параметры, пока ранг не станет достижим, — так ранг ключа равномерен и ключ не угадывается
    медианой или «центром кластера» (аудит банка 21.10: у части семейств ключ всегда был вторым по величине).
    Подписи должны различаться. None — при этих параметрах ранг недостижим.
    """
    below = [n for n, v in pool.items() if v is not None and v < good]
    above = [n for n, v in pool.items() if v is not None and v > good]
    if len(below) < n_below or len(above) < k - n_below:
        return None
    for _ in range(20):
        picked = rng.sample(below, n_below) + rng.sample(above, k - n_below)
        texts = [fmt(good)] + [fmt(pool[n]) for n in picked]
        if len(set(texts)) == len(texts):
            return picked
    return None
