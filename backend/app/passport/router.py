"""API паспорта грейда.

Публично (без входа; на стенде — и без пароля nginx, infra/nginx/fsp.neuropeople.pro.passport.conf):
    GET  /api/passport/keys          открытые ключи JWKS (ротация по kid)
    GET  /api/passport/{id}          подписанный паспорт + статус по реестру
    GET  /api/passport/{id}/qr.svg   QR-код ссылки /verify/{id}
    POST /api/passport/verify        проверка присланного файла паспорта (подпись, совпадение с реестром)
Кандидат: GET /api/me/passport, POST /api/me/passport/revoke, POST /api/me/passport/reissue.
Работодатель: GET /api/employer/candidates/{ref}/passport. Администратор: POST /api/admin/passports/{id}/revoke.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.core.ratelimit import SlidingWindow, client_ip, hit
from app.modules.auth.models import User
from app.passport import crypto, service
from app.passport.models import GradePassport

TAGS = [{"name": "passport", "description": "Подписанный паспорт грейда (Ed25519): публичная проверка, ключи, отзыв"}]
router = APIRouter(tags=["passport"])
candidate = require_role(UserRole.candidate)
employer = require_role(UserRole.employer)
admin = require_role(UserRole.admin)
NOT_FOUND = {404: err("Паспорт не найден")}
_verify_rate = SlidingWindow(120, 60)  # POST /verify: проверка подписи дешёвая, но без лимита — лёгкая цель


def _get(db: Session, pid: str) -> GradePassport:
    p = db.get(GradePassport, pid) if 8 <= len(pid) <= 32 else None
    if p is None:
        raise api_error(404, "passport_not_found", "Паспорт не найден: проверьте ссылку")
    return p


# ------------------------------------------------------------------ публично

@router.get("/api/passport/keys", summary="Открытые ключи подписи паспортов (JWKS, ротация по kid)")
def keys(db: Session = Depends(get_db)) -> dict:
    return {"keys": list(service.known_keys(db).values()), "alg": crypto.ALG, "schema": crypto.SCHEMA}


class SignedIn(BaseModel):
    passport: dict = Field(description="Состав паспорта (поле passport из GET /api/passport/{id})")
    signature: dict = Field(description="{alg, kid, value}")


@router.post("/api/passport/verify", summary="Проверить файл паспорта: подпись по ключу kid и совпадение с реестром",
             responses={429: err("Слишком много проверок")})
def verify_file(data: SignedIn, request: Request, db: Session = Depends(get_db)) -> dict:
    hit(_verify_rate, client_ip(request), "passport_verify_rate", "Слишком много проверок паспорта")
    kid = str(data.signature.get("kid") or data.passport.get("kid") or "")
    value = str(data.signature.get("value") or "")
    try:
        document = crypto.canonical(data.passport).decode("utf-8")
    except (TypeError, ValueError):
        raise api_error(422, "passport_invalid", "Файл не похож на паспорт: неверный JSON") from None
    sig = service.verify_document(db, document, value, kid)
    pid = data.passport.get("id")
    reg = db.get(GradePassport, pid) if isinstance(pid, str) and 8 <= len(pid) <= 32 else None
    registry = service.evaluate(db, reg) if reg is not None else None
    same = bool(reg is not None and reg.document == document and reg.signature == value)
    state = "invalid_signature" if not sig["signature_valid"] else (registry["state"] if registry and same else
                                                                     "not_in_registry" if reg is None else "differs")
    return {**sig, "state": state, "registry": registry, "matches_registry": same,
            "kid_note": None if sig["kid_known"] else "Ключ с таким kid нам неизвестен"}


@router.get("/api/passport/{pid}", summary="Паспорт грейда: подписанный документ, подпись и статус по реестру",
            responses=NOT_FOUND)
def get_passport(pid: str, db: Session = Depends(get_db)) -> dict:
    return service.public_view(db, _get(db, pid))


@router.get("/api/passport/{pid}/qr.svg", summary="QR-код ссылки на публичную проверку паспорта", responses=NOT_FOUND,
            response_class=Response)
def passport_qr(pid: str, db: Session = Depends(get_db)) -> Response:
    from app.jury_live import qr

    p = _get(db, pid)
    return Response(qr.svg(service.verify_url(p.id)), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=3600"})


# ------------------------------------------------------------------ кандидат

AUTH_C = {401: err("Не выполнен вход"), 403: err("Только для кандидата")}


@router.get("/api/me/passport", summary="Мой паспорт грейда: действующий (выпускается, если положен) и история",
            responses=AUTH_C)
def my_passport(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    p = service.ensure_current(db, user.id)
    db.commit()
    return service.owner_view(db, p, user.id)


@router.post("/api/me/passport/revoke", summary="Отозвать ссылку на паспорт (страница проверки покажет «Отозван»)",
             responses={**AUTH_C, 404: err("Действующего паспорта нет")})
def revoke_mine(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    service.candidate_revoke(db, user.id)
    db.commit()
    return service.owner_view(db, None, user.id)


@router.post("/api/me/passport/reissue", summary="Выпустить паспорт с новой ссылкой (старая — «Отозван»)",
             responses={**AUTH_C, 409: err("Категории ещё нет")})
def reissue_mine(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    p = service.candidate_reissue(db, user.id)
    db.commit()
    return service.owner_view(db, p, user.id)


# ------------------------------------------------------------------ работодатель и администратор

@router.get("/api/employer/candidates/{ref}/passport", summary="Паспорт кандидата из карточки: ссылка и статус",
            responses={401: err("Не выполнен вход"), 403: err("Только для работодателя"),
                       404: err("Кандидат не найден или паспорт отозван")})
def candidate_passport(ref: str, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    from app.modules.invitations.service import profile_by_ref
    from app.modules.matching.router import my_company

    my_company(db, user)
    prof = profile_by_ref(db, ref)
    p = service.ensure_current(db, prof.user_id)
    db.commit()
    if p is None:
        raise api_error(404, "passport_not_found", "Кандидат отозвал ссылку на паспорт")
    return service.brief(db, p)


class RevokeIn(BaseModel):
    reason: Literal["integrity_annulled", "admin"] = "admin"


@router.post("/api/admin/passports/{pid}/revoke", summary="Отозвать паспорт решением администратора "
             "(аннулирование результата по проверке достоверности)",
             responses={401: err("Не выполнен вход"), 403: err("Только для администратора"), **NOT_FOUND})
def admin_revoke(pid: str, data: RevokeIn, user: User = Depends(admin), db: Session = Depends(get_db)) -> dict:
    p = _get(db, pid)
    if p.revoked_at is None:
        service._revoke(p, data.reason)
        db.commit()
    return service.evaluate(db, p)
