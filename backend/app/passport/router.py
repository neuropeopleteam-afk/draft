"""API паспорта грейда.

Публично (без входа; на стенде — и без пароля nginx, infra/nginx/fsp.neuropeople.pro.passport.conf):
    GET  /api/passport/keys          открытые ключи JWKS (ротация по kid)
    GET  /api/passport/{id}          подписанный паспорт + статус по реестру
    GET  /api/passport/{id}/qr.svg   QR-код ссылки /verify/{id}
    POST /api/passport/verify        проверка присланного файла паспорта (подпись, совпадение с реестром)
    GET  /.well-known/jwks.json      те же ключи JWKS по стандартному адресу
                                     (и /api/.well-known/jwks.json — за прокси /api)
    GET  /api/passport/{id}/offline.json  файл для офлайн-проверки: паспорт + подпись + открытый ключ JWKS
Демо жюри (KF1 «Паспорт-щит», только при JURY_MODE_AVAILABLE): GET /api/passport/demo — паспорт демо-кандидата
(выпускается при первом запросе), POST /api/passport/demo/revoke и /demo/reissue — показ отзыва и нового выпуска.
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
from app.core.config import get_settings
from app.core.deps import get_current_user, require_role
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
_demo_rate = SlidingWindow(60, 60)  # GET /demo: выпуск при первом запросе — тоже с лимитом


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
        forms = [f.decode("utf-8") for f in crypto.canonical_forms(data.passport)]
    except (TypeError, ValueError):
        raise api_error(422, "passport_invalid", "Файл не похож на паспорт: неверный JSON") from None
    # канон; если не сошлось — канон первых паспортов (до замены 1.0 → 1)
    document, sig = forms[0], service.verify_document(db, forms[0], value, kid)
    for alt in forms[1:]:
        if not sig["signature_valid"] and (alt_sig := service.verify_document(db, alt, value, kid))["signature_valid"]:
            document, sig = alt, alt_sig
    pid = data.passport.get("id")
    reg = db.get(GradePassport, pid) if isinstance(pid, str) and 8 <= len(pid) <= 32 else None
    registry = service.evaluate(db, reg) if reg is not None else None
    same = bool(reg is not None and reg.document == document and reg.signature == value)
    state = "invalid_signature" if not sig["signature_valid"] else (registry["state"] if registry and same else
                                                                     "not_in_registry" if reg is None else "differs")
    return {**sig, "state": state, "registry": registry, "matches_registry": same,
            "kid_note": None if sig["kid_known"] else "Ключ с таким kid нам неизвестен"}


@router.get("/.well-known/jwks.json", summary="Открытые ключи подписи паспортов по стандартному адресу JWKS",
            include_in_schema=False)
@router.get("/api/.well-known/jwks.json", summary="Открытые ключи подписи паспортов (JWKS) — адрес за прокси /api")
def well_known_jwks(db: Session = Depends(get_db)) -> Response:
    import json

    body = {"keys": list(service.known_keys(db).values()), "alg": crypto.ALG, "schema": crypto.SCHEMA}
    return Response(json.dumps(body, ensure_ascii=False), media_type="application/jwk-set+json",
                    headers={"Cache-Control": "public, max-age=300", "Access-Control-Allow-Origin": "*"})


# ------------------------------------------------------------------ демо жюри (KF1 «Паспорт-щит»)

def _demo_available() -> None:
    if not get_settings().jury_mode_available:
        raise api_error(404, "jury_disabled", "Режим жюри выключен")


def _demo_sid(scenario: str | None) -> str:
    from app.modules.jury import scope

    sid = (scenario or "").strip().lower()
    if sid in ("", scope.SHARED):
        return ""
    if not scope.SID_RE.match(sid):
        raise api_error(422, "scenario_invalid", "Неверный идентификатор песочницы жюри")
    return sid


def _demo_user(db: Session, sid: str):
    uid = service.demo_user_id(db, sid)
    if uid is None:
        raise api_error(404, "demo_not_ready", "Демо-кандидат ещё не создан: войдите в режим жюри на главной")
    return uid


def _jury_sid(user: User) -> str:
    from app.modules.jury import scope

    persona, sid = scope.parse(user.email)
    if persona is None:
        raise api_error(403, "jury_only", "Только для демо-персон жюри")
    return sid or ""


DEMO_ERR = {404: err("Режим жюри выключен или демо-кандидат не создан"), 422: err("Неверный идентификатор песочницы")}


@router.get("/api/passport/demo", summary="Демо жюри: паспорт демо-кандидата (QR, kid, ссылка на проверку)",
            description="Паспорт кандидата «Мария Королёва» общего демо или песочницы scenario; выпускается при первом "
                        "запросе. Только при включённом режиме жюри.",
            responses={**DEMO_ERR, 429: err("Слишком много запросов")})
def demo_passport(request: Request, scenario: str | None = None, db: Session = Depends(get_db)) -> dict:
    _demo_available()
    hit(_demo_rate, client_ip(request), "passport_demo_rate", "Слишком много запросов демо-паспорта")
    return service.demo_view(db, _demo_user(db, _demo_sid(scenario)))


@router.post("/api/passport/demo/revoke", summary="Демо жюри: отозвать паспорт демо-кандидата своей песочницы",
             responses={**DEMO_ERR, 401: err("Не выполнен вход"), 403: err("Только для демо-персон жюри")})
def demo_revoke(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    _demo_available()
    uid = _demo_user(db, _jury_sid(user))
    if service.active(db, uid) is not None:
        service.candidate_revoke(db, uid)
        db.commit()
    return service.demo_view(db, uid)


@router.post("/api/passport/demo/reissue", summary="Демо жюри: выпустить паспорт демо-кандидата заново (новая ссылка)",
             responses={**DEMO_ERR, 401: err("Не выполнен вход"), 403: err("Только для демо-персон жюри"),
                        409: err("Категории ещё нет")})
def demo_reissue(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    _demo_available()
    uid = _demo_user(db, _jury_sid(user))
    service.candidate_reissue(db, uid)
    db.commit()
    return service.demo_view(db, uid)


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


@router.get("/api/passport/{pid}/offline.json", responses=NOT_FOUND,
            summary="Файл для офлайн-проверки: паспорт, подпись и открытый ключ JWKS")
def passport_offline(pid: str, db: Session = Depends(get_db)) -> Response:
    import json

    p = _get(db, pid)
    return Response(json.dumps(service.offline_bundle(db, p), ensure_ascii=False, indent=2),
                    media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="passport-{p.id}.json"',
                             "Cache-Control": "no-store"})


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
    reason: Literal["integrity_annulled", "appeal_revoked", "admin"] = "admin"


@router.post("/api/admin/passports/{pid}/revoke", summary="Отозвать паспорт решением администратора "
             "(аннулирование результата по проверке достоверности)",
             responses={401: err("Не выполнен вход"), 403: err("Только для администратора"), **NOT_FOUND})
def admin_revoke(pid: str, data: RevokeIn, user: User = Depends(admin), db: Session = Depends(get_db)) -> dict:
    p = _get(db, pid)
    if p.revoked_at is None:
        service._revoke(p, data.reason)
        db.commit()
    return service.evaluate(db, p)
