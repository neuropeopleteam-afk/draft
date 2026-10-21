"""Быстрая очистка индекса протоколов ФСП (P0-0 перед выкладкой волны 1).

Что убирается и почему:
- записи судей: в справках о составе судейской коллегии, которые лежат в тех же PDF, распознаватель
  принял судей за спортсменов («разряд» = судейская категория ВК/1К/2К/3К);
- документ ``kr_2025_sk_otbor`` целиком — это справка о судейской коллегии, а не протокол;
- записи с тем же ``fio_hash``, что у судьи, в том же документе (страховка от судьи без категории).
Что чистится в оставшихся записях:
- поле ``rank`` оставляется только для настоящих спортивных званий и разрядов (МСМК, МС, КМС, I–III,
  юношеские); прочее (пол «М/Ж», баллы, «Спортсмен») — ``None``, исходное значение — ``rank_raw``.

Исходный ``index.json`` не меняется; результат — новый файл (по умолчанию ``index_w1.json``, права 600)
и отчёт ``clean_w1_report.json`` без персональных данных.

Запуск на сервере:  python3 tools/fsp_protocols/clean_w1.py /opt/spectrek_fsp/data_local/fsp_protocols
"""
from __future__ import annotations

import collections
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

JUDGE_CATEGORIES = {"ВК", "1К", "2К", "3К", "ССВК", "СС1К", "СС2К", "СС3К", "ЮС", "МК"}
SPORT_RANKS = {"МСМК", "МС", "КМС", "I", "II", "III", "Iю", "IIю", "IIIю"}
RANK_ALIASES = {"1": None, "КМС.": "КМС", "1ю": "Iю", "2ю": "IIю", "3ю": "IIIю", "1 разряд": "I",
                "2 разряд": "II", "3 разряд": "III"}
NOT_PROTOCOL_DOCS = {"g6txm9cku30ktl7o93u8xw40kpjv9kin.pdf"}  # kr_2025_sk_otbor — справка о судьях


def clean(index: dict) -> tuple[dict, dict]:
    recs = index["records"]
    judge_fio_by_doc: dict[str, set[str]] = collections.defaultdict(set)
    for r in recs:
        if (r.get("rank") or "").strip() in JUDGE_CATEGORIES:
            judge_fio_by_doc[r["pdf_url"]].add(r.get("fio_hash"))
    removed = collections.Counter()
    removed_by_doc = collections.Counter()
    rank_cleaned = collections.Counter()
    out = []
    for r in recs:
        fn = r["pdf_url"].rsplit("/", 1)[-1]
        rk = (r.get("rank") or "").strip()
        if fn in NOT_PROTOCOL_DOCS:
            removed["справка о судейской коллегии (не протокол)"] += 1
            removed_by_doc[fn] += 1
            continue
        if rk in JUDGE_CATEGORIES:
            removed["судья (судейская категория вместо разряда)"] += 1
            removed_by_doc[fn] += 1
            continue
        if r.get("fio_hash") in judge_fio_by_doc.get(r["pdf_url"], ()):
            removed["то же ФИО, что у судьи этого документа"] += 1
            removed_by_doc[fn] += 1
            continue
        r = dict(r)
        if rk and rk not in SPORT_RANKS:
            new = RANK_ALIASES.get(rk)
            r["rank_raw"] = rk
            r["rank"] = new
            rank_cleaned[rk] += 1
        out.append(r)
    new_index = dict(index)
    new_index["records"] = out
    new_index["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_index["schema_version"] = str(index.get("schema_version", "1")) + "+w1clean"
    new_index["sources"] = [s for s in index.get("sources", []) if s.get("pdf_url", "").rsplit("/", 1)[-1] not in NOT_PROTOCOL_DOCS]
    by_url = collections.Counter(r["pdf_url"] for r in out)
    for s in new_index["sources"]:
        s["records_count"] = by_url.get(s.get("pdf_url"), 0)
    stats = dict(index.get("stats", {}))
    stats.update({
        "documents_count": len(new_index["sources"]),
        "total_records": len(out),
        "unique_athletes_count": len({r.get("fio_hash") for r in out}),
        "unique_teams_count": len({r.get("team") for r in out if r.get("team")}),
        "by_doc_id": {s["doc_id"]: s["records_count"] for s in new_index["sources"]},
    })
    new_index["stats"] = stats
    report = {
        "generated_at": new_index["generated_at"],
        "input_records": len(recs),
        "output_records": len(out),
        "removed_total": sum(removed.values()),
        "removed_by_reason": dict(removed),
        "removed_by_document": dict(removed_by_doc),
        "rank_values_cleaned": dict(rank_cleaned),
        "unique_athletes_before": len({r.get("fio_hash") for r in recs}),
        "unique_athletes_after": stats["unique_athletes_count"],
        "documents_after": stats["documents_count"],
        "note": "без персональных данных; исходный index.json не изменён",
    }
    return new_index, report


def main() -> None:
    base = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/spectrek_fsp/data_local/fsp_protocols")
    out_name = sys.argv[2] if len(sys.argv) > 2 else "index_w1.json"
    index = json.loads((base / "index.json").read_text(encoding="utf-8"))
    new_index, report = clean(index)
    target = base / out_name
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(new_index, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(target)
    rep = base / "clean_w1_report.json"
    rep.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(rep, 0o600)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
