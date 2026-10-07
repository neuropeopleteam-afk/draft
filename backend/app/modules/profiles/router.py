from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db, utcnow
from app.core.deps import get_current_user, require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.modules.auth.models import User
from app.modules.fsp.models import FspAchievement, FspPassport
from app.modules.profiles.models import CandidateProfile, Company, EmployerProfile
from app.modules.profiles.schemas import (
    CandidateProfileOut,
    CandidateProfileUpdate,
    CompanyOut,
    CompanyUpdate,
    EmployerOut,
    FspStatusOut,
    MeOut,
)

router = APIRouter(prefix="/api/me", tags=["profiles"])
AUTH_ERRORS = {401: err("Не выполнен вход или токен истёк"), 403: err("Недостаточно прав")}


def build_me(db: Session, user: User) -> MeOut:
    me = MeOut(
        id=user.id, email=user.email, role=user.role, is_email_verified=user.is_email_verified, created_at=user.created_at
    )
    if user.role == UserRole.candidate:
        profile = db.get(CandidateProfile, user.id)
        me.candidate = CandidateProfileOut.model_validate(profile) if profile else None
        if me.candidate:
            from app.modules.profiles.facts import load_bundles
            from app.modules.profiles.specializations import summary

            b = load_bundles(db, [user.id])[user.id]
            me.candidate.specializations = [summary(r, b.tests_by_direction.get(r.direction_id))
                                           for r in sorted(b.specializations.values(), key=lambda r: (not r.is_primary, r.direction_id))]
        passport = db.scalar(select(FspPassport).where(FspPassport.user_id == user.id))
        count = (
            db.scalar(select(func.count()).select_from(FspAchievement).where(FspAchievement.passport_id == passport.id))
            if passport
            else 0
        )
        me.fsp = FspStatusOut(
            linked=passport is not None,
            link_source=passport.link_source.value if passport else None,
            achievements_count=count or 0,
        )
    elif user.role == UserRole.employer:
        ep = db.get(EmployerProfile, user.id)
        company = db.get(Company, ep.company_id) if ep and ep.company_id else None
        me.employer = EmployerOut(
            full_name=ep.full_name if ep else None,
            position=ep.position if ep else None,
            company=CompanyOut.model_validate(company) if company else None,
        )
    return me


@router.get("", response_model=MeOut, summary="Текущий пользователь и его профиль", responses=AUTH_ERRORS)
def get_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeOut:
    return build_me(db, user)


@router.patch(
    "/candidate-profile",
    response_model=MeOut,
    summary="Обновить профиль кандидата",
    responses=AUTH_ERRORS,
)
def update_candidate_profile(
    data: CandidateProfileUpdate,
    user: User = Depends(require_role(UserRole.candidate)),
    db: Session = Depends(get_db),
) -> MeOut:
    profile = db.get(CandidateProfile, user.id) or CandidateProfile(user_id=user.id)
    db.add(profile)
    for k, v in data.model_dump(exclude_unset=True).items():
        if k in ("age_group", "parental_consent") and v is None:
            raise api_error(422, "age_group_required", "Возрастная группа и отметка согласия не могут быть пустыми")
        setattr(profile, k, v)
    if profile.age_group == "18+":
        profile.parental_consent = False
    profile.parental_consent_at = ((profile.parental_consent_at or utcnow()) if profile.parental_consent else None)
    db.commit()
    return build_me(db, user)


@router.patch(
    "/company",
    response_model=MeOut,
    summary="Обновить профиль компании работодателя",
    responses={**AUTH_ERRORS, 404: err("Компания не найдена")},
)
def update_company(
    data: CompanyUpdate,
    user: User = Depends(require_role(UserRole.employer)),
    db: Session = Depends(get_db),
) -> MeOut:
    ep = db.get(EmployerProfile, user.id)
    company = db.get(Company, ep.company_id) if ep and ep.company_id else None
    if company is None:
        raise api_error(404, "company_not_found", "Компания не найдена")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(company, k, v)
    db.commit()
    return build_me(db, user)
