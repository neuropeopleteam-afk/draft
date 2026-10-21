"""Обезличенные файлы для репозитория из индекса протоколов (запуск на сервере, stdlib).

  python3 export_public.py <index.json> <out_dir> <каталог с protocol_stats.py>
Пишет: aggregates.json (агрегаты, группы < 3 человек скрыты), index_stats.json (контракт для NUMBERS.json).
Дополнительно проверяет, что ни одно ФИО, хэш ФИО или дата рождения из индекса не попали в файлы.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

index_path, out_dir, code = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
spec = importlib.util.spec_from_file_location("protocol_stats", code / "protocol_stats.py")
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)  # type: ignore[union-attr]

idx = json.loads(index_path.read_text(encoding="utf-8"))
recs = idx["records"]
agg = ps.aggregates(3, records=recs)
agg["source"] = {"index": index_path.name, "schema_version": idx.get("schema_version"), "generated_at": idx.get("generated_at"),
                 "recompute": "python3 tools/fsp_protocols/export_public.py /opt/spectrek_fsp/data_local/fsp_protocols/" + index_path.name
                              + " docs/realdata/fsp_protocols backend/app/modules/fsp"}
years = sorted({(r.get("date") or "")[:4] for r in recs if r.get("date")})
st = idx.get("stats", {})
persons = [r for r in recs if r.get("person")]
stats = {
    "documents": st.get("documents_count"),
    "events": st.get("events_count"),
    "results": len(recs),
    "person_results": len(persons),
    "athletes": len({r.get("fio_hash") for r in persons}),
    "regions": agg["totals"]["regions"],
    "years": f"{years[0]}–{years[-1]}" if years else None,
    "athletes_with_evsk_norm": agg["totals"]["athletes_with_evsk_norm"],
    "athletes_with_evsk_norm_by_rank": agg["totals"]["athletes_with_evsk_norm_by_rank"],
    "what": "Официальные протоколы ФСП России 2025–2026 (fsp-russia.ru/about/documents): результаты, привязанные к соревнованиям; "
            "судьи, тренеры и строки справок исключены; норматив ЕВСК — по месту, числу субъектов РФ и составу судейской коллегии.",
    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "index": index_path.name,
    "recompute": agg["source"]["recompute"],
    "code_ref": "tools/fsp_protocols/build_index_v2.py, backend/app/modules/fsp/evsk.py, backend/app/modules/fsp/protocol_stats.py",
}
out_dir.mkdir(parents=True, exist_ok=True)
a_txt = json.dumps(agg, ensure_ascii=False, indent=1)
s_txt = json.dumps(stats, ensure_ascii=False, indent=1)
# проверка на утечку ПДн
needles = set()
for r in recs:
    for k in ("fio_norm", "fio_hash", "key_hash"):
        if r.get(k):
            needles.add(str(r[k]).lower())
    if r.get("birth_date") and len(str(r["birth_date"])) >= 8:
        needles.add(str(r["birth_date"]))
low = (a_txt + s_txt).lower()
leaks = [n for n in needles if len(n) >= 8 and n in low]
if leaks:
    sys.exit(f"ПДн в агрегатах: {len(leaks)} совпадений — файлы не записаны")
(out_dir / "aggregates.json").write_text(a_txt + "\n", encoding="utf-8")
(out_dir / "index_stats.json").write_text(s_txt + "\n", encoding="utf-8")
print(json.dumps({"ok": True, "checked_needles": len(needles), **{k: stats[k] for k in ("documents", "events", "results", "athletes", "regions", "years", "athletes_with_evsk_norm")}}, ensure_ascii=False))
