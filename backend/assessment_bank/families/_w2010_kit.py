"""Помощники семейств волны 20.10 («расширение банка до 455+»): короткие Principal у границы θ ≈ 3,0 и
короткие Senior/Lead по навыкам вакансий hh.ru, которых не было в банке.

Три шаблона, общие для всех семейств волны; содержание (модель предметной области, ловушки, тексты) — в файле
семейства.

* :func:`numeric_variant` — расчётный mcq_concept с числовым ответом. Модель предметной области — исходный текст
  Python (``MODEL``) с функциями ``answer(P)``, ``traps(P) -> {имя ловушки: значение}`` и ``fmt(x) -> подпись``;
  по желанию ``brute(P)`` — независимый расчёт другим способом (перебор, пошаговая имитация). Генератор и проверка
  исполняют ОДИН и тот же текст модели: проверка «model» печатает букву варианта, совпадающего с ``fmt(answer(P))``,
  проверка «brute» (если есть) — букву по ``brute(P)``, проверка «trap» — букву самой «соблазнительной» ловушки и
  ожидает, что она отличается от ключа (ловушка действительно неверна при этих числах). Сколько ловушек больше ключа
  (0–3) выбирается по seed ДО подбора чисел — ключ не угадывается по месту числа среди четырёх.
* :func:`choice_variant` — mcq_concept «какую из четырёх альтернатив выбрать»: модель — ``best(P) -> имя`` и
  ``traps(P) -> {ловушка: имя альтернативы}``; целевая альтернатива выбрана по seed до подбора чисел (ответ
  равновероятен среди альтернатив), не меньше двух ловушек указывают на другие альтернативы.
* :func:`codefix_variant` — choose_fix: показан код с дефектом и четыре замены; каждая замена исполняется
  (python или sqlite) и сравнивается с выводом эталона: верная — stdout_equals, остальные — stdout_differs,
  показанный код с дефектом — тоже stdout_differs.

Позиция ключа — по кругу от seed (сдвиг от family_id), остальные варианты перемешиваются rng: на 20 seed каждая
буква ключом ровно 5 раз.
"""
from __future__ import annotations

from fractions import Fraction

import contextlib
import io
import sqlite3
import zlib
from typing import Any, Callable, Sequence

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check, Option

LETTERS = "ABCDEF"
SHORT_NOTE = "Ответ проверяется программой-моделью по тем же числам, что в условии."


def key_pos(family_id: str, seed: int, n: int = 4) -> int:
    return (zlib.crc32(family_id.encode()) + seed) % n


def place(family_id: str, seed: int, rng: Any, good: tuple[str, str | None],
          wrong: Sequence[tuple[str, str | None]]) -> tuple[list[Option], str]:
    """Ключ — на позицию key_pos, остальные — в случайном порядке."""
    ws = list(wrong)
    rng.shuffle(ws)
    pos = key_pos(family_id, seed, len(ws) + 1)
    items = ws[:pos] + [good] + ws[pos:]
    if len({(t, c) for t, c in items}) != len(items):
        raise ValueError("варианты ответа совпадают")
    opts = [Option(id=LETTERS[i], text=t, code=c) for i, (t, c) in enumerate(items)]
    return opts, LETTERS[pos]


def load_model(src: str) -> dict[str, Any]:
    ns: dict[str, Any] = {"__name__": "model"}
    exec(compile(src, "<model>", "exec"), ns)  # noqa: S102 — наш собственный код модели
    return ns


def _letter_program(model: str, P: dict, shown: dict[str, str], expr: str) -> str:
    return (f"{model}\n\nP = {P!r}\nopts = {shown!r}\nans = {expr}\n"
            "hit = [k for k, t in opts.items() if t == ans]\n"
            "print(hit[0] if len(hit) == 1 else 'AMBIGUOUS')\n")


def search(rng: Any, sample: Callable[[Any], dict], accept: Callable[[dict], Any], tries: int = 20000):
    for _ in range(tries):
        p = sample(rng)
        r = accept(p)
        if r is not None:
            return p, r
    raise RuntimeError("не удалось подобрать параметры")


def _distinct(vals: Sequence[float], rel: float, abs_min: float) -> bool:
    v = sorted(vals)
    return all(b - a >= max(rel * max(abs(b), 1e-9), abs_min) for a, b in zip(v, v[1:]))


def numeric_variant(family_id: str, seed: int, *, contexts: Sequence[Any], sample: Callable[[Any], dict],
                    model: str, stem: Callable[[dict, Any], str], explain: Callable[[dict, Any, dict], str],
                    accept: Callable[[dict, dict], bool] | None = None, rel: float = 0.12, abs_min: float = 1.0,
                    trap_first: str | None = None, note: str = SHORT_NOTE,
                    trap_desc: dict[str, str] | None = None, n_above_choices: Sequence[int] = (0, 1, 2, 3)) -> Any:
    rng = make_rng(family_id, seed)
    ctx = contexts[seed % len(contexts)] if len(contexts) >= 4 else rng.choice(list(contexts))
    n_above = 0
    ns = load_model(model)

    def ok(P):
        if accept is not None and not accept(P, ns):
            return None
        a = ns["answer"](P)
        cand = {k: v for k, v in ns["traps"](P).items() if v is not None and v != a}
        above = sorted(k for k, v in cand.items() if v > a)
        below = sorted(k for k, v in cand.items() if v < a)
        if len(above) < n_above or len(below) < 3 - n_above:
            return None
        for _ in range(12):
            names = rng.sample(above, n_above) + rng.sample(below, 3 - n_above)
            vals = [a] + [cand[n] for n in names]
            texts = [ns["fmt"](x) for x in vals]
            if _distinct(vals, rel, abs_min) and len(set(texts)) == 4:
                return a, {n: cand[n] for n in sorted(names)}
        return None

    first = list(n_above_choices)[seed % len(n_above_choices)]
    rest = [x for x in n_above_choices if x != first]
    rng.shuffle(rest)                      # запасной ход — равновероятно среди остальных (ранг ключа не смещается)
    for n_above in [first] + rest:
        try:
            P, (a, traps) = search(rng, sample, ok, tries=4000)
            break
        except RuntimeError:
            continue
    else:
        raise RuntimeError("не удалось подобрать параметры")
    if "brute" in ns and ns["fmt"](ns["brute"](P)) != ns["fmt"](a):
        raise RuntimeError("модель и независимый расчёт расходятся")
    good = ns["fmt"](a)
    opts, key = place(family_id, seed, rng, (good, None), [(ns["fmt"](v), None) for v in traps.values()])
    shown = {o.id: o.text for o in opts}
    checks = [Check(name="model", runner="python", program=_letter_program(model, P, shown, "fmt(answer(P))"),
                    expect="stdout_equals", expected_stdout=key, embeds_display_code=False)]
    if "brute" in ns:
        checks.append(Check(name="brute", runner="python",
                            program=_letter_program(model, P, shown, "fmt(brute(P))"),
                            expect="stdout_equals", expected_stdout=key, embeds_display_code=False))
    tname = trap_first if trap_first in traps else sorted(traps)[0]
    checks.append(Check(name=f"trap:{tname}", runner="python",
                        program=_letter_program(model, P, shown, f"fmt(traps(P)[{tname!r}])"),
                        expect="stdout_differs", expected_stdout=key, embeds_display_code=False))
    expl = explain(P, a, traps)
    if trap_desc:
        expl += " Неверные варианты: " + "; ".join(f"{ns['fmt'](v)} — {trap_desc[n]}" for n, v in traps.items()) + "."
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    params = {k: v for k, v in P.items()}
    params.update({"answer": float(a) if isinstance(a, Fraction) else a, "traps": sorted(traps), "n_above": n_above})
    return build_variant(family_id, seed, stem=stem(P, ctx), options=opts, answer_key=ak,
                         context=ctx if isinstance(ctx, str) else ctx[0], verification="execution",
                         checks=checks, language="text", display_code_note=note, params=params)


def choice_variant(family_id: str, seed: int, *, contexts: Sequence[Any], alts: dict[str, str],
                   sample: Callable[[Any], dict], model: str, stem: Callable[[dict, Any], str],
                   explain: Callable[[dict, str, dict], str], trap_first: str | None = None,
                   note: str = SHORT_NOTE, trap_desc: dict[str, str] | None = None) -> Any:
    rng = make_rng(family_id, seed)
    ctx = contexts[seed % len(contexts)] if len(contexts) >= 4 else rng.choice(list(contexts))
    order = list(alts)
    target = order[(seed * 7 + zlib.crc32(family_id.encode())) % len(order)]
    ns = load_model(model)

    def ok(P):
        b = ns["best"](P)
        if b != target:
            return None
        tr = ns["traps"](P)
        if sum(1 for v in tr.values() if v != b) < 2:
            return None
        return b, tr

    P, (b, tr) = search(rng, sample, ok)
    opts, key = place(family_id, seed, rng, (alts[b], None), [(alts[m], None) for m in order if m != b])
    shown = {o.id: o.text for o in opts}
    labels = repr(alts)
    checks = [Check(name="model", runner="python",
                    program=_letter_program(model + f"\nLABELS = {labels}\n", P, shown, "LABELS[best(P)]"),
                    expect="stdout_equals", expected_stdout=key, embeds_display_code=False)]
    wrong = [k for k, v in sorted(tr.items()) if v != b]
    tname = trap_first if trap_first in wrong else wrong[0]
    checks.append(Check(name=f"trap:{tname}", runner="python",
                        program=_letter_program(model + f"\nLABELS = {labels}\n", P, shown,
                                                f"LABELS[traps(P)[{tname!r}]]"),
                        expect="stdout_differs", expected_stdout=key, embeds_display_code=False))
    expl = explain(P, b, tr)
    if trap_desc:
        expl += " Ловушки: " + "; ".join(f"{trap_desc[n]} — «{alts[m]}»" for n, m in sorted(tr.items()) if m != b) + "."
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    params = {k: v for k, v in P.items()}
    params.update({"best": b, "traps": tr})
    return build_variant(family_id, seed, stem=stem(P, ctx), options=opts, answer_key=ak,
                         context=ctx if isinstance(ctx, str) else ctx[0], verification="execution",
                         checks=checks, language="text", display_code_note=note, params=params)


# --------------------------------------------------------------------------- choose_fix с исполнением
def run_py(program: str) -> str:
    buf = io.StringIO()
    ns: dict[str, Any] = {"__name__": "__main__"}
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(program, "<fix>", "exec"), ns)  # noqa: S102 — наш код и показанные варианты
    except Exception as exc:  # noqa: BLE001 — падение = «другой вывод»
        return buf.getvalue().strip() + f"\nERROR {type(exc).__name__}"
    return buf.getvalue().strip()


def run_sql(setup: str, query: str) -> str:
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(setup)
        rows = con.execute(query).fetchall()
    except sqlite3.Error as exc:
        return f"ERROR: {exc}"
    finally:
        con.close()
    return "\n".join("|".join("NULL" if v is None else str(v) for v in r) for r in rows)


def codefix_variant(family_id: str, seed: int, rng: Any, *, ctx: str, stem: str, runner: str, buggy: str,
                    good: str, wrongs: Sequence[tuple[str, str]], label: str, harness: Callable[[str], str] | None,
                    setup: str = "", explanation: str, defect_type: str, params: dict[str, Any],
                    language: str) -> Any:
    """runner python: harness(code) -> программа (код дословно + тест, печать результата); sqlite: setup + запрос."""
    def out(code):
        return run_py(harness(code)) if runner == "python" else run_sql(setup, code)

    ref = out(good)
    if not ref or "ERROR" in ref:
        raise RuntimeError(f"эталон не исполняется: {ref[:200]}")
    if out(buggy) == ref:
        raise RuntimeError("показанный код совпадает с эталоном по выводу")
    for name, w in wrongs:
        if out(w) == ref:
            raise RuntimeError(f"неверная замена {name} даёт вывод эталона")
    opts, key = place(family_id, seed, rng, (label, good), [(label, w) for _n, w in wrongs])
    files = {"setup.sql": setup} if runner == "sqlite" else {}
    prog = (lambda c: c) if runner == "sqlite" else harness
    checks = [Check(name="buggy_differs", runner=runner, program=prog(buggy), files=files,
                    expect="stdout_differs", expected_stdout=ref)]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner=runner, program=prog(o.code), files=files,
                            embeds_display_code=False,
                            expect="stdout_equals" if o.id == key else "stdout_differs", expected_stdout=ref))
    ak = AnswerKey(kind="option", value=key, explanation=explanation)
    return build_variant(family_id, seed, stem=stem, code=buggy, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type=defect_type, language=language,
                         params={**params, "wrongs": [n for n, _ in wrongs]})


def num(x: float, nd: int = 0) -> str:
    """Число по-русски: десятичная запятая, неразрывный пробел в тысячах."""
    s = f"{x:,.{nd}f}".replace(",", "\u00a0").replace(".", ",")
    return s
