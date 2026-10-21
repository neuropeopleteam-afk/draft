"""Общий конструктор расчётных и кодовых семейств волны 10 и волны 20.10-S."""
from __future__ import annotations

import contextlib
from fractions import Fraction
import hashlib
import io
import math
import random
import sqlite3
from typing import Any, Callable, Sequence
import zlib

from assessment_bank.gen_utils import LETTERS, build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check, Option, Variant

SHORT_NOTE = "Ответ проверяется программой-моделью по тем же числам, что в условии."


def num(v: int | float | Fraction, nd: int = 0, *, decimals: int | None = None) -> str:
    """Форматирование числа по-русски: неразрывный пробел между тысячами, запятая в дробной части."""
    if decimals is not None:
        nd = decimals
    if isinstance(v, Fraction):
        if v.denominator == 1 and nd == 0:
            v = int(v)
        else:
            v = float(v)
    if nd > 0:
        s = f"{float(v):,.{nd}f}"
    elif isinstance(v, int) or (isinstance(v, float) and v.is_integer()):
        s = f"{int(round(v)):,}"
    else:
        s = f"{float(v):,.2f}".rstrip("0").rstrip(".")
    return s.replace(",", "\u00a0").replace(".", ",")


def key_pos(family_id: str, seed: int, n: int = 4) -> int:
    return (zlib.crc32(family_id.encode()) + seed) % n


def place(
    family_id: str,
    seed: int,
    rng: Any,
    good: tuple[str, str | None],
    wrong: Sequence[tuple[str, str | None]],
) -> tuple[list[Option], str]:
    """Ключ — на позицию key_pos, остальные — в случайном порядке."""
    ws = list(wrong)
    rng.shuffle(ws)
    pos = key_pos(family_id, seed, len(ws) + 1)
    items = ws[:pos] + [good] + ws[pos:]
    if len({(t, c) for t, c in items}) != len(items):
        raise ValueError("варианты ответа совпадают")
    opts = [Option(id=LETTERS[i], text=t, code=c) for i, (t, c) in enumerate(items)]
    return opts, LETTERS[pos]


def _letter_program(model: str, P: dict, shown: dict[str, str], expr: str) -> str:
    return (
        f"{model}\n\nP = {P!r}\nopts = {shown!r}\nans = {expr}\n"
        "hit = [k for k, t in opts.items() if t == ans]\n"
        "print(hit[0] if len(hit) == 1 else 'AMBIGUOUS')\n"
    )


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


_CHECK_TMPL = """{model}

P = {params}
ans = answer(P)
assert ans is not None, "answer(P) вернул None"
if "brute" in dir():
    b = brute(P)
    assert b == ans, f"answer={{ans}} != brute={{b}}"
key_str = fmt(ans)
raw_traps = {{k: fmt(v) for k, v in traps(P).items() if v is not None}}
options = {options}
expected_key = {key!r}
assert options[expected_key] == key_str, f"ключ {{expected_key}}={{options[expected_key]!r}} != {{key_str!r}}"
trap_pool = {{v for v in raw_traps.values() if v != key_str}}
for k, v in options.items():
    if k != expected_key:
        assert v in trap_pool, f"дистрактор {{k}}={{v!r}} не из модели ошибок"
print(expected_key)
"""


def load_model(model: str) -> dict[str, Any]:
    ns: dict[str, Any] = {"__name__": "model", "Fraction": Fraction, "F": Fraction, "math": math, "num": num}
    exec(compile(model, "<model>", "exec"), ns)  # noqa: S102 — исполняется только собственный код генератора
    return ns


def _pick_traps(
    rng: random.Random,
    key_val: int | float | Fraction,
    traps: dict[str, Any],
    n_above: int,
    fmt: Callable[[Any], str],
    *,
    rel: float,
    abs_min: float,
    trap_first: str | None = None,
    n_distractors: int = 3,
) -> list[tuple[str, str]] | None:
    """Выбрать ``n_distractors`` ловушек: ровно ``n_above`` строго больше ключа и ``n_distractors - n_above`` строго меньше."""
    kv = float(key_val)
    key_s = fmt(key_val)
    primary_above: list[tuple[float, str, str]] = []
    primary_below: list[tuple[float, str, str]] = []
    fallback_above: list[tuple[float, str, str]] = []
    fallback_below: list[tuple[float, str, str]] = []
    for name, val in traps.items():
        if val is None:
            continue
        tv = float(val)
        if not math.isfinite(tv) or tv <= 0:
            continue
        ts = fmt(val)
        if ts == key_s:
            continue
        if abs(tv - kv) < max(abs_min, rel * max(abs(kv), 1e-9)):
            continue
        is_fb = name.startswith("_fb_")
        if tv > kv:
            (fallback_above if is_fb else primary_above).append((tv, name, ts))
        elif tv < kv:
            (fallback_below if is_fb else primary_below).append((tv, name, ts))
    rng.shuffle(primary_above)
    rng.shuffle(primary_below)
    rng.shuffle(fallback_above)
    rng.shuffle(fallback_below)
    if trap_first:
        primary_above.sort(key=lambda x: 0 if x[1] == trap_first else 1)
        primary_below.sort(key=lambda x: 0 if x[1] == trap_first else 1)
    above = primary_above + fallback_above
    below = primary_below + fallback_below

    def select(pool: list[tuple[float, str, str]], need: int) -> list[tuple[str, str]] | None:
        if need == 0:
            return []
        chosen: list[tuple[float, str, str]] = []
        used_str = {key_s}
        for tv, name, ts in pool:
            if ts in used_str:
                continue
            if all(abs(tv - cv) >= max(abs_min, rel * 0.65 * max(abs(cv), abs(tv), 1e-9)) for cv, _, _ in chosen):
                chosen.append((tv, name, ts))
                used_str.add(ts)
                if len(chosen) == need:
                    return [(n, s) for _, n, s in chosen]
        return None

    n_below = n_distractors - n_above
    if n_above < 0 or n_below < 0:
        return None
    pa = select(above, n_above)
    if pa is None:
        return None
    pb = select(below, n_below)
    if pb is None:
        return None
    return pa + pb


def numeric_variant(
    family_id: str,
    seed: int,
    *,
    contexts: Sequence[Any],
    sample: Callable[[random.Random], dict[str, Any]],
    model: str,
    stem: Callable[[dict[str, Any], Any], str],
    explain: Callable[[dict[str, Any], Any, Any], str],
    code: Callable[[dict[str, Any], Any], str | None] | None = None,
    accept: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
    rel: float = 0.04,
    abs_min: float = 1.0,
    tries: int = 800,
    trap_first: str | None = None,
    note: str = SHORT_NOTE,
    trap_desc: dict[str, str] | None = None,
    n_above_choices: Sequence[int] = (0, 1, 2, 3),
    n_distractors: int = 3,
    ns_cached: dict[str, Any] | None = None,
    stratified: bool = False,
) -> Variant:
    """Собрать расчётный вариант с гарантированным разбросом дистракторов и проверкой исполнением."""
    rng = make_rng(family_id, seed)
    ctx = contexts[seed % len(contexts)] if len(contexts) >= 4 else rng.choice(list(contexts))
    ns = ns_cached if ns_cached is not None else load_model(model)
    fmt = ns["fmt"]
    fam_h = int.from_bytes(hashlib.sha256(family_id.encode("utf-8")).digest()[:4], "big")
    choices_tup = tuple(n_above_choices)
    if stratified:
        target_na = choices_tup[(fam_h + seed) % len(choices_tup)]
    else:
        target_na = choices_tup[seed % len(choices_tup)]
    trap_keys = sorted(trap_desc) if trap_desc else []
    if trap_first is None and trap_keys:
        trap_first = trap_keys[seed % len(trap_keys)]

    picked: list[tuple[str, str]] | None = None
    P: dict[str, Any] = {}
    ans: Any = None
    n_above = target_na
    for _ in range(tries):
        P = sample(rng)
        if accept is not None and not accept(P, ns):
            continue
        ans = ns["answer"](P)
        if ans is None:
            continue
        raw_traps = ns["traps"](P)
        picked = _pick_traps(
            rng, ans, raw_traps, target_na, fmt,
            rel=rel, abs_min=abs_min, trap_first=trap_first, n_distractors=n_distractors,
        )
        if picked is not None:
            break
    else:
        order = list(choices_tup)
        rng.shuffle(order)
        for _ in range(tries):
            P = sample(rng)
            if accept is not None and not accept(P, ns):
                continue
            ans = ns["answer"](P)
            if ans is None:
                continue
            raw_traps = ns["traps"](P)
            for na in order:
                picked = _pick_traps(
                    rng, ans, raw_traps, na, fmt,
                    rel=rel, abs_min=abs_min, trap_first=trap_first, n_distractors=n_distractors,
                )
                if picked is not None:
                    n_above = na
                    break
            if picked is not None:
                break
        else:
            raise RuntimeError(f"{family_id}: не удалось подобрать параметры (seed={seed})")

    key_str = fmt(ans)
    trap_names = [n for n, _ in picked]
    raw_all = ns["traps"](P)
    trap_dict = {n: raw_all[n] for n in trap_names if n in raw_all}
    if stratified:
        n_tot = n_distractors + 1
        key_idx = (fam_h // 7 + seed * 2) % n_tot
        dist_strs = [s for _, s in picked]
        rng.shuffle(dist_strs)
        opts: list[Option] = []
        di = 0
        for i in range(n_tot):
            if i == key_idx:
                opts.append(Option(id=LETTERS[i], text=key_str))
            else:
                opts.append(Option(id=LETTERS[i], text=dist_strs[di]))
                di += 1
        key = LETTERS[key_idx]
    else:
        opts, key = place(family_id, seed, rng, (key_str, None), [(s, None) for _, s in picked])
    shown = {o.id: o.text for o in opts}
    prog = _CHECK_TMPL.format(model=model.strip(), params=repr(P), options=repr(shown), key=key)
    chk = Check(name="model_and_traps", runner="python", program=prog, expect="stdout_equals",
                expected_stdout=key, embeds_display_code=False)
    ctx_name = ctx if isinstance(ctx, str) else ctx[0]
    code_str = code(P, ctx) if code is not None else None
    try:
        expl = explain(P, ans, trap_dict if not stratified else trap_names)
    except Exception:
        expl = explain(P, ans, trap_names)
    if trap_desc:
        val_of = {n: s for n, s in picked}
        real = [f"«{val_of[n]}» — {trap_desc[n]}" for n in trap_names if n in trap_desc and not n.startswith("_fb_")]
        ctrl = [f"«{val_of[n]}»" for n in trap_names if n.startswith("_fb_")]
        if real:
            expl = f"{expl} Дистракторы — типичные ошибки: {'; '.join(real)}."
        if ctrl:
            expl = (f"{expl} Контрольные значения рядом с ответом (не связаны с конкретной ошибкой): "
                    f"{', '.join(ctrl)}.")
    return build_variant(
        family_id, seed,
        stem=stem(P, ctx),
        code=code_str,
        options=opts,
        answer_key=AnswerKey(kind="option", value=key, explanation=expl),
        context=ctx_name,
        verification="execution",
        checks=[chk],
        language="text",
        display_code_note=note,
        params={**P, "answer": float(ans) if isinstance(ans, Fraction) else ans, "n_above": n_above, "traps": trap_names},
    )


def choice_variant(
    family_id: str,
    seed: int,
    *,
    contexts: Sequence[Any],
    alts: dict[str, str],
    sample: Callable[[Any], dict],
    model: str,
    stem: Callable[[dict, Any], str],
    explain: Callable[[dict, str, dict], str],
    trap_first: str | None = None,
    note: str = SHORT_NOTE,
    trap_desc: dict[str, str] | None = None,
) -> Any:
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


def codefix_variant(
    family_id: str,
    seed: int,
    rng: Any,
    *,
    ctx: str,
    stem: str,
    runner: str,
    buggy: str,
    good: str,
    wrongs: Sequence[tuple[str, str]],
    label: str,
    harness: Callable[[str], str] | None,
    setup: str = "",
    explanation: str,
    defect_type: str,
    params: dict[str, Any],
    language: str,
) -> Any:
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
