"""Песочницы жюри: у каждого эксперта жюри свой «сценарий» — собственный набор демо-персон.

Почты персон: общее демо — ``candidate@jury.example.com``; песочница ``sid`` — ``candidate+<sid>@jury.example.com``
(sid — 10 символов [a-z0-9], выдаётся при первом входе в один клик и хранится в браузере эксперта).

Видимость: кандидаты песочницы видны в подборках и поиске только работодателю своей песочницы, ответы «на
проверке» — только эксперту своей песочницы. Остальные пользователи (и общее демо) песочниц не видят. Песочница
текущего запроса берётся из подписанного поля ``jsc`` токена (ставит POST /api/jury/login) — без запроса к БД.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import re
import secrets

from sqlalchemy import or_

DOMAIN = "jury.example.com"
PERSONA_LOCAL = {"candidate": "candidate", "candidate_nofsp": "candidate-nofsp", "candidate_junior": "candidate-junior",
                 "candidate_new": "candidate-new",
                 "employer": "employer", "expert": "expert", "fsp": "fsp-analyst"}
SID_RE = re.compile(r"^[a-z0-9]{10}$")
CLAIM = "jsc"
SHARED = "shared"  # ключ общего демо (sid "") там, где нужна непустая строка
_scope: ContextVar[str | None] = ContextVar("jury_scope", default=None)


def new_sid() -> str:
    return secrets.token_hex(5)


def emails(sid: str = "") -> dict[str, str]:
    suffix = f"+{sid}" if sid else ""
    return {p: f"{local}{suffix}@{DOMAIN}" for p, local in PERSONA_LOCAL.items()}


def parse(email: str | None) -> tuple[str | None, str | None]:
    """(персона, sid) для почты жюри; sid "" — общее демо; (None, None) — не учётка жюри."""
    if not email or not email.endswith("@" + DOMAIN):
        return None, None
    base, _, sid = email[: -len(DOMAIN) - 1].partition("+")
    persona = next((p for p, local in PERSONA_LOCAL.items() if local == base), None)
    if persona is None or (sid and not SID_RE.match(sid)):
        return None, None
    return persona, sid


def key_of(email: str | None) -> str | None:
    """Ключ демо жюри учётки: sid песочницы, SHARED — общее демо, None — не учётка жюри (app.cup: Cup.jury_scope)."""
    persona, sid = parse(email)
    return None if persona is None else (sid or SHARED)


def current() -> str | None:
    """Песочница текущего запроса: None — не жюри или общее демо."""
    return _scope.get() or None


@contextmanager
def use(sid: str | None):
    tok = _scope.set(sid or None)
    try:
        yield
    finally:
        _scope.reset(tok)


def pool_clause(email_col):
    """SQL-условие по почте пользователя: какие учётки видны в текущем запросе."""
    sid = current()
    sandbox = email_col.like(f"%+%@{DOMAIN}")
    if not sid:
        return ~sandbox
    return or_(~email_col.like(f"%@{DOMAIN}"), email_col.like(f"%+{sid}@{DOMAIN}"))


def visible(email: str | None) -> bool:
    """То же условие, что pool_clause, для одной почты."""
    e, sid = email or "", current()
    is_jury = e.endswith("@" + DOMAIN)
    if not sid:
        return not (is_jury and "+" in e)
    return not is_jury or e.endswith(f"+{sid}@{DOMAIN}")


def sees_demo(user) -> bool:
    """Демо-объекты и синтетические профили видны только демо-персонам и жюри."""
    if user is None:
        return False
    return bool(getattr(user, "is_demo", False) or key_of(getattr(user, "email", None)) is not None)


def real_default(user, explicit: bool | None = None, db=None) -> bool:
    """Значение real_only по умолчанию: True для настоящих учёток, False для демо/жюри."""
    if explicit is not None:
        return bool(explicit)
    if sees_demo(user):
        return False
    if db is not None:
        from sqlalchemy import select
        from app.modules.auth.models import User as UserModel

        has_jury = db.scalar(select(UserModel.id).where(UserModel.email.like(f"%@{DOMAIN}")).limit(1)) is not None
        if not has_jury:
            from app.modules.profiles.models import CandidateProfile

            has_synth = (
                db.scalar(select(CandidateProfile.user_id).where(CandidateProfile.is_synthetic.is_(True)).limit(1))
                is not None
            )
            if has_synth:
                return False
    return True


def demo_visible(obj, user) -> bool:
    """Единый фильтр видимости объекта (Cup, Vacancy, Assignment, Company) для пользователя."""
    scope_val = getattr(obj, "jury_scope", None)
    if scope_val is not None and scope_val != key_of(getattr(user, "email", None) if user else None):
        return False
    if not sees_demo(user):
        if getattr(obj, "is_demo", False) or getattr(obj, "is_synthetic", False):
            return False
    return True


def _sid_from_header(value: str) -> str | None:
    if not value.lower().startswith("bearer "):
        return None
    from app.core.security import decode_access_token

    try:
        sid = decode_access_token(value[7:].strip()).get(CLAIM)
    except Exception:  # noqa: BLE001 — недействительный токен: обычная видимость, ошибку вернёт авторизация
        return None
    return sid if isinstance(sid, str) and SID_RE.match(sid) else None


class JuryScopeMiddleware:
    """ASGI: выставляет песочницу жюри из токена на время запроса (contextvar доходит и до пула потоков)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        sid = None
        for k, v in scope.get("headers") or []:
            if k == b"authorization":
                sid = _sid_from_header(v.decode("latin-1"))
                break
        tok = _scope.set(sid)
        try:
            await self.app(scope, receive, send)
        finally:
            _scope.reset(tok)
