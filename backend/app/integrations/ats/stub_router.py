"""Тестовая ATS-заглушка для демо: подмножество API Хантфлоу v2 и приёмник вебхуков с проверкой подписи.

Платформа обращается к ней по настоящему HTTP (через публичный адрес), как к внешней системе. Токен Bearer =
ключ ящика компании (выдаётся при подключении заглушки). Пришедшие записи видны работодателю в разделе «ATS».
"""
from __future__ import annotations

import itertools

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db, utcnow
from app.core.errors import api_error
from app.integrations.ats.clients import verify_signature
from app.integrations.ats.models import AtsSettings, AtsStubRecord
from app.integrations.crypto import decrypt

router = APIRouter(prefix="/api/ats-stub", tags=["ats-stub"])
STATUSES = [{"id": 11, "type": "user", "name": "Новые", "order": 1, "removed": None, "stay_duration": None},
            {"id": 12, "type": "user", "name": "Первичный контакт", "order": 2, "removed": None, "stay_duration": None},
            {"id": 13, "type": "user", "name": "Интервью", "order": 3, "removed": None, "stay_duration": None},
            {"id": 14, "type": "hired", "name": "Вышел на работу", "order": 4, "removed": None, "stay_duration": None}]
_ids = itertools.count(int(utcnow().timestamp()) % 100000 * 10)


def _key(authorization: str | None, db: Session) -> str:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token or db.scalar(select(AtsSettings.company_id).where(AtsSettings.stub_key == token)) is None:
        raise api_error(401, "invalid_token", "Тестовая ATS: неверный токен")
    return token


@router.get("/huntflow/v2/me", summary="Заглушка Хантфлоу: GET /me")
def me(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> dict:
    _key(authorization, db)
    return {"id": 1, "name": "Тестовая ATS (Хантфлоу-совместимая)", "position": "Рекрутер", "email": None,
            "phone": None, "locale": "ru_RU"}


@router.get("/huntflow/v2/accounts", summary="Заглушка Хантфлоу: GET /accounts")
def accounts(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> dict:
    _key(authorization, db)
    return {"items": [{"id": 1, "name": "Демо-организация", "nick": "demo", "member_type": "owner"}]}


@router.get("/huntflow/v2/accounts/{account_id}/vacancies/statuses", summary="Заглушка Хантфлоу: этапы подбора")
def statuses(account_id: int, authorization: str | None = Header(None), db: Session = Depends(get_db)) -> dict:
    _key(authorization, db)
    return {"items": STATUSES}


@router.get("/huntflow/v2/accounts/{account_id}/vacancies", summary="Заглушка Хантфлоу: вакансии организации")
def hf_vacancies(account_id: int, authorization: str | None = Header(None), db: Session = Depends(get_db)) -> dict:
    _key(authorization, db)
    return {"page": 1, "count": 3, "total_pages": 1, "total_items": 3,
            "items": [{"id": 101, "position": "Backend-разработчик (платежи)", "company": "Платёжная платформа",
                       "state": "OPEN", "money": "240 000 – 280 000 ₽"},
                      {"id": 102, "position": "Python-разработчик (интеграции)", "company": "Интеграции", "state": "OPEN"},
                      {"id": 103, "position": "Аналитик данных", "company": "Аналитика", "state": "CLOSED"}]}


@router.post("/huntflow/v2/accounts/{account_id}/applicants", summary="Заглушка Хантфлоу: создать кандидата")
async def create_applicant(account_id: int, request: Request, authorization: str | None = Header(None),
                           db: Session = Depends(get_db)) -> dict:
    key = _key(authorization, db)
    body = await request.json()
    if not body.get("first_name") or not body.get("last_name"):
        raise api_error(400, "validation_error", "first_name и last_name обязательны")
    aid = next(_ids)
    db.add(AtsStubRecord(stub_key=key, kind="huntflow_applicant", external_id=aid, payload=body))
    db.commit()
    return {**{k: body.get(k) for k in ("first_name", "last_name", "middle_name", "money", "phone", "email",
                                        "position", "company")}, "id": aid, "created": utcnow().isoformat(),
            "files": [], "doubles": [], "agreement": None, "external": [{"id": aid + 1, "auth_type": "NATIVE"}],
            "social": body.get("social") or []}


@router.post("/huntflow/v2/accounts/{account_id}/applicants/{applicant_id}/vacancy",
             summary="Заглушка Хантфлоу: закрепить кандидата на вакансии")
async def add_to_vacancy(account_id: int, applicant_id: int, request: Request,
                         authorization: str | None = Header(None), db: Session = Depends(get_db)) -> dict:
    key = _key(authorization, db)
    body = await request.json()
    if not body.get("vacancy") or not body.get("status"):
        raise api_error(400, "validation_error", "vacancy и status обязательны")
    lid = next(_ids)
    db.add(AtsStubRecord(stub_key=key, kind="huntflow_vacancy", external_id=applicant_id,
                         payload={**body, "status_name": next((s["name"] for s in STATUSES if s["id"] == body["status"]),
                                                              None), "link_id": lid}))
    db.commit()
    return {"id": lid, "changed": utcnow().isoformat(), "vacancy": body["vacancy"], "status": body["status"],
            "rejection_reason": None}


@router.post("/webhook/{stub_key}", summary="Заглушка: приёмник вебхука (проверяет подпись HMAC)")
async def webhook(stub_key: str, request: Request, x_vstrechny_signature: str | None = Header(None),
                  db: Session = Depends(get_db)) -> dict:
    st = db.scalar(select(AtsSettings).where(AtsSettings.stub_key == stub_key))
    if st is None:
        raise api_error(404, "inbox_not_found", "Нет такого ящика")
    raw = await request.body()
    if len(raw) > 512 * 1024:
        raise api_error(413, "too_large", "Слишком большое тело")
    valid = verify_signature(decrypt(st.webhook_secret_enc) or "", raw, x_vstrechny_signature)
    try:
        import json

        payload = json.loads(raw)
    except ValueError:
        payload = {"raw": raw[:500].decode(errors="replace")}
    n = db.scalar(select(func.count()).select_from(AtsStubRecord).where(AtsStubRecord.stub_key == stub_key)) or 0
    db.add(AtsStubRecord(stub_key=stub_key, kind="webhook", external_id=n + 1, payload=payload, signature_valid=valid))
    db.commit()
    if not valid:
        raise api_error(401, "bad_signature", "Подпись вебхука не прошла проверку")
    return {"received": True}
