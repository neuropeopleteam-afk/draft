"""Автопроверка в кубке: задания банка (assessment_bank) с ключом, у каждого участника свои варианты.

* Семейства выбираются при создании кубка (одинаковые для всех — сопоставимая сложность), а seed варианта —
  при старте участия из криптостойкого ГСЧ: список ответов, переданный другу, не подходит к его варианту.
* Только форматы с однозначным ключом: choose_fix, mcq_concept (вариант), find_bug (строка), predict_output (вывод).
  Канарейки не используются. Код участников не исполняется — ответы сверяются с ключом.
* Ключ и seed хранятся в cup_entries.tasks и наружу не отдаются (public_tasks).
"""
from __future__ import annotations

import random
import secrets

from assessment_bank import generate, load_specs
from assessment_bank.metrics import normalize_output

AUTO_FORMATS = ("choose_fix", "mcq_concept", "find_bug", "predict_output")
ANSWER_KIND = {"choose_fix": "option", "mcq_concept": "option", "find_bug": "line", "predict_output": "text"}
SEED_MIN, SEED_MAX = 10_000_000, 2**31 - 1
MAX_TEXT = 4000


def available_families(direction: str, grade: str) -> dict[str, list[str]]:
    """Семейства банка для кубка: блок направления и общий блок, подходящие грейду (иначе — любые)."""
    specs = load_specs()
    out: dict[str, list[str]] = {}
    for block in (direction, "common"):
        pool = [s for s in specs.values() if s.direction == block and s.format in AUTO_FORMATS and not s.canary]
        fit = [s.family_id for s in pool if grade in s.target_grades]
        out[block] = sorted(fit if len(fit) >= 2 else [s.family_id for s in pool])
    return out


def pick_families(direction: str, grade: str, n: int, seed: int | None = None) -> list[str]:
    """n семейств: примерно 2/3 из направления, остальное — общий блок; разные форматы по возможности."""
    rnd = random.Random(seed if seed is not None else secrets.randbits(32))
    av = available_families(direction, grade)
    n_dir = min(len(av[direction]), max(1, round(n * 2 / 3)))
    chosen = rnd.sample(av[direction], n_dir)
    rest = [f for f in av["common"] if f not in chosen]
    chosen += rnd.sample(rest, min(len(rest), n - len(chosen)))
    if len(chosen) < n:  # мало общего блока — добираем из направления
        extra = [f for f in av[direction] if f not in chosen]
        chosen += rnd.sample(extra, min(len(extra), n - len(chosen)))
    return chosen


def issue(families: list[str]) -> list[dict]:
    """Варианты для одного участника (свои seed)."""
    specs = load_specs()
    items = []
    for i, fid in enumerate(families, start=1):
        seed = SEED_MIN + secrets.randbelow(SEED_MAX - SEED_MIN)
        v = generate(fid, seed)
        pv = v.public_view()
        fmt = specs[fid].format
        items.append({
            "token": secrets.token_urlsafe(9), "position": i, "family_id": fid, "seed": seed, "format": fmt,
            "kind": ANSWER_KIND[fmt], "language": specs[fid].language,
            "public": {"stem": pv["stem"], "code": pv["code"],
                       "options": [{k: o[k] for k in ("id", "text", "code") if o.get(k) is not None}
                                   for o in (pv["options"] or [])] or None,
                       "code_lines": len((pv["code"] or "").splitlines())},
            "key": v.answer_key.model_dump(include={"kind", "value", "accept"}),
            "answer": None, "correct": None,
        })
    return items


def public_tasks(items: list[dict], reveal_result: bool = False) -> list[dict]:
    """Что видит участник: текст, код, варианты, тип ответа; после отправки — верно/неверно (без ключа)."""
    out = []
    for it in items:
        d = {"token": it["token"], "position": it["position"], "format": it["format"], "kind": it["kind"],
             "language": it.get("language"), **it["public"], "answer": it.get("answer")}
        if reveal_result:
            d["correct"] = it.get("correct")
        out.append(d)
    return out


def _norm(it: dict, raw) -> str | int | None:
    if raw is None:
        return None
    if it["kind"] == "option":
        a = str(raw).strip().upper()
        return a if a in {o["id"] for o in (it["public"]["options"] or [])} else None
    if it["kind"] == "line":
        try:
            n = int(str(raw).strip())
        except (TypeError, ValueError):
            return None
        return n if 1 <= n <= max(1, it["public"]["code_lines"]) else None
    return str(raw)[:MAX_TEXT]


def _is_correct(it: dict, a) -> bool:
    key = it["key"]
    if a is None:
        return False
    if it["kind"] == "option":
        return a == key["value"] or a in key.get("accept", [])
    if it["kind"] == "line":
        return a == int(key["value"]) or str(a) in key.get("accept", [])
    got = normalize_output(str(a))
    return got == normalize_output(str(key["value"])) or got in {normalize_output(x) for x in key.get("accept", [])}


def score(items: list[dict], answers: dict[str, object]) -> float:
    """Записывает ответы и верность в items, возвращает долю верных (0..1)."""
    if not items:
        return 0.0
    ok = 0
    for it in items:
        a = _norm(it, answers.get(it["token"]))
        it["answer"] = a
        it["correct"] = _is_correct(it, a)
        ok += int(it["correct"])
    return round(ok / len(items), 4)
