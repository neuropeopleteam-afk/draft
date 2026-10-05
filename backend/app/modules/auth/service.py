"""Бизнес-логика регистрации, подтверждения почты и входа."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import as_aware, utcnow
from app.core.enums import ConsentKind, UserRole, VerificationPurpose
from app.core.errors import api_error
from app.core.security import (
    codes_equal,
    create_access_token,
    generate_code,
    hash_code,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.modules.auth.models import Consent, EmailVerification, User
from app.modules.auth.schemas import RegisterIn, TokenOut, UserOut
from app.modules.notifications.mailer import send_verification_code
from app.modules.profiles.models import CandidateProfile, Company, EmployerProfile

CONSENT_DOC_VERSION = "2026-10-05"
# Фиктивный хеш для выравнивания времени ответа, когда пользователя нет (защита от перебора почт).
_DUMMY_HASH = hash_password("timing-equalizer-0")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def register_user(db: Session, data: RegisterIn) -> tuple[User, str]:
    if not data.consent_processing:
        raise api_error(422, "consent_required", "Нужно согласие на обработку персональных данных")
    email = normalize_email(data.email)
    if db.scalar(select(User).where(User.email == email)):
        raise api_error(409, "email_taken", "Пользователь с такой почтой уже зарегистрирован")

    user = User(email=email, password_hash=hash_password(data.password), role=data.role)
    db.add(user)
    db.flush()
    db.add(Consent(user_id=user.id, kind=ConsentKind.processing, document_version=CONSENT_DOC_VERSION))
    if data.role == UserRole.candidate:
        db.add(CandidateProfile(user_id=user.id, full_name=data.full_name))
    else:
        company = Company(name=data.company_name or "Моя компания", created_by=user.id, contact_email=email)
        db.add(company)
        db.flush()
        db.add(EmployerProfile(user_id=user.id, company_id=company.id, full_name=data.full_name))
    code = _issue_code(db, user)
    db.commit()
    send_verification_code(email, code)
    return user, code


def _issue_code(db: Session, user: User) -> str:
    s = get_settings()
    # Прежние неиспользованные коды гасим — действует только последний.
    for v in db.scalars(
        select(EmailVerification).where(
            EmailVerification.user_id == user.id, EmailVerification.consumed_at.is_(None)
        )
    ):
        v.consumed_at = utcnow()
    code = generate_code()
    db.add(
        EmailVerification(
            user_id=user.id,
            purpose=VerificationPurpose.email_confirm,
            code_hash=hash_code(code),
            expires_at=utcnow() + timedelta(minutes=s.email_code_ttl_minutes),
        )
    )
    return code


def resend_code(db: Session, email: str) -> str | None:
    s = get_settings()
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None or user.is_email_verified:
        return None  # не раскрываем, есть ли такой адрес
    last = db.scalar(
        select(EmailVerification)
        .where(EmailVerification.user_id == user.id)
        .order_by(EmailVerification.created_at.desc())
        .limit(1)
    )
    if last and (utcnow() - as_aware(last.created_at)).total_seconds() < s.email_code_resend_seconds:
        raise api_error(429, "too_frequent", "Повторно запросить код можно через минуту")
    code = _issue_code(db, user)
    db.commit()
    send_verification_code(user.email, code)
    return code


def verify_email(db: Session, email: str, code: str) -> User:
    s = get_settings()
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        raise api_error(400, "invalid_code", "Неверный или просроченный код")
    if user.is_email_verified:
        return user
    v = db.scalar(
        select(EmailVerification)
        .where(EmailVerification.user_id == user.id, EmailVerification.consumed_at.is_(None))
        .order_by(EmailVerification.created_at.desc())
        .limit(1)
    )
    if v is None or as_aware(v.expires_at) < utcnow():
        raise api_error(400, "invalid_code", "Неверный или просроченный код")
    if v.attempts >= s.email_code_max_attempts:
        raise api_error(429, "too_many_attempts", "Слишком много попыток. Запросите новый код")
    if not codes_equal(v.code_hash, code):
        v.attempts += 1
        db.commit()
        raise api_error(400, "invalid_code", "Неверный или просроченный код")
    v.consumed_at = utcnow()
    user.is_email_verified = True
    user.email_verified_at = utcnow()
    db.commit()
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        verify_password(_DUMMY_HASH, password)
        raise api_error(401, "invalid_credentials", "Неверная почта или пароль")
    if not verify_password(user.password_hash, password):
        raise api_error(401, "invalid_credentials", "Неверная почта или пароль")
    if not user.is_active:
        raise api_error(403, "user_blocked", "Учётная запись заблокирована")
    if not user.is_email_verified:
        raise api_error(403, "email_not_verified", "Подтвердите почту — код отправлен при регистрации")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = utcnow()
    db.commit()
    return user


def issue_token(user: User) -> TokenOut:
    token, ttl = create_access_token(user.id, user.role.value, user.token_version)
    return TokenOut(access_token=token, expires_in=ttl, user=UserOut.model_validate(user))
