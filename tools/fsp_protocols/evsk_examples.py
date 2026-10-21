"""Обезличенные примеры норматива ЕВСК по реальным записям индекса (для README и проверки приёмки).

  FSP_EVSK_DATA_DIR=<evsk_data> python3 evsk_examples.py <index.json> <code_dir> <out.json>
Для каждого случая берётся первая по key_hash (HMAC — порядок не связан с ФИО) запись индекса с заданным
соревнованием и местом; в результат попадают только реквизиты соревнования, место и вывод ЕВСК —
без ФИО, даты рождения, команды, субъекта РФ и хэшей.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

CASES = [  # (соревнование, место, что показывает пример)
    ("kr2025_prod_final", 2, "финал Кубка России 2025, призёр"),
    ("chr2025_prod", 1, "Чемпионат России 2025, победитель: мало субъектов РФ (п. 30–31 Положения о ЕВСК)"),
    ("kr2026_algo_stage", 1, "этап Кубка России 2026, алгоритмическое, победитель"),
    ("kf2026_sib_final", 1, "финал Кубка ФСП 2026 (физкультурное мероприятие ЕКП), победитель"),
    ("fo2026_champ_pfo_prod", 1, "чемпионат ПФО 2026, победитель: условие п. 32.1 о субъектах округа"),
]


def main() -> None:
    idx_path, code, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    spec = importlib.util.spec_from_file_location("evsk", code / "evsk.py")
    evsk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evsk)  # type: ignore[union-attr]
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    recs = [r for r in idx["records"] if r.get("person")]
    examples = []
    for event_id, place, what in CASES:
        cand = sorted((r for r in recs if r.get("event_id") == event_id and r.get("place") == place and not r.get("place_uncertain")),
                      key=lambda r: r["key_hash"])
        if not cand:
            examples.append({"event_id": event_id, "place": place, "what": what, "found": False})
            continue
        r = cand[0]
        e = evsk.evsk_rank_for(r)
        b = e.get("basis") or {}
        examples.append({
            "what": what, "found": True, "event_id": event_id, "event_title": r.get("event_title"), "ekp_no": r.get("ekp_no"),
            "discipline": r.get("discipline"), "date": r.get("date"), "place": r.get("place"),
            "protocol": {"pdf_url": r.get("pdf_url"), "page": r.get("page")},
            "evsk": {"rank": e.get("rank"), "status": e.get("status"), "fulfilled": e.get("fulfilled"), "pending": e.get("pending"),
                     "basis": {k: b.get(k) for k in ("page", "row", "column", "places")} if b else None,
                     "conditions": [{k: c.get(k) for k in ("code", "ok", "value", "need")} for c in e.get("conditions") or []
                                    if c.get("code") != "age"],
                     "explain": e.get("explain")},
            "records_like_this": len(cand),
        })
    doc = {"what": "Пять реальных записей индекса протоколов ФСП с выводом ЕВСК, обезличенно (без ФИО, даты рождения, команды)",
           "index": idx_path.name, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "recompute": "FSP_EVSK_DATA_DIR=<evsk_data> python3 tools/fsp_protocols/evsk_examples.py <index.json> <код> <out.json>",
           "examples": examples}
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps([(x["event_id"], x["place"], x.get("evsk", {}).get("rank"), x.get("evsk", {}).get("status")) for x in examples],
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
