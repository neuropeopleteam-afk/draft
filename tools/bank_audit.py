"""Аудит банка заданий (А3, 21.10.2026): то, что проверка 20.10 нашла руками, — одной командой.

Запуск (из backend/):
    PYTHONPATH=. python3 ../tools/bank_audit.py --seeds 20 --jobs 2 --out ../docs/bank/audit_2110.json

Что считает по всем семействам выдачи (`registry.load_specs()`), seed = 1..N:
1. generation_errors — семейства, у которых генерация падает хотя бы на одном seed.
2. grade_in_stem — в тексте, видимом кандидату (условие, код, варианты, шаги), названо слово грейда
   (Стажёр, Junior, Middle, Senior, Lead, Principal, «уровень …»).
3. public_leak — в публичном виде варианта (`Variant.public_view()`, то, что уходит в браузер) есть
   служебное поле (sim_effect, required, helpful, harmful, trap, opt_*, answer, correct, rubric, checks, key)
   или для find_bug/predict_output — сам ключ отдельным полем.
4. key_constancy — для каждого семейства доля самого частого «содержания» правильного ответа по seed:
   текст+код верного варианта (choose_fix, mcq_concept), текст строки дефекта (find_bug), ожидаемый вывод
   (predict_output), содержание верных вариантов по шагам (open_book_3step, incident_sim).
   Порог проверки 20.10 — 0,8: при большей доле одна шпаргалка закрывает семейство.
5. guess_attack — «решатель без знаний» на числовых вариантах выбора (все варианты ответа — числа):
   эвристики без расчёта (медиана, ближайший к среднему, самый «круглый», самый длинный, исключение
   вариантов вне ряда X из условия обратной задачи); итог — лучшая эвристика и её точность против шанса.

Ни одного числа руками: все цифры — из прогона, в JSON (`--out`).
"""
from __future__ import annotations

import argparse
import collections
import json
import multiprocessing as mp
import re
import statistics
import sys
import time
from typing import Any

# Слово грейда как метка уровня задания: английские названия с заглавной буквы, «уровень …», «principal-инженер» и
# русский сленг. Роли в сюжете («тимлид просит тест») и идентификаторы в коде (`middle`, `lead :=`) — не метка уровня;
# код варианта и код вариантов ответа в проверку не входят.
GRADE_RX = re.compile(
    r"(?-i:\b(Junior|Middle|Senior|Lead|Principal)\b)|\bСтаж[её]р|\b(junior|middle|senior|lead|principal)[-‑]?(инженер|разработчик|аналитик|архитектор)"
    r"|\bуров(ень|ня|не|нем)\s+(стаж|junior|middle|senior|lead|principal|джун|мидл|сень|синь|лид|принц)"
    r"|\b(джун\w*|мидл\w*|сеньор\w*|синьор\w*)\b",
    re.IGNORECASE,
)
_CAPS_ONLY = re.compile(r"\b(Junior|Middle|Senior|Lead|Principal)\b")
LEAK_KEYS = {"sim_effect", "required", "helpful", "harmful", "trap", "traps", "answer", "answer_key", "correct",
             "is_correct", "rubric", "checks", "key", "expected", "expected_stdout", "explanation", "solution",
             "effect", "score", "weight", "good", "bad", "params", "defect_type"}
NUM_RX = re.compile(r"^\s*[-−]?\d[\d\u00a0\u202f ]*(?:[.,]\d+)?")
SERIES_RX = re.compile(r"от\s+([\d\u00a0 ]+(?:[.,]\d+)?)\s*\S*\s+до\s+([\d\u00a0 ]+(?:[.,]\d+)?)\s*\S*\s+с шагом\s+"
                       r"([\d\u00a0 ]+(?:[.,]\d+)?)")


PREFIX_RX = re.compile(r"^\s*(?:≈|~|около|примерно|до)\s*")


def _num(s: str) -> float | None:
    m = NUM_RX.match(PREFIX_RX.sub("", s or ""))
    if not m:
        return None
    t = m.group(0).replace("\u00a0", "").replace("\u202f", "").replace(" ", "").replace("−", "-").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _walk_keys(obj: Any, path: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in LEAK_KEYS or kl.startswith("opt_"):
                out.append(f"{path}.{k}")
            out.extend(_walk_keys(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_walk_keys(v, f"{path}[{i}]"))
    return out


def _public_text(pv: dict[str, Any]) -> str:
    """Текст, который кандидат читает как условие: без кода (идентификаторы вроде `middle` — не подсказка)."""
    parts = [pv.get("stem") or ""]
    for o in pv.get("options") or []:
        parts += [o.get("text") or ""]
    for s in (pv.get("meta") or {}).get("steps") or []:
        parts.append(s.get("prompt") or "")
    if pv.get("incident") is not None:
        parts.append(json.dumps(pv["incident"], ensure_ascii=False))
    return "\n".join(parts)


def _key_content(v: Any) -> str | None:
    fmt = v.meta.format
    key = v.answer_key
    if fmt in ("choose_fix", "mcq_concept"):
        o = next((o for o in v.options or [] if o.id == key.value and o.step is None), None)
        return None if o is None else f"{o.text}\n{o.code or ''}".strip()
    if fmt == "find_bug":
        lines = (v.code or "").splitlines()
        try:
            n = int(key.value if not isinstance(key.value, list) else key.value[0])
        except (TypeError, ValueError):
            return None
        return lines[n - 1].strip() if 0 < n <= len(lines) else None
    if fmt == "predict_output":
        return str(key.value).strip()
    if fmt in ("open_book_3step", "incident_sim"):
        val = key.value
        if isinstance(val, dict):
            items = sorted(val.items())
        elif isinstance(val, list):
            items = list(enumerate(val, 1))
        else:
            return str(val)
        parts = []
        for st, kv in items:
            o = next((o for o in v.options or [] if o.step == int(st) and o.id == kv), None)
            parts.append(f"{st}:{(o.text + (o.code or '')) if o else kv}")
        return "|".join(parts)
    return None


def _guess(v: Any) -> dict[str, float] | None:
    """Точность эвристик без знаний на одном варианте (1 — угадала, 0 — нет, дробь — случайный выбор из k)."""
    if v.meta.format not in ("mcq_concept",) or not v.options:
        return None
    vals = [_num(o.text) for o in v.options]
    if any(x is None for x in vals) or len(set(vals)) < len(vals):
        return None
    ids = [o.id for o in v.options]
    key = v.answer_key.value
    n = len(vals)
    order = sorted(range(n), key=lambda i: vals[i])
    res: dict[str, float] = {"chance": 1.0 / n}
    res["median"] = 1.0 if ids[order[n // 2]] == key else 0.0
    mean = sum(vals) / n
    res["closest_to_mean"] = 1.0 if ids[min(range(n), key=lambda i: abs(vals[i] - mean))] == key else 0.0
    res["min"] = 1.0 if ids[order[0]] == key else 0.0
    res["max"] = 1.0 if ids[order[-1]] == key else 0.0

    def roundness(x: float) -> int:
        s = f"{abs(x):.6f}".rstrip("0").rstrip(".").replace(".", "")
        return len(s) - len(s.rstrip("0"))
    rmax = max(roundness(x) for x in vals)
    rbest = [i for i in range(n) if roundness(vals[i]) == rmax]
    res["roundest"] = (1.0 / len(rbest)) if any(ids[i] == key for i in rbest) else 0.0
    lens = [len(o.text) for o in v.options]
    lb = [i for i in range(n) if lens[i] == max(lens)]
    res["longest"] = (1.0 / len(lb)) if any(ids[i] == key for i in lb) else 0.0
    # «Самый типичный»: вариант с наименьшей суммой расстояний до остальных (центр кластера дистракторов)
    cen = min(range(n), key=lambda i: sum(abs(vals[i] - vals[j]) for j in range(n)))
    res["cluster_center"] = 1.0 if ids[cen] == key else 0.0
    # Исключение вне ряда X (обратные задачи): остаются варианты на сетке [lo, hi] с шагом st
    m = SERIES_RX.search(v.stem or "")
    if m:
        lo, hi, st = (_num(g) for g in m.groups())
        if lo is not None and hi is not None and st:
            inside = [i for i in range(n) if lo - 1e-9 <= vals[i] <= hi + 1e-9
                      and abs(((vals[i] - lo) / st) - round((vals[i] - lo) / st)) < 1e-6]
            res["series_exclusion"] = ((1.0 / len(inside)) if any(ids[i] == key for i in inside) else 0.0) \
                if inside else 1.0 / n
            res["series_all_out"] = 1.0 if len(inside) == 1 else 0.0
    return res


def _audit_family(args: tuple[str, int]) -> dict[str, Any]:
    fid, n_seeds = args
    from assessment_bank.registry import generate, get_spec
    spec = get_spec(fid)
    rep: dict[str, Any] = {"family_id": fid, "format": spec.format, "direction": spec.direction,
                           "grades": list(spec.target_grades), "errors": [], "grade_in_stem": 0,
                           "leak_fields": [], "key_contents": [], "guess": []}
    for s in range(1, n_seeds + 1):
        try:
            v = generate(fid, s)
        except Exception as e:  # noqa: BLE001
            rep["errors"].append(f"seed {s}: {type(e).__name__}: {str(e)[:200]}")
            continue
        pv = v.public_view()
        if GRADE_RX.search(_public_text(pv)):
            rep["grade_in_stem"] += 1
        lk = _walk_keys({k: pv[k] for k in pv if k != "meta"}) + _walk_keys(pv.get("meta") or {}, ".meta")
        if lk:
            rep["leak_fields"].extend(lk[:5])
        kc = _key_content(v)
        if kc is not None:
            rep["key_contents"].append(kc)
        g = _guess(v)
        if g is not None:
            rep["guess"].append(g)
    kcs = rep.pop("key_contents")
    if kcs:
        top, cnt = collections.Counter(kcs).most_common(1)[0]
        rep["key_constancy"] = round(cnt / len(kcs), 4)
        rep["key_distinct"] = len(set(kcs))
    rep["leak_fields"] = sorted(set(rep["leak_fields"]))[:10]
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--families", nargs="*")
    ap.add_argument("--out", default=None)
    ap.add_argument("--constancy-threshold", type=float, default=0.8)
    a = ap.parse_args()
    from assessment_bank.registry import load_specs
    fids = a.families or sorted(load_specs())
    t0 = time.time()
    with mp.Pool(a.jobs) as pool:
        reps = pool.map(_audit_family, [(f, a.seeds) for f in fids], chunksize=8)
    gen_err = [r for r in reps if r["errors"]]
    grade = [r for r in reps if r["grade_in_stem"]]
    leak = [r for r in reps if r["leak_fields"]]
    const = [r for r in reps if r.get("key_constancy", 0) >= a.constancy_threshold]
    # «решатель без знаний»: точность каждой эвристики по всем числовым вариантам выбора
    allg: dict[str, list[float]] = collections.defaultdict(list)
    by_kind: dict[str, dict[str, list[float]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in reps:
        kind = "inverse" if "_solve_" in r["family_id"] else ("forward" if "_fwd_" in r["family_id"] else "other")
        for g in r["guess"]:
            for h, x in g.items():
                allg[h].append(x)
                by_kind[kind][h].append(x)

    def summ(d: dict[str, list[float]]) -> dict[str, Any]:
        out = {h: round(statistics.mean(xs), 4) for h, xs in d.items() if xs}
        best = max((h for h in out if h != "chance"), key=lambda h: out[h], default=None)
        return {"n_variants": len(d.get("chance", [])), "chance": out.get("chance"), "best_heuristic": best,
                "best_accuracy": out.get(best) if best else None, "by_heuristic": out}
    fmt_counts = collections.Counter(r["format"] for r in reps)
    result = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "command": " ".join(["python3", "../tools/bank_audit.py"] + sys.argv[1:]),
        "n_families": len(reps), "n_seeds": a.seeds, "seconds": round(time.time() - t0, 1),
        "formats": dict(fmt_counts),
        "generation_errors": {"n_families": len(gen_err), "families": {r["family_id"]: r["errors"][:2] for r in gen_err}},
        "grade_in_stem": {"n_families": len(grade), "families": [r["family_id"] for r in grade][:200]},
        "public_leak": {"n_families": len(leak), "families": {r["family_id"]: r["leak_fields"] for r in leak}},
        "key_constancy": {
            "threshold": a.constancy_threshold, "n_families_at_or_above": len(const),
            "n_families_measured": sum(1 for r in reps if "key_constancy" in r),
            "families": {r["family_id"]: r["key_constancy"] for r in sorted(const, key=lambda r: -r["key_constancy"])},
            "by_format_mean": {f: round(statistics.mean([r["key_constancy"] for r in reps
                                                         if r["format"] == f and "key_constancy" in r]), 4)
                               for f in fmt_counts if any(r["format"] == f and "key_constancy" in r for r in reps)},
        },
        "guess_attack": {"all_numeric_choice": summ(allg), **{k: summ(v) for k, v in by_kind.items()}},
    }
    js = json.dumps(result, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(js + "\n")
    short = {k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk not in ("families",)})
             for k, v in result.items()}
    print(json.dumps(short, ensure_ascii=False, indent=1)[:6000])
    bad = len(gen_err) + len(grade) + len(leak)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
