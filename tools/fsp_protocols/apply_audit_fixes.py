"""Исправления индекса по итогам разбора глазами (аудит v5) → новый файл индекса (выложенные версии не перезаписываются).

    python3 apply_audit_fixes.py <index_in.json> <fixes.json> <index_out.json>

fixes.json (с ПДн — только в /opt/spectrek_fsp/data_local/fsp_protocols/work/ocr_audit_v4/, 600):
    {"fixes": [
       {"file": "<pdf>", "page": N, "key_hash": "<hmac>", "set": {"fio_norm": "..."}, "why": "..."},
       {"file": "<pdf>", "page": N, "drop": true, "why": "раздел «Тренеры и специалисты» — не спортсмены"}
    ]}
Без key_hash правило относится ко всем записям страницы. ФИО меняется — fio_hash и key_hash пересчитываются (HMAC,
FSP_INDEX_HMAC_KEY обязателен). Сводка stats пересчитывается теми же правилами, что в build_index_v2.py.
Печатаются только счётчики (без ПДн).
"""
from __future__ import annotations

import collections
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normalize as norm  # noqa: E402

APP_UID = 10001
ORDER = {"МС": 0, "КМС": 1, "I": 2, "II": 3, "III": 4}


def _file(r: dict) -> str:
    return r["pdf_url"].rsplit("/", 1)[-1]


def recompute_stats(stats: dict, recs: list[dict]) -> dict:
    persons = [r for r in recs if r.get("person")]
    best: dict[str, dict] = {}
    for r in persons:
        if r.get("evsk_status") == "fulfilled" and r.get("evsk_rank"):
            k = r["fio_hash"]
            if k not in best or ORDER.get(r["evsk_rank"], 9) < ORDER.get(best[k]["evsk_rank"], 9):
                best[k] = r
    ranks = collections.Counter(r.get("evsk_rank") for r in persons if r.get("evsk_status") in ("fulfilled", "needs_second_result"))
    out = dict(stats)
    out.update({
        "events_count": len({r["event_id"] for r in recs}),
        "total_records": len(recs),
        "person_records": len(persons),
        "team_only_records": len(recs) - len(persons),
        "unique_athletes_count": len({r["fio_hash"] for r in persons}),
        "by_event": dict(collections.Counter(r["event_id"] for r in recs)),
        "evsk_status_counts": dict(collections.Counter(r.get("evsk_status") for r in persons)),
        "evsk_rank_counts_fulfilled_or_second": {k: v for k, v in ranks.items() if k},
        "athletes_with_fulfilled_norm": len(best),
        "place_status_counts_persons": dict(collections.Counter(r.get("place_status") for r in persons)),
        "place_unverified_persons": sum(1 for r in persons if r.get("place_uncertain")),
        "athletes_with_fulfilled_norm_by_rank": dict(collections.Counter(r["evsk_rank"] for r in best.values())),
    })
    return out


def apply(idx: dict, fixes: list[dict]) -> tuple[dict, dict]:
    recs = idx["records"]
    used = collections.Counter()
    keep = []
    for r in recs:
        drop = False
        for i, f in enumerate(fixes):
            if _file(r) != f["file"] or r.get("page") != f["page"]:
                continue
            if f.get("key_hash") and r.get("key_hash") != f["key_hash"]:
                continue
            used[i] += 1
            if f.get("drop"):
                drop = True
                continue
            for k, v in f.get("set", {}).items():
                r.setdefault("audit_fix", {})[k] = r.get(k)  # прежнее значение — для истории (вне git)
                r[k] = v
            if "fio_norm" in f.get("set", {}):
                by = str(r.get("birth_date") or "")[:4]
                r["fio_hash"] = norm.compute_fio_hash(r["fio_norm"])
                r["key_hash"] = norm.compute_key_hash(r["fio_norm"], by if by.isdigit() else None)
        if not drop:
            keep.append(r)
    unused = [i for i in range(len(fixes)) if not used[i]]
    if unused:
        raise SystemExit(f"правила без совпадений: {unused} — индекс не записан")
    out = dict(idx)
    out["records"] = keep
    out["stats"] = recompute_stats(idx["stats"], keep)
    out["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out["audit_fixes"] = [{"file": f["file"], "page": f["page"], "records": used[i], "kind": "drop" if f.get("drop") else
                           "set:" + ",".join(sorted(f.get("set", {}))), "why": f.get("why")} for i, f in enumerate(fixes)]
    for s in out.get("sources", []):
        s["records_count"] = sum(1 for r in keep if _file(r) == s["filename"])
    summary = {"records_in": len(recs), "records_out": len(keep), "rules": len(fixes),
               "matched": {str(i): used[i] for i in range(len(fixes))},
               "persons": out["stats"]["person_records"], "unique_athletes": out["stats"]["unique_athletes_count"]}
    return out, summary


if __name__ == "__main__":
    norm.require_key()
    src, fx, dst = map(Path, sys.argv[1:4])
    if dst.exists():
        sys.exit(f"{dst} уже существует: выложенные версии индекса не перезаписываются")
    idx = json.loads(src.read_text(encoding="utf-8"))
    out, summary = apply(idx, json.loads(fx.read_text(encoding="utf-8"))["fixes"])
    out["based_on"] = src.name
    tmp = dst.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    try:
        os.chown(tmp, APP_UID, APP_UID)
    except PermissionError:
        pass
    tmp.replace(dst)
    print(json.dumps(summary, ensure_ascii=False))
