"""Демо-подключение ATS для компании: заглушки Хантфлоу, Talantix, «Потока» и вебхука (без реальных токенов).

Используется кнопками в разделе «Интеграция с ATS» и сидом жюри — у демо-компании все системы подключены, и
принятие приглашения Ильёй Сергеевым сразу видно в журнале передач и во «входящих» тестовой ATS.
"""
from __future__ import annotations

import json
import secrets
import uuid

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.integrations.ats import providers
from app.integrations.ats import service as svc
from app.integrations.ats import stub_providers as stub
from app.integrations.ats.models import AtsConnection, AtsLink, AtsSettings
from app.integrations.ats.providers.talantix import parse_tokens
from app.integrations.crypto import encrypt
from app.integrations.settings import get_isettings


def reset_links(db: Session, company_id: uuid.UUID, code: str) -> None:
    """Сменилась система (демо ↔ реальная или другой адрес) — прежние id кандидатов там недействительны."""
    db.execute(delete(AtsLink).where(AtsLink.company_id == company_id, AtsLink.provider == code))


def stub_huntflow_webhook(st: AtsSettings) -> None:
    """Хантфлоу-совместимая заглушка и приёмник вебхука с подписью (ящик компании — stub_key)."""
    st.stub_key = st.stub_key or secrets.token_urlsafe(24)
    base = get_isettings().stub_public_base
    st.huntflow_enabled, st.huntflow_base_url = True, f"{base}/api/ats-stub/huntflow/v2"
    st.huntflow_account_id, st.huntflow_vacancy_id, st.huntflow_status_id = 1, 101, None
    st.huntflow_token_enc = encrypt(st.stub_key)
    st.webhook_enabled, st.webhook_url = True, f"{base}/api/ats-stub/webhook/{st.stub_key}"
    if not st.webhook_secret_enc:
        st.webhook_secret_enc = encrypt(secrets.token_urlsafe(32))
    st.auto_push = True


def connect_demo(db: Session, company_id: uuid.UUID, code: str) -> AtsConnection:
    """Демо-режим Talantix / «Потока»: токены выдаёт заглушка, имитирующая их API по настоящему HTTP."""
    st = svc.company_settings(db, company_id)
    st.stub_key = st.stub_key or secrets.token_urlsafe(24)
    conn = providers.connection(db, company_id, code)
    if conn.mode != "demo" or conn.base_url:
        reset_links(db, company_id, code)
    conn.mode, conn.base_url, conn.enabled = "demo", None, True
    if code == "talantix":
        tok = stub.talantix_issue(db, st.stub_key)
        parsed = parse_tokens(json.dumps(tok))
        providers.set_secrets(conn, {"access_token": parsed["access_token"], "refresh_token": parsed["refresh_token"]})
        conn.token_expires_at, conn.refresh_expires_at = parsed["expires_at"], parsed["refresh_expires_at"]
        conn.token_refreshed_at, conn.source_id = None, None
    else:
        providers.set_secrets(conn, {"token": stub.potok_token(st.stub_key)})
    v = stub.DEMO_VACANCIES[0]
    conn.vacancy_id, conn.vacancy_title = v["id"], v["title"]
    conn.stage_id = conn.stage_title = None
    conn.vacancy_map = {}
    st.auto_push = True
    db.flush()
    return conn


def connect_demo_all(db: Session, company_id: uuid.UUID) -> None:
    """Все демо-системы сразу: Хантфлоу, Talantix, «Поток» и вебхук."""
    st = svc.company_settings(db, company_id)
    stub_huntflow_webhook(st)
    for code in providers.CONNECTION_PROVIDERS:
        connect_demo(db, company_id, code)
