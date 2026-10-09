"""Я11 (С3-1…С3-3): разбор потребности на 50 реальных вакансиях — парсер ревизии REV против рабочего дерева.

Те же поля и та же silver-разметка, что в tools/realdata/benchmark.py (measure): точность направления, грейда,
опыта, формата, вилки; P/R стека; цитаты. Плюс две метрики правок Я11:
  * spread — сколько перечислений «обязательно» (одно предложение / один список) получили РАЗНЫЕ веса
    (С3-3: «Docker 0,53 при Django 0,85 в одном перечислении»);
  * changed — какие вакансии разобраны иначе (поля и веса), с ожидаемым значением разметки.
Модель не вызывается (use_llm=False): путь правил. Без записи в docs/ по умолчанию; --out <файл> — сохранить JSON.

  cd backend && python ../tools/realdata/parse_compare.py --rev 601e2ba [--out /tmp/x.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools/realdata"))
from benchmark import FIELDS, measure  # noqa: E402

from app.modules.matching import need_parser  # noqa: E402


def parser_at(rev: str):
    """parse_need из need_parser.py ревизии rev; словарь, справочник и остальные модули — текущие."""
    src = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{rev}:backend/app/modules/matching/need_parser.py"],
                                  text=True)
    ns: dict = {"__name__": f"need_parser_{rev}"}
    exec(compile(src, f"need_parser@{rev}", "exec"), ns)
    return ns["parse_need"]


def _groups(text: str, items: list[dict]) -> list[list[float]]:
    """Веса обязательных навыков, сгруппированные по предложению/строке цитаты (одно перечисление)."""
    sents = need_parser._sentences(text)
    out: dict[int, list[float]] = {}
    for it in items:
        s = (it.get("evidence") or {}).get("start")
        if s is None:
            continue
        k = next((i for i, (a, b, _t) in enumerate(sents) if a <= s < b), -1)
        out.setdefault(k, []).append(it["weight"])
    return [w for w in out.values() if len(w) > 1]


def spread(rows, results) -> dict:
    groups = [g for row, req in zip(rows, results) for g in _groups(row["text"], req["stack_required"])]
    uneven = [g for g in groups if max(g) - min(g) > 1e-9]
    return {"lists_with_2plus": len(groups), "lists_uneven": len(uneven),
            "max_gap": round(max((max(g) - min(g) for g in uneven), default=0.0), 2)}


def summary(m: dict) -> dict:
    return {**{f: f"{m['fields'][f]['correct']}/{m['fields'][f]['n']}" for f in FIELDS},
            "stack_P": m["stack_micro_precision"], "stack_R": m["stack_micro_recall"],
            "quotes": m["quotes"], "invalid_quotes": m["invalid_quotes"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default="601e2ba")
    ap.add_argument("--out")
    a = ap.parse_args()
    rows = json.loads((ROOT / "docs/realdata/vacancies_50.json").read_text())["vacancies"]
    before = [parser_at(a.rev)(r["text"], use_llm=False) for r in rows]
    after = [need_parser.parse_need(r["text"], use_llm=False) for r in rows]
    mb, ma = measure(rows, before), measure(rows, after)
    changed = []
    for r, b, x in zip(rows, before, after):
        d = {f: [b.get(f), x.get(f), r["expected"][f]] for f in FIELDS if b.get(f) != x.get(f)}
        wb = {i["tag"]: i["weight"] for i in b["stack_required"] + b["stack_desired"]}
        wa = {i["tag"]: i["weight"] for i in x["stack_required"] + x["stack_desired"]}
        if wb != wa:
            d["weights"] = {t: [wb.get(t), wa.get(t)] for t in sorted(set(wb) | set(wa)) if wb.get(t) != wa.get(t)}
        if d:
            changed.append({"id": r["id"], **d})
    out = {"rev": a.rev, "n": len(rows), "before": summary(mb), "after": summary(ma),
           "spread_before": spread(rows, before), "spread_after": spread(rows, after),
           "fields_changed": [c for c in changed if set(c) - {"id", "weights"}],
           "weights_changed": sum("weights" in c for c in changed)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps({**out, "changed": changed}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    re  # noqa: B018 — модуль re нужен exec-копии парсера через общий импорт
    main()
