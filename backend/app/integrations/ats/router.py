"""API ATS для работодателя: настройки Хантфлоу и вебхука, проверка связи, журнал, ручная передача, экспорт JSON."""
from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.core.enums import InvitationStatus, UserRole
from app.core.errors import api_error, err
from app.integrations.ats import service as svc
from app.integrations.ats.clients import AtsError, HuntflowClient, check_url
from app.integrations.ats.models import AtsDelivery, AtsSettings, AtsStubRecord
from app.integrations.crypto import decrypt, encrypt, mask
from app.integrations.settings import get_isettings
from app.integrations.vacancies.models import Vacancy, VacancyApplication
from app.modules.auth.models import User
from app.modules.invitations.models import Invitation
from app.modules.matching.router import my_company

router = APIRouter(prefix="/api/employer/ats", tags=["ats"])
export_router = APIRouter(prefix="/api/employer", tags=["ats"])
employer = require_role(UserRole.employer)
AUTH = {401: err("Не выполнен вход"), 403: err("Только для работодателя"), 409: err("Нет профиля компании")}


def settings_out(st: AtsSettings) -> dict:
    stub_base = get_isettings().stub_base
    return {
        "auto_push": st.auto_push,
        "huntflow": {"enabled": st.huntflow_enabled, "base_url": st.huntflow_base_url
                     or get_isettings().huntflow_default_base_url, "account_id": st.huntflow_account_id,
                     "vacancy_id": st.huntflow_vacancy_id, "status_id": st.huntflow_status_id,
                     "token_set": bool(st.huntflow_token_enc), "token_masked": mask(decrypt(st.huntflow_token_enc))},
        "webhook": {"enabled": st.webhook_enabled, "url": st.webhook_url, "secret_set": bool(st.webhook_secret_enc),
                    "secret_masked": mask(decrypt(st.webhook_secret_enc)),
                    "signature_header": "X-Vstrechny-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, '<unix>.<body>')>"},
        "stub": {"connected": bool(st.stub_key), "huntflow_base_url": f"{stub_base}/api/ats-stub/huntflow/v2",
                 "webhook_url": f"{stub_base}/api/ats-stub/webhook/{st.stub_key}" if st.stub_key else None},
    }


@router.get("/settings", summary="Настройки ATS компании (токены маскируются)", responses=AUTH)
def get_settings_(user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    st = svc.company_settings(db, my_company(db, user).id)
    db.commit()
    return settings_out(st)


class HuntflowIn(BaseModel):
    enabled: bool = False
    base_url: str | None = Field(None, max_length=255)
    account_id: int | None = Field(None, gt=0)
    vacancy_id: int | None = Field(None, gt=0)
    status_id: int | None = Field(None, gt=0)
    token: str | None = Field(None, max_length=4000, description="Пусто — оставить прежний токен")


class WebhookIn(BaseModel):
    enabled: bool = False
    url: str | None = Field(None, max_length=500)
    secret: str | None = Field(None, min_length=16, max_length=200, description="Пусто — оставить прежний / сгенерировать")


class SettingsIn(BaseModel):
    auto_push: bool = True
    huntflow: HuntflowIn = HuntflowIn()
    webhook: WebhookIn = WebhookIn()


@router.put("/settings", summary="Сохранить настройки ATS (Хантфлоу: токен и id вакансии; вебхук: URL и секрет)",
            responses={**AUTH, 422: err("Некорректный адрес (нужен https, внешний хост)")})
def put_settings(data: SettingsIn, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    st = svc.company_settings(db, my_company(db, user).id)
    try:
        if data.huntflow.base_url:
            check_url(data.huntflow.base_url.rstrip("/"))
        if data.webhook.url:
            check_url(data.webhook.url)
    except AtsError as e:
        raise api_error(422, "ats_url_invalid", str(e)) from None
    st.auto_push = data.auto_push
    h = data.huntflow
    st.huntflow_enabled, st.huntflow_account_id = h.enabled, h.account_id
    st.huntflow_vacancy_id, st.huntflow_status_id = h.vacancy_id, h.status_id
    st.huntflow_base_url = (h.base_url or "").rstrip("/") or None
    if h.token:
        st.huntflow_token_enc = encrypt(h.token.strip())
    if h.enabled and not (st.huntflow_token_enc and st.huntflow_account_id):
        raise api_error(422, "huntflow_incomplete", "Для Хантфлоу укажите токен и id организации (account_id)")
    w = data.webhook
    st.webhook_enabled, st.webhook_url = w.enabled, w.url
    if w.secret:
        st.webhook_secret_enc = encrypt(w.secret)
    elif w.enabled and not st.webhook_secret_enc:
        st.webhook_secret_enc = encrypt(secrets.token_urlsafe(32))
    if w.enabled and not w.url:
        raise api_error(422, "webhook_incomplete", "Укажите адрес вебхука")
    db.commit()
    return settings_out(st)


@router.get("/webhook-secret", summary="Показать секрет вебхука (только владельцу настроек)", responses=AUTH)
def webhook_secret(user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    st = svc.company_settings(db, my_company(db, user).id)
    return {"secret": decrypt(st.webhook_secret_enc)}


@router.post("/huntflow/check", summary="Проверить связь с Хантфлоу: /me, /accounts, этапы подбора",
             responses={**AUTH, 502: err("Хантфлоу ответил ошибкой")})
def huntflow_check(user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    st = svc.company_settings(db, my_company(db, user).id)
    token = decrypt(st.huntflow_token_enc)
    if not token:
        raise api_error(422, "huntflow_incomplete", "Сначала сохраните токен Хантфлоу")
    try:
        cl = HuntflowClient(st.huntflow_base_url or get_isettings().huntflow_default_base_url, token)
        me = cl.me()
        accounts = cl.accounts()
        statuses = cl.statuses(st.huntflow_account_id) if st.huntflow_account_id else []
    except AtsError as e:
        raise api_error(502, "huntflow_error", str(e)) from None
    return {"ok": True, "me": {"id": me.get("id"), "name": me.get("name")},
            "accounts": [{"id": a.get("id"), "name": a.get("name")} for a in accounts],
            "statuses": [{"id": s.get("id"), "name": s.get("name"), "order": s.get("order")} for s in statuses]}


@router.post("/stub/connect", summary="Подключить тестовую ATS-заглушку (Хантфлоу-совместимый API + вебхук) для демо",
             responses=AUTH)
def stub_connect(user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    st = svc.company_settings(db, my_company(db, user).id)
    st.stub_key = st.stub_key or secrets.token_urlsafe(24)
    base = get_isettings().stub_base
    st.huntflow_enabled, st.huntflow_base_url = True, f"{base}/api/ats-stub/huntflow/v2"
    st.huntflow_account_id, st.huntflow_vacancy_id, st.huntflow_status_id = 1, 101, None
    st.huntflow_token_enc = encrypt(st.stub_key)
    st.webhook_enabled, st.webhook_url = True, f"{base}/api/ats-stub/webhook/{st.stub_key}"
    if not st.webhook_secret_enc:
        st.webhook_secret_enc = encrypt(secrets.token_urlsafe(32))
    st.auto_push = True
    db.commit()
    return settings_out(st)


@router.get("/stub/records", summary="Тестовая ATS: что в неё пришло (кандидаты и вебхуки)", responses=AUTH)
def stub_records(user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    st = svc.company_settings(db, my_company(db, user).id)
    if not st.stub_key:
        return []
    rows = db.scalars(select(AtsStubRecord).where(AtsStubRecord.stub_key == st.stub_key)
                      .order_by(AtsStubRecord.created_at.desc()).limit(100)).all()
    return [{"id": str(r.id), "kind": r.kind, "external_id": r.external_id, "signature_valid": r.signature_valid,
             "payload": r.payload, "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/deliveries", summary="Журнал передач кандидатов в ATS", responses=AUTH)
def deliveries(user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    c = my_company(db, user)
    rows = db.scalars(select(AtsDelivery).where(AtsDelivery.company_id == c.id)
                      .order_by(AtsDelivery.created_at.desc()).limit(100)).all()
    return [svc.delivery_out(db, d) for d in rows]


class PushIn(BaseModel):
    invitation_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    target: str | None = Field(None, pattern="^(huntflow|webhook)$")


def _own_invitation(db: Session, company_id, inv_id) -> Invitation:
    i = db.get(Invitation, inv_id)
    if i is None or i.company_id != company_id:
        raise api_error(404, "invitation_not_found", "Приглашение не найдено")
    if i.status != InvitationStatus.accepted:
        raise api_error(409, "not_accepted", "Передать в ATS можно только принятое приглашение — до этого контакты закрыты")
    return i


def _own_application(db: Session, company_id, app_id) -> VacancyApplication:
    a = db.get(VacancyApplication, app_id)
    v = db.get(Vacancy, a.vacancy_id) if a else None
    if a is None or v is None or v.company_id != company_id:
        raise api_error(404, "application_not_found", "Отклик не найден")
    if a.status == "withdrawn":
        raise api_error(409, "application_withdrawn", "Кандидат отозвал отклик")
    return a


@router.post("/push", summary="Передать кандидата в ATS вручную (принятое приглашение или отклик)",
             responses={**AUTH, 404: err("Не найдено"), 409: err("Контакты ещё не раскрыты или ATS не настроена")})
def push(data: PushIn, user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    c = my_company(db, user)
    st = svc.company_settings(db, c.id)
    if not (st.huntflow_enabled or st.webhook_enabled):
        raise api_error(409, "ats_not_configured", "Включите Хантфлоу или вебхук в настройках ATS")
    if data.invitation_id:
        _own_invitation(db, c.id, data.invitation_id)
        rows = svc.deliver(db, c.id, invitation_id=data.invitation_id, trigger="manual", only=data.target)
    elif data.application_id:
        _own_application(db, c.id, data.application_id)
        rows = svc.deliver(db, c.id, application_id=data.application_id, trigger="manual", only=data.target)
    else:
        raise api_error(422, "target_required", "Укажите приглашение или отклик")
    return [svc.delivery_out(db, d) for d in rows]


@export_router.get("/invitations/{inv_id}/export.json", summary="Экспорт карточки кандидата в JSON (после принятия)",
                   responses={**AUTH, 404: err("Приглашение не найдено"), 409: err("Приглашение не принято")})
def export_invitation(inv_id: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)):
    c = my_company(db, user)
    i = _own_invitation(db, c.id, inv_id)
    p = svc.export_payload(db, c, invitation=i)
    return JSONResponse(p, headers={"Content-Disposition": f'attachment; filename="candidate-{p["candidate"]["ref"]}.json"'})


@export_router.get("/applications/{app_id}/export.json", summary="Экспорт карточки откликнувшегося кандидата в JSON",
                   responses={**AUTH, 404: err("Отклик не найден")})
def export_application(app_id: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)):
    c = my_company(db, user)
    a = _own_application(db, c.id, app_id)
    p = svc.export_payload(db, c, application=a)
    return JSONResponse(p, headers={"Content-Disposition": f'attachment; filename="candidate-{p["candidate"]["ref"]}.json"'})
