"""Быстрый разбор вакансий без базы: направление и грейд против меток hh.ru — ТОЛЬКО для набора разработки (414).

Нужен для разбора ошибок классификатора направления/грейда (план 21.10, P1-5); на отложенном наборе запускать нельзя —
для него есть один прогон hh_holdout.py run. Отказывается работать с hh_holdout_corpus.json.

  cd backend && HH_CORPUS_DIR=<сырьё> python ../tools/realdata/hh_parse_eval.py [--errors]
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools/realdata"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--errors", action="store_true")
    ap.add_argument("--out", help="записать JSON-артефакт (docs/realdata/hh_dev_parse.json)")
    ap.add_argument("--dump", help="тексты расхождений для арбитража набора разработки (jsonl вне git)")
    a = ap.parse_args()
    if "holdout" in (os.environ.get("HH_MATCH_CORPUS") or ""):
        sys.exit("отложенный набор здесь не разбирается — только hh_holdout.py run (один раз)")
    os.environ.pop("HH_MATCH_CORPUS", None)
    import hh_plus as hp
    from app.modules.catalog import ext as catalog_ext
    from app.modules.catalog.seed_data import DIRECTIONS as BASE
    from app.modules.hh.directions import HH_DIRECTIONS
    from app.modules.matching import need_parser

    DIRECTIONS = [d for d in HH_DIRECTIONS if d in BASE or catalog_ext.is_visible(d)]  # как hh_plus.match

    corpus, items, raws = hp._load_corpus()
    assert corpus.get("kind") != "holdout"
    c = Counter()
    conf = Counter()
    errs = []
    for it in items:
        v = raws.get(it["id"])
        if v is None:
            continue
        lb = it["labels"]
        d = lb["direction"]
        r = need_parser.parse_need(hp.text_of(v), use_llm=False)
        if d in DIRECTIONS:
            c["dir_n"] += 1
            c[f"dir_n.{d}"] += 1
            ok = r.get("direction") == d
            c["dir_ok"] += ok
            c[f"dir_ok.{d}"] += ok
            if not ok:
                conf[(d, r.get("direction"))] += 1
                errs.append(("direction", d, r.get("direction"), v.get("name"), it["id"], hp.text_of(v)[:3000]))
        if lb["grade_title"]:
            c["gr_n"] += 1
            ok = r.get("grade") == lb["grade_title"]
            c["gr_ok"] += ok
            if not ok:
                errs.append(("grade", lb["grade_title"], r.get("grade"), v.get("name"), it["id"], hp.text_of(v)[:3000]))
    out = {"direction_ok": [c["dir_ok"], c["dir_n"], round(c["dir_ok"] / max(1, c["dir_n"]), 4)],
           "grade_ok": [c["gr_ok"], c["gr_n"], round(c["gr_ok"] / max(1, c["gr_n"]), 4)],
           "by_direction": {d: [c[f"dir_ok.{d}"], c[f"dir_n.{d}"]] for d in sorted(DIRECTIONS) if c[f"dir_n.{d}"]},
           "confusion": {f"{a}→{b}": n for (a, b), n in conf.most_common()}}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if a.out:
        from datetime import datetime, timezone

        art = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "code": os.environ.get("CODE_COMMIT") or "unknown", "set": "набор разработки (414 вакансий hh.ru, 2026-10-10; "
               "на нём настраивались словарь, синонимы и классификатор — оптимистично)", "corpus_collected_at": corpus["collected_at"],
               "direction_ok": {"value": out["direction_ok"][2], "k": out["direction_ok"][0], "n": out["direction_ok"][1]},
               "grade_ok": {"value": out["grade_ok"][2], "k": out["grade_ok"][0], "n": out["grade_ok"][1]},
               "by_direction": out["by_direction"], "confusion": out["confusion"],
               "recompute": "cd backend && CATALOG_EXT_ENABLED=1 HH_CORPUS_DIR=<сырьё> python ../tools/realdata/hh_parse_eval.py --out ../docs/realdata/hh_dev_parse.json"}
        Path(a.out).write_text(json.dumps(art, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if a.errors:
        for e in errs:
            print("\t".join(str(x) for x in e[:4]))
    if a.dump:
        with open(a.dump, "w", encoding="utf-8") as fh:
            for f, exp, act, title, vid, text in errs:
                fh.write(json.dumps({"id": vid, "field": f, "expected": exp, "actual": act, "title": title or "",
                                     "text": text}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
