"""Общий конструктор расчётных и кодовых семейств волны 10 (1 000+ семейств).

Требования волны:
* в каждом варианте есть проверка исполнением (``Check``): модель предметной области считает
  эталонный ответ, а для обратных задач — ещё и независимая проверка полным перебором сетки;
* все дистракторы получаются из явных ловушек модели (забытый множитель, неверное округление,
  перепутанные единицы, ошибка в направлении неравенства и т.п.) и проверяются в той же программе;
* место правильного ответа по величине не фиксировано: в вариантах с числовыми ответами ключ
  равновероятно оказывается на любом месте по возрастанию (среди 4 или 5 вариантов).
"""
from __future__ import annotations

import hashlib
import math
import random
from fractions import Fraction
from typing import Any, Callable, Sequence

from assessment_bank.gen_utils import LETTERS, build_variant, changed_lines, make_options, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check, Option, Variant


def num(v: int | float | Fraction, *, decimals: int | None = None) -> str:
    """Форматирование числа по-русски: неразрывный пробел между тысячами, запятая в дробной части."""
    if isinstance(v, Fraction):
        if v.denominator == 1 and decimals is None:
            v = int(v)
        else:
            v = float(v)
    if decimals is not None:
        s = f"{float(v):,.{decimals}f}"
    elif isinstance(v, int) or (isinstance(v, float) and v.is_integer()):
        s = f"{int(round(v)):,}"
    else:
        s = f"{float(v):,.2f}".rstrip("0").rstrip(".")
    return s.replace(",", "\u00a0").replace(".", ",")


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
    ns: dict[str, Any] = {"Fraction": Fraction, "F": Fraction, "math": math, "num": num}
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
    explain: Callable[[dict[str, Any], Any, list[str]], str],
    code: Callable[[dict[str, Any], Any], str | None] | None = None,
    accept: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
    rel: float = 0.04,
    abs_min: float = 1.0,
    tries: int = 800,
    note: str = "Ответ и ловушки проверяются программой-моделью предметной области (plus перебор сетки для обратных задач).",
    trap_desc: dict[str, str] | None = None,
    n_above_choices: tuple[int, ...] = (0, 1, 2, 3),
    n_distractors: int = 3,
    ns_cached: dict[str, Any] | None = None,
    stratified: bool = False,
) -> Variant:
    """Собрать расчётный вариант с гарантированным разбросом дистракторов и проверкой исполнением."""
    rng = make_rng(family_id, seed)
    ctx = contexts[seed % len(contexts)]
    ns = ns_cached if ns_cached is not None else load_model(model)
    fmt = ns["fmt"]
    brute_fn = ns.get("brute")
    fam_h = int.from_bytes(hashlib.sha256(family_id.encode("utf-8")).digest()[:4], "big")
    if stratified:
        target_na = n_above_choices[(fam_h + seed) % len(n_above_choices)]
    else:
        target_na = rng.choice(n_above_choices)
    trap_keys = sorted(trap_desc) if trap_desc else []
    trap_first = trap_keys[seed % len(trap_keys)] if trap_keys else None

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
        order = list(n_above_choices)
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
        opts, key = make_options(rng, (key_str, None), [(s, None) for _, s in picked])
    shown = {o.id: o.text for o in opts}
    prog = _CHECK_TMPL.format(model=model.strip(), params=repr(P), options=repr(shown), key=key)
    chk = Check(name="model_and_traps", runner="python", program=prog, expect="stdout_equals",
                expected_stdout=key, embeds_display_code=False)
    ctx_name = ctx[0] if isinstance(ctx, tuple) else str(ctx)
    code_str = code(P, ctx) if code is not None else None
    expl = explain(P, ans, trap_names)
    if trap_desc:
        td = "; ".join(f"{n} — {trap_desc[n]}" for n in trap_names if n in trap_desc)
        if td:
            expl = f"{expl} Дистракторы (типичные ошибки): {td}."
    return build_variant(
        family_id, seed,
        stem=stem(P, ctx),
        code=code_str,
        options=opts,
        answer_key=AnswerKey(kind="option", value=key, explanation=expl),
        context=ctx_name,
        verification="execution",
        checks=[chk],
        display_code_note=note,
        params={**P, "n_above": n_above, "traps": trap_names},
    )


def codefix_variant(
    family_id: str,
    seed: int,
    *,
    contexts: Sequence[Any],
    defect_type: str,
    build: Callable[[random.Random, Any], dict[str, Any]],
) -> Variant:
    """Собрать вариант ``find_bug`` или ``choose_fix`` с проверкой всех патчей в песочнице."""
    from assessment_bank.registry import get_spec

    spec = get_spec(family_id)
    rng = make_rng(family_id, seed)
    ctx = contexts[seed % len(contexts)]
    d = build(rng, ctx)
    buggy: str = d["buggy"].strip("\n")
    fixed: str = d["fixed"].strip("\n")
    tests: str = d["tests"]
    runner: str = d.get("runner", "python")
    harness: Callable[[str, str], str] = d.get("harness", py_harness)
    ch = changed_lines(buggy, fixed)
    assert len(ch) == 1, f"{family_id}: changed_lines={ch}"
    line_no = next(iter(ch))
    ctx_name = ctx[0] if isinstance(ctx, tuple) else str(ctx)

    if spec.format == "find_bug":
        checks = [
            Check(name="buggy_fails", runner=runner, program=harness(buggy, tests), expect="fail"),
            Check(name="fixed_passes", runner=runner, program=harness(fixed, tests), expect="pass",
                  embeds_display_code=False),
        ]
        return build_variant(
            family_id, seed,
            stem=d["stem"],
            code=buggy,
            answer_key=AnswerKey(kind="line", value=line_no, explanation=d["explain"]),
            context=ctx_name,
            verification="execution",
            checks=checks,
            defect_type=defect_type,
            params={"fixed_code": fixed, "bug_line": line_no, **d.get("params", {})},
        )

    label = d.get("label", f"Заменить строку {line_no} на:")
    opts, key = make_options(
        rng,
        (label, d["fix_line"]),
        [(label, bad) for bad in d["bad_lines"]],
    )
    blines = buggy.splitlines()
    checks = []
    for o in opts:
        patched = "\n".join(blines[: line_no - 1] + [o.code or ""] + blines[line_no:])
        checks.append(Check(
            name=f"option:{o.id}",
            runner=runner,
            program=harness(patched, tests),
            expect="pass" if o.id == key else "fail",
            embeds_display_code=False,
        ))
    return build_variant(
        family_id, seed,
        stem=d["stem"],
        code=buggy,
        options=opts,
        answer_key=AnswerKey(kind="option", value=key, explanation=d["explain"]),
        context=ctx_name,
        verification="execution",
        checks=checks,
        defect_type=defect_type,
        display_code_note="Каждый вариант подставляется в строку с дефектом и прогоняется тестами в песочнице.",
        params={"bug_line": line_no, **d.get("params", {})},
    )
