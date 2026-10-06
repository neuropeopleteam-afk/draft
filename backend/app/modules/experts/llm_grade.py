"""Оценки модели-оценщика на ответах пакета B (для согласия «модель — эксперты»).

Каждая модель оценивает все 24 ответа несколько раз (по умолчанию 3 прогона — разброс между прогонами).
Результат пишется в hidden["llm"][модель] объектов B. Без LLM (не настроен или выключен) — ничего не пишется,
на /validation остаётся статус «оценки модели не получены».
"""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.modules.assessment.grader import grade_open
from app.modules.experts.models import ExpertItem
from app.modules.experts.pack import PACK

DEFAULT_MODELS = ("yandexgpt/latest", "gpt-oss-120b/latest")


def grade_pack(db: Session, models: list[str] | None = None, runs: int = 3, pack: str = PACK,
               replace: bool = False) -> dict:
    if not get_settings().llm_configured:
        return {"ok": False, "error": "llm_not_configured", "message": "LLM не настроен или выключен (LLM_DISABLED)"}
    models = list(models or DEFAULT_MODELS)
    items = db.scalars(select(ExpertItem).where(ExpertItem.pack == pack, ExpertItem.kind == "B")
                       .order_by(ExpertItem.position)).all()
    stat = {m: {"scored": 0, "failed": 0} for m in models}
    t0 = time.time()
    for it in items:
        p = it.payload
        llm = dict((it.hidden or {}).get("llm") or {})
        for m in models:
            have = [] if replace else list(llm.get(m) or [])
            while len(have) < runs:
                g = grade_open(stem=p["stem"], code=p.get("code"), step_prompt=p.get("step_prompt"),
                               rubric=p.get("rubric"), answer=p["answer"], model=m)
                have.append({"status": g.status, "score": g.score, "criteria": g.criteria, "level": g.level,
                             "model": g.model, "latency_ms": g.latency_ms, "error": g.error, "at": time.time()})
                stat[m]["scored" if g.status == "scored" else "failed"] += 1
            llm[m] = have
        it.hidden = {**(it.hidden or {}), "llm": llm}
        flag_modified(it, "hidden")
        db.commit()
    return {"ok": True, "models": models, "runs": runs, "items": len(items), "stat": stat,
            "seconds": round(time.time() - t0, 1)}
