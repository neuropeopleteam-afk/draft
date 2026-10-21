#!/usr/bin/env python3
"""Счёт корпуса вакансий hh.ru для NUMBERS (А4): сколько собрано и сколько в проверках — только подсчётом файлов.

Собрано — число JSON-файлов в data_local/hh_corpus/raw (вне git, на «Москве»); в проверках — три непересекающихся
набора из docs/realdata: разработка (hh_match_corpus.json), отложенный №1 (hh_holdout_corpus.json), №2
(hh_holdout2_corpus.json); пересечение по id проверяется. Результат — docs/validation/hh_corpus_counts.json.

Запуск (на «Москве», из корня репозитория):
  python3 tools/publish/hh_corpus_counts.py --raw /opt/spectrek_fsp/data_local/hh_corpus/raw
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETS = {"dev": "docs/realdata/hh_match_corpus.json", "holdout1": "docs/realdata/hh_holdout_corpus.json",
        "holdout2": "docs/realdata/hh_holdout2_corpus.json"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", default=str(ROOT / "docs" / "validation" / "hh_corpus_counts.json"))
    a = ap.parse_args()
    raw = Path(a.raw)
    raw_ids = {p.stem for p in raw.glob("*.json")}
    sets, ids = {}, {}
    for k, rel in SETS.items():
        d = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        ids[k] = {str(i["id"]) for i in d["items"]}
        sets[k] = {"n": len(ids[k]), "file": rel, "collected_at": d.get("collected_at")}
    keys = list(SETS)
    overlap = {f"{x}&{y}": len(ids[x] & ids[y]) for i, x in enumerate(keys) for y in keys[i + 1:]}
    in_checks = set().union(*ids.values())
    out = {"collected": len(raw_ids), "collected_where": "data_local/hh_corpus/raw (вне git, 152-ФЗ не затрагивается: вакансии)",
           "in_checks": len(in_checks), "sets": sets, "overlap_by_id": overlap,
           "in_checks_found_in_raw": len(in_checks & raw_ids),
           "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "recompute": "python3 tools/publish/hh_corpus_counts.py --raw /opt/spectrek_fsp/data_local/hh_corpus/raw"}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("collected", "in_checks", "overlap_by_id", "in_checks_found_in_raw")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
