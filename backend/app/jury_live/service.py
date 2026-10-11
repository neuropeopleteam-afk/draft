"""Сервис живой демонстрации: зал, гости, мини-тест → экспресс-категория → подборка → автоприглашение → push.

Путь гостя — те же модули, что у живого кандидата: факты T1 (profiles.facts), подборка (matching.ranking,
новая версия SelectionVersion потребности работодателя), приглашение (invitations.service с проверкой вилки
и доказательствами), Web Push (integrations.push). Подборка и приглашение считаются сразу по завершении
теста, а «появляются» на экранах по расписанию (selected_at, invited_at): пауза в несколько секунд — чтобы зал
видел шаги по очереди; без фоновых потоков, переживает перезапуск API. Push уходит фоновой задачей в момент
invited_at; если её не было (перезапуск), — при следующем опросе ленты, один раз (push_state).
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
import hashlib
import logging
import secrets
import time
import uuid

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal, as_aware, utcnow
from app.core.enums import EvidenceLevel, FactSource, NeedStatus, UserRole, WorkFormat
from app.core.errors import api_error
from app.integrations.push.models import PushSubscription
from app.jury_live import mini
from app.jury_live.models import LiveGuest, LiveRoom
from app.modules.auth.models import User
from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import DIRECTIONS, GRADES, category_title, tag_title
from app.modules.invitations import service as inv_svc
from app.modules.invitations.models import Invitation
from app.modules.jury import scope
from app.modules.matching import ranking
from app.modules.matching.models import EmployerNeed, SelectionVersion
from app.modules.matching.need_parser import parse_need
from app.modules.profiles.facts import refresh_rating
from app.modules.profiles.models import CandidateFact, CandidateProfile, Company, EmployerProfile
from app.modules.profiles.refs import new_public_ref

log = logging.getLogger(__name__)

CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # без 0/o, 1/l/i — код читается вслух и со слайда
CODE_LEN = 6
GUESTS_MAX = 100  # на зал; «Очистить зал» освобождает
SELECTION_LIMIT = 60
GUEST_PREFIX = "guest-"
NEED_PREFIX = "Живая демонстрация: "
NEED_TEXTS = {
    # Ф2 × живая демонстрация: обязательным — то, что мини-тест из 3 заданий реально подтверждает (по пулу mini.py:
    # backend — Python, frontend — JavaScript, data_ml — Python, qa — тест-дизайн, security — OWASP); остальное — желательно,
    # иначе у гостя на проекторе почти всегда ярус «не хватает обязательного»
    "backend": ("Backend-разработчик", "Backend-разработчик в команду платежей: обязательно Python, желательно SQL, "
                                       "REST API, PostgreSQL, Redis и FastAPI. Удалённо."),
    "frontend": ("Frontend-разработчик", "Frontend-разработчик для личного кабинета: обязательно JavaScript, желательно "
                                         "TypeScript, React, HTML/CSS и доступность (a11y). Удалённо."),
    "data_ml": ("Data/ML-инженер", "Data/ML-инженер в команду антифрода: обязательно Python, желательно pandas, SQL, "
                                   "scikit-learn и статистика. Удалённо."),
    "qa": ("QA-инженер", "QA-инженер в команду платежей: обязательно тест-дизайн, желательно Python, pytest, SQL и "
                         "нагрузочное тестирование. Удалённо."),
    "security": ("AppSec-специалист", "Специалист по информационной безопасности (AppSec): обязательно OWASP, желательно "
                                      "сетевая безопасность, Python, криптография и SQL. Удалённо."),
}
RULE = ("Правило демо-работодателя на защите: приглашение получает каждый, кому мини-тест дал экспресс-категорию; "
        "вилка — по рынку этой категории. Полный тест (8–16 заданий) уточняет грейд.")
EVENT_TEXT = {
    "joined": "открыл мини-тест", "answered": "ответил на задание {n} из 3", "finished": "завершил мини-тест",
    "no_category": "завершил мини-тест: категория не присвоена", "selected": "попал в подборку: место {rank} из {total}",
    "invited": "получил приглашение: {salary}", "push": "push: {push}", "viewed": "открыл приглашение",
    "accepted": "принял приглашение — контакты открыты работодателю", "declined": "отклонил приглашение",
}


def _rub(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ₽"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _iso(dt: datetime | None) -> str | None:
    return as_aware(dt).isoformat() if dt else None


def _ev(kind: str, at: datetime | None = None, **extra) -> dict:
    return {"at": (at or utcnow()).isoformat(), "kind": kind, **extra}


# ------------------------------------------------------------------ зал
def employer_of(db: Session, sid: str) -> tuple[User, Company] | None:
    """Работодатель песочницы и её демо-компания (None — песочницы сейчас нет: удалена по лимиту или сбрасывается)."""
    if not sid:
        return None
    u = db.scalar(select(User).where(User.email == scope.emails(sid)["employer"]))
    ep = db.get(EmployerProfile, u.id) if u else None
    c = db.get(Company, ep.company_id) if ep and ep.company_id else None
    return (u, c) if c else None


def room_by_code(db: Session, code: str) -> LiveRoom | None:
    code = (code or "").strip().lower()
    if not (3 <= len(code) <= 16) or any(ch not in CODE_ALPHABET for ch in code):
        return None
    return db.scalar(select(LiveRoom).where(LiveRoom.code == code))


def room_for(db: Session, sid: str) -> LiveRoom:
    """Зал песочницы: один на sid и переживает её сброс — QR на слайде остаётся рабочим."""
    room = db.scalar(select(LiveRoom).where(LiveRoom.sid == sid))
    for _ in range(5):
        if room is not None:
            return room
        room = LiveRoom(code="".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN)), sid=sid)
        db.add(room)
        try:
            db.commit()
        except IntegrityError:  # совпал код или зал создан параллельным запросом
            db.rollback()
            room = db.scalar(select(LiveRoom).where(LiveRoom.sid == sid))
    raise api_error(503, "room_unavailable", "Не удалось создать зал, повторите")


def bump(db: Session, room_id: uuid.UUID) -> None:
    db.execute(update(LiveRoom).where(LiveRoom.id == room_id)
               .values(rev=LiveRoom.rev + 1, last_activity_at=utcnow()))


def bump_sid(db: Session, sid: str) -> None:
    db.execute(update(LiveRoom).where(LiveRoom.sid == sid).values(rev=LiveRoom.rev + 1))


def keep_alive(db: Session, sid: str) -> None:
    """Зал активен — песочница не самая давняя и не будет вытеснена по лимиту (seed.sandboxes: время входа)."""
    u = db.scalar(select(User).where(User.email == scope.emails(sid)["employer"]))
    now = utcnow()
    if u is not None and (u.last_login_at is None or as_aware(u.last_login_at) < now - timedelta(minutes=1)):
        u.last_login_at = now
        db.commit()


def guest_emails_like(sid: str) -> str:
    return f"{GUEST_PREFIX}%+{sid}@{scope.DOMAIN}"


def delete_guests(db: Session, user_ids: list) -> None:
    """Гости и их учётки (профиль, факты, приглашения, подписки push — каскадом в PostgreSQL; в SQLite — явно)."""
    if not user_ids:
        return
    db.execute(delete(LiveGuest).where(LiveGuest.user_id.in_(user_ids)))
    db.execute(delete(PushSubscription).where(PushSubscription.user_id.in_(user_ids)))
    db.execute(delete(CandidateFact).where(CandidateFact.user_id.in_(user_ids)))
    db.execute(delete(Invitation).where(Invitation.candidate_user_id.in_(user_ids)))
    db.execute(delete(CandidateProfile).where(CandidateProfile.user_id.in_(user_ids)))
    db.execute(delete(User).where(User.id.in_(user_ids)))


def clear_room(db: Session, room: LiveRoom) -> int:
    ids = db.scalars(select(LiveGuest.user_id).where(LiveGuest.room_id == room.id)).all()
    delete_guests(db, list(ids))
    bump(db, room.id)
    db.commit()
    return len(ids)


# ------------------------------------------------------------------ гость
def start_guest(db: Session, room: LiveRoom, direction: str) -> tuple[LiveGuest, str]:
    if direction not in mini.DIRECTIONS:
        raise api_error(422, "bad_direction", "Неизвестное направление")
    if employer_of(db, room.sid) is None:
        raise api_error(409, "room_closed", "Демонстрация сейчас перезапускается — отсканируйте QR ещё раз через минуту")
    n = db.scalar(select(func.count()).select_from(LiveGuest).where(LiveGuest.room_id == room.id)) or 0
    if n >= GUESTS_MAX:
        raise api_error(409, "room_full", "В зале уже много участников — попросите докладчика очистить зал")
    from app.modules.demo.seed import _user as demo_user

    # Пароля нет (хэш недействителен — вход по паролю невозможен); доступ — только по токену гостя
    u = demo_user(db, f"{GUEST_PREFIX}{secrets.token_hex(4)}+{room.sid}@{scope.DOMAIN}", UserRole.candidate,
                  "!jury-live-guest")
    number = n + 1
    db.add(CandidateProfile(
        user_id=u.id, full_name=f"Гость жюри {number}", city="Москва", work_format=WorkFormat.remote,
        privacy={}, visible_to_employers=True, public_ref=new_public_ref(db), onboarding_completed_at=utcnow(),
        roles=["developer"], headline=f"{DIRECTIONS[direction]} · мини-тест (гость жюри)", jury_mode=True))
    db.flush()
    token = secrets.token_urlsafe(24)
    g = LiveGuest(room_id=room.id, user_id=u.id, token_hash=hash_token(token),
                  ref=db.get(CandidateProfile, u.id).public_ref, number=number, direction=direction,
                  stage="testing", state=mini.new_state(direction), events=[_ev("joined")], last_seen_at=utcnow())
    db.add(g)
    bump(db, room.id)
    db.commit()
    return g, token


def guest_by_token(db: Session, room: LiveRoom, token: str | None) -> LiveGuest:
    g = db.scalar(select(LiveGuest).where(LiveGuest.token_hash == hash_token(token or ""),
                                          LiveGuest.room_id == room.id)) if token else None
    if g is None:
        raise api_error(401, "guest_unknown", "Сессия мини-теста не найдена — начните заново")
    return g


def answer(db: Session, room: LiveRoom, g: LiveGuest, token: str, value) -> list:
    """Ответ на текущее задание; после третьего — итог, подборка и приглашение. Возвращает отложенные задачи."""
    if g.stage != "testing":
        raise api_error(409, "test_finished", "Мини-тест уже завершён")
    # двойное касание или повтор запроса: ответ принимает только один запрос (CAS по stage)
    r = db.execute(update(LiveGuest).where(LiveGuest.id == g.id, LiveGuest.stage == "testing")
                   .values(stage="answering"))
    db.commit()
    if r.rowcount != 1:
        raise api_error(409, "answer_in_progress", "Ответ уже принимается")
    try:
        st = copy.deepcopy(g.state)
        ok = mini.answer(st, token, value)
        if ok is None:
            raise api_error(422, "bad_answer", "Ответ не принят: выберите вариант или строку текущего задания")
        done = sum(1 for it in st["items"] if it["done"])
        g.state = st
        g.stage = "testing"
        g.last_seen_at = utcnow()
        g.events = [*g.events, _ev("answered", n=done)]
        tasks = finish(db, room, g) if mini.finished(st) else []
        bump(db, room.id)
        db.commit()
        return tasks
    except Exception:
        db.rollback()
        db.execute(update(LiveGuest).where(LiveGuest.id == g.id, LiveGuest.stage == "answering")
                   .values(stage="testing"))
        db.commit()
        raise


def _market_offer(cat: Category | None) -> tuple[int, int]:
    """Вилка по рынку категории: от — медиана (округление вниз до 10 тыс.), до — не выше 1,3 «от» и верха рынка."""
    if cat is None:
        return 150_000, 195_000
    mid = cat.market_salary_median or (cat.market_salary_from + cat.market_salary_to) // 2
    lo = max(10_000, mid // 10_000 * 10_000)
    hi = max(lo + 10_000, min(int(lo * 1.3) // 10_000 * 10_000, max(cat.market_salary_to, lo)))
    return lo, min(hi, int(lo * 1.5))


def live_need(db: Session, company: Company, employer: User, direction: str) -> EmployerNeed:
    """Потребность «Живая демонстрация: …» направления — создаётся при первом госте (в песочнице, не в общем демо)."""
    title, text = NEED_TEXTS[direction]
    full = NEED_PREFIX + title
    n = db.scalar(select(EmployerNeed).where(EmployerNeed.company_id == company.id, EmployerNeed.title == full))
    if n is None:
        req = parse_need(text, use_llm=False)
        req["direction"], req["grade"] = direction, None  # все грейды направления: экспресс-оценка грубее полной
        n = EmployerNeed(company_id=company.id, created_by=employer.id, title=full, raw_text=text, requirements=req,
                         direction_id=direction, grade_id=None, status=NeedStatus.active)
        db.add(n)
        db.flush()
    return n


def _cat_title(res: dict) -> str:
    """«Backend · Middle (предварительно)» — категория мини-теста всегда предварительная (и у старых итогов)."""
    return res.get("category_title") or f"{category_title(res['category_id'])} (предварительно)"


def _write_facts(db: Session, g: LiveGuest, res: dict) -> None:
    db.execute(delete(CandidateFact).where(CandidateFact.user_id == g.user_id, CandidateFact.source == FactSource.test))
    src = f"jury_live:{g.id}"
    db.add(CandidateFact(
        user_id=g.user_id, kind="test_result", key=f"{g.direction}.{res['grade']}",
        title=f"Мини-тест {g.direction} · {res['grade']}",
        value={"theta": res["theta"], "se": res["se"], "grade": res["grade"], "confirmed": True, "mini": True,
               "correct": res["correct"], "answered": res["answered"], "engine": mini.ENGINE,
               # 3 задания: категория предварительная и не выше Middle (grades.category_level, Ф3)
               "preliminary": True, "mode": "mini"},
        evidence_level=EvidenceLevel.T1, source=FactSource.test, source_ref=src))
    totals: dict[str, list[int]] = {}
    for it in res["items"]:
        for tag in it["skills"]:
            t = totals.setdefault(tag, [0, 0])
            t[0] += int(it["correct"])
            t[1] += 1
    for tag, (ok, total) in totals.items():
        db.add(CandidateFact(user_id=g.user_id, kind="skill", key=tag, title=tag_title(tag),
                             value={"score": round(ok / total, 2), "correct": ok, "total": total},
                             evidence_level=EvidenceLevel.T1, source=FactSource.test, source_ref=src))


def finish(db: Session, room: LiveRoom, g: LiveGuest) -> list:
    """Итог мини-теста → экспресс-категория → подборка (новая версия) → приглашение с вилкой по рынку."""
    s = get_settings()
    now = utcnow()
    res = mini.result(g.state)
    g.result, g.finished_at = res, now
    if not res["grade"]:
        g.stage = "no_category"
        g.events = [*g.events, _ev("no_category", now)]
        return []
    p = db.get(CandidateProfile, g.user_id)
    p.current_direction_id, p.current_grade_id, p.current_category_id = g.direction, res["grade"], res["category_id"]
    _write_facts(db, g, res)
    db.flush()
    refresh_rating(db, g.user_id)
    g.events = [*g.events, _ev("finished", now)]
    emp = employer_of(db, room.sid)
    if emp is None:
        g.stage = "done"
        return []
    employer, company = emp
    with scope.use(room.sid):
        need = live_need(db, company, employer, g.direction)
        # гость ищется по всей выдаче: в мире из 500 кандидатов его место может быть и за пределами первых 60
        sel = ranking.build_selection(db, need.requirements, {}, limit=SELECTION_LIMIT, include_refs=(g.ref,))
    last = db.scalar(select(func.max(SelectionVersion.version)).where(SelectionVersion.need_id == need.id)) or 0
    db.add(SelectionVersion(need_id=need.id, version=last + 1, parent_version=last or None, filters={},
                            requirements=need.requirements, results=sel["results"],
                            algorithm_version=sel["algorithm"], created_by=employer.id))
    labels = dict(db.execute(select(LiveGuest.ref, LiveGuest.number).where(LiveGuest.room_id == room.id)).all())
    mine = next((r for r in sel["results"] if r["ref"] == g.ref), None)
    first = sel["results"][:8]
    top = [_row(r, labels, g.ref) for r in first]
    if mine is not None and all(r["ref"] != g.ref for r in first):  # свой ряд — один раз, даже при узком окне
        top.append(_row(mine, labels, g.ref))
    sel_at = now + timedelta(seconds=s.jury_live_select_delay_s)
    g.selection = {
        "need_id": str(need.id), "need_title": need.title, "version": last + 1, "total": sel["total_matched"],
        "rank": mine["rank"] if mine else None, "score": mine["score"] if mine else None,
        "components": mine["components"] if mine else {}, "reasons": mine["reasons"] if mine else [],
        "weights": sel.get("weights"), "top": top,
    }
    g.selected_at = sel_at
    g.events = [*g.events, _ev("selected", sel_at, rank=g.selection["rank"], total=g.selection["total"])]
    # приглашение — по правилу экрана: его получает каждый, кому мини-тест дал экспресс-категорию, где бы ни было место
    cat = db.get(Category, res["category_id"])
    place = f", вы на {mine['rank']}-м месте из {sel['total_matched']}" if mine is not None else ""
    lo, hi = _market_offer(cat)
    title = f"{NEED_TEXTS[g.direction][0]} ({GRADES[res['grade']]})"
    try:
        inv = inv_svc.create_invitation(
            db, employer, company, p, position_title=title,
            offer_description=(f"Вы прошли мини-тест из 3 заданий банка и получили экспресс-категорию "
                               f"{_cat_title(res)} — подборка работодателя пересчиталась{place}. "
                               f"{RULE} Это демо-компания: "
                               f"собеседования не будет, а путь приглашения — настоящий."),
            salary_from=lo, salary_to=hi, contact_method="Демо: ответ — кнопками на этой странице",
            need_id=need.id, probe_id=None)
    except HTTPException as e:  # вилка или кулдаун: гость остаётся в подборке без приглашения
        log.warning("jury_live invite failed: %s", e.detail)
        g.stage = "selected"
        return []
    inv_at = sel_at + timedelta(seconds=s.jury_live_invite_delay_s)
    g.invite = {"id": str(inv.id), "position_title": title, "salary_from": lo, "salary_to": hi,
                "market": {"from": cat.market_salary_from, "to": cat.market_salary_to,
                           "median": cat.market_salary_median} if cat else None}
    g.invited_at = inv_at
    g.stage = "invited"
    g.events = [*g.events, _ev("invited", inv_at, salary=f"{_rub(lo)} – {_rub(hi)}")]
    return [("push", g.id)]


def _row(r: dict, labels: dict, own: str) -> dict:
    c = r.get("card") or {}
    t = c.get("test") or {}
    n = labels.get(r["ref"])
    return {"ref": r["ref"], "rank": r["rank"], "score": r["score"], "category_id": r.get("category_id"),
            "label": f"Гость {n}" if n else None, "is_guest": n is not None, "is_self": r["ref"] == own,
            "fsp": bool((c.get("fsp") or {}).get("level")), "mini": t.get("engine") == mini.ENGINE,
            "theta": t.get("theta"), "se": t.get("se")}


def visible_stage(g: LiveGuest, now: datetime | None = None) -> str:
    now = now or utcnow()
    if g.stage in ("testing", "answering"):
        return "testing"
    if g.stage in ("no_category", "accepted", "declined"):
        return g.stage
    if g.invited_at and g.stage == "invited" and as_aware(g.invited_at) <= now:
        return "invited"
    if g.selected_at and as_aware(g.selected_at) <= now:
        return "selected"
    return "done"


# ------------------------------------------------------------------ push
def deliver_push(db: Session, guest_id: uuid.UUID, code: str) -> bool:
    """Push гостю о приглашении — ровно один раз (push_state: "" → sending → done)."""
    r = db.execute(update(LiveGuest).where(LiveGuest.id == guest_id, LiveGuest.push_state == "",
                                           LiveGuest.stage.in_(("invited", "accepted", "declined")))
                   .values(push_state="sending"))
    db.commit()
    if r.rowcount != 1:
        return False
    from app.integrations.push.service import send_to_user

    g = db.get(LiveGuest, guest_id)
    devices = db.scalar(select(func.count()).select_from(PushSubscription)
                        .where(PushSubscription.user_id == g.user_id)) or 0
    inv = g.invite or {}
    try:
        sent = send_to_user(db, g.user_id, "Приглашение: Демо жюри «Северный платёж»",
                            f"«{inv.get('position_title')}», {_rub(inv.get('salary_from', 0))} – "
                            f"{_rub(inv.get('salary_to', 0))}", f"/j/{code}", f"live-{g.id}")
    except Exception:  # noqa: BLE001 — сбой push не ломает показ: страница гостя обновится сама
        log.exception("jury_live push failed")
        sent = 0
    g = db.get(LiveGuest, guest_id)
    g.push_state = "done"
    g.invite = {**(g.invite or {}), "push": {"devices": devices, "delivered": sent, "at": utcnow().isoformat()}}
    text = (f"доставлен на {sent} из {devices} устр." if devices else "нет подписки — страница обновилась сама")
    g.events = [*g.events, _ev("push", push=text)]
    bump(db, g.room_id)
    db.commit()
    return True


def push_later(guest_id: uuid.UUID, code: str) -> None:
    """Фоновая задача: дождаться момента приглашения и отправить push (своя сессия БД)."""
    db = SessionLocal()
    try:
        g = db.get(LiveGuest, guest_id)
        if g is None or g.invited_at is None:
            return
        wait = (as_aware(g.invited_at) - utcnow()).total_seconds()
        db.close()
        if wait > 0:
            time.sleep(min(wait, 30))
        db = SessionLocal()
        deliver_push(db, guest_id, code)
    except Exception:  # noqa: BLE001
        log.exception("jury_live push_later failed")
    finally:
        db.close()


def catch_up(db: Session, room: LiveRoom, guests: list[LiveGuest]) -> None:
    """Запасной путь: приглашение показано, а push так и не ушёл (перезапуск API) — отправить при опросе."""
    now = utcnow()
    for g in guests:
        if g.push_state == "" and g.invited_at and g.stage in ("invited", "accepted", "declined") \
                and as_aware(g.invited_at) < now - timedelta(seconds=5):
            deliver_push(db, g.id, room.code)


def subscribe(db: Session, g: LiveGuest, endpoint: str, p256dh: str, auth: str, ua: str) -> int:
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if sub is None:
        sub = PushSubscription(endpoint=endpoint, user_id=g.user_id, p256dh=p256dh, auth=auth)
        db.add(sub)
    sub.user_id, sub.p256dh, sub.auth, sub.user_agent = g.user_id, p256dh, auth, ua[:255]
    db.commit()
    return db.scalar(select(func.count()).select_from(PushSubscription)
                     .where(PushSubscription.user_id == g.user_id)) or 0


# ------------------------------------------------------------------ ответ на приглашение
def respond(db: Session, room: LiveRoom, g: LiveGuest, accept: bool) -> uuid.UUID:
    if visible_stage(g) != "invited":
        raise api_error(409, "no_invitation", "Приглашения пока нет или на него уже ответили")
    inv = db.get(Invitation, uuid.UUID(g.invite["id"]))
    if inv is None:
        raise api_error(409, "no_invitation", "Приглашение не найдено")
    inv_svc.respond(db, inv, g.user_id, accept, None)
    g = db.get(LiveGuest, g.id)
    g.stage = "accepted" if accept else "declined"
    g.responded_at = utcnow()
    g.events = [*g.events, _ev(g.stage)]
    bump(db, room.id)
    db.commit()
    return inv.id


def mark_viewed(db: Session, room: LiveRoom, g: LiveGuest) -> None:
    """Гость увидел приглашение на телефоне — отметка «просмотрено» у работодателя и в ленте зала."""
    if visible_stage(g) != "invited" or any(e["kind"] == "viewed" for e in g.events):
        return
    inv = db.get(Invitation, uuid.UUID(g.invite["id"]))
    if inv is not None:
        inv_svc.mark_viewed(db, inv, g.user_id)
    g = db.get(LiveGuest, g.id)
    g.events = [*g.events, _ev("viewed")]
    bump(db, room.id)
    db.commit()


# ------------------------------------------------------------------ вывод
def _event_text(e: dict) -> str:
    t = EVENT_TEXT.get(e["kind"], e["kind"])
    if e["kind"] == "selected" and e.get("rank") is None:  # места нет — «на -м месте» не пишем
        t = "подборка пересчитана: {total} кандидатов"
    try:
        return t.format(**{k: ("—" if v is None else v) for k, v in e.items()})
    except (KeyError, IndexError):
        return t


def guest_out(db: Session, g: LiveGuest, *, now: datetime, own: bool) -> dict:
    """Состояние гостя. own — для его телефона (текущее задание, доказательства); иначе — для большого экрана."""
    stage = visible_stage(g, now)
    answered = sum(1 for it in (g.state or {}).get("items", []) if it.get("done"))
    out = {"number": g.number, "label": f"Гость {g.number}", "ref": g.ref, "direction": g.direction,
           "direction_title": DIRECTIONS.get(g.direction), "stage": stage, "answered": answered,
           "total": mini.N_ITEMS, "created_at": _iso(g.created_at), "finished_at": _iso(g.finished_at),
           "result": None, "selection": None, "invite": None, "invite_failed": g.stage == "selected"}
    if not own:
        out["id"] = str(g.id)
    if stage == "testing" and own:
        out["item"] = mini.public_item(g.state)
    if stage != "testing":
        r = g.result or {}
        out["result"] = {k: r.get(k) for k in ("theta", "se", "grade", "category_id", "correct", "answered", "time_s",
                                                "ceiling", "capped")}
        out["result"]["category_title"] = _cat_title(r) if r.get("category_id") else None
        out["result"]["preliminary"] = bool(r.get("category_id"))
        out["result"]["skills"] = [{"tag": k, "title": tag_title(k), "score": v}
                                   for k, v in sorted((r.get("skills") or {}).items())]
    if stage in ("selected", "invited", "accepted", "declined") and g.selection:
        sel = g.selection
        out["selection"] = {k: sel.get(k) for k in ("need_title", "version", "rank", "total", "score", "reasons",
                                                      "components")}
        out["selection"]["selected_at"] = _iso(g.selected_at)
        if not own:
            out["selection"]["top"] = sel.get("top") or []
    if stage in ("invited", "accepted", "declined") and g.invite:
        inv = g.invite
        out["invite"] = {"position_title": inv.get("position_title"), "salary_from": inv.get("salary_from"),
                         "salary_to": inv.get("salary_to"), "market": inv.get("market"), "push": inv.get("push"),
                         "sent_at": _iso(g.invited_at), "responded_at": _iso(g.responded_at),
                         "viewed": any(e["kind"] == "viewed" for e in g.events or [])}
        if own:
            i = db.get(Invitation, uuid.UUID(inv["id"]))
            if i is not None:
                out["invite"].update({"offer_description": i.offer_description, "evidence": i.evidence,
                                      "contact_method": i.contact_method, "status": i.status.value})
                c = db.get(Company, i.company_id)
                out["invite"]["company"] = {"name": c.name, "industry": c.industry, "city": c.city} if c else None
                out["invite"]["trust"] = _trust(db, c, i)
    return out


def _trust(db: Session, c: Company | None, inv: Invitation) -> dict | None:
    if c is None:
        return None
    try:
        from app.integrations.egrul import trust as trust_mod

        return trust_mod.short(trust_mod.compute(db, c, invitation=inv))
    except Exception:  # noqa: BLE001 — индекс доверия не обязателен для показа
        log.exception("jury_live trust failed")
        return None


def counters(guests: list[LiveGuest], now: datetime) -> dict:
    st = [visible_stage(g, now) for g in guests]
    return {"joined": len(guests), "testing": st.count("testing"),
            "finished": sum(1 for s in st if s != "testing"),
            "with_category": sum(1 for g, s in zip(guests, st) if s != "testing" and (g.result or {}).get("grade")),
            "selected": sum(1 for s in st if s in ("selected", "invited", "accepted", "declined")),
            "invited": sum(1 for s in st if s in ("invited", "accepted", "declined")),
            "accepted": st.count("accepted"), "declined": st.count("declined"),
            "push_delivered": sum(1 for g in guests if ((g.invite or {}).get("push") or {}).get("delivered"))}


def room_guests(db: Session, room: LiveRoom) -> list[LiveGuest]:
    return list(db.scalars(select(LiveGuest).where(LiveGuest.room_id == room.id)
                           .order_by(LiveGuest.created_at)).all())


def screen_feed(db: Session, room: LiveRoom, guests: list[LiveGuest]) -> dict:
    now = utcnow()
    events = []
    for g in guests:
        for e in g.events or []:
            if datetime.fromisoformat(e["at"]) <= now:
                events.append({"at": e["at"], "kind": e["kind"], "guest": g.number, "label": f"Гость {g.number}",
                               "ref": g.ref, "text": _event_text(e)})
    events.sort(key=lambda e: e["at"], reverse=True)
    out = [guest_out(db, g, now=now, own=False) for g in guests]
    pending = [as_aware(t) for g in guests for t in (g.selected_at, g.invited_at) if t and as_aware(t) > now]
    return {"rev": room.rev, "now": now.isoformat(), "code": room.code, "guests": out, "events": events[:60],
            "counters": counters(guests, now), "rule": RULE,
            "next_reveal_at": min(pending).isoformat() if pending else None}
