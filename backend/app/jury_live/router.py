"""API живой демонстрации: /api/jury/live/...

Гость (телефон эксперта) — без регистрации и без входа на стенд: код зала из QR + токен гостя в заголовке
X-Guest-Token (выдаётся при старте мини-теста, хранится в браузере телефона). Экран зала — работодатель песочницы
жюри (JWT с полем jsc): общее демо и обычные работодатели залов не создают.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import as_aware, get_db, utcnow
from app.core.deps import require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.core.ratelimit import SlidingWindow, client_ip, hit
from app.integrations.events import invitation_answered
from app.integrations.push.router import SubscriptionIn
from app.integrations.settings import get_isettings
from app.jury_live import mini, qr
from app.jury_live import service as svc
from app.jury_live.models import LiveGuest, LiveRoom
from app.modules.auth.models import User
from app.modules.catalog.seed_data import DIRECTIONS
from app.modules.jury import scope
from app.modules.jury.seed import COMPANY

TAGS = [{"name": "jury-live", "description": "Живая демонстрация для жюри: QR → мини-тест на телефоне → "
                                             "экспресс-категория → подборка → автоприглашение с push"}]
router = APIRouter(prefix="/api/jury/live", tags=["jury-live"])

_s = get_settings()
_guest_ip = SlidingWindow(_s.jury_live_guests_per_ip_hour, 3600)
_guest_room = SlidingWindow(_s.jury_live_guests_per_room_hour, 3600)
_guest_all = SlidingWindow(_s.jury_live_guests_total_hour, 3600)
_push_ip = SlidingWindow(30, 3600)
HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$")
E_ROOM = {404: err("Зал не найден")}
E_GUEST = {**E_ROOM, 401: err("Токен гостя не найден")}


LOOPBACK = ("localhost", "127.0.0.1")
ORIGIN_RE = re.compile(r"^(https?)://([A-Za-z0-9.\-]+)(:\d{1,5})?$")


def origin(request: Request) -> str:
    """Адрес стенда, как его видит браузер: Host и X-Forwarded-Proto от nginx; иначе — PUBLIC_BASE_URL.
    Локально (прокси Vite меняет Host на адрес API) — origin страницы из параметра, только для loopback."""
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
    if not HOST_RE.match(host) or proto not in ("http", "https"):
        return get_settings().public_base_url.rstrip("/")
    hint = ORIGIN_RE.match(request.query_params.get("origin") or "")
    if hint and hint.group(2) in LOOPBACK and host.split(":")[0] in LOOPBACK:
        return hint.group(0)
    return f"{proto}://{host}"


def _room(db: Session, code: str) -> LiveRoom:
    room = svc.room_by_code(db, code)
    if room is None:
        raise api_error(404, "room_not_found", "Зал не найден: проверьте код или отсканируйте QR ещё раз")
    return room


def _push_cfg() -> dict:
    s = get_isettings()
    return {"enabled": bool(s.push_enabled and s.vapid_public_key), "vapid_public_key": s.vapid_public_key}


# ------------------------------------------------------------------ телефон гостя
@router.get("/j/{code}", summary="Зал по коду из QR: открыт ли, направления, правило приглашения", responses=E_ROOM)
def room_public(code: str, db: Session = Depends(get_db)) -> dict:
    room = _room(db, code)
    return {"code": room.code, "company": COMPANY, "open": svc.employer_of(db, room.sid) is not None,
            "items": mini.N_ITEMS, "rule": svc.RULE, "push": _push_cfg(),
            "directions": [{"id": d, "title": DIRECTIONS[d], "need": svc.NEED_TEXTS[d][0]} for d in mini.DIRECTIONS]}


class StartIn(BaseModel):
    direction: Literal["backend", "frontend", "data_ml", "qa", "security"]


@router.post("/j/{code}/start", status_code=201, summary="Начать мини-тест (гость без регистрации)",
             responses={**E_ROOM, 409: err("Зал закрыт или заполнен"), 429: err("Слишком много мини-тестов")})
def start(code: str, data: StartIn, request: Request, db: Session = Depends(get_db)) -> dict:
    room = _room(db, code)
    hit(_guest_ip, client_ip(request), "live_rate_limited", "С этого адреса уже начато много мини-тестов")
    hit(_guest_room, room.code, "live_rate_limited", "В этом зале уже начато много мини-тестов")
    hit(_guest_all, "all", "live_rate_limited", "Сейчас начато слишком много мини-тестов")
    g, token = svc.start_guest(db, room, data.direction)
    return {"token": token, "guest": svc.guest_out(db, g, now=utcnow(), own=True)}


@router.get("/j/{code}/me", summary="Мой мини-тест: текущее задание, итог, место в подборке, приглашение",
            responses=E_GUEST)
def me(code: str, visible: bool = Query(False, description="Страница на экране — отметить приглашение просмотренным"),
       x_guest_token: str | None = Header(None), db: Session = Depends(get_db)) -> dict:
    room = _room(db, code)
    g = svc.guest_by_token(db, room, x_guest_token)
    svc.catch_up(db, room, [g])
    if visible:
        svc.mark_viewed(db, room, g)
    g = db.get(LiveGuest, g.id)
    g.last_seen_at = utcnow()
    db.commit()
    return svc.guest_out(db, g, now=utcnow(), own=True)


class AnswerIn(BaseModel):
    token: str = Field(min_length=4, max_length=64, description="Токен задания из item.token")
    value: Any = Field(description="id варианта (A–D) или номер строки кода")


@router.post("/j/{code}/answer", summary="Ответ на текущее задание (правильность — только в итоге)",
             responses={**E_GUEST, 409: err("Тест завершён"), 422: err("Ответ не принят")})
def answer(code: str, data: AnswerIn, bg: BackgroundTasks, x_guest_token: str | None = Header(None),
           db: Session = Depends(get_db)) -> dict:
    room = _room(db, code)
    g = svc.guest_by_token(db, room, x_guest_token)
    for kind, gid in svc.answer(db, room, g, data.token, data.value):
        if kind == "push":
            bg.add_task(svc.push_later, gid, room.code)
    return svc.guest_out(db, db.get(LiveGuest, g.id), now=utcnow(), own=True)


@router.post("/j/{code}/push", status_code=201, summary="Подписать телефон гостя на push о приглашении",
             responses={**E_GUEST, 429: err("Слишком много подписок")})
def push_subscribe(code: str, data: SubscriptionIn, request: Request, x_guest_token: str | None = Header(None),
                   db: Session = Depends(get_db)) -> dict:
    room = _room(db, code)
    g = svc.guest_by_token(db, room, x_guest_token)
    hit(_push_ip, client_ip(request), "live_rate_limited", "Слишком много подписок с этого адреса")
    n = svc.subscribe(db, g, data.endpoint, data.keys.p256dh, data.keys.auth, request.headers.get("user-agent") or "")
    svc.bump(db, room.id)
    db.commit()
    return {"subscribed": True, "devices": n}


class RespondIn(BaseModel):
    accept: bool


@router.post("/j/{code}/respond", summary="Принять или отклонить приглашение",
             responses={**E_GUEST, 409: err("Приглашения нет или на него уже ответили")})
def respond(code: str, data: RespondIn, bg: BackgroundTasks, x_guest_token: str | None = Header(None),
            db: Session = Depends(get_db)) -> dict:
    room = _room(db, code)
    g = svc.guest_by_token(db, room, x_guest_token)
    inv_id = svc.respond(db, room, g, data.accept)
    bg.add_task(invitation_answered, inv_id, data.accept)  # push работодателю и демо-ATS песочницы
    return svc.guest_out(db, db.get(LiveGuest, g.id), now=utcnow(), own=True)


@router.get("/j/{code}/qr.svg", summary="QR-код зала (SVG, для экрана)", responses=E_ROOM)
def qr_svg(code: str, request: Request, db: Session = Depends(get_db)) -> Response:
    room = _room(db, code)
    return Response(qr.svg(f"{origin(request)}/j/{room.code}"), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=300"})


@router.get("/j/{code}/qr.png", summary="QR-код зала (PNG, для слайда)", responses=E_ROOM)
def qr_png(code: str, request: Request, download: bool = False, db: Session = Depends(get_db)) -> Response:
    room = _room(db, code)
    headers = {"Cache-Control": "public, max-age=300"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="qr-zal-{room.code}.png"'
    return Response(qr.png(f"{origin(request)}/j/{room.code}"), media_type="image/png", headers=headers)


@router.get("/j/{code}/manifest.webmanifest", summary="Манифест PWA зала: с главного экрана iPhone — сразу мини-тест",
            responses=E_ROOM)
def manifest(code: str, db: Session = Depends(get_db)) -> JSONResponse:
    room = _room(db, code)
    icons = [{"src": f"/icons/{n}-{s}.png", "sizes": f"{s}x{s}", "type": "image/png",
              "purpose": "maskable" if n == "maskable" else "any"} for n in ("icon", "maskable") for s in (192, 512)]
    body = {"id": f"/j/{room.code}", "name": "Драфт: мини-тест жюри", "short_name": "Мини-тест",
            "lang": "ru", "start_url": f"/j/{room.code}?source=pwa", "scope": "/", "display": "standalone",
            "orientation": "portrait", "background_color": "#FBF8FC", "theme_color": "#310F53", "icons": icons}
    return JSONResponse(body, media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------------ большой экран (работодатель песочницы)
def _screen_user(user: User = Depends(require_role(UserRole.employer))) -> tuple[User, str]:
    persona, sid = scope.parse(user.email)
    if persona != "employer" or not sid:
        raise api_error(403, "jury_sandbox_only", "Демонстрация для жюри — из своей песочницы жюри (вход в один клик "
                                                  "работодателем на главной)")
    return user, sid


def _room_out(room: LiveRoom, request: Request) -> dict:
    base = f"/api/jury/live/j/{room.code}"
    return {"code": room.code, "url": f"{origin(request)}/j/{room.code}", "qr_svg": f"{base}/qr.svg",
            "qr_png": f"{base}/qr.png", "rule": svc.RULE, "company": COMPANY, "items": mini.N_ITEMS,
            "push": _push_cfg()}


@router.post("/room", summary="Зал моей песочницы жюри (создаётся при первом запросе, код постоянный)",
             responses={403: err("Не работодатель песочницы жюри")})
def room(request: Request, who: tuple[User, str] = Depends(_screen_user), db: Session = Depends(get_db)) -> dict:
    _, sid = who
    r = svc.room_for(db, sid)
    svc.keep_alive(db, sid)
    return _room_out(r, request)


@router.get("/room/feed", summary="Лента зала для экрана: гости, подборка, приглашения, события",
            responses={403: err("Не работодатель песочницы жюри")})
def feed(request: Request, rev: int | None = None, since: datetime | None = None,
         who: tuple[User, str] = Depends(_screen_user), db: Session = Depends(get_db)) -> dict:
    _, sid = who
    r = svc.room_for(db, sid)
    svc.keep_alive(db, sid)
    now = utcnow()
    if rev is not None and since is not None and rev == r.rev:
        t0 = as_aware(since)
        times = db.execute(select(LiveGuest.selected_at, LiveGuest.invited_at).where(LiveGuest.room_id == r.id)).all()
        due = any(t is not None and t0 < as_aware(t) <= now for row in times for t in row)
        if not due:  # ничего не изменилось и ничего не «наступило» — экран не перерисовывается
            return {"changed": False, "rev": r.rev, "now": now.isoformat()}
    guests = svc.room_guests(db, r)
    svc.catch_up(db, r, guests)
    db.refresh(r)
    guests = svc.room_guests(db, r)
    return {"changed": True, **_room_out(r, request), **svc.screen_feed(db, r, guests)}


@router.post("/room/clear", summary="Очистить зал: удалить гостей и их приглашения (только этот зал)",
             responses={403: err("Не работодатель песочницы жюри")})
def clear(who: tuple[User, str] = Depends(_screen_user), db: Session = Depends(get_db)) -> dict:
    _, sid = who
    return {"deleted": svc.clear_room(db, svc.room_for(db, sid))}
