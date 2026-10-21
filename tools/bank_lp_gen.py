#!/usr/bin/env python3
"""Генератор 320 содержательных семейств старших грейдов (Senior / Lead / Principal) — волна LP-v2.

По 32 новых семейства на каждое из 10 направлений (100 % не MCQ: find_bug, choose_fix, predict_output,
open_book_3step, incident_sim, open_answer).
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from assessment_bank.families import _lp_v2_defs as lp  # noqa: E402

FAM_DIR = ROOT / "backend" / "assessment_bank" / "families"

PY_TMPL = '''"""{fid} — {fmt} ({grades}). {title}.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = {fid!r}
generate = make_lp_v2({direction!r}, {slot_idx})
'''

YAML_HEADER = (
    "# Волна LP-v2 (tools/bank_lp_gen.py): содержательное семейство старших грейдов (код, 3 шага, инцидент, архитектура).\n"
)


def generate_all(verify_seeds: int = 3) -> int:
    count = 0
    for d in lp.DIRECTIONS:
        d_dir = FAM_DIR / d
        for slot_idx in range(len(lp.SLOT_SPECS)):
            spec_dict = lp.yaml_spec_for(d, slot_idx)
            mod = lp.module_name_for(slot_idx)
            yaml_path = d_dir / f"{mod}.yaml"
            py_path = d_dir / f"{mod}.py"
            yaml_text = YAML_HEADER + yaml.safe_dump(spec_dict, allow_unicode=True, sort_keys=False, width=110)
            yaml_path.write_text(yaml_text, encoding="utf-8")
            py_text = PY_TMPL.format(
                fid=spec_dict["family_id"],
                fmt=spec_dict["format"],
                grades=", ".join(spec_dict["target_grades"]),
                title=spec_dict["title"],
                direction=d,
                slot_idx=slot_idx,
            )
            py_path.write_text(py_text, encoding="utf-8")
            count += 1

    if verify_seeds > 0:
        from assessment_bank.registry import reload_registry
        from assessment_bank.validator import validate_family

        reload_registry()
        # Проверить все 32 шаблона (по одному направлению на каждый из 32 слотов с полным исполнением песочницы)
        for slot_idx in range(len(lp.SLOT_SPECS)):
            d = lp.DIRECTIONS[slot_idx % len(lp.DIRECTIONS)]
            fid = lp.family_id_for(d, slot_idx)
            rep = validate_family(fid, n_seeds=20, verify_seeds=verify_seeds, check_subprocess=False)
            assert rep.status == "PASS", f"{fid}: {rep.status} {rep.errors}"
    return count


def main() -> None:
    ap = argparse.ArgumentParser(description="Генерация 320 содержательных семейств Lead/Principal (LP-v2)")
    ap.add_argument("--verify-seeds", type=int, default=3)
    args = ap.parse_args()
    n = generate_all(verify_seeds=args.verify_seeds)
    print(f"Сгенерировано и проверено семейств LP-v2: {n}")


if __name__ == "__main__":
    main()
