#!/usr/bin/env python3
"""Мутационный самоконтроль кодовых заданий банка (А3, 21.10.2026) — честная версия.

Запуск из корня: python3 tools/bank_mutation_check.py [--seeds 1,2] [--limit 8]
Пишет docs/bank/mutation_report.json и docs/bank/MUTATION_REPORT.md. Метод — в assessment_bank/mutation.py
(audit_solution_mutations): мутируется только эталонное решение, тесты задания не меняются.
Прежняя версия (audit_code_mutations) давала 100 % по построению и больше не используется для цифр.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from assessment_bank.mutation import audit_solution_mutations  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1")
    ap.add_argument("--limit", type=int, default=8)
    a = ap.parse_args()
    seeds = tuple(int(s) for s in a.seeds.split(","))
    t0 = time.time()
    rep = audit_solution_mutations(seeds=seeds, limit=a.limit)
    rep["elapsed_s"] = round(time.time() - t0, 1)
    rep["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    rep["recompute"] = f"python3 tools/bank_mutation_check.py --seeds {a.seeds} --limit {a.limit}"
    out = ROOT / "docs" / "bank"
    out.mkdir(parents=True, exist_ok=True)
    (out / "mutation_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pct = lambda x: "—" if x is None else f"{x * 100:.1f} %".replace(".", ",")  # noqa: E731
    lines = ["# Мутационный самоконтроль кодовых заданий банка", "",
             f"Метод: {rep['method']}.", "",
             f"- Семейств: {rep['n_families']}, эталон проходит тесты: {rep['n_ref_ok']}",
             f"- Мутантов решения: {rep['n_mutants']}, отвергнуто тестами: {rep['n_killed']} "
             f"({pct(rep['mutation_kill_rate'])})",
             f"- Известных дефектов и неверных исправлений: {rep['n_known_bad']}, отвергнуто тестами: "
             f"{rep['n_known_bad_rejected']} ({pct(rep['known_bad_reject_rate'])})",
             f"- Семейств с исполнителем без мутаций решения (go, java, bash, sqlite, git): "
             f"{rep['unsupported_runner_families']}",
             f"- seed: {rep['seeds']}, время {rep['elapsed_s']} с; пересчёт: `{rep['recompute']}`", "",
             "| Формат | Семейств | Мутантов | Отвергнуто | Известных дефектов отвергнуто |", "|---|---|---|---|---|"]
    for f, b in rep["by_format"].items():
        lines.append(f"| {f} | {b['families']} | {b['mutants']} | {pct(b['kill_rate'])} | "
                     f"{pct(b['known_bad_reject_rate'])} |")
    lines += ["", "## Самые слабые тесты (доля отвергнутых мутантов)", ""]
    for w in rep["weakest_families"][:15]:
        lines.append(f"- `{w['family_id']}` — {pct(w['kill_rate'])}; выжили: {'; '.join(w['survivors'])}")
    (out / "MUTATION_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k not in ("by_format", "weakest_families")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
