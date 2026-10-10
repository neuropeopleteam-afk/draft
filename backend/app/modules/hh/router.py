"""API hh.ru: импорт своей вакансии (черновик), «Рынок по hh.ru» у вилки, замер разбора на корпусе hh.ru.

Без HH_ENABLED или без токена приложения — 404 ``hh_disabled`` (интерфейс кнопку и блок не показывает: /api/meta → hh).
Модели ответов описаны явно (OpenAPI, как у остальных методов с response_model).
"""
from __future__ import annotations

import json
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.modules.auth.models import User
from app.modules.hh import importer, market as hh_market
from app.modules.hh.client import HhError
from app.modules.matching.router import my_company

router = APIRouter(prefix="/api/employer", tags=["hh"])
validation_router = APIRouter(prefix="/api/validation", tags=["validation"])
employer = require_role(UserRole.employer)
TAGS = [{"name": "hh", "description": "hh.ru: импорт своей вакансии работодателя (только чтение GET /vacancies/{id}) и "
                                      "«Рынок по hh.ru» — медиана и p25–p75 вилок живых вакансий. Без HH_ENABLED и "
                                      "токена приложения — 404 hh_disabled."}]
DATA = Path(__file__).resolve().parents[1] / "validation" / "data" / "hh_parse.json"
E = {401: err("Не выполнен вход"), 403: err("Только для работодателя"), 404: err("Интеграция с hh.ru выключена "
                                                                                  "(hh_disabled) или вакансия не найдена"),
     409: err("Нет профиля компании"), 422: err("Неверная ссылка или номер вакансии"),
     429: err("hh.ru ограничил частоту запросов"), 502: err("hh.ru ответил ошибкой или недоступен"),
     503: err("Очередь запросов к hh.ru занята"), 504: err("hh.ru не ответил вовремя")}


def meta() -> dict:
    """Для /api/meta: показывать ли кнопку импорта, «Рынок по hh.ru» и блок замера на /validation."""
    s = get_settings()
    return {"enabled": s.hh_available, "stub": bool(s.hh_available and s.hh_stub)}


def _need_on():
    if not get_settings().hh_available:
        raise api_error(404, "hh_disabled", "Интеграция с hh.ru не включена на этом сервере")


def _raise(e: HhError):
    return api_error(e.status, e.code, e.message)


# ------------------------------------------------------------------ модели ответов
class HhPreviewOut(BaseModel):
    hh_id: str = Field(description="Номер вакансии на hh.ru")
    url: str
    title: str
    employer_name: str | None = Field(description="Работодатель вакансии в hh.ru")
    own_company: bool | None = Field(description="Совпадает ли работодатель hh.ru с компанией на платформе")
    confirm_required: bool = Field(description="Импорт требует подтверждения «это вакансия нашей компании»")
    archived: bool
    experience: str | None
    conditions: str = Field(description="«Условия с hh.ru — опыт · график · формат · занятость» (строка в описании)")
    salary_hh: str = Field(description="Зарплата в hh.ru как есть: от/до, валюта, до вычета НДФЛ или на руки")
    key_skills: list[str]
    category_id: str | None
    stack: list[str]
    stack_from_key_skills: list[str] = Field(description="Навыки, добавленные из key_skills (в тексте их нет)")
    stack_titles: list[str]
    salary_from: int
    salary_to: int
    salary_basis: str = Field(description="gross — до вычета НДФЛ, net — на руки")
    salary_from_hh: bool = Field(description="Вилка взята из hh.ru целиком")
    salary_source: str = Field("market", description="hh — вилка из hh.ru; hh_partial — только «от»/«до» или шире 1,5, "
                                                    "вторая граница достроена; market — рыночный диапазон категории")
    work_format: str
    city: str | None
    description_preview: str
    parse_method: str = Field(description="Разбор потребности: rules (без LLM)")
    notes: list[str]
    state: str = Field(description="new | same | changed | edited")
    state_title: str
    vacancy_id: str | None
    fetched_at: str | None
    stub: bool = Field(description="Заглушка hh.ru (демо-данные), не настоящий API")


class HhImportIn(BaseModel):
    ref: str = Field(min_length=1, max_length=300, description="Ссылка на вакансию hh.ru или её номер")
    confirm_own: bool = Field(False, description="Подтверждаю, что это вакансия нашей компании")


class HhImportOut(HhPreviewOut):
    result: str = Field(description="created | updated | skipped")
    text: str
    imported_at: str | None = None


class HhArea(BaseModel):
    id: str
    name: str


class HhTried(BaseModel):
    area: str
    by: str
    n: int
    found: int


class HhMarketOut(BaseModel):
    available: bool
    reason: str | None = None
    category_id: str | None = None
    category_title: str | None = None
    area: HhArea | None = None
    area_requested: HhArea | None = None
    area_fallback: bool | None = None
    remote: bool | None = None
    grade_by: str | None = Field(None, description="name — слово грейда в названии; experience — опыт hh.ru ≈ грейд")
    grade_by_title: str | None = None
    n: int | None = Field(None, description="Вакансий с зарплатой в рублях за месяц в расчёте")
    found: int | None = Field(None, description="Найдено hh.ru по запросу (в расчёте — первые до 100 свежих)")
    sample: int | None = None
    excluded: dict[str, int] | None = None
    gross_share: float | None = Field(None, description="Доля сумм «до вычета НДФЛ» до приведения к «на руки»")
    basis: str | None = Field(None, description="net — все суммы на руки")
    median: int | None = None
    p25: int | None = None
    p75: int | None = None
    median_gross: int | None = Field(None, description="≈ медиана до вычета НДФЛ (шкала 13–22 %)")
    as_of: str | None = Field(None, description="Когда получены данные hh.ru (кэш 24 ч)")
    cached: bool | None = None
    stale: bool | None = Field(None, description="hh.ru недоступен — показан кэш прошлой даты")
    stub: bool | None = None
    few_data: bool | None = None
    shown: bool | None = Field(None, description="Медиана посчитана (n ≥ 8)")
    tried: list[HhTried] | None = None
    search_url: str | None = Field(None, description="Тот же поиск на hh.ru — для самопроверки")
    note: str | None = None


class HhParseOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    missing: bool | None = None
    generated_at: str | None = None
    code_commit: str | None = None
    n: int | None = None


# ------------------------------------------------------------------ импорт своей вакансии
@router.get("/vacancies/import/hh/preview", response_model=HhPreviewOut, responses=E,
            summary="Импорт своей вакансии с hh.ru: что придёт в черновик (только чтение hh.ru)")
def hh_preview(ref: str = Query(..., min_length=1, max_length=300, description="Ссылка или номер вакансии"),
               user: User = Depends(employer), db: Session = Depends(get_db)):
    _need_on()
    c = my_company(db, user)
    try:
        return importer.preview(db, c, ref)
    except HhError as e:
        raise _raise(e) from None


@router.post("/vacancies/import/hh", response_model=HhImportOut, responses=E,
             summary="Импортировать свою вакансию с hh.ru → черновик вакансии (источник «hh.ru», ссылка, дата импорта)")
def hh_import(data: HhImportIn, user: User = Depends(employer), db: Session = Depends(get_db)):
    _need_on()
    c = my_company(db, user)
    try:
        return importer.run_import(db, c, user, data.ref, confirm_own=data.confirm_own)
    except HhError as e:
        db.rollback()
        raise _raise(e) from None


# ------------------------------------------------------------------ рынок по hh.ru
def _context(db: Session, company, category_id: str | None, city: str | None, ref: str | None,
             need_id: uuid.UUID | None) -> tuple[str | None, str | None, bool]:
    from app.modules.matching.models import EmployerNeed

    remote = False
    need = db.get(EmployerNeed, need_id) if need_id else None
    if need is not None and need.company_id != company.id:
        need = None
    req = (need.requirements or {}) if need is not None else {}
    if not category_id and need is not None and need.direction_id and need.grade_id:
        category_id = f"{need.direction_id}.{need.grade_id}"
    if not category_id and ref:
        from app.modules.invitations.service import profile_by_ref

        category_id = profile_by_ref(db, ref).current_category_id
    if not city:
        city = req.get("city") or company.city
    remote = req.get("work_format") == "remote"
    return category_id, city, remote


@router.get("/market/hh", response_model=HhMarketOut, responses=E,
            summary="«Рынок по hh.ru»: медиана и p25–p75 вилок живых вакансий роли, грейда и региона (кэш 24 ч)")
def hh_market_view(category_id: str | None = Query(None, max_length=48), city: str | None = Query(None, max_length=100),
                   ref: str | None = Query(None, max_length=32, description="Кандидат: его категория, если нет своей"),
                   need_id: uuid.UUID | None = Query(None, description="Потребность: категория, город, формат"),
                   user: User = Depends(employer), db: Session = Depends(get_db)):
    _need_on()
    c = my_company(db, user)
    cat, city, remote = _context(db, c, category_id, city, ref, need_id)
    if not cat:
        return hh_market.unavailable("Категория не определена — рынок по hh.ru не считается")
    try:
        return hh_market.market(cat, city, remote=remote)
    except HhError as e:
        if e.code == "hh_category":
            return hh_market.unavailable(e.message)
        raise _raise(e) from None


# ------------------------------------------------------------------ замер разбора на корпусе hh.ru
@validation_router.get("/hh-parse", response_model=HhParseOut,
                       summary="Разбор потребности на корпусе вакансий hh.ru: полнота полей, навыки, отрицания "
                               "(пересчёт: tools/realdata/hh_corpus.py run)")
def hh_parse():
    if not DATA.exists():
        return {"missing": True}
    return json.loads(DATA.read_text(encoding="utf-8"))
