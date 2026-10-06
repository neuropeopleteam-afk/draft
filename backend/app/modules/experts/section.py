"""Раздел «Экспертная разметка» страницы /validation: статус панели, метрики по разметке, проверка на синтетике.

Публичный: отдаёт только агрегаты и коды экспертов E1–E3, без имён, текстов оценок и служебных полей пакета.
Оценки демо-эксперта жюри (is_demo) в расчёт не входят.
"""
from __future__ import annotations

import threading

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.experts import analysis as A
from app.modules.experts import pack as P
from app.modules.experts import service, synth
from app.modules.experts.models import ExpertItem, ExpertLabel, ExpertPanelist

_cache: dict = {}
_mx = threading.Lock()
MIN_READY = {"A_needs": 10, "coders": 2}


def load(db: Session, pack: str = P.PACK, include_demo: bool = False) -> tuple[dict, list[dict]]:
    items = {i.key: {"kind": i.kind, "grp": i.grp, "payload": i.payload, "hidden": i.hidden, "id": i.id}
             for i in db.scalars(select(ExpertItem).where(ExpertItem.pack == pack).order_by(ExpertItem.position))}
    by_id = {v["id"]: k for k, v in items.items()}
    q = (select(ExpertLabel, ExpertPanelist.code).join(ExpertPanelist, ExpertPanelist.id == ExpertLabel.panelist_id)
         .where(ExpertPanelist.pack == pack))
    if not include_demo:
        q = q.where(ExpertPanelist.is_demo.is_(False))
    labels = [{"coder": code, "key": by_id[lb.item_id], "value": lb.value} for lb, code in db.execute(q).all()
              if lb.item_id in by_id]
    return items, labels


def _fingerprint(db: Session) -> tuple:
    n = db.scalar(select(func.count()).select_from(ExpertLabel)) or 0
    last = db.scalar(select(func.max(ExpertLabel.updated_at)))
    pans = db.scalar(select(func.count()).select_from(ExpertPanelist)) or 0
    items = db.scalar(select(func.count()).select_from(ExpertItem)) or 0
    return n, str(last), pans, items


def _pack_info(items: dict) -> dict:
    a = [it for it in items.values() if it["kind"] == "A"]
    return {"version": P.PACK, "A_pairs": len(a), "A_needs": len({it["grp"] for it in a}),
            "B_answers": sum(1 for it in items.values() if it["kind"] == "B"),
            "B_controls": sum(1 for it in items.values() if it["kind"] == "B" and it["hidden"].get("control")),
            "C_families": sum(1 for it in items.values() if it["kind"] == "C"),
            "llm_graded": sorted({m for it in items.values() if it["kind"] == "B" for m in (it["hidden"].get("llm") or {})}),
            "plan": {"A": "топ-5 платформы ∪ топ-5 BM25 ∪ 2 случайных кандидата из остальной базы на потребность; "
                          "ядро N00, N06, N08 — всем экспертам, остальные — двоим",
                     "B": "24 ответа на открытые задания банка (2 контрольных), одинаковые у всех",
                     "C": "ядро 10 семейств общего блока — всем, ещё 20 — по направлениям эксперта"}}


def _status(panel: list[dict], res: dict) -> dict:
    started = [p for p in panel if p["started"]]
    m = res.get("matching") or {}
    if not panel:
        return {"state": "waiting", "title": "Ожидает экспертов",
                "text": "Приглашения ещё не отправлены. Метрики подбора выше посчитаны по разметке по правилам; "
                        "после экспертной разметки здесь появятся те же метрики по оценкам людей, которые нанимают."}
    if not started:
        return {"state": "waiting", "title": "Ожидает экспертов",
                "text": f"Приглашено экспертов: {len(panel)}. Разметка ещё не начата."}
    ready = (m.get("needs_complete", 0) >= MIN_READY["A_needs"] and len(res.get("coders") or []) >= MIN_READY["coders"])
    return {"state": "ready" if ready else "partial",
            "title": "Разметка завершена" if ready else "Разметка идёт",
            "text": (f"Экспертов приступило: {len(started)} из {len(panel)}. Потребностей размечено полностью: "
                     f"{m.get('needs_complete', 0)} из {m.get('needs_total', len(P.A_NEEDS))}. "
                     + ("" if ready else "Цифры ниже предварительные — обновляются по мере разметки."))}


def synthetic(items: dict) -> dict | None:
    key = ("synth", len(items))
    with _mx:
        if key not in _cache:
            _cache[key] = synth.check(items) if items else None
        return _cache[key]


def section(db: Session) -> dict:
    """Готовый раздел для /api/validation/report. Пакет собирается при первом обращении (если есть демо-данные)."""
    try:
        P.ensure_pack(db)
    except Exception:  # noqa: BLE001 — раздел валидации не должен падать из-за сборки пакета
        db.rollback()
    fp = _fingerprint(db)
    with _mx:
        hit = _cache.get("real")
        if hit and hit[0] == fp:
            return hit[1]
    items, labels = load(db)
    panel = service.panel_status(db)
    res = A.analyze(items, labels) if labels else {"matching": None, "agreement": None, "llm": None, "angoff": None,
                                                    "labels": 0, "coders": []}
    llm_only = A.llm_agreement(items, [], None) if not labels else None
    out = {"pack": _pack_info(items) if items else None, "panel": panel, "status": _status(panel, res), **res,
           "llm_without_experts": llm_only, "synthetic_check": synthetic(items) if items else None,
           "current_cuts": {b: v for b, (_, v) in A.CURRENT_CUTS.items()}}
    with _mx:
        _cache["real"] = (fp, out)
    return out
