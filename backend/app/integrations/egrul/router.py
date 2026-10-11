"""API проверки работодателя по ИНН и индекса доверия."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_db
from app.core.deps import get_current_user, require_role
from app.core.enums import InvitationStatus, UserRole
from app.core.errors import api_error, err
from app.integrations.egrul import trust as trust_mod
from app.integrations.egrul.client import check_inn
from app.integrations.egrul.models import RegistryCheck
from app.modules.auth.models import User
from app.modules.invitations.models import Invitation
from app.modules.matching.router import my_company
from app.modules.profiles.models import Company

router = APIRouter(tags=["employer-trust"])
employer = require_role(UserRole.employer)
candidate = require_role(UserRole.candidate)


def _bg_check(inn: str, company_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        check_inn(db, inn, company_id=company_id)
    finally:
        db.close()


def _ensure_checked(db: Session, bg: BackgroundTasks, c: Company) -> None:
    """Компания с ИНН, ещё не проверенная в ФНС, — проверка в фоне (кандидат не ждёт ответа ФНС)."""
    if c.inn and db.scalar(select(RegistryCheck.id).where(RegistryCheck.inn == c.inn.strip())) is None:
        bg.add_task(_bg_check, c.inn.strip(), c.id)


@router.post("/api/employer/company/registry-check",
             summary="Проверить мою компанию по ИНН в ЕГРЮЛ (egrul.nalog.ru) и пересчитать индекс доверия",
             description="Сведения ФНС кэшируются на 7 дней. При капче или сбое ФНС — статус «не удалось проверить», "
                         "индекс помечается как предварительный (мягкая деградация).",
             responses={401: err("Не выполнен вход"), 403: err("Только для работодателя"),
                        422: err("В профиле компании не указан ИНН")})
def registry_check(force: bool = False, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    if not c.inn:
        raise api_error(422, "inn_required", "Укажите ИНН в профиле компании")
    check_inn(db, c.inn, force=force, company_id=c.id)
    return trust_mod.compute(db, c)


@router.get("/api/employer/company/trust", summary="Индекс доверия моей компании (как его видит кандидат)",
            responses={401: err("Не выполнен вход"), 403: err("Только для работодателя")})
def my_trust(bg: BackgroundTasks, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    _ensure_checked(db, bg, c)
    return trust_mod.compute(db, c)


def _tariff_badge(db: Session, company_id) -> dict:
    from app.modules.tariffs.service import badge

    return badge(db, company_id)


@router.get("/api/companies/{company_id}", summary="Профиль компании с индексом доверия (для кандидата)",
            responses={401: err("Не выполнен вход"), 404: err("Компания не найдена")})
def company_profile(company_id: uuid.UUID, bg: BackgroundTasks, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> dict:
    c = db.get(Company, company_id)
    if c is None:
        raise api_error(404, "company_not_found", "Компания не найдена")
    _ensure_checked(db, bg, c)
    from app.integrations.vacancies.models import Vacancy

    vac = db.scalars(select(Vacancy).where(Vacancy.company_id == c.id, Vacancy.status == "published")
                     .order_by(Vacancy.published_at.desc())).all()
    return {"id": str(c.id), "name": c.name, "industry": c.industry, "description": c.description,
            "website": c.website, "city": c.city, "inn": c.inn, "is_demo": c.is_demo,
            **_tariff_badge(db, c.id),  # Я29: метка «Партнёр ФСП» — только при TARIFFS_ENABLED
            "trust": trust_mod.compute(db, c),
            "vacancies": [{"id": str(v.id), "title": v.title, "salary_from": v.salary_from, "salary_to": v.salary_to,
                           "category_id": v.category_id} for v in vac]}


@router.get("/api/candidate/invitations-trust",
            summary="Индекс доверия работодателя по каждому моему приглашению (кратко)",
            responses={401: err("Не выполнен вход"), 403: err("Только для кандидата")})
def invitations_trust(bg: BackgroundTasks, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(Invitation).where(Invitation.candidate_user_id == user.id,
                                               Invitation.status != InvitationStatus.withdrawn)).all()
    out, cache = {}, {}
    for i in rows:
        c = db.get(Company, i.company_id)
        if c.id not in cache:
            _ensure_checked(db, bg, c)
            cache[c.id] = trust_mod.compute(db, c)
        t = trust_mod.compute(db, c, invitation=i) if cache[c.id] else None
        out[str(i.id)] = {**trust_mod.short(t), "company_id": str(c.id)}
    return out


@router.get("/api/candidate/invitations/{inv_id}/trust",
            summary="Индекс доверия работодателя для приглашения: причины и оценка вилки этого предложения",
            responses={401: err("Не выполнен вход"), 403: err("Только для кандидата"),
                       404: err("Приглашение не найдено")})
def invitation_trust(inv_id: uuid.UUID, bg: BackgroundTasks, user: User = Depends(candidate),
                     db: Session = Depends(get_db)) -> dict:
    i = db.get(Invitation, inv_id)
    if i is None or i.candidate_user_id != user.id:
        raise api_error(404, "invitation_not_found", "Приглашение не найдено")
    c = db.get(Company, i.company_id)
    _ensure_checked(db, bg, c)
    return trust_mod.compute(db, c, invitation=i)
