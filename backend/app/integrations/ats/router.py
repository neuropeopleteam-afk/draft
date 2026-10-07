"""API ATS для работодателя: провайдеры (Хантфлоу, Talantix, «Поток») и вебхук — настройки, проверка подключения,
вакансии и этапы из ATS, журнал передач с повтором, ручная передача, экспорт JSON, ссылка на PDF-профиль."""
from __future__ import annotations

import json
from typing import Literal
import secrets
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.db import get_db, utcnow
from app.core.deps import require_role
from app.core.enums import InvitationStatus, UserRole
from app.core.errors import api_error, err
from app.core.ratelimit import SlidingWindow, hit
from app.integrations.ats import profile as prof
from app.integrations.ats import providers
from app.integrations.ats import service as svc
from app.integrations.ats import stub_providers as stub
from app.integrations.ats.demo import connect_demo, connect_demo_all, reset_links, stub_huntflow_webhook
from app.integrations.ats.clients import AtsError, check_url
from app.integrations.ats import stages
from app.integrations.ats.models import AtsConnection, AtsDelivery, AtsLink, AtsSettings, AtsStageEvent, AtsStubRecord
from app.integrations.ats.providers.talantix import parse_tokens
from app.integrations.crypto import decrypt, encrypt, mask
from app.integrations.settings import get_isettings
from app.integrations.vacancies.models import Vacancy, VacancyApplication
from app.modules.auth.models import User
from app.modules.invitations.models import Invitation
from app.modules.matching.router import my_company

router = APIRouter(prefix="/api/employer/ats", tags=["ats"])
export_router = APIRouter(prefix="/api/employer", tags=["ats"])
public_router = APIRouter(prefix="/api/ats", tags=["ats"])
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
    if not decrypt(st.huntflow_token_enc):
        raise api_error(422, "huntflow_incomplete", "Сначала сохраните токен Хантфлоу")
    try:
        return providers.make(db, st.company_id, "huntflow").check()
    except AtsError as e:
        raise api_error(502, "huntflow_error", str(e)) from None


@router.post("/stub/connect", summary="Подключить тестовую ATS-заглушку (Хантфлоу-совместимый API + вебхук) для демо",
             responses=AUTH)
def stub_connect(user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    st = svc.company_settings(db, my_company(db, user).id)
    stub_huntflow_webhook(st)
    db.commit()
    return settings_out(st)


@router.post("/demo/connect-all", summary="Демо: подключить все ATS-заглушки — Хантфлоу, Talantix, «Поток» и вебхук",
             responses=AUTH)
def demo_connect_all(user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    c = my_company(db, user)
    connect_demo_all(db, c.id)
    db.commit()
    return providers_list(db, c.id)


@router.get("/stub/records", summary="Тестовая ATS: что в неё пришло (Хантфлоу, Talantix, «Поток», вебхуки)",
            responses=AUTH)
def stub_records(user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    st = svc.company_settings(db, my_company(db, user).id)
    if not st.stub_key:
        return []
    rows = db.scalars(select(AtsStubRecord).where(AtsStubRecord.stub_key == st.stub_key,
                                                  AtsStubRecord.kind.notin_(stub.INTERNAL_KINDS))
                      .order_by(AtsStubRecord.created_at.desc()).limit(150)).all()
    return [{"id": str(r.id), "kind": r.kind, "system": stub.kind_system(r.kind), "external_id": r.external_id,
             "signature_valid": r.signature_valid, "payload": r.payload, "created_at": r.created_at.isoformat()}
            for r in rows]


# ------------------------------------------------------------------ провайдеры

def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def provider_out(db: Session, company_id: uuid.UUID, code: str) -> dict:
    links = db.scalar(select(func.count()).select_from(AtsLink).where(
        AtsLink.company_id == company_id, AtsLink.provider == code, AtsLink.external_id.is_not(None))) or 0
    base = {"code": code, "title": providers.TITLES[code], "docs_url": providers.DOCS[code],
            "real_base_url": providers.real_base(code), "demo_base_url": providers.demo_base(code),
            "candidates_linked": links}
    if code == "huntflow":
        st = svc.company_settings(db, company_id)
        url = (st.huntflow_base_url or providers.real_base(code)).rstrip("/")
        return {**base, "enabled": st.huntflow_enabled, "mode": "demo" if url == providers.demo_base(code) else "real",
                "base_url": url, "token_set": bool(st.huntflow_token_enc),
                "token_masked": mask(decrypt(st.huntflow_token_enc)), "account_id": st.huntflow_account_id,
                "vacancy_id": st.huntflow_vacancy_id, "vacancy_title": None, "stage_id": st.huntflow_status_id,
                "stage_title": None, "vacancy_map": {}, "last_check_at": None, "last_check_ok": None,
                "last_check_info": {}}
    c = providers.connection(db, company_id, code)
    sec = providers.secrets_of(c)
    tok = sec.get("access_token") or sec.get("token")
    return {**base, "enabled": c.enabled, "mode": c.mode, "base_url": providers.base_url(c),
            "custom_base_url": c.base_url, "token_set": bool(tok), "token_masked": mask(tok),
            "refresh_set": bool(sec.get("refresh_token")), "token_expires_at": _iso(c.token_expires_at),
            "refresh_expires_at": _iso(c.refresh_expires_at), "token_refreshed_at": _iso(c.token_refreshed_at),
            "vacancy_id": c.vacancy_id, "vacancy_title": c.vacancy_title, "stage_id": c.stage_id,
            "stage_title": c.stage_title, "vacancy_map": c.vacancy_map or {}, "source_id": c.source_id,
            "last_check_at": _iso(c.last_check_at), "last_check_ok": c.last_check_ok,
            "last_check_info": c.last_check_info or {}}


def providers_list(db: Session, company_id: uuid.UUID) -> list[dict]:
    return [provider_out(db, company_id, code) for code in providers.PROVIDERS]


def _code(code: str) -> str:
    if code not in providers.PROVIDERS:
        raise api_error(404, "ats_provider_unknown", "Неизвестная ATS: доступны huntflow, talantix, potok")
    return code


@router.get("/providers", summary="ATS-провайдеры компании: режим, токены (маска), вакансия, последняя проверка",
            responses=AUTH)
def get_providers(user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    c = my_company(db, user)
    out = providers_list(db, c.id)
    db.commit()
    return out


class MapItem(BaseModel):
    id: int = Field(gt=0)
    title: str | None = Field(None, max_length=255)
    stage_id: int | None = Field(None, gt=0)
    stage_title: str | None = Field(None, max_length=255)


class ConnectionIn(BaseModel):
    enabled: bool = False
    mode: Literal["demo", "real"] = "real"
    base_url: str | None = Field(None, max_length=255, description="Свой адрес API (обычно пусто — официальный)")
    token: str | None = Field(None, max_length=8000, description="«Поток» — токен; Talantix — JSON со ссылки или "
                                                                 "access-токен. Пусто — оставить прежний")
    refresh_token: str | None = Field(None, max_length=4000, description="Talantix: refresh-токен (если не в JSON)")
    vacancy_id: int | None = Field(None, gt=0)
    vacancy_title: str | None = Field(None, max_length=255)
    stage_id: int | None = Field(None, gt=0)
    stage_title: str | None = Field(None, max_length=255)
    vacancy_map: dict[str, MapItem] = Field(default_factory=dict,
                                            description="Вакансия платформы (uuid) → вакансия и этап в ATS")


@router.put("/providers/{code}", summary="Сохранить подключение Talantix или «Потока» (токены шифруются)",
            responses={**AUTH, 404: err("Неизвестная ATS"), 422: err("Не хватает токена / некорректный адрес")})
def put_provider(code: str, data: ConnectionIn, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    if _code(code) == "huntflow":
        raise api_error(422, "use_settings", "Хантфлоу настраивается через PUT /api/employer/ats/settings")
    conn = providers.connection(db, c.id, code)
    custom = (data.base_url or "").strip().rstrip("/") or None
    if custom and data.mode == "real":
        try:
            check_url(custom)
        except AtsError as e:
            raise api_error(422, "ats_url_invalid", str(e)) from None
    new_base = custom if data.mode == "real" else None
    if conn.mode != data.mode or conn.base_url != new_base:
        reset_links(db, c.id, code)
        conn.secrets_enc, conn.token_expires_at, conn.refresh_expires_at, conn.source_id = None, None, None, None
        conn.last_check_at = conn.last_check_ok = None
        conn.last_check_info = {}
    conn.mode, conn.base_url = data.mode, new_base
    if data.mode == "demo" and not providers.secrets_of(conn):
        connect_demo(db, c.id, code)
    sec = providers.secrets_of(conn)
    if data.token and data.token.strip():
        if code == "potok":
            sec = {"token": data.token.strip()}
        else:
            try:
                t = parse_tokens(data.token, data.refresh_token)
            except AtsError as e:
                raise api_error(422, "talantix_tokens_invalid", str(e)) from None
            sec = {"access_token": t["access_token"], "refresh_token": t["refresh_token"]}
            conn.token_expires_at, conn.refresh_expires_at = t["expires_at"], t["refresh_expires_at"]
            conn.token_refreshed_at = None
    elif code == "talantix" and data.refresh_token and data.refresh_token.strip() and sec:
        sec["refresh_token"] = data.refresh_token.strip()
    providers.set_secrets(conn, sec)
    if data.enabled and not (sec.get("token") or sec.get("access_token")):
        raise api_error(422, f"{code}_incomplete", f"Для {providers.TITLES[code]} укажите токен")
    conn.enabled = data.enabled
    if data.mode != "demo" or data.vacancy_id:
        conn.vacancy_id, conn.vacancy_title = data.vacancy_id, data.vacancy_title if data.vacancy_id else None
        conn.stage_id, conn.stage_title = data.stage_id, data.stage_title if data.stage_id else None
    conn.vacancy_map = {k: v.model_dump() for k, v in data.vacancy_map.items()}
    db.commit()
    return provider_out(db, c.id, code)


@router.post("/providers/{code}/demo", summary="Демо-режим провайдера: заглушка, имитирующая API Talantix / «Потока»",
             responses={**AUTH, 404: err("Неизвестная ATS")})
def provider_demo(code: str, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    if _code(code) == "huntflow":
        stub_huntflow_webhook(svc.company_settings(db, c.id))
    else:
        connect_demo(db, c.id, code)
    db.commit()
    return provider_out(db, c.id, code)


def _provider_or_error(db: Session, company_id: uuid.UUID, code: str):
    try:
        return providers.make(db, company_id, code)
    except AtsError as e:
        raise api_error(422, f"{code}_incomplete", str(e)) from None


@router.post("/providers/{code}/check", summary="Проверить подключение: токен, владелец, число активных вакансий",
             responses={**AUTH, 404: err("Неизвестная ATS"), 502: err("ATS ответила ошибкой")})
def provider_check(code: str, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    pr = _provider_or_error(db, c.id, _code(code))
    conn = providers.connection(db, c.id, code) if code != "huntflow" else None
    try:
        res = pr.check()
    except AtsError as e:
        if conn is not None:
            conn.last_check_at, conn.last_check_ok, conn.last_check_info = utcnow(), False, {"error": str(e)}
            db.commit()
        raise api_error(502, f"{code}_error", str(e)) from None
    if conn is not None:
        conn.last_check_at, conn.last_check_ok = utcnow(), True
        conn.last_check_info = {k: res.get(k) for k in ("account", "vacancies_active", "details", "token_refreshed")}
        db.commit()
    return res


@router.get("/providers/{code}/vacancies", summary="Вакансии работодателя в ATS — для выбора, куда передавать",
            responses={**AUTH, 404: err("Неизвестная ATS"), 502: err("ATS ответила ошибкой")})
def provider_vacancies(code: str, user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    c = my_company(db, user)
    pr = _provider_or_error(db, c.id, _code(code))
    try:
        return pr.vacancies()
    except AtsError as e:
        raise api_error(502, f"{code}_error", str(e)) from None


@router.get("/providers/{code}/vacancies/{vacancy_id}/stages", summary="Этапы подбора вакансии в ATS",
            responses={**AUTH, 404: err("Неизвестная ATS"), 502: err("ATS ответила ошибкой")})
def provider_stages(code: str, vacancy_id: int, user: User = Depends(employer),
                    db: Session = Depends(get_db)) -> list[dict]:
    c = my_company(db, user)
    pr = _provider_or_error(db, c.id, _code(code))
    try:
        return pr.stages(vacancy_id)
    except AtsError as e:
        raise api_error(502, f"{code}_error", str(e)) from None


@router.get("/deliveries", summary="Журнал передач кандидатов в ATS", responses=AUTH)
def deliveries(user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    c = my_company(db, user)
    rows = db.scalars(select(AtsDelivery).where(AtsDelivery.company_id == c.id)
                      .order_by(AtsDelivery.created_at.desc()).limit(100)).all()
    return [svc.delivery_out(db, d) for d in rows]


class PushIn(BaseModel):
    invitation_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    target: str | None = Field(None, pattern="^(huntflow|talantix|potok|webhook)$")
    ats_vacancy_id: int | None = Field(None, gt=0, description="Вакансия в ATS (иначе — из настроек провайдера)")
    force: bool = Field(False, description="Передать повторно, даже если уже передано (дубликат кандидата в ATS "
                                           "всё равно не создаётся — обновляется комментарий/этап)")


def _already_sent(db: Session, company_id, data: PushIn, targets: set[str]) -> list[AtsDelivery]:
    """Последние успешные передачи этого кандидата по нужным адресатам — их не повторяем без force."""
    q = select(AtsDelivery).where(AtsDelivery.company_id == company_id, AtsDelivery.status == "ok")
    q = q.where(AtsDelivery.invitation_id == data.invitation_id) if data.invitation_id \
        else q.where(AtsDelivery.application_id == data.application_id)
    latest: dict[str, AtsDelivery] = {}
    for d in db.scalars(q.order_by(AtsDelivery.created_at.desc())):
        latest.setdefault(d.target, d)
    return [latest[t] for t in sorted(targets) if t in latest]


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
    enabled = providers.enabled_targets(db, c.id, st)
    if not enabled:
        raise api_error(409, "ats_not_configured", "Подключите ATS (Хантфлоу, Talantix, «Поток») или вебхук")
    want = {data.target} & set(enabled) if data.target else set(enabled)
    if not want:
        raise api_error(409, "ats_not_configured", f"{svc.TARGET_TITLES.get(data.target)} не подключена")
    if data.invitation_id:
        _own_invitation(db, c.id, data.invitation_id)
    elif data.application_id:
        _own_application(db, c.id, data.application_id)
    else:
        raise api_error(422, "target_required", "Укажите приглашение или отклик")
    done: list[AtsDelivery] = []
    if not data.force and not data.ats_vacancy_id:  # другая вакансия в ATS — явный запрос, не повтор
        done = _already_sent(db, c.id, data, want)
        want -= {d.target for d in done}
        if not want:
            return [{**svc.delivery_out(db, d), "already_sent": True} for d in done]
    rows = svc.deliver(db, c.id, invitation_id=data.invitation_id, application_id=data.application_id,
                       trigger="manual", only=want, vacancy_override=data.ats_vacancy_id, force=data.force)
    return [{**svc.delivery_out(db, d), "already_sent": True} for d in done] + [svc.delivery_out(db, d) for d in rows]


@router.post("/deliveries/{delivery_id}/retry", summary="Повторить передачу из журнала (дубликат не создаётся)",
             responses={**AUTH, 404: err("Запись не найдена"), 409: err("ATS отключена")})
def retry_delivery(delivery_id: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    c = my_company(db, user)
    d = db.get(AtsDelivery, delivery_id)
    if d is None or d.company_id != c.id:
        raise api_error(404, "delivery_not_found", "Запись журнала не найдена")
    if d.target not in providers.enabled_targets(db, c.id, svc.company_settings(db, c.id)):
        raise api_error(409, "ats_not_configured", f"{svc.TARGET_TITLES.get(d.target)} сейчас отключена")
    if d.invitation_id:
        _own_invitation(db, c.id, d.invitation_id)
    elif d.application_id:
        _own_application(db, c.id, d.application_id)
    rows = svc.deliver(db, c.id, invitation_id=d.invitation_id, application_id=d.application_id, trigger="retry",
                       only=d.target)
    return [svc.delivery_out(db, x) for x in rows]


# ------------------------------------------------------------------ обратный канал: этапы из ATS («Поток»)

_stage_sync_rl = SlidingWindow(12, 60)


def _stage_refs(db: Session, rows) -> dict:
    from app.modules.profiles.models import CandidateProfile

    ids = {e.candidate_user_id for e in rows if e.candidate_user_id}
    return {p.user_id: p.public_ref for p in db.scalars(select(CandidateProfile)
                                                         .where(CandidateProfile.user_id.in_(ids)))} if ids else {}


@router.get("/stages", summary="Обратный канал: последний опрос этапов в ATS и журнал изменений",
            responses=AUTH)
def stage_journal(user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    rows = db.scalars(select(AtsStageEvent).where(AtsStageEvent.company_id == c.id)
                      .order_by(AtsStageEvent.created_at.desc()).limit(100)).all()
    refs = _stage_refs(db, rows)
    out = {"poll_s": get_isettings().ats_stage_poll_s, "providers": [], "events": [stages.event_out(e, refs)
                                                                                   for e in rows]}
    for code in stages.PROVIDERS_WITH_STAGES:
        conn = db.get(AtsConnection, (c.id, code))
        out["providers"].append({"code": code, "title": providers.TITLES[code], "enabled": bool(conn and conn.enabled),
                                 "mode": conn.mode if conn else None,
                                 "synced_at": _iso(conn.stages_synced_at) if conn else None,
                                 "info": (conn.stages_sync_info or {}) if conn else {},
                                 "linked": db.scalar(select(func.count()).select_from(AtsLink).where(
                                     AtsLink.company_id == c.id, AtsLink.provider == code,
                                     AtsLink.external_id.is_not(None))) or 0})
    return out


@router.post("/stages/sync", summary="Обратный канал: опросить этапы кандидатов в ATS сейчас",
             responses={**AUTH, 422: err("ATS не подключена"), 429: err("Слишком часто")})
def stage_sync(code: str = "potok", user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    hit(_stage_sync_rl, str(c.id), "too_many_requests", "Этапы обновляются не чаще 12 раз в минуту")
    try:
        return stages.sync_company(db, c.id, _code(code), trigger="manual")
    except AtsError as e:
        raise api_error(422, "ats_not_configured", str(e)) from None


@router.get("/stub/potok/pipeline", summary="Демо-«Поток»: кандидаты на вакансиях и этапы — как видит рекрутёр",
            responses=AUTH)
def stub_potok_pipeline(user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    st = svc.company_settings(db, my_company(db, user).id)
    return stub.potok_demo_pipeline(db, st.stub_key) if st.stub_key else []


class StubMoveIn(BaseModel):
    join_id: int
    stage_id: int | None = None
    decline: bool = False


@router.post("/stub/potok/move", summary="Демо-«Поток»: рекрутёр переводит кандидата на этап или отклоняет",
             responses={**AUTH, 404: err("Кандидата нет в демо-«Потоке»"), 409: err("«Поток» не в демо-режиме")})
def stub_potok_move(data: StubMoveIn, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    conn = db.get(AtsConnection, (c.id, "potok"))
    st = svc.company_settings(db, c.id)
    if conn is None or conn.mode != "demo" or not st.stub_key:
        raise api_error(409, "not_demo", "Двигать кандидатов здесь можно только в демо-«Потоке»; в настоящем — в его "
                                         "интерфейсе, платформа узнает при опросе")
    r = stub.potok_demo_move(db, st.stub_key, data.join_id, stage_id=data.stage_id, decline=data.decline)
    if r is None:
        raise api_error(404, "not_found", "Кандидата или этапа нет в демо-«Потоке»")
    return {"moved": r, "pipeline": stub.potok_demo_pipeline(db, st.stub_key)}


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


@public_router.get("/profile/{token}.pdf", summary="PDF-профиль кандидата по подписанной ссылке из карточки в ATS",
                   responses={404: err("Ссылка недействительна или истекла"), 200: {"content": {"application/pdf": {}}}},
                   response_class=Response)
def ats_profile_pdf(token: str, db: Session = Depends(get_db)) -> Response:
    """Ссылка подписана (JWT, 180 дней) и привязана к компании и кандидату: открывается из Talantix / «Потока»
    без входа на платформу. Контакты — только если они раскрыты этой компании (приглашение принято / отклик)."""
    from app.modules.catalog.models import Category
    from app.modules.invitations.service import candidate_contacts, contacts_revealed
    from app.modules.pdf.profile_pdf import render_profile
    from app.modules.profiles.facts import card, load_bundles
    from app.modules.profiles.models import CandidateProfile

    ids = prof.read_pdf_token(token)
    if ids is None:
        raise api_error(404, "pdf_link_invalid", "Ссылка на профиль недействительна или истекла")
    try:
        company_id, cand_id = uuid.UUID(ids[0]), uuid.UUID(ids[1])
    except ValueError:
        raise api_error(404, "pdf_link_invalid", "Ссылка на профиль недействительна или истекла") from None
    cp = db.get(CandidateProfile, cand_id)
    bundles = load_bundles(db, [cand_id]) if cp is not None else {}
    if cp is None or cand_id not in bundles:
        raise api_error(404, "pdf_link_invalid", "Кандидат не найден")
    cats = {x.id: x for x in db.scalars(select(Category)).all()}
    revealed = contacts_revealed(db, company_id, cand_id) or _applied(db, company_id, cand_id)
    contacts = candidate_contacts(db, cand_id) if revealed else None
    pdf = render_profile(card(bundles[cand_id], cats), contacts=contacts, audience="employer")
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="profile-{cp.public_ref}.pdf"',
                             "Cache-Control": "private, max-age=300"})


def _applied(db: Session, company_id: uuid.UUID, cand_id: uuid.UUID) -> bool:
    """Кандидат сам откликнулся на вакансию компании — контакты раскрыты им самим."""
    return db.scalar(select(func.count()).select_from(VacancyApplication)
                     .join(Vacancy, Vacancy.id == VacancyApplication.vacancy_id)
                     .where(Vacancy.company_id == company_id, VacancyApplication.candidate_user_id == cand_id,
                            VacancyApplication.status != "withdrawn")) > 0
