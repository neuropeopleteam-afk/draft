"""Проверка пакета банка заданий backend/assessment_bank в CI: валидатор на каждом семействе.

Что проверяется (assessment_bank/validator.py): детерминизм генерации по seed, уникальность и разнообразие
вариантов, соблюдение инвариантов (размер кода, число операций, тип дефекта), публичная часть без ключа и рубрики,
ключи ответов — исполнением кода в песочнице (python, node, bash, git, sqlite) на части seed.

Запуск (из каталога backend):
    python ../tools/ci/check_bank.py --seeds 20 --verify-seeds 3 --out /tmp/bank_report
Код возврата 1, если есть семейство со статусом FAIL или проваленная проверка ключа; WARN не валит сборку.
`python -m assessment_bank validate` сам код ошибки не возвращает (сверяет несуществующее поле n_fail), поэтому
решение принимается здесь. Сводка в Markdown — в $GITHUB_STEP_SUMMARY, если он задан.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--verify-seeds", type=int, default=3)
    ap.add_argument("--out", default="bank_report")
    a = ap.parse_args()

    sys.path.insert(0, str(Path.cwd()))
    from assessment_bank.validator import report_markdown, validate_bank

    res = validate_bank(a.seeds, a.verify_seeds, None, progress=True)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation_report.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), "utf-8")
    (out / "validation_report.md").write_text(report_markdown(res), "utf-8")

    s = res["summary"]
    status = dict(s["status"])
    failed = [f for f in res["families"] if f["status"] == "FAIL"]
    by_dir = ", ".join(f"{k}: {v}" for k, v in sorted(dict(s["by_direction"]).items()))
    lines = [
        "### Банк заданий: валидатор",
        "",
        f"Семейств: **{s['n_families']}** ({by_dir}); вариантов: {s['n_variants_generated']}, "
        f"уникальных: {s['n_unique_variants']}; проверок ключа исполнением: {s['n_checks']}, "
        f"провалено: **{s['n_checks_failed']}**; статусы: {status}; время: {s['seconds']} с "
        f"(seed на семейство: {a.seeds}, с исполнением: {a.verify_seeds}).",
    ]
    for f in failed:
        lines.append(f"- FAIL `{f['family_id']}`: {'; '.join(f['errors'][:3])}")
    text = "\n".join(lines) + "\n"
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 1 if failed or s["n_checks_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
