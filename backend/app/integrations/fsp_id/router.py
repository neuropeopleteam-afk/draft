"""Вход и связка аккаунта через «ФСП ID (демо)» — Keycloak, realm fsp, OIDC Authorization Code + PKCE.

Поток (backend-for-frontend — токены Keycloak в браузер не попадают):
1. ``POST /api/fsp-id/start`` → state, nonce, code_verifier в БД → ``authorize_url`` Keycloak;
2. Keycloak → ``GET /api/fsp-id/callback?code&state`` → обмен кода (code_verifier) → проверка id_token по JWKS
   (подпись, iss, aud, exp, nonce) → одноразовый билет → редирект на ``/fsp-id/done?ticket=…``;
3. фронтенд ``POST /api/fsp-id/exchange`` → наш JWT; новому пользователю — сначала согласие 152-ФЗ
   (``POST /api/fsp-id/complete``), до него учётная запись не создаётся.
"""
from __future__ import annotations

from datetime import timedelta
import logging
import secrets
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
import jwt
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import as_aware, get_db, utcnow
from app.core.deps import oauth2_scheme
from app.core.enums import ConsentKind, UserRole
from app.core.errors import api_error, err
from app.core.legal import CONSENT_VERSION
from app.core.security import decode_access_token, hash_password
from app.integrations.fsp_id import oidc
from app.integrations.fsp_id.mapping import apply_claims, passport_preview
from app.integrations.fsp_id.models import OidcLoginState
from app.integrations.settings import get_isettings
from app.modules.auth.models import Consent, User
from app.modules.auth.service import issue_token
from app.modules.profiles.models import CandidateProfile
from app.modules.profiles.refs import new_public_ref

router = APIRouter(prefix="/api/fsp-id", tags=["fsp-id"])
log = logging.getLogger(__name__)
STATE_TTL = timedelta(minutes=10)
TICKET_TTL = timedelta(minutes=5)

DEMO_TITLES = {
    "fsp-champion": "Победитель всероссийских соревнований, КМС (продуктовое и алгоритмическое программирование)",
    "fsp-prizer": "Призёр региональных соревнований, II разряд (информационная безопасность)",
    "fsp-newcomer": "Участник без истории ФСП — нейтральное состояние",
}


def _optional_user(token: str | None, db: Session) -> User | None:
    if not token:
        return None
    try:
        p = decode_access_token(token)
        u = db.get(User, uuid.UUID(p["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    return u if u and u.is_active and p.get("ver", 0) == u.token_version else None


@router.get("/config", summary="Настройки входа через ФСП ID (демо) и демо-учётки realm fsp")
def config() -> dict:
    s = get_isettings()
    return {"enabled": s.fsp_enabled, "title": "ФСП ID (демо)", "issuer": s.fsp_oidc_issuer,
            "client_id": s.fsp_oidc_client_id, "flow": "authorization_code+pkce(S256)",
            "demo_accounts": [{"username": u, "title": DEMO_TITLES.get(u, "")}
                              for u in s.fsp_demo_accounts.split(",") if u.strip()] if s.fsp_enabled else [],
            "demo_password": s.fsp_demo_password if s.fsp_enabled else None,
            "note": "Демонстрационный Keycloak с синтетическими участниками. Реальный ФСП ID подключается сменой "
                    "issuer и секрета клиента (docs/FSP_INTEGRATION.md)."}


class StartIn(BaseModel):
    intent: str = Field("login", pattern="^(login|link)$")
    return_to: str | None = Field(None, max_length=200, pattern=r"^/[A-Za-z0-9/_\-?=&.]*$")


@router.post("/start", summary="Начать вход или связку через ФСП ID: ссылка на страницу входа Keycloak",
             responses={401: err("Для связки нужен вход кандидата"), 409: err("ФСП ID не настроен на сервере")})
def start(data: StartIn, token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> dict:
    if not get_isettings().fsp_enabled:
        raise api_error(409, "fsp_id_disabled", "Вход через ФСП ID на этом сервере не настроен")
    user = _optional_user(token, db)
    if data.intent == "link" and (user is None or user.role != UserRole.candidate):
        raise api_error(401, "candidate_required", "Чтобы связать ФСП ID, войдите как кандидат")
    verifier, challenge = oidc.pkce_pair()
    st = OidcLoginState(state=secrets.token_urlsafe(32), nonce=secrets.token_urlsafe(24), code_verifier=verifier,
                        intent=data.intent, user_id=user.id if data.intent == "link" else None,
                        return_to=data.return_to)
    db.add(st)
    db.commit()
    return {"authorize_url": oidc.authorize_url(st.state, st.nonce, challenge, prompt_login=data.intent == "link"),
            "state": st.state}


def _done(**q) -> RedirectResponse:
    from urllib.parse import urlencode

    return RedirectResponse("/fsp-id/done?" + urlencode(q), status_code=303)


@router.get("/callback", summary="Возврат из Keycloak: обмен кода, проверка id_token, одноразовый билет",
            include_in_schema=True, response_class=RedirectResponse)
def callback(state: str | None = None, code: str | None = None, error: str | None = None,
             error_description: str | None = None, db: Session = Depends(get_db)) -> RedirectResponse:
    st = db.scalar(select(OidcLoginState).where(OidcLoginState.state == (state or "")))
    if st is None or st.consumed_at is not None or as_aware(st.created_at) + STATE_TTL < utcnow():
        return _done(error="Сеанс входа устарел — начните заново")
    st.consumed_at = utcnow()
    if error or not code:
        st.error = (error_description or error or "нет кода")[:255]
        db.commit()
        return _done(error="Вход через ФСП ID отменён" if error == "access_denied" else f"ФСП ID: {st.error}")
    try:
        tok = oidc.exchange_code(code, st.code_verifier)
        claims = oidc.verify_id_token(tok["id_token"], st.nonce)
        # Атрибуты паспорта могут прийти только в userinfo (зависит от настроек клиента) — объединяем
        info = oidc.userinfo(tok.get("access_token", ""))
        if info.get("sub") == claims["sub"]:
            claims = {**info, **claims}
    except (oidc.OidcError, KeyError) as e:
        st.error = str(e)[:255]
        db.commit()
        log.warning("fsp-id callback: %s", st.error)
        return _done(error=str(e))
    keep = {k: claims.get(k) for k in ("sub", "iss", "email", "email_verified", "preferred_username", "fsp_id",
                                       "fsp_rank", "fsp_disciplines", "fsp_achievements")}
    linked = db.scalar(select(User).where(User.fsp_subject == claims["sub"]))
    if st.intent == "link":
        if linked is not None and linked.id != st.user_id:
            st.error = "sub уже связан с другой учётной записью"
            db.commit()
            return _done(error="Этот ФСП ID уже связан с другой учётной записью платформы")
        u = db.get(User, st.user_id)
        u.fsp_subject = claims["sub"]
        apply_claims(db, u.id, keep)
        st.result_user_id = u.id
    elif linked is not None:
        if linked.role == UserRole.candidate:
            apply_claims(db, linked.id, keep)
        st.result_user_id = linked.id
    st.claims = keep
    st.ticket = secrets.token_urlsafe(32)
    st.ticket_expires_at = utcnow() + TICKET_TTL
    db.commit()
    return _done(ticket=st.ticket, intent=st.intent)


def _ticket(db: Session, ticket: str) -> OidcLoginState:
    st = db.scalar(select(OidcLoginState).where(OidcLoginState.ticket == ticket))
    if st is None or st.ticket_expires_at is None or as_aware(st.ticket_expires_at) < utcnow():
        raise api_error(400, "ticket_invalid", "Билет входа недействителен или истёк — войдите ещё раз")
    return st


class TicketIn(BaseModel):
    ticket: str = Field(min_length=10, max_length=64)


@router.post("/exchange", summary="Обменять одноразовый билет на JWT платформы (или запросить согласие нового пользователя)",
             responses={400: err("Билет недействителен")})
def exchange(data: TicketIn, db: Session = Depends(get_db)) -> dict:
    st = _ticket(db, data.ticket)
    if st.result_user_id:
        u = db.get(User, st.result_user_id)
        st.ticket_expires_at = utcnow()  # одноразовый
        u.last_login_at = utcnow()
        db.commit()
        out = issue_token(u).model_dump(mode="json")
        return {"status": "ok", "intent": st.intent, "token": out, "passport": passport_preview(st.claims or {})}
    email = (st.claims or {}).get("email")
    taken = bool(email and db.scalar(select(User.id).where(User.email == email.lower())))
    return {"status": "consent_required", "passport": passport_preview(st.claims or {}), "email_taken": taken}


class CompleteIn(TicketIn):
    consent_processing: bool
    consent_publication: bool = False


@router.post("/complete", summary="Новый пользователь ФСП ID: согласие 152-ФЗ → учётная запись кандидата → JWT",
             responses={400: err("Билет недействителен"), 409: err("Почта уже занята"),
                        422: err("Нужно согласие на обработку ПДн")})
def complete(data: CompleteIn, db: Session = Depends(get_db)) -> dict:
    st = _ticket(db, data.ticket)
    if st.result_user_id:
        return exchange(TicketIn(ticket=data.ticket), db)
    if not data.consent_processing:
        raise api_error(422, "consent_required", "Нужно согласие на обработку персональных данных")
    c = st.claims or {}
    email = (c.get("email") or f"{c['sub'][:12]}@users.fsp-id.invalid").lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise api_error(409, "email_taken", "Учётная запись с этой почтой уже есть: войдите паролем и свяжите "
                                            "ФСП ID в разделе «Паспорт ФСП»")
    u = User(email=email, password_hash=hash_password(secrets.token_urlsafe(32)), role=UserRole.candidate,
             is_email_verified=bool(c.get("email_verified")), email_verified_at=utcnow(),
             fsp_subject=c["sub"], last_login_at=utcnow())
    db.add(u)
    db.flush()
    db.add(Consent(user_id=u.id, kind=ConsentKind.processing, document_version=CONSENT_VERSION))
    if data.consent_publication:
        db.add(Consent(user_id=u.id, kind=ConsentKind.publication, document_version=CONSENT_VERSION))
    db.add(CandidateProfile(user_id=u.id, public_ref=new_public_ref(db),
                            visible_to_employers=data.consent_publication))
    db.flush()
    apply_claims(db, u.id, c)
    st.result_user_id = u.id
    st.ticket_expires_at = utcnow()
    db.commit()
    return {"status": "ok", "intent": "login", "created": True, "token": issue_token(u).model_dump(mode="json"),
            "passport": passport_preview(c)}
