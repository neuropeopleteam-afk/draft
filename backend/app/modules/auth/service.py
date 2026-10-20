"""Бизнес-логика регистрации, подтверждения почты и входа."""
from datetime import timedelta
import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import as_aware, utcnow
from app.core.enums import ConsentKind, UserRole, VerificationPurpose
from app.core.errors import api_error
from app.core.legal import CONSENT_VERSION as CONSENT_DOC_VERSION
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
from app.modules.notifications.mailer import Message, get_mailer, send_verification_code
from app.modules.profiles.models import CandidateProfile, Company, EmployerProfile
from app.modules.profiles.refs import new_public_ref

# Фиктивный хеш для выравнивания времени ответа, когда пользователя нет (защита от перебора почт).
_DUMMY_HASH = hash_password("timing-equalizer-0")

# Лимит перебора пароля (В1): 10 неудач на адрес за 15 минут → 429. Счётчик в памяти процесса (без миграции);
# при 2 воркерах uvicorn фактический предел — до 20 попыток за окно. Неудачные попытки ввода кода почты
# переносятся на новый код в течение часа.
LOGIN_MAX_FAILS = 10
LOGIN_WINDOW_S = 15 * 60
CODE_ATTEMPTS_WINDOW_MIN = 60
_LOGIN_FAILS: dict[str, list[float]] = {}
_LOGIN_LOCK = threading.Lock()


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
        db.add(CandidateProfile(user_id=user.id, full_name=data.full_name, public_ref=new_public_ref(db)))
    else:
        company = Company(name=data.company_name or "Моя компания", created_by=user.id, contact_email=email)
        db.add(company)
        db.flush()
        db.add(EmployerProfile(user_id=user.id, company_id=company.id, full_name=data.full_name))
    code = _issue_code(db, user)
    db.commit()
    send_verification_code(email, code)
    return user, code


def _issue_code(db: Session, user: User, purpose: VerificationPurpose = VerificationPurpose.email_confirm) -> str:
    s = get_settings()
    # Прежние неиспользованные коды этой же цели гасим — действует только последний. Неудачные попытки переносятся на новый
    # код (окно — час): повторная отправка не обнуляет лимит ввода.
    inherited = 0
    window_start = utcnow() - timedelta(minutes=CODE_ATTEMPTS_WINDOW_MIN)
    for v in db.scalars(
        select(EmailVerification).where(
            EmailVerification.user_id == user.id,
            EmailVerification.purpose == purpose,
            EmailVerification.consumed_at.is_(None),
        )
    ):
        if as_aware(v.created_at) >= window_start:
            inherited = max(inherited, v.attempts or 0)
        v.consumed_at = utcnow()
    code = generate_code()
    db.add(
        EmailVerification(
            user_id=user.id,
            purpose=purpose,
            code_hash=hash_code(code),
            expires_at=utcnow() + timedelta(minutes=s.email_code_ttl_minutes),
            attempts=inherited,
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
        .where(
            EmailVerification.user_id == user.id,
            EmailVerification.purpose == VerificationPurpose.email_confirm,
        )
        .order_by(EmailVerification.created_at.desc())
        .limit(1)
    )
    if last and (utcnow() - as_aware(last.created_at)).total_seconds() < s.email_code_resend_seconds:
        raise api_error(429, "too_frequent", "Повторно запросить код можно через минуту")
    code = _issue_code(db, user, VerificationPurpose.email_confirm)
    db.commit()
    send_verification_code(user.email, code)
    return code


def _send_password_reset_code(email: str, code: str) -> None:
    import logging

    s = get_settings()
    log = logging.getLogger("notifications")
    text = (
        f"Здравствуйте!\n\nКод для восстановления пароля на платформе «{s.product_name}»: {code}\n"
        f"Код действует {s.email_code_ttl_minutes} минут.\n\n"
        "Если вы не запрашивали сброс пароля, просто проигнорируйте это письмо."
    )
    html = (
        f"<p>Здравствуйте!</p><p>Код для восстановления пароля: <b style='font-size:20px'>{code}</b></p>"
        f"<p>Код действует {s.email_code_ttl_minutes} минут.</p>"
    )
    try:
        get_mailer().send(Message(to=email, subject="Восстановление пароля", text=text, html=html))
    except Exception:  # noqa: BLE001
        log.exception("Не удалось отправить письмо сброса пароля на %s", email)
    if s.effective_dev_mode:
        log.warning("DEV_MODE: код сброса пароля для %s: %s", email, code)


def forgot_password(db: Session, email: str) -> str | None:
    s = get_settings()
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None or not user.is_active or user.is_demo:
        return None  # не раскрываем наличие адреса в системе
    last = db.scalar(
        select(EmailVerification)
        .where(
            EmailVerification.user_id == user.id,
            EmailVerification.purpose == VerificationPurpose.password_reset,
        )
        .order_by(EmailVerification.created_at.desc())
        .limit(1)
    )
    if last and (utcnow() - as_aware(last.created_at)).total_seconds() < s.email_code_resend_seconds:
        raise api_error(429, "too_frequent", "Повторно запросить код можно через минуту")
    code = _issue_code(db, user, VerificationPurpose.password_reset)
    db.commit()
    _send_password_reset_code(user.email, code)
    return code


def reset_password(db: Session, email: str, code: str, new_password: str) -> User:
    s = get_settings()
    key = normalize_email(email)
    user = db.scalar(select(User).where(User.email == key))
    if user is None or not user.is_active or user.is_demo:
        verify_password(_DUMMY_HASH, new_password)
        raise api_error(400, "invalid_code", "Неверный или просроченный код")
    v = db.scalar(
        select(EmailVerification)
        .where(
            EmailVerification.user_id == user.id,
            EmailVerification.purpose == VerificationPurpose.password_reset,
            EmailVerification.consumed_at.is_(None),
        )
        .order_by(EmailVerification.created_at.desc())
        .limit(1)
    )
    if v is None or as_aware(v.expires_at) < utcnow():
        raise api_error(400, "invalid_code", "Неверный или просроченный код")
    if v.attempts >= s.email_code_max_attempts:
        raise api_error(
            429,
            "too_many_attempts",
            "Слишком много попыток ввода кода. Попробуйте через час: новый код лимит не сбрасывает",
        )
    if not codes_equal(v.code_hash, code):
        v.attempts += 1
        db.commit()
        raise api_error(400, "invalid_code", "Неверный или просроченный код")
    v.consumed_at = utcnow()
    user.password_hash = hash_password(new_password)
    user.token_version = (user.token_version or 0) + 1
    if not user.is_email_verified:
        user.is_email_verified = True
        user.email_verified_at = utcnow()
    with _LOGIN_LOCK:
        _LOGIN_FAILS.pop(key, None)
    db.commit()
    return user


def verify_email(db: Session, email: str, code: str) -> User:
    s = get_settings()
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        raise api_error(400, "invalid_code", "Неверный или просроченный код")
    if user.is_email_verified:
        # Токен — только за верный код. Для уже подтверждённой почты кода нет: та же ошибка, что и для неверного
        # (не раскрываем, что адрес подтверждён), вход — по паролю.
        raise api_error(400, "invalid_code", "Неверный или просроченный код. Если почта уже подтверждена — войдите по паролю")
    v = db.scalar(
        select(EmailVerification)
        .where(
            EmailVerification.user_id == user.id,
            EmailVerification.purpose == VerificationPurpose.email_confirm,
            EmailVerification.consumed_at.is_(None),
        )
        .order_by(EmailVerification.created_at.desc())
        .limit(1)
    )
    if v is None or as_aware(v.expires_at) < utcnow():
        raise api_error(400, "invalid_code", "Неверный или просроченный код")
    if v.attempts >= s.email_code_max_attempts:
        raise api_error(429, "too_many_attempts",
                        "Слишком много попыток ввода кода. Попробуйте через час: новый код лимит не сбрасывает")
    if not codes_equal(v.code_hash, code):
        v.attempts += 1
        db.commit()
        raise api_error(400, "invalid_code", "Неверный или просроченный код")
    v.consumed_at = utcnow()
    user.is_email_verified = True
    user.email_verified_at = utcnow()
    db.commit()
    return user


def _login_blocked(email: str) -> bool:
    now = time.monotonic()
    with _LOGIN_LOCK:
        fails = [t for t in _LOGIN_FAILS.get(email, []) if now - t < LOGIN_WINDOW_S]
        if fails:
            _LOGIN_FAILS[email] = fails
        else:
            _LOGIN_FAILS.pop(email, None)
        return len(fails) >= LOGIN_MAX_FAILS


def _login_failed(email: str) -> None:
    with _LOGIN_LOCK:
        if len(_LOGIN_FAILS) > 50_000:  # защита памяти: старые записи отбрасываем
            _LOGIN_FAILS.clear()
        _LOGIN_FAILS.setdefault(email, []).append(time.monotonic())


def authenticate(db: Session, email: str, password: str) -> User:
    key = normalize_email(email)
    if _login_blocked(key):
        raise api_error(429, "too_many_attempts", "Слишком много неудачных попыток входа. Попробуйте через 15 минут")
    user = db.scalar(select(User).where(User.email == key))
    if user is None:
        verify_password(_DUMMY_HASH, password)
        _login_failed(key)
        raise api_error(401, "invalid_credentials", "Неверная почта или пароль")
    if not verify_password(user.password_hash, password):
        _login_failed(key)
        raise api_error(401, "invalid_credentials", "Неверная почта или пароль")
    with _LOGIN_LOCK:
        _LOGIN_FAILS.pop(key, None)
    if not user.is_active:
        raise api_error(403, "user_blocked", "Учётная запись заблокирована")
    if not user.is_email_verified:
        raise api_error(403, "email_not_verified", "Подтвердите почту — код отправлен при регистрации")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = utcnow()
    db.commit()
    return user


def issue_token(user: User, extra: dict | None = None) -> TokenOut:
    token, ttl = create_access_token(user.id, user.role.value, user.token_version, extra)
    return TokenOut(access_token=token, expires_in=ttl, user=UserOut.model_validate(user))
