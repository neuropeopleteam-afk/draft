"""Маппинг claims ФСП ID → паспорт ФСП платформы (факты уровня T2).

Claims (client scope ``fsp_passport`` в realm fsp, см. docs/FSP_INTEGRATION.md):

| claim | тип | пример | куда |
|---|---|---|---|
| ``sub`` | строка | UUID Keycloak | ``users.fsp_subject``, ``fsp_passports.fsp_subject`` |
| ``fsp_id`` | строка | ``FSP-770012`` | ``candidate_profiles.fsp_id_claimed`` (теперь подтверждён) |
| ``fsp_rank`` | строка | ``КМС`` | ``fsp_passports.sport_rank`` (разряд по ЕВСК) |
| ``fsp_disciplines`` | массив строк | ``["product", "algorithmic"]`` | ``fsp_passports.raw.disciplines`` |
| ``fsp_achievements`` | массив объектов | ``{discipline, event, level, date, place, result, team, role}`` | ``fsp_achievements`` (verified) |

Нет claims ``fsp_*`` (участник без истории ФСП) — паспорт связан, достижений нет: нейтральное состояние,
бонуса в рейтинге нет, штрафа нет. Неизвестные дисциплины и уровни отбрасываются (значения сверяются со справочником).
"""
from __future__ import annotations

from datetime import date
import json

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.enums import FspEventLevel, FspLinkSource
from app.modules.catalog.constants import FSP_DISCIPLINES
from app.modules.fsp.models import FspAchievement, FspPassport
from app.modules.profiles.facts import refresh_rating
from app.modules.profiles.models import CandidateProfile

DISCIPLINES = {d["id"] for d in FSP_DISCIPLINES}
LEVELS = {lv.value for lv in FspEventLevel}
PASSPORT_CLAIMS = ("fsp_id", "fsp_rank", "fsp_disciplines", "fsp_achievements")


def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return [v]
    return v if isinstance(v, list) else [v]


def parse_achievements(raw) -> list[dict]:
    out = []
    for a in _as_list(raw):
        if isinstance(a, str):
            try:
                a = json.loads(a)
            except ValueError:
                continue
        if not isinstance(a, dict):
            continue
        disc, lvl = a.get("discipline"), a.get("level")
        if disc not in DISCIPLINES or lvl not in LEVELS or not a.get("event"):
            continue
        try:
            d = date.fromisoformat(a["date"]) if a.get("date") else None
        except ValueError:
            d = None
        place = a.get("place")
        out.append({"discipline": disc, "event": str(a["event"])[:255], "level": lvl, "date": d,
                    "place": int(place) if isinstance(place, int | str) and str(place).isdigit() else None,
                    "result": (str(a.get("result") or "")[:100] or None), "team": (str(a.get("team") or "")[:200] or None),
                    "role": (str(a.get("role") or "")[:100] or None)})
    return out


def passport_preview(claims: dict) -> dict:
    """Что придёт в паспорт — показывается пользователю до согласия (без ФИО и контактов)."""
    ach = parse_achievements(claims.get("fsp_achievements"))
    return {"fsp_id": claims.get("fsp_id"), "sport_rank": claims.get("fsp_rank"),
            "disciplines": [d for d in _as_list(claims.get("fsp_disciplines")) if d in DISCIPLINES],
            "achievements": [{**a, "date": a["date"].isoformat() if a["date"] else None} for a in ach],
            "has_history": bool(ach), "email": claims.get("email"), "username": claims.get("preferred_username")}


def apply_claims(db: Session, user_id, claims: dict) -> FspPassport:
    """Создаёт или обновляет паспорт по claims ФСП ID; достижения заменяются целиком (источник истины — ФСП ID)."""
    sub = claims["sub"]
    pp = db.scalar(select(FspPassport).where(FspPassport.user_id == user_id))
    other = db.scalar(select(FspPassport).where(FspPassport.fsp_subject == sub, FspPassport.user_id != user_id))
    if other is not None:
        other.fsp_subject = None
    if pp is None:
        pp = FspPassport(user_id=user_id, link_source=FspLinkSource.keycloak)
        db.add(pp)
    pp.fsp_subject = sub
    pp.link_source = FspLinkSource.keycloak
    pp.linked_at = pp.linked_at or utcnow()
    pp.synced_at = utcnow()
    pp.sport_rank = (claims.get("fsp_rank") or None)
    prev = passport_preview(claims)
    pp.raw = {"source": "fsp_id_oidc", "fsp_id": claims.get("fsp_id"), "disciplines": prev["disciplines"],
              "issuer": claims.get("iss"), "evidence_level": "T2", "has_history": prev["has_history"]}
    db.flush()
    db.execute(delete(FspAchievement).where(FspAchievement.passport_id == pp.id))
    for a in parse_achievements(claims.get("fsp_achievements")):
        db.add(FspAchievement(passport_id=pp.id, discipline=a["discipline"], event_name=a["event"],
                              event_level=FspEventLevel(a["level"]), event_date=a["date"], place=a["place"],
                              result_title=a["result"], team_name=a["team"], role_in_team=a["role"],
                              verified=True, source_ref=f"fsp-id:{sub}"))
    cp = db.get(CandidateProfile, user_id)
    if cp is not None and claims.get("fsp_id"):
        cp.fsp_id_claimed = str(claims["fsp_id"])[:64]
    db.flush()
    refresh_rating(db, user_id)
    return pp
