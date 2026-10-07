"""Предложение API ФСП v1 и синтетический реестр. Ни одного реального участника."""
from datetime import date
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter
import httpx
from pydantic import BaseModel, Field

from app.core.errors import api_error, err
from app.integrations.settings import get_isettings

router = APIRouter(prefix="/api/fsp-registry/v1", tags=["fsp-registry"])


class RegistryTeam(BaseModel):
    id: str
    name: str
    place: int | None = Field(None, ge=1)
    members_count: int | None = Field(None, ge=1)
    role: str | None = None


class RegistryAchievement(BaseModel):
    id: str = Field(max_length=100)
    event_id: str = Field(max_length=100)
    event_name: str = Field(max_length=255)
    event_type: str = Field(description="Тип мероприятия — справочная информация, не вес рейтинга")
    event_level: Literal["school", "regional", "interregional", "national", "international"]
    date: date
    discipline: Literal["algorithmic", "product", "security", "robotics", "uav"]
    evsk_code: str | None = Field(None, max_length=64, description="Код из актуального справочника ЕВСК")
    place: int | None = Field(None, ge=1)
    result: Literal["winner", "prize", "finalist", "participant"]
    sport_rank: str | None = Field(None, max_length=64)
    team: RegistryTeam | None = None
    verified: bool = True


class RegistryPassport(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    fsp_id: str = Field(max_length=64)
    sport_rank: str | None = Field(None, max_length=64)
    updated_at: date
    demo: bool = True
    achievements: list[RegistryAchievement] = Field(default_factory=list, max_length=1000)


def mock_passport(fsp_id: str) -> RegistryPassport:
    if fsp_id not in ("FSP-770012", "FSP-770013", "FSP-770014"):
        raise api_error(404, "registry_participant_not_found", "В синтетическом реестре нет такого ФСП ID")
    champion = fsp_id == "FSP-770012"
    achievements = []
    if fsp_id != "FSP-770014":
        achievements = [RegistryAchievement(
            id="demo-a1" if champion else "demo-a2", event_id="demo-fsp-2026-product" if champion else "demo-ctf-2026",
            event_name="Демо: командный чемпионат по продуктовому программированию" if champion else "Демо: открытый CTF",
            event_type="championship" if champion else "online_selection",
            event_level="national" if champion else "regional", date=date(2026, 5, 16),
            discipline="product" if champion else "security", evsk_code=None,
            place=1 if champion else 3, result="winner" if champion else "prize",
            sport_rank="КМС" if champion else "II разряд",
            team=RegistryTeam(id="demo-team-7", name="Демо: Команда 7", place=1, members_count=3, role="разработчик")
            if champion else None)]
    return RegistryPassport(fsp_id=fsp_id, sport_rank="КМС" if champion else "II разряд" if achievements else None,
                            updated_at=date(2026, 10, 7), achievements=achievements)


@router.get("/participants/{fsp_id}/achievements", response_model=RegistryPassport,
            summary="Синтетический реестр ФСП: места, разряды, ЕВСК, команды, даты",
            responses={404: err("Синтетический участник не найден")})
def mock_endpoint(fsp_id: str) -> RegistryPassport:
    return mock_passport(fsp_id)


def fetch_passport(fsp_id: str) -> RegistryPassport:
    s = get_isettings()
    if s.fsp_registry_mode == "mock" and not s.fsp_registry_base_url:
        return mock_passport(fsp_id)
    if s.fsp_registry_mode not in ("mock", "external") or not s.fsp_registry_base_url:
        raise ValueError("Не настроен FSP_REGISTRY_BASE_URL")
    # Реестр — отдельный сервис; адрес и сервисный токен задаются оператором, не пользователем.
    headers = {"Authorization": f"Bearer {s.fsp_registry_token}"} if s.fsp_registry_token else {}
    r = httpx.get(s.fsp_registry_base_url.rstrip("/") + "/participants/" + quote(fsp_id, safe="") + "/achievements",
                  headers=headers, timeout=s.fsp_registry_timeout_s)
    r.raise_for_status()
    passport = RegistryPassport.model_validate(r.json())
    if passport.fsp_id != fsp_id:
        raise ValueError("ФСП ID в ответе реестра не совпадает")
    return passport


def registry_claims(passport: RegistryPassport) -> dict:
    ru = {"winner": "победитель", "prize": "призёр", "finalist": "финалист", "participant": "участник"}
    return {"fsp_id": passport.fsp_id, "fsp_rank": passport.sport_rank,
            "fsp_disciplines": sorted({a.discipline for a in passport.achievements}),
            "fsp_achievements": [
                {"id": a.id, "event_id": a.event_id, "discipline": a.discipline, "event": a.event_name,
                 "level": a.event_level, "event_type": a.event_type, "date": a.date.isoformat(), "place": a.place,
                 "result": ru[a.result], "result_kind": a.result, "evsk_code": a.evsk_code,
                 "sport_rank": a.sport_rank, "verified": a.verified,
                 "team": a.team.name if a.team else None, "role": a.team.role if a.team else None,
                 "team_result": a.team.model_dump() if a.team else None} for a in passport.achievements]}
