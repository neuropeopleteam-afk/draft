"""Второй фактор входа: TOTP (RFC 6238) и одноразовые резервные коды.

Политика
* Обязателен для ролей из TWOFA_REQUIRED_ROLES (по умолчанию admin и fsp_analyst) с реальной учётной записью:
  такой пользователь без подключённого второго фактора после пароля получает не вход, а токен «только
  подключение» (typ=2fa_setup) — кабинет откроется после подтверждения первого кода.
* Демо-учётки песочниц жюри (users.is_demo, вход в один клик) — по умолчанию без второго фактора, с честной
  пометкой в интерфейсе. Любая учётка может подключить TOTP добровольно; тогда её вход (пароль, персональная
  ссылка эксперта или один клик жюри) спрашивает код. «Сбросить демо» пересоздаёт учётки песочницы — подключение
  исчезает, другие эксперты жюри не затронуты.

Защита
* секрет в БД — Fernet (TWOFA_SECRET_KEY или производный от JWT_SECRET), после подключения API его не отдаёт;
* окно ±1 шаг (30 с); повтор: код шага не новее последнего использованного отклоняется (last_used_step);
* перебор: 5 неверных кодов подряд → блокировка на 15 минут (счётчик в БД, общий для воркеров) и лимит
  попыток с адреса; промежуточный токен живёт 5 минут;
* резервные коды — 10 штук, формат XXXX-XXXX без похожих символов, хранятся HMAC-хешами, каждый один раз.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import re
import secrets
import uuid

from cryptography.fernet import Fernet, InvalidToken
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import totp
from app.core.config import get_settings
from app.core.db import as_aware, utcnow
from app.core.enums import UserRole
from app.core.errors import api_error
from app.core.security import (
    TOKEN_TYPE_2FA_PENDING,
    TOKEN_TYPE_2FA_SETUP,
    codes_equal,
    create_access_token,
    decode_access_token,
    hash_code,
)
from app.modules.auth.models import TwoFactorRecoveryCode, User, UserTwoFactor
from app.modules.auth.schemas import TokenOut, TwoFactorChallengeOut, UserOut

RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без похожих 0/O и 1/I
RECOVERY_LEN = 8
# Поля промежуточного токена, которые переносятся в итоговый (песочница жюри — обязательно, иначе её не видно)
_CARRY = ("jsc",)
_CTX = ("persona", "landing", "scenario", "shared", "code")


# ----------------------------------------------------------------------------------------------- шифрование

def _fernet() -> Fernet:
    s = get_settings()
    raw = (s.twofa_secret_key or f"twofa:{s.jwt_secret}").encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw).digest()))


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


# ----------------------------------------------------------------------------------------------- политика

def required_for(user: User) -> bool:
    """Обязателен ли второй фактор: роль из списка и реальная учётка (не демо-песочница жюри)."""
    return user.role.value in get_settings().twofa_required_role_set and not user.is_demo


def get(db: Session, user: User) -> UserTwoFactor | None:
    return db.get(UserTwoFactor, user.id)


def enabled(db: Session, user: User) -> bool:
    tf = get(db, user)
    return tf is not None and tf.confirmed_at is not None


def issuer() -> str:
    s = get_settings()
    return s.twofa_issuer or s.product_name


# ----------------------------------------------------------------------------------------------- статус

def _recovery_left(db: Session, user_id: uuid.UUID) -> int:
    return len(db.scalars(select(TwoFactorRecoveryCode.id).where(
        TwoFactorRecoveryCode.user_id == user_id, TwoFactorRecoveryCode.used_at.is_(None))).all())


def status(db: Session, user: User) -> dict:
    tf = get(db, user)
    on = tf is not None and tf.confirmed_at is not None
    locked = tf is not None and tf.locked_until is not None and as_aware(tf.locked_until) > utcnow()
    demo_note = None
    if user.is_demo:
        demo_note = ("Это демо-учётка песочницы жюри: в демо-песочнице второй фактор отключён, чтобы вход в один клик "
                     "работал; для реальных учёток администратора и аналитика ФСП он обязателен. Подключите его здесь, "
                     "чтобы проверить: вход в один клик под этой персоной начнёт спрашивать код, у других экспертов жюри "
                     "ничего не изменится; «Сбросить демо» снимает подключение.")
    return {
        "enabled": on,
        "required": required_for(user),
        "pending_setup": tf is not None and tf.confirmed_at is None,
        "rotation_pending": on and bool(tf.pending_secret_enc),
        "confirmed_at": tf.confirmed_at if on else None,
        "last_verified_at": tf.last_verified_at if on else None,
        "recovery_codes_left": _recovery_left(db, user.id) if on else 0,
        "recovery_codes_total": get_settings().twofa_recovery_codes,
        "locked_until": tf.locked_until if locked else None,
        "method": "totp",
        "params": {"algorithm": totp.ALGORITHM, "digits": totp.DIGITS, "period_s": totp.PERIOD_S,
                   "window_steps": get_settings().twofa_window_steps},
        "can_disable": on and not required_for(user),
        "is_demo": user.is_demo,
        "demo_note": demo_note,
    }


# ----------------------------------------------------------------------------------------------- подключение

def begin_setup(db: Session, user: User, code: str | None = None) -> dict:
    """Новый секрет: QR, ключ для ручного ввода. Если второй фактор уже подключён — это перевыпуск, нужен
    действующий код (или резервный); старый ключ работает, пока новый не подтверждён."""
    tf = get(db, user)
    secret = totp.generate_secret()
    if tf is not None and tf.confirmed_at is not None:
        if not code:
            raise api_error(400, "code_required", "Для перевыпуска ключа введите текущий код из приложения или резервный код")
        verify_second_factor(db, user, code)
        tf.pending_secret_enc = encrypt_secret(secret)
    elif tf is None:
        tf = UserTwoFactor(user_id=user.id, secret_enc=encrypt_secret(secret))
        db.add(tf)
    else:
        tf.secret_enc = encrypt_secret(secret)  # подключение начато заново — прежний неподтверждённый ключ забыт
    db.commit()
    uri = totp.otpauth_uri(issuer(), user.email, secret)
    from app.jury_live.qr import svg

    return {"secret": secret, "secret_grouped": totp.grouped(secret), "otpauth_uri": uri, "qr_svg": svg(uri),
            "issuer": issuer(), "account": user.email, "algorithm": totp.ALGORITHM, "digits": totp.DIGITS,
            "period_s": totp.PERIOD_S, "rotation": tf.confirmed_at is not None}


def _new_recovery_codes(db: Session, user_id: uuid.UUID) -> list[str]:
    for old in db.scalars(select(TwoFactorRecoveryCode).where(TwoFactorRecoveryCode.user_id == user_id)):
        db.delete(old)
    codes = []
    for _ in range(get_settings().twofa_recovery_codes):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LEN))
        db.add(TwoFactorRecoveryCode(user_id=user_id, code_hash=hash_code(raw)))
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def confirm_setup(db: Session, user: User, code: str) -> list[str]:
    """Первый код с нового ключа: подключение (или завершение перевыпуска) и свежие резервные коды."""
    tf = get(db, user)
    if tf is None:
        raise api_error(400, "setup_not_started", "Сначала получите QR-код: подключение не начато")
    rotating = tf.confirmed_at is not None
    if rotating and not tf.pending_secret_enc:
        raise api_error(400, "setup_not_started", "Перевыпуск не начат: получите новый QR-код")
    secret = decrypt_secret(tf.pending_secret_enc if rotating else tf.secret_enc)
    if secret is None:
        raise api_error(500, "secret_unreadable", "Ключ второго фактора не читается: сменился ключ шифрования. Начните подключение заново")
    _check_lock(tf)
    step = totp.verify(secret, code, window=get_settings().twofa_window_steps)
    if step is None:
        _fail(db, tf)
        raise api_error(400, "invalid_code", "Код не подошёл. Проверьте время на телефоне и введите код ещё раз")
    now = utcnow()
    if rotating:
        tf.secret_enc, tf.pending_secret_enc = tf.pending_secret_enc, None
    tf.confirmed_at = now
    tf.last_used_step = step
    tf.last_verified_at = now
    tf.fail_count = 0
    tf.locked_until = None
    codes = _new_recovery_codes(db, user.id)
    db.commit()
    return codes


def regenerate_recovery(db: Session, user: User, code: str) -> list[str]:
    _require_enabled(db, user)
    verify_second_factor(db, user, code)
    codes = _new_recovery_codes(db, user.id)
    db.commit()
    return codes


def disable(db: Session, user: User, code: str) -> None:
    tf = _require_enabled(db, user)
    if required_for(user):
        raise api_error(403, "twofa_required_role",
                        "Для вашей роли второй фактор обязателен: его можно только перевыпустить. Сброс — через администратора")
    verify_second_factor(db, user, code)
    _drop(db, tf)
    db.commit()


def _drop(db: Session, tf: UserTwoFactor) -> None:
    for rc in db.scalars(select(TwoFactorRecoveryCode).where(TwoFactorRecoveryCode.user_id == tf.user_id)):
        db.delete(rc)
    db.delete(tf)


def _require_enabled(db: Session, user: User) -> UserTwoFactor:
    tf = get(db, user)
    if tf is None or tf.confirmed_at is None:
        raise api_error(400, "twofa_not_enabled", "Второй фактор не подключён")
    return tf


# ----------------------------------------------------------------------------------------------- проверка кода

def _check_lock(tf: UserTwoFactor) -> None:
    if tf.locked_until is not None and as_aware(tf.locked_until) > utcnow():
        left = int((as_aware(tf.locked_until) - utcnow()).total_seconds() // 60) + 1
        raise api_error(429, "too_many_attempts", f"Слишком много неверных кодов. Повторите через {left} мин")


def _fail(db: Session, tf: UserTwoFactor) -> None:
    s = get_settings()
    tf.fail_count = (tf.fail_count or 0) + 1
    if tf.fail_count >= s.twofa_max_fails:
        tf.locked_until = utcnow() + timedelta(minutes=s.twofa_lock_minutes)
        tf.fail_count = 0
    db.commit()


def normalize_code(code: str) -> tuple[str, str]:
    """(вид, значение): totp — 6 цифр; recovery — 8 символов без дефиса и пробелов; other — не похоже ни на что."""
    raw = (code or "").strip()
    digits = raw.replace(" ", "")
    if digits.isdigit() and len(digits) == totp.DIGITS:
        return "totp", digits
    # резервный код: регистр, дефисы и пробелы не важны; похожих символов (0/O, 1/I) в алфавите нет
    rec = re.sub(r"[^A-Z2-9]", "", raw.upper())
    if len(rec) == RECOVERY_LEN:
        return "recovery", rec
    return "other", raw


def verify_second_factor(db: Session, user: User, code: str) -> str:
    """Проверяет код из приложения (окно ±1 шаг, без повторов) или резервный код (одноразово).
    Возвращает «totp» или «recovery»; иначе — ошибка 400/429."""
    tf = _require_enabled(db, user)
    _check_lock(tf)
    kind, value = normalize_code(code)
    now = utcnow()
    if kind == "totp":
        secret = decrypt_secret(tf.secret_enc)
        step = totp.verify(secret, value, window=get_settings().twofa_window_steps) if secret else None
        if step is None:
            _fail(db, tf)
            raise api_error(400, "invalid_code", "Код не подошёл. Введите текущий код из приложения или резервный код")
        if tf.last_used_step is not None and step <= tf.last_used_step:
            # повтор (или код более старого шага) — не принимаем, но и не считаем перебором
            raise api_error(400, "code_reused", "Этот код уже использован. Дождитесь следующего кода в приложении")
        tf.last_used_step = step
        tf.last_verified_at = now
        tf.fail_count = 0
        db.commit()
        return "totp"
    if kind == "recovery":
        for rc in db.scalars(select(TwoFactorRecoveryCode).where(TwoFactorRecoveryCode.user_id == user.id,
                                                                  TwoFactorRecoveryCode.used_at.is_(None))):
            if codes_equal(rc.code_hash, value):
                rc.used_at = now
                tf.last_verified_at = now
                tf.fail_count = 0
                db.commit()
                return "recovery"
        _fail(db, tf)
        raise api_error(400, "invalid_code", "Резервный код не подошёл или уже использован")
    _fail(db, tf)
    raise api_error(400, "invalid_code", "Введите 6 цифр из приложения или резервный код вида XXXX-XXXX")


# ----------------------------------------------------------------------------------------------- вход

@dataclass
class Pending:
    user: User
    payload: dict


def challenge(user: User, extra: dict | None = None, **context) -> TwoFactorChallengeOut:
    """Пароль (или ссылка) принят, второй фактор подключён: промежуточный токен на 5 минут, вход — после кода."""
    s = get_settings()
    ctx = {k: v for k, v in context.items() if v is not None}
    token, ttl = create_access_token(user.id, user.role.value, user.token_version,
                                     {**(extra or {}), **ctx, "typ": TOKEN_TYPE_2FA_PENDING},
                                     ttl_minutes=s.twofa_pending_ttl_minutes)
    return TwoFactorChallengeOut(pending_token=token, expires_in=ttl, setup_required=False,
                                 methods=["totp", "recovery"], email=user.email, role=user.role,
                                 landing=context.get("landing"), **{k: v for k, v in ctx.items() if k in ("persona", "scenario", "shared")})


def setup_challenge(user: User, **context) -> TwoFactorChallengeOut:
    """Роль с обязательным вторым фактором, но он не подключён: токен только для подключения (15 минут)."""
    s = get_settings()
    ctx = {k: v for k, v in context.items() if v is not None}
    token, ttl = create_access_token(user.id, user.role.value, user.token_version,
                                     {**ctx, "typ": TOKEN_TYPE_2FA_SETUP}, ttl_minutes=s.twofa_setup_ttl_minutes)
    return TwoFactorChallengeOut(pending_token=token, expires_in=ttl, setup_required=True, methods=["totp"],
                                 email=user.email, role=user.role, landing=context.get("landing"))


def after_first_factor(db: Session, user: User, extra: dict | None = None, **context) -> TokenOut | TwoFactorChallengeOut:
    """Единая точка после первого фактора (пароль, ссылка эксперта, один клик жюри): токен или запрос кода."""
    if enabled(db, user):
        return challenge(user, extra, **context)
    if required_for(user):
        return setup_challenge(user, **context)
    token, ttl = create_access_token(user.id, user.role.value, user.token_version, extra)
    return TokenOut(access_token=token, expires_in=ttl, user=UserOut.model_validate(user))


def _decode_pending(db: Session, token: str, expected_typ: str) -> Pending:
    try:
        payload = decode_access_token(token)
        user = db.get(User, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise api_error(401, "invalid_token", "Сеанс входа истёк — введите пароль ещё раз") from None
    if payload.get("typ") != expected_typ or user is None or not user.is_active or payload.get("ver", 0) != user.token_version:
        raise api_error(401, "invalid_token", "Сеанс входа истёк — введите пароль ещё раз")
    return Pending(user, payload)


def complete_login(db: Session, pending_token: str, code: str) -> tuple[TokenOut, dict, str]:
    """Код к промежуточному токену → полноценный токен (с переносом песочницы жюри) и контекст входа."""
    p = _decode_pending(db, pending_token, TOKEN_TYPE_2FA_PENDING)
    method = verify_second_factor(db, p.user, code)
    extra = {k: p.payload[k] for k in _CARRY if k in p.payload}
    extra["amr"] = ["pwd", "otp" if method == "totp" else "rc"]  # как прошёл вход: пароль + код (RFC 8176)
    p.user.last_login_at = utcnow()
    db.commit()
    token, ttl = create_access_token(p.user.id, p.user.role.value, p.user.token_version, extra)
    ctx = {k: p.payload[k] for k in _CTX if k in p.payload}
    return TokenOut(access_token=token, expires_in=ttl, user=UserOut.model_validate(p.user)), ctx, method


def user_for_setup(db: Session, token: str) -> tuple[User, bool]:
    """Пользователь по обычному токену или по токену обязательного подключения. (user, по токену подключения)."""
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise api_error(401, "invalid_token", "Токен недействителен или истёк") from None
    typ = payload.get("typ")
    if typ == TOKEN_TYPE_2FA_SETUP:
        return _decode_pending(db, token, TOKEN_TYPE_2FA_SETUP).user, True
    if typ:
        raise api_error(401, "second_factor_required", "Подтвердите вход кодом из приложения-аутентификатора")
    from app.core.deps import get_current_user

    return get_current_user(token, db), False


def finish_setup_token(db: Session, user: User, payload_ctx: dict | None = None) -> TokenOut:
    """После подтверждения первого кода по токену подключения — полноценный вход."""
    user.last_login_at = utcnow()
    db.commit()
    token, ttl = create_access_token(user.id, user.role.value, user.token_version,
                                     {"amr": ["pwd", "otp"], **(payload_ctx or {})})
    return TokenOut(access_token=token, expires_in=ttl, user=UserOut.model_validate(user))


# ----------------------------------------------------------------------------------------------- администратор

def admin_list(db: Session) -> list[dict]:
    rows = db.execute(select(UserTwoFactor, User).join(User, User.id == UserTwoFactor.user_id)
                      .order_by(User.role, User.email)).all()
    return [{"email": u.email, "role": u.role, "is_demo": u.is_demo, "enabled": tf.confirmed_at is not None,
             "confirmed_at": tf.confirmed_at, "last_verified_at": tf.last_verified_at,
             "recovery_codes_left": _recovery_left(db, u.id) if tf.confirmed_at else 0,
             "locked_until": tf.locked_until if tf.locked_until and as_aware(tf.locked_until) > utcnow() else None,
             "required": required_for(u)} for tf, u in rows]


def admin_reset(db: Session, admin: User, email: str) -> dict:
    """Снять второй фактор пользователю (телефон потерян): подключение удаляется, все его сеансы отзываются.
    Для обязательных ролей следующий вход снова потребует подключить приложение."""
    target = db.scalar(select(User).where(User.email == email.strip().lower()))
    if target is None:
        raise api_error(404, "user_not_found", "Пользователь с такой почтой не найден")
    if target.id == admin.id:
        raise api_error(409, "self_reset", "Свой второй фактор перевыпустите в настройках безопасности, а не сбрасывайте")
    tf = get(db, target)
    if tf is None:
        raise api_error(404, "twofa_not_enabled", "У этого пользователя второй фактор не подключён")
    _drop(db, tf)
    target.token_version += 1  # выход со всех устройств: украденный сеанс не переживёт сброс
    db.commit()
    return {"ok": True, "email": target.email, "role": target.role, "required": required_for(target),
            "sessions_revoked": True}


def staff_roles() -> tuple[UserRole, ...]:
    return (UserRole.admin, UserRole.fsp_analyst)
