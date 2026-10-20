#!/usr/bin/env python3
"""Запуск мутационного самоконтроля всех кодовых заданий банка (P0) и сохранение отчёта."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from assessment_bank.mutation import audit_code_mutations  # noqa: E402


def main() -> None:
    t0 = time.time()
    rep = audit_code_mutations(seed=1)
    dt = round(time.time() - t0, 2)
    rep["elapsed_s"] = dt

    out_dir = ROOT / "docs" / "bank"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {k: v for k, v in rep.items() if k != "families"}
    (out_dir / "mutation_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Мутационный самоконтроль кодовых заданий банка (P0)",
        "",
        f"- Проверено кодовых семейств: **{rep['n_code_families']}**",
        f"- Эталонных решений прошло тесты: **{rep['n_ref_passed']} из {rep['n_code_families']} ({rep['ref_pass_rate'] * 100:.1f} %)**",
        f"- Сгенерировано и проверено мутантов (инверсия условия, сдвиг границы ±1, пропуск ветки, дефектная строка): **{rep['n_mutants']}**",
        f"- Отбраковано (убито) мутантов тестовой обвязкой: **{rep['n_killed']} из {rep['n_mutants']} ({rep['mutation_kill_rate'] * 100:.2f} %)**",
        f"- Время проверки: **{dt} с**",
        "",
        "## Разбивка по форматам",
        "",
        "| Формат | Семейств | Мутантов | Убито | Доля отбраковки |",
        "|---|---:|---:|---:|---:|",
    ]
    for fmt, bf in sorted(rep["by_format"].items()):
        lines.append(f"| `{fmt}` | {bf['families']} | {bf['mutants']} | {bf['killed']} | {bf['kill_rate'] * 100:.2f} % |")
    lines.extend([
        "",
        "## Команда воспроизведения",
        "```bash",
        "python3 tools/bank_mutation_check.py",
        "```",
    ])
    (out_dir / "MUTATION_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
