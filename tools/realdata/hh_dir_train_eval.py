"""Разбор направления против ЧИСТЫХ меток на обучающих наборах (набор разработки + первый отложенный набор после его
единственного отчёта): метка = итог арбитража для спорных (оба арбитра согласны), иначе метка hh.ru. Не для отчёта —
отчёт только на новом отложенном наборе. NEED_TITLE_ROLE=0 — без правил роли в названии (dir-v2) для сравнения.

  cd backend && HH_CORPUS_DIR=<сырьё> CATALOG_EXT_ENABLED=1 python ../tools/realdata/hh_dir_train_eval.py [--errors]
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools/realdata"))

SETS = (("dev", "docs/realdata/hh_match_corpus.json", "docs/realdata/hh_dev_adjudication.json"),
        ("holdout1_now_train", "docs/realdata/hh_holdout_corpus.json", "docs/realdata/hh_holdout_adjudication.json"))


def main() -> None:
    import hh_plus as hp
    from app.modules.catalog import ext as catalog_ext
    from app.modules.catalog.seed_data import DIRECTIONS as BASE
    from app.modules.hh.directions import HH_DIRECTIONS
    from app.modules.matching import need_parser

    dirs = [d for d in HH_DIRECTIONS if d in BASE or catalog_ext.is_visible(d)]
    show = "--errors" in sys.argv
    res = {}
    for name, corpus, adj in SETS:
        items = json.loads((ROOT / corpus).read_text(encoding="utf-8"))["items"]
        fin = {}
        a = json.loads((ROOT / adj).read_text(encoding="utf-8"))
        for r in a["rows"]:
            if r["field"] == "direction" and len(set(r["arbiters"].values())) == 1 and None not in r["arbiters"].values():
                fin[r["id"]] = r["final"]
        ok = n = notit_ok = notit_n = 0
        for it in items:
            d = it["labels"]["direction"]
            if d not in dirs:
                continue
            lab = fin.get(it["id"], d)
            v = hp.detail(None, it["id"])
            if v is None:
                continue
            p = need_parser.parse_need(hp.text_of(v), use_llm=False).get("direction")
            if lab == "not_it":
                notit_n += 1
                notit_ok += p is None
                continue
            n += 1
            ok += p == lab
            if show and p != lab:
                print(name, lab, p, (v.get("name") or "")[:90], sep="\t")
        res[name] = {"it_ok": [ok, n, round(ok / max(1, n), 4)], "not_it_none": [notit_ok, notit_n]}
    print(json.dumps({"title_role": os.environ.get("NEED_TITLE_ROLE", "1"), **res}, ensure_ascii=False))


if __name__ == "__main__":
    main()
