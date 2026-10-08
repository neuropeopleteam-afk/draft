"""Командная строка: python -m assessment_bank {list|generate|validate|simulate|canary-leak}."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="assessment_bank", description="Банк заданий: генерация, валидация, симуляция")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="список семейств")
    p.add_argument("--direction")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("generate", help="сгенерировать вариант")
    p.add_argument("family_id")
    p.add_argument("seed", type=int)
    p.add_argument("--public", action="store_true", help="только то, что видит кандидат")
    p = sub.add_parser("validate", help="валидатор банка")
    p.add_argument("--seeds", type=int, default=200)
    p.add_argument("--verify-seeds", type=int, default=None,
                   help="на скольких seed исполнять проверки ключа (по умолчанию на всех)")
    p.add_argument("--families", nargs="*")
    p.add_argument("--out", default="reports")
    p = sub.add_parser("simulate", help="симуляция адаптивного теста")
    p.add_argument("--n", type=int, default=1000)
    p.add_argument("--seed", type=int, default=20261005)
    p.add_argument("--out", default="reports")
    p = sub.add_parser("canary-leak", help="выгрузить опубликованные канарейки (демо утечки)")
    p.add_argument("--out", default="reports/canary_leak.json")
    a = ap.parse_args(argv)

    if a.cmd == "list":
        from .registry import list_families
        fams = list_families(direction=a.direction)
        if a.json:
            print(json.dumps([f.model_dump(mode="json") for f in fams], ensure_ascii=False, indent=2))
        else:
            for f in fams:
                print(f"{f.family_id:42} {f.format:16} {','.join(f.target_grades):22} "
                      f"{'canary' if f.canary else ''}")
            print(f"всего: {len(fams)}")
        return 0
    if a.cmd == "generate":
        from .registry import generate
        v = generate(a.family_id, a.seed)
        data = v.public_view() if a.public else v.model_dump(mode="json")
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return 0
    if a.cmd == "validate":
        from .validator import report_markdown, validate_bank
        res = validate_bank(a.seeds, a.verify_seeds, a.families, progress=True)
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "validation_report.json").write_text(json.dumps(res, ensure_ascii=False, indent=2,
                                                               default=str), encoding="utf-8")
        (out / "validation_report.md").write_text(report_markdown(res), encoding="utf-8")
        s = res["summary"]
        print(json.dumps(s, ensure_ascii=False, indent=2))
        # код выхода 1, если хоть одно семейство FAIL (считается и по n_fail, и по счётчику статусов —
        # на случай отчёта, собранного старой версией)
        n_fail = int(s.get("n_fail") or 0) or int(dict(s.get("status") or {}).get("FAIL", 0) or 0)
        return 1 if n_fail else 0
    if a.cmd == "simulate":
        from .simulation import run_all
        run_all(n=a.n, seed=a.seed, out_dir=a.out)
        print(f"отчёт: {Path(a.out) / 'simulation_report.md'}")
        return 0
    if a.cmd == "canary-leak":
        from .serving import export_canary_leak
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(export_canary_leak(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(a.out)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
