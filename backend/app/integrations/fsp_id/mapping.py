"""Маппинг claims ФСП ID → паспорт ФСП платформы (факты уровня T2).

Claims (мапперы атрибутов клиента spectrek-platform в realm fsp, см. docs/FSP_INTEGRATION.md):

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
from app.integrations.settings import get_isettings

DISCIPLINES = {d["id"] for d in FSP_DISCIPLINES}
LEVELS = {lv.value for lv in FspEventLevel}
PASSPORT_CLAIMS = ("fsp_id", "fsp_rank", "fsp_disciplines", "fsp_achievements")


def normalize_claims(claims: dict) -> dict:
    """Настраиваемые dotted paths. Стандартные OIDC-поля безопасности не переименовываются."""
    out = dict(claims)
    allowed = {*PASSPORT_CLAIMS, "email", "email_verified", "preferred_username"}
    for target, path in get_isettings().fsp_oidc_claims_map.items():
        if target not in allowed:
            raise ValueError(f"Недопустимое поле в FSP_OIDC_CLAIMS_MAP: {target}")
        value = claims
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        out[target] = value
    return out


def identity_subject(claims: dict) -> str:
    """Одинаковые sub двух issuer — разные люди (смена стенда безопасна)."""
    import hashlib

    return "oidc:" + hashlib.sha256(f"{claims['iss']}|{claims['sub']}".encode()).hexdigest()


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
                    "role": (str(a.get("role") or "")[:100] or None),
                    "event_id": str(a.get("event_id") or "")[:100] or None,
                    "result_kind": a.get("result_kind") if a.get("result_kind") in
                    ("winner", "prize", "finalist", "participant") else None,
                    "evsk_code": str(a.get("evsk_code") or "")[:64] or None,
                    "sport_rank": str(a.get("sport_rank") or "")[:64] or None,
                    "team_result": a.get("team_result") if isinstance(a.get("team_result"), dict) else None,
                    "verified": a.get("verified") is not False,
                    "source_id": str(a.get("id") or "")[:100] or None})
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
    sub = identity_subject(claims)
    pp = db.scalar(select(FspPassport).where(FspPassport.user_id == user_id))
    if pp is not None and claims.get("_registry_warning"):
        pp.raw = {**(pp.raw or {}), "registry_warning": claims["_registry_warning"]}
        return pp  # сбой реестра не стирает ранее подтверждённые результаты
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
    pp.sport_rank = str(claims.get("fsp_rank") or "")[:64] or None
    prev = passport_preview(claims)
    pp.raw = {"source": "fsp_id_oidc", "fsp_id": claims.get("fsp_id"), "disciplines": prev["disciplines"],
              "issuer": claims.get("iss"), "oidc_sub": claims["sub"], "evidence_level": "T2",
              "has_history": prev["has_history"], "registry": claims.get("_registry"),
              "registry_warning": claims.get("_registry_warning")}
    db.flush()
    # Факты T1 кубков работодателей — другой источник; синхронизация ФСП их не удаляет.
    db.execute(delete(FspAchievement).where(FspAchievement.passport_id == pp.id,
                                           ~FspAchievement.source_ref.like("cup:%") |
                                           FspAchievement.source_ref.is_(None)))
    for a in parse_achievements(claims.get("fsp_achievements")):
        db.add(FspAchievement(passport_id=pp.id, discipline=a["discipline"], event_name=a["event"],
                              event_level=FspEventLevel(a["level"]), event_date=a["date"], place=a["place"],
                              result_title=a["result"], team_name=a["team"], role_in_team=a["role"],
                              verified=a["verified"], source_ref=f"registry:{a['source_id']}" if a["source_id"]
                              else f"fsp-id:{sub}", event_id=a["event_id"], result_kind=a["result_kind"],
                              evsk_code=a["evsk_code"], sport_rank=a["sport_rank"], team_result=a["team_result"]))
    cp = db.get(CandidateProfile, user_id)
    if cp is not None and claims.get("fsp_id"):
        cp.fsp_id_claimed = str(claims["fsp_id"])[:64]
    db.flush()
    refresh_rating(db, user_id)
    return pp
