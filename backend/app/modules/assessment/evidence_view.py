"""Я13: «Доказательства: цитаты из ответа» — по пунктам рубрики для кандидата и работодателя, блок для /validation.

Что показывается: по каждому развёрнутому ответу, оценённому моделью, — пункты рубрики («Пункт N», вес, балл) и
фрагменты ответа кандидата, которые код сверил с текстом ответа (evidence.verify_quote); число отброшенных фрагментов
и пометка «без подтверждённой цитаты — на шаг ниже»; что изменила проверка скептиком. Тексты пунктов рубрики и
эталонные ответы не показываются (банк заданий закрыт), условие задания — тоже: только номер задания и навыки.
Подпись — «оценка модели», с названием модели. Кандидат может скрыть цитаты от работодателей (privacy.show_evidence).
Данные есть, только если ответ оценивался при включённом GRADING_EVIDENCE; иначе — пустой список и пояснение.
"""
from __future__ import annotations

import json
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.modules.assessment.attempts import Direction
from app.modules.assessment.evidence import SKEPTIC_LABEL, WHY_TITLES
from app.modules.auth.models import User

NOTE = ("Оценка модели. Каждая цитата — дословный фрагмент вашего ответа: программа сверила её с текстом ответа. "
        "Пункт без подтверждённой цитаты не получает полный балл. Итог проверяет эксперт, если модели разошлись.")
NOTE_EMPLOYER = ("Оценка модели. Цитаты — дословные фрагменты ответа кандидата, сверенные программой с текстом "
                 "ответа; пункт без подтверждённой цитаты не получает полный балл. Тексты заданий и рубрик закрыты.")
METHOD_TITLES = {"llm": "оценка модели", "llm2": "оценка модели, проверено скептиком", "expert": "оценка эксперта"}
VERDICT_TITLES = {"agree": "скептик согласился", "kept": "скептик не ответил — осталась первая оценка",
                  "disagree": "скептик не согласился — решает эксперт", "manipulation": "попытка повлиять на оценку — "
                  "решает эксперт", "failed": "проверка скептиком не выполнена — решает эксперт"}


def _raised(second: dict | None) -> dict[str, dict]:
    """Пункты, которые скептик повысил с цитатой, подтверждённой кодом (принятые изменения «вверх»)."""
    if not second or second.get("kind") != "skeptic" or second.get("verdict") != "agree":
        return {}
    return {ch["criterion"]: ch for ch in second.get("changes") or []
            if ch.get("accepted") and ch.get("direction") == "up" and ch.get("quote")}


def _criteria(rubric: dict | None, ev: dict, final: dict | None, raised: dict[str, dict] | None = None) -> list[dict]:
    """score — итог пункта (после скептика); cap_score — балл после правила «без цитаты — на шаг ниже» (до скептика).
    Пункт, который скептик повысил с подтверждённой цитатой, показывает эту цитату (how = skeptic) и не помечается
    «без подтверждённой цитаты»."""
    out = []
    crit = (rubric or {}).get("criteria") or []
    for n, c in enumerate(crit, 1):
        e = (ev.get("criteria") or {}).get(c["id"]) or {}
        quotes = [{"text": q["text"][:400], "how": q.get("how")} for q in (e.get("quotes") or [])][:3]
        up = (raised or {}).get(c["id"])
        if up:
            quotes = [*quotes[:2], {"text": str(up["quote"])[:400], "how": "skeptic"}]
        out.append({
            "n": n, "title": f"Пункт {n}", "weight": round(float(c.get("weight") or 0), 3),
            "score": (final or {}).get(c["id"], e.get("score")), "model_score": e.get("model_score"),
            "cap_score": e.get("score"),
            "quotes": quotes,
            "dropped": len(e.get("dropped") or []),
            "dropped_why": sorted({WHY_TITLES.get(d.get("why"), d.get("why")) for d in e.get("dropped") or []}),
            "capped": bool(e.get("capped")) and not up,
        })
    return out


def _skeptic(second: dict | None) -> dict | None:
    if not second or second.get("kind") != "skeptic":
        return None
    if second.get("status") == "pending":
        return {"status": "pending", "title": "проверка скептиком идёт"}
    v = second.get("verdict")
    return {"status": "done", "verdict": v, "title": VERDICT_TITLES.get(v, v), "label": SKEPTIC_LABEL,
            "model_label": second.get("model_label"),
            "changes": [{"n": None, "criterion": ch.get("criterion"), "from": ch.get("from"), "to": ch.get("to"),
                         "accepted": bool(ch.get("accepted")), "direction": ch.get("direction")}
                        for ch in second.get("changes") or []]}


def items_view(state: dict) -> list[dict]:
    """Развёрнутые ответы с доказательствами из состояния сессии (без условий, рубрик и эталонов)."""
    out = []
    for it in state.get("items") or []:
        for part, g in enumerate(it.get("grading") or []):
            if not isinstance(g, dict) or not g.get("evidence"):
                continue
            criteria = _criteria(it.get("rubric"), g["evidence"], g.get("criteria"), _raised(g.get("second")))
            ids = [c["id"] for c in (it.get("rubric") or {}).get("criteria") or []]
            sk = _skeptic(g.get("second"))
            if sk:
                for ch in sk.get("changes") or []:
                    ch["n"] = ids.index(ch["criterion"]) + 1 if ch["criterion"] in ids else None
                    ch.pop("criterion", None)
            method = g.get("method") or "llm"
            out.append({
                "position": it.get("position"), "part": part + 1, "parts": it.get("parts") or 1,
                "skills": list(it.get("skills") or [])[:3],
                "status": g.get("status"), "score": it.get("x", [None])[part] if part < len(it.get("x") or []) else None,
                "method": method, "method_title": METHOD_TITLES.get(method, "оценка модели"),
                "model_label": g.get("model_label"), "criteria": criteria, "skeptic": sk,
                "disputed": bool(g.get("disputed")),
                "quotes_total": sum(len(c["quotes"]) for c in criteria),
                "dropped_total": sum(c["dropped"] for c in criteria),
            })
    return out


def for_session(state: dict, audience: str = "candidate") -> dict:
    items = items_view(state)
    return {"enabled": bool(get_settings().grading_evidence), "label": "оценка модели",
            "title": "Доказательства: цитаты из ответа",
            "note": NOTE if audience == "candidate" else NOTE_EMPLOYER, "items": items,
            "empty_text": (None if items else "В этом тесте нет развёрнутых ответов, оценённых с цитатами")}


# ------------------------------------------------------------------ API
candidate_router = APIRouter(prefix="/api/assessment", tags=["assessment"])
employer_router = APIRouter(prefix="/api/employer", tags=["employer"])
validation_router = APIRouter(prefix="/api/validation", tags=["validation"])
_candidate = require_role(UserRole.candidate)
_employer = require_role(UserRole.employer)


@candidate_router.get("/sessions/{session_id}/evidence",
                      summary="Доказательства оценки развёрнутых ответов: цитаты из ответа по пунктам рубрики",
                      responses={401: err("Не выполнен вход"), 404: err("Сессия не найдена"),
                                 409: err("Тест ещё не завершён")})
def candidate_evidence(session_id: uuid.UUID, user: User = Depends(_candidate), db: Session = Depends(get_db)) -> dict:
    from app.core.enums import TestSessionStatus
    from app.modules.assessment import service

    ts = service.get_own_session(db, user.id, session_id)
    if ts.status != TestSessionStatus.finished:
        raise api_error(409, "test_not_finished", "Тест ещё не завершён")
    return for_session((ts.result or {}).get("state") or {}, "candidate")


@employer_router.get("/candidates/{ref}/evidence",
                     summary="Доказательства оценки развёрнутых ответов последнего теста кандидата (если не скрыл)",
                     responses={401: err("Не выполнен вход"), 403: err("Только для работодателя"),
                                404: err("Кандидат не найден или скрыл профиль"),
                                409: err("company_required — сначала заполните профиль компании")})
def employer_evidence(ref: str, direction: Direction | None = None, user: User = Depends(_employer),
                      db: Session = Depends(get_db)) -> dict:
    from app.modules.assessment.attempts import _direction, finished_attempts
    from app.modules.invitations.service import profile_by_ref
    from app.modules.matching.router import my_company
    from app.modules.profiles.facts import DEFAULT_PRIVACY

    my_company(db, user)
    p = profile_by_ref(db, ref)
    privacy = {**DEFAULT_PRIVACY, **(p.privacy or {})}
    if not privacy.get("show_evidence", True):
        return {"available": False, "reason": "hidden_by_candidate", "items": [],
                "text": "Кандидат скрыл цитаты из ответов теста"}
    d = _direction(db, p.user_id, direction)
    rows = finished_attempts(db, p.user_id, d) if d else []
    if not rows:
        return {"available": False, "reason": "no_test", "items": [], "text": "Кандидат ещё не прошёл тест"}
    out = for_session((rows[-1].result or {}).get("state") or {}, "employer")
    return {"available": True, "direction": d, **out}


BENCH = Path(__file__).resolve().parents[1] / "validation" / "data" / "evidence_bench.json"


@validation_router.get("/evidence", summary="Доказательная оценка: флаг выкл/вкл на одних ответах набора оценщика")
def validation_evidence() -> dict:
    d = json.loads(BENCH.read_text(encoding="utf-8")) if BENCH.exists() else {"missing": True}
    return {**d, "enabled": bool(get_settings().grading_evidence)}
