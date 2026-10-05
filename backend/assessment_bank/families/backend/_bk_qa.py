"""Локальная приёмка семейств backend (не часть ядра; реестр этот модуль не импортирует).

Запуск из каталога bank/:
    ../.venv_bank/bin/python -m assessment_bank.families.backend._bk_qa [FID ...] [--seeds 200]

Для каждого семейства: validate_family на N seed (с проверкой детерминизма в отдельном
процессе), отношение длины правильного варианта к средней длине дистракторов, доля
вариантов, где правильный ответ — самый длинный, число строк кода в вариантах choose_fix.
Сводка сохраняется в families/backend/_evidence/qa_backend.json.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

from assessment_bank import generate, list_families
from assessment_bank.validator import validate_family

EVIDENCE = Path(__file__).parent / "_evidence"


def option_lengths(fid: str, n: int) -> dict:
    ratios, longest, total, line_spread = [], 0, 0, 0
    for s in range(1, n + 1):
        v = generate(fid, s)
        if not v.options:
            return {}
        key = v.answer_key.value
        groups: dict = {}
        for o in v.options:
            groups.setdefault(o.step, []).append(o)
        for st, opts in groups.items():
            k = key if st is None else key.get(str(st))
            ln = lambda o: len(o.text) + len(o.code or "")
            c = [ln(o) for o in opts if o.id == k]
            d = [ln(o) for o in opts if o.id != k]
            if not c or not d:
                continue
            ratios.append(c[0] / statistics.mean(d))
            longest += c[0] > max(d)
            total += 1
            if any(o.code for o in opts):
                nl = {len((o.code or "").splitlines()) for o in opts}
                line_spread = max(line_spread, max(nl) - min(nl))
    if not ratios:
        return {}
    return {"ratio_mean": round(statistics.mean(ratios), 3), "ratio_min": round(min(ratios), 3),
            "ratio_max": round(max(ratios), 3), "correct_longest_share": round(longest / total, 3),
            "code_line_spread": line_spread}


def main(argv: list[str]) -> int:
    n = 200
    if "--seeds" in argv:
        n = int(argv[argv.index("--seeds") + 1])
        argv = [a for i, a in enumerate(argv) if a != "--seeds" and argv[i - 1] != "--seeds"]
    fids = argv or [f.family_id for f in list_families(direction="backend")]
    out, bad = {}, 0
    for fid in fids:
        r = validate_family(fid, n_seeds=n, check_subprocess=True)
        ol = option_lengths(fid, n)
        out[fid] = {"status": r.status, "unique": r.unique_ratio, "n_unique": r.n_unique,
                    "keys": r.n_distinct_keys, "jaccard": r.mean_jaccard_distance,
                    "contexts": r.n_contexts, "lines": r.code_lines_observed,
                    "ops": r.operations_observed, "checks": r.n_checks,
                    "checks_failed": r.n_checks_failed, "positions": r.key_positions,
                    "position_p": r.key_position_p, "determinism_subprocess": r.determinism_subprocess,
                    "errors": r.errors[:5], "warnings": r.warnings[:5], "options": ol,
                    "seconds": r.seconds}
        bad += r.status == "FAIL"
        print(f"{r.status:4} {fid:48} uniq={r.unique_ratio:.3f} checks={r.n_checks}"
              f" failed={r.n_checks_failed} jacc={r.mean_jaccard_distance:.2f} {ol}", flush=True)
        for e in r.errors[:4] + r.warnings[:3]:
            print("   !", e[:300])
    EVIDENCE.mkdir(exist_ok=True)
    name = "qa_backend.json" if not argv else "qa_backend_partial.json"
    (EVIDENCE / name).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
