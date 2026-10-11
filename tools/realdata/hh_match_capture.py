"""Снимок подборки на корпусе hh.ru для разбора порядка выдачи без повторного прогона БД.

Для каждой вакансии корпуса: разбор правилами (parse_need, без LLM) → build_selection на демо-пуле (модельные
кандидаты, модель, не люди) → сохраняем всё, что нужно для пересортировки: балл и компоненты, ярус статуса грейда,
ярус обязательного, ядро роли, навыки T1 (доля верных) и заявленные T0. Тексты вакансий в файл не попадают (только id,
наши метки и разбор тегами). Файл — вне репозитория (по умолчанию /tmp/hh_match_capture.pkl).

  cd backend && DATABASE_URL=sqlite:///<демо-БД> LLM_DISABLED=true python ../tools/realdata/hh_match_capture.py
"""
from __future__ import annotations

import os
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools/realdata"))

from hh_plus import _load_corpus, text_of  # noqa: E402

OUT = Path(os.environ.get("HH_CAPTURE", "/tmp/hh_match_capture.pkl"))
WIDE = os.environ.get("HH_CAPTURE_WIDE") == "1"  # пул — все грейды направления потребности (для оценки «соседних»)


def main() -> None:
    from app.core.db import SessionLocal, get_engine
    from app.modules.matching import need_parser, ranking

    corpus, items, raws = _load_corpus()
    get_engine()
    box: dict = {}
    orig = ranking.selection_order

    def spy(scored, must, core, policy=None):
        box["x"] = (scored, must, core)
        return orig(scored, must, core, policy)

    ranking.selection_order = spy
    rows = []
    t0 = time.time()
    with SessionLocal() as db:
        for i, it in enumerate(items, 1):
            v = raws.get(it["id"])
            if v is None:
                continue
            r = need_parser.parse_need(text_of(v), use_llm=False)
            box.clear()
            flt = {}
            if WIDE and r.get("direction"):
                from app.modules.catalog.seed_data import GRADES
                flt = {"categories": [f"{r['direction']}.{g}" for g in GRADES]}
            sel = ranking.build_selection(db, r, flt, limit=10)
            scored, must, core = box.get("x", ([], {}, {}))
            cands = []
            for s, b, comps, _reasons in scored:
                uid = b.profile.user_id
                cands.append({
                    "ref": b.profile.public_ref, "score": s, "comps": dict(comps), "tier": ranking.tier(b),
                    "must": dict(must.get(uid) or {}), "core_key": (core.get(uid) or {}).get("key", 0),
                    "core_state": (core.get(uid) or {}).get("state"),
                    "rating": b.rating or 0.0, "category_id": b.category_id,
                    "grade_status": b.grade_status, "grade": b.grade,
                    "t1": {t: float(f.value.get("score", 0)) for t, f in b.skills_t1.items()},
                    "t0": sorted(b.stack_t0),
                })
            rows.append({"id": it["id"], "labels": it["labels"],
                         "req": {"direction": r.get("direction"), "grade": r.get("grade"),
                                 "stack_required": [{"tag": x["tag"], "weight": x["weight"]}
                                                    for x in r.get("stack_required") or []],
                                 "stack_desired": [{"tag": x["tag"], "weight": x["weight"]}
                                                   for x in r.get("stack_desired") or []]},
                         "product_top": [x["ref"] for x in sel["results"][:10]], "cands": cands})
            if i % 25 == 0:
                print(f"… {i}/{len(items)} {time.time() - t0:.0f} с", flush=True)
    OUT.write_bytes(pickle.dumps({"collected_at": corpus["collected_at"], "rows": rows}))
    print(OUT, len(rows), f"{time.time() - t0:.0f} с")


if __name__ == "__main__":
    main()
