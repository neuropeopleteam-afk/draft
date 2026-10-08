"""Режим жюри: вход в один клик под демо-персоной и сброс демо в исходное состояние (см. seed.py, scope.py).

Песочницы: вход с ``scenario: "new"`` создаёт эксперту жюри собственный набор персон, дальше браузер передаёт
полученный ``scenario`` — переключение персон идёт внутри своей песочницы. Сброс — только по токену
демо-персоны и только своей песочницы: другие эксперты жюри не теряют прогресс.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal, get_db, get_engine, utcnow
from app.core.deps import get_current_user
from app.core.errors import api_error, err
from app.core.ratelimit import SlidingWindow, client_ip
from app.modules.auth.models import User
from app.modules.auth.service import issue_token
from app.modules.jury import scope, seed

router = APIRouter(prefix="/api/jury", tags=["jury"])
log = logging.getLogger(__name__)
_state: dict[str, float] = {}  # sid ("" — общее демо) → время последнего сброса
_mx = threading.Lock()
# Создание песочницы — несколько секунд CPU: не больше 12 в час с адреса и 60 в час всего (на воркер).
# Лимит исчерпан — вход в общее демо (в один клик работает всегда).
_new_ip = SlidingWindow(12, 3600)
_new_all = SlidingWindow(60, 3600)
LANDING = {"candidate": "/candidate", "candidate_nofsp": "/candidate", "candidate_junior": "/candidate/category",
           "candidate_new": "/candidate/express", "employer": "/employer", "expert": "/expert", "fsp": "/fsp"}


class LoginIn(BaseModel):
    persona: Literal["candidate", "candidate_nofsp", "candidate_junior", "candidate_new", "employer", "expert", "fsp"]
    scenario: str | None = Field(None, pattern=r"^(new|[a-z0-9]{10})$",
                                 description="new — создать свою песочницу; id — продолжить свою; пусто — общее демо")


def _available() -> None:
    if not get_settings().jury_mode_available:
        raise api_error(404, "jury_disabled", "Режим жюри выключен")


def _token(db: Session, sid: str, persona: str) -> dict:
    user = db.scalar(select(User).where(User.email == scope.emails(sid)[persona]))
    if user is None:
        raise api_error(503, "jury_not_ready", "Демо-учётки жюри ещё создаются, повторите через несколько секунд")
    user.last_login_at = utcnow()
    db.commit()
    tok = issue_token(user, {scope.CLAIM: sid} if sid else None)
    return {**tok.model_dump(), "persona": persona, "landing": LANDING[persona], "scenario": sid or None,
            "shared": not sid}


def _new_sandbox(db: Session, request: Request, sid: str | None = None) -> str | None:
    """Выдаёт новую песочницу: запасную (мгновенно) или создаёт сейчас; sid — пересоздать удалённую по лимиту.
    None — лимит создания исчерпан."""
    if _new_ip.retry_after(client_ip(request)) or _new_all.retry_after("all"):
        return None
    if sid is None:
        for spare in seed.spares(db):
            if seed.claim(db, spare):
                _refill()
                return spare
    sid = sid or scope.new_sid()
    seed.evict(db, keep=max(1, get_settings().jury_sandboxes_max) - 1, protect=sid)
    seed.ensure(db, sid)
    _refill()
    return sid


_spare_mx = threading.Lock()


def make_spare() -> str | None:
    """Создать запасную песочницу, если запаса нет (по очереди между воркерами — advisory lock в seed)."""
    s = get_settings()
    if s.jury_spare_sandboxes <= 0 or not s.jury_mode_available or not _spare_mx.acquire(blocking=False):
        return None
    try:
        get_engine()  # фоновый поток при старте — до первого запроса движок БД ещё не создан
        with SessionLocal() as db:
            if len(seed.spares(db)) >= s.jury_spare_sandboxes:
                return None
            seed.evict(db, keep=max(1, s.jury_sandboxes_max) - 1)
            sid = scope.new_sid()
            with seed.as_spare():
                seed.ensure(db, sid)
            seed.ensure_ideas(db)  # общее демо кубков и Кабинета ФСП — заодно, пока никто не ждёт
            return sid
    except Exception:  # запас — оптимизация: при ошибке песочница создастся при входе, как без запаса
        log.exception("Запасная песочница жюри не создана")
        return None
    finally:
        _spare_mx.release()


def _refill() -> None:
    if get_settings().jury_spare_sandboxes > 0:
        threading.Thread(target=make_spare, name="jury-spare", daemon=True).start()


@router.get("/status", summary="Персоны режима жюри")
def status(db: Session = Depends(get_db)):
    s = get_settings()
    if s.jury_mode_available:
        _refill()  # главная страница открыта — готовим песочницу заранее
    have = set(db.scalars(select(User.email).where(User.email.in_(list(seed.EMAILS.values())))).all())
    return {"available": s.jury_mode_available,
            "personas": [{**p, "email": seed.EMAILS[p["id"]], "ready": seed.EMAILS[p["id"]] in have,
                          "landing": LANDING[p["id"]]} for p in seed.PERSONAS],
            "reset_cooldown_s": s.jury_reset_cooldown_s, "sandboxes": True}


@router.post("/login", summary="Вход в один клик под демо-персоной жюри (своя песочница: scenario=new)")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    _available()
    created, sid = False, ""
    if data.scenario == "new":
        sid = _new_sandbox(db, request) or ""
        created = bool(sid)
    elif data.scenario:
        sid = data.scenario
        if not seed._complete(db, sid):  # песочница удалена по лимиту — пересоздаём с тем же id
            sid = _new_sandbox(db, request, sid) or ""
            created = bool(sid)
    if not sid:
        created = seed.ensure(db)
    seed.ensure_ideas(db)  # кубки демо-компаний и история приглашений для Кабинета ФСП (одни на всех)
    return {**_token(db, sid, data.persona), "created": created}


@router.post("/reset", summary="Сбросить СВОЮ песочницу жюри в исходное состояние (токен демо-персоны)",
             responses={401: err("Не выполнен вход"), 403: err("Только для демо-персон жюри"),
                        429: err("Сброс только что был")})
def reset(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _available()
    persona, sid = scope.parse(user.email)
    if persona is None or not user.is_demo:
        raise api_error(403, "jury_only", "Сбросить демо может только демо-персона жюри")
    if not sid:
        # общее демо не сбрасываем — у него могут быть другие эксперты; вместо сброса — своя чистая песочница
        new = _new_sandbox(db, request)
        if new is None:
            raise api_error(429, "jury_sandbox_limit", "Слишком много новых песочниц с вашего адреса, повторите позже")
        return {"ok": True, "deleted_users": 0, "seconds": 0.0, **_token(db, new, persona), "moved": True}
    cd = get_settings().jury_reset_cooldown_s
    with _mx:
        left = cd - (time.time() - _state.get(sid, 0.0))
        if left > 0:
            raise api_error(429, "jury_reset_cooldown", f"Демо уже сбрасывали только что, повторите через {int(left) + 1} с")
        _state[sid] = time.time()
        if len(_state) > 10_000:
            _state.clear()
    out = seed.reset(db, sid)
    return {"ok": True, **out, **_token(db, sid, persona)}


@router.delete("/sandbox", summary="Удалить СВОЮ песочницу жюри (токен демо-персоны песочницы)",
               description="Удаляет все учётки, компанию, кубки и гостей живой демонстрации своей песочницы без "
                           "пересоздания — дешевле сброса; e2e-прогон убирает за собой так. Общее демо не удаляется.",
               responses={401: err("Не выполнен вход"), 403: err("Только для демо-персон своей песочницы")})
def delete_sandbox(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _available()
    persona, sid = scope.parse(user.email)
    if persona is None or not user.is_demo:
        raise api_error(403, "jury_only", "Удалить песочницу может только демо-персона жюри")
    if not sid:
        raise api_error(403, "jury_shared", "Общее демо не удаляется — оно одно на всех экспертов жюри")
    t0 = time.time()
    with seed._lock(db):
        n = seed.delete_jury(db, sid)
    with _mx:
        _state.pop(sid, None)
    log.info("jury: песочница %s удалена по запросу (%d учёток)", sid, n)
    return {"ok": True, "scenario": sid, "deleted_users": n, "seconds": round(time.time() - t0, 1)}
