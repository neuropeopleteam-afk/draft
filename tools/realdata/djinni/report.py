"""Таблицы REPORT.md из external_djinni.json (ни одного числа руками): python tools/realdata/djinni/report.py"""
from __future__ import annotations

import collections
import json
from pathlib import Path

DOCS = Path(__file__).resolve().parents[3] / "docs/realdata/djinni"
NAMES = {"ndcg@10": "nDCG@10", "mrr_rel1": "MRR (≥1)", "mrr_rel2": "MRR (=2)", "p@5_rel1": "P@5 (≥1)", "p@5_rel2": "P@5 (=2)"}
CFG = {"B_grade_from_text": "«Драфт», B — грейд из текста (основная)", "A_direction_only": "«Драфт», A — только направление"}


def f(x: dict) -> str:
    return f"{x['mean']:.3f} [{x['ci95'][0]:.3f}; {x['ci95'][1]:.3f}]"


def main() -> str:
    o = json.loads((DOCS / "external_djinni.json").read_text(encoding="utf-8"))
    c = o["configs"]
    lines = ["| Метод | " + " | ".join(NAMES.values()) + " |", "|---" * (len(NAMES) + 1) + "|"]
    for n, title in CFG.items():
        lines.append(f"| {title} | " + " | ".join(f(c[n]["summary"]["draft"][k]) for k in NAMES) + " |")
    b = c[o["main_config"]]["summary"]
    lines.append("| BM25 | " + " | ".join(f(b["bm25"][k]) for k in NAMES) + " |")
    lines.append("| Случайный порядок | " + " | ".join(f(b["random"][k]) for k in NAMES) + " |")
    lines += ["", "Разность «Драфт − BM25» на тех же вакансиях (парный бутстреп, 95 % ДИ):", "",
              "| Конфигурация | " + " | ".join(NAMES.values()) + " |", "|---" * (len(NAMES) + 1) + "|"]
    for n, title in CFG.items():
        d = c[n]["draft_minus_bm25"]
        lines.append(f"| {title} | " + " | ".join(f"{d[k]['diff']:+.3f} [{d[k]['ci95'][0]:+.3f}; {d[k]['ci95'][1]:+.3f}]"
                                                   for k in NAMES) + " |")
    pv = o["per_vacancy"][o["main_config"]]
    by = collections.defaultdict(list)
    for p in pv:
        by[p["category"]].append(p)
    lines += ["", "По категориям (основная конфигурация, среднее nDCG@10; «мало кандидатов» — в выдаче меньше 10):", "",
              "| Категория | Вакансий | «Драфт» | BM25 | Мало кандидатов |", "|---|---|---|---|---|"]
    for cat, ps in sorted(by.items()):
        m = lambda s: sum(p[s]["ndcg@10"] for p in ps) / len(ps)  # noqa: E731
        lines.append(f"| {cat} | {len(ps)} | {m('draft'):.3f} | {m('bm25'):.3f} | {sum(1 for p in ps if p['eligible'] < 10)} |")
    return "\n".join(lines)


if __name__ == "__main__":
    print(main())
