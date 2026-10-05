"""Локальная приёмка security; выводы сохраняются только в собственном каталоге.

Из bank/: ../.venv_bank/bin/python -m assessment_bank.families.security._qa_security --grade junior
Повторить для middle и senior. Вызывает именно tools/dev_family.py FAMILY_ID 200.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from assessment_bank.registry import generate, list_families
from assessment_bank.validator import subprocess_hashes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--grade", choices=["junior", "middle", "senior"], required=True)
    args = parser.parse_args()
    outdir = Path(__file__).parent / "_evidence"
    outdir.mkdir(exist_ok=True)
    root = Path(__file__).resolve().parents[3]
    rows = []
    for spec in list_families(direction="security", grade=args.grade):
        command = [sys.executable, "tools/dev_family.py", spec.family_id, "200"]
        result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
        logpath = outdir / f"{spec.family_id}.txt"
        logpath.write_text(result.stdout + result.stderr, encoding="utf-8")
        summary = next((s for s in result.stdout.splitlines() if s.startswith("STATUS ")), "")
        assert result.returncode == 0, (spec.family_id, result.stderr)
        assert summary and not summary.startswith("STATUS FAIL"), (spec.family_id, summary)
        pairs = [(spec.family_id, s) for s in range(1, 201)]
        hashes = subprocess_hashes(pairs, hashseed="8675309")
        assert hashes == [generate(fid, s).canonical_hash() for fid, s in pairs], spec.family_id
        variants = [generate(spec.family_id, s) for s in range(1, 201)]
        for variant in variants:
            pv = variant.public_view()
            assert "answer_key" not in pv and "rubric" not in pv
            assert all(k not in pv["meta"] for k in ["checks", "params", "verification", "defect_type"])
            assert variant.meta.family_id.startswith("security.")
            if spec.format in ["open_book_3step", "open_answer"]:
                assert len(variant.rubric.criteria) == 3
                assert len({variant.rubric.strong, variant.rubric.medium, variant.rubric.weak}) == 3
        # Для choose_fix нет подсказки по числу строк; текст действия одинаков для всех.
        if spec.format == "choose_fix":
            for variant in variants:
                assert len({o.text for o in variant.options}) == 1
                lines = [len(o.code.splitlines()) for o in variant.options]
                assert max(lines) - min(lines) <= 1, (spec.family_id, lines)
        match = re.search(r"checks (\d+) failed (\d+)", summary)
        row = {
            "family_id": spec.family_id, "format": spec.format, "grades": spec.target_grades,
            "b": spec.prior_difficulty.b, "canary": spec.canary,
            "status": summary.split()[1], "dev_command": command,
            "summary": summary, "n_checks": int(match[1]), "n_checks_failed": int(match[2]),
            "warnings": [s[4:] for s in result.stdout.splitlines() if s.startswith("  ! ")],
            "cross_process_seeds": 200, "cross_process_hashseed": "8675309",
            "runners": dict(Counter(c.runner for v in variants for c in v.meta.checks)),
            "unique": len({v.fingerprint() for v in variants}),
            "public_view_and_rubrics": "PASS", "log": str(logpath),
        }
        rows.append(row)
        print(spec.family_id, summary, flush=True)
    reportpath = outdir / f"validation_{args.grade}.json"
    reportpath.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("SAVED", reportpath, flush=True)


if __name__ == "__main__":
    main()
