"""ATS-провайдеры в общем интерфейсе (base.Provider): Хантфлоу, Talantix, «Поток».

Фабрика ``make(db, company_id, code)`` собирает провайдера из настроек компании: адрес (реальный API или
демо-заглушка), расшифрованные токены, колбэк сохранения новой пары токенов Talantix (refresh одноразовый).
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy.orm import Session

from app.core.db import as_aware, utcnow
from app.integrations.ats.clients import AtsError, HuntflowClient
from app.integrations.ats.models import PROVIDERS, AtsConnection, AtsSettings
from app.integrations.ats.providers.base import LinkState, Provider, Target  # noqa: F401
from app.integrations.ats.providers.huntflow import DOCS_URL as HUNTFLOW_DOCS
from app.integrations.ats.providers.huntflow import HuntflowProvider
from app.integrations.ats.providers.potok import DOCS_URL as POTOK_DOCS
from app.integrations.ats.providers.potok import PotokClient, PotokProvider
from app.integrations.ats.providers.talantix import DOCS_URL as TALANTIX_DOCS
from app.integrations.ats.providers.talantix import TalantixClient, TalantixProvider
from app.integrations.crypto import decrypt, encrypt
from app.integrations.settings import get_isettings

TITLES = {"huntflow": "Хантфлоу", "talantix": "Talantix", "potok": "Поток"}
DOCS = {"huntflow": HUNTFLOW_DOCS, "talantix": TALANTIX_DOCS, "potok": POTOK_DOCS}
CONNECTION_PROVIDERS = ("talantix", "potok")  # хранятся в ats_connections; Хантфлоу — в ats_settings


def real_base(code: str) -> str:
    s = get_isettings()
    return {"talantix": s.talantix_base_url, "potok": s.potok_base_url,
            "huntflow": s.huntflow_default_base_url}[code].rstrip("/")


def demo_base(code: str) -> str:
    stub = get_isettings().stub_public_base  # хранится и показывается публичный; вызов — clients.check_url
    return {"talantix": f"{stub}/api/ats-stub/talantix", "potok": f"{stub}/api/ats-stub/potok/api/v3",
            "huntflow": f"{stub}/api/ats-stub/huntflow/v2"}[code]


def secrets_of(conn: AtsConnection) -> dict:
    raw = decrypt(conn.secrets_enc)
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def set_secrets(conn: AtsConnection, data: dict) -> None:
    clean = {k: v for k, v in data.items() if v}
    conn.secrets_enc = encrypt(json.dumps(clean)) if clean else None


def connection(db: Session, company_id: uuid.UUID, code: str, *, create: bool = True) -> AtsConnection | None:
    if code not in CONNECTION_PROVIDERS:
        raise AtsError(f"Неизвестный провайдер {code}", 404)
    c = db.get(AtsConnection, (company_id, code))
    if c is None and create:
        c = AtsConnection(company_id=company_id, provider=code, enabled=False, mode="real", vacancy_map={},
                          last_check_info={})
        db.add(c)
        db.flush()
    return c


def base_url(conn: AtsConnection) -> str:
    return (conn.base_url or (demo_base(conn.provider) if conn.mode == "demo" else real_base(conn.provider))).rstrip("/")


def make(db: Session, company_id: uuid.UUID, code: str) -> Provider:
    """Провайдер компании. AtsError — если подключение не настроено (нет токена / организации)."""
    if code == "huntflow":
        st = db.get(AtsSettings, company_id)
        token = decrypt(st.huntflow_token_enc) if st else None
        if not token:
            raise AtsError("Хантфлоу: не задан токен", 422)
        return HuntflowProvider(HuntflowClient(st.huntflow_base_url or real_base("huntflow"), token),
                                st.huntflow_account_id)
    conn = connection(db, company_id, code, create=False)
    sec = secrets_of(conn) if conn else {}
    if code == "potok":
        if not sec.get("token"):
            raise AtsError("«Поток»: не задан токен", 422)
        return PotokProvider(PotokClient(base_url(conn), sec["token"]))
    if not sec.get("access_token"):
        raise AtsError("Talantix: не заданы токены", 422)

    def save_tokens(tok: dict) -> None:
        # refresh-токен одноразовый: новую пару фиксируем отдельной транзакцией сразу после ответа oauth/token
        set_secrets(conn, {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token")})
        conn.token_expires_at = tok.get("expires_at")
        conn.refresh_expires_at = tok.get("refresh_expires_at") or conn.refresh_expires_at
        conn.token_refreshed_at = utcnow()
        db.commit()

    def save_source(sid: int) -> None:
        conn.source_id = sid
        db.commit()

    cl = TalantixClient(base_url(conn), sec["access_token"], sec.get("refresh_token"), as_aware(conn.token_expires_at),
                        on_tokens=save_tokens)
    return TalantixProvider(cl, source_id=conn.source_id, on_source=save_source)


def enabled_targets(db: Session, company_id: uuid.UUID, st: AtsSettings | None) -> list[str]:
    out = []
    if st is not None and st.huntflow_enabled:
        out.append("huntflow")
    for code in CONNECTION_PROVIDERS:
        c = db.get(AtsConnection, (company_id, code))
        if c is not None and c.enabled:
            out.append(code)
    if st is not None and st.webhook_enabled:
        out.append("webhook")
    return out


__all__ = ["PROVIDERS", "TITLES", "DOCS", "make", "connection", "enabled_targets", "secrets_of", "set_secrets",
           "base_url", "demo_base", "real_base", "LinkState", "Target", "Provider"]
