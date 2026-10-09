"""Доставка уведомлений: запись в кабинете, push (VAPID), письмо через Postbox, дайджест, тихие часы.

Порядок: сначала строка user_notifications (идемпотентная по dedupe_key), потом отправка. Если процесс упадёт между
ними, повторной отправки не будет: «лучше пропустить, чем продублировать». Демо-учётки жюри письма не получают
(как в notifications.mailer.notify), но видят то же самое в кабинете: «Уведомления».
"""
from __future__ import annotations

from datetime import datetime, timedelta
import html as _html
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import as_aware, utcnow
from app.core.enums import UserRole
from app.integrations.push import service as push
from app.integrations.push.models import PushSubscription
from app.integrations.settings import get_isettings
from app.modules.auth.models import User
from app.modules.notifications.mailer import Message, get_mailer
from app.modules.subs import texts
from app.modules.subs.models import NeedSubEntry, NeedSubscription, NotifyPrefs, UserNotification

log = logging.getLogger(__name__)
DISPATCH_BATCH = 200


def is_synthetic(email: str) -> bool:
    """Заведомо несуществующие адреса (демо-кандидаты каталога) — им уведомления не создаём."""
    return email.endswith(".invalid")


def is_demo_mail(user: User) -> bool:
    return bool(user.is_demo) or user.email.endswith((".invalid", "@jury.example.com"))


def prefs_of(db: Session, user_id: uuid.UUID) -> NotifyPrefs:
    p = db.get(NotifyPrefs, user_id)
    if p is None:
        p = NotifyPrefs(user_id=user_id, push_enabled=True, email_enabled=True, reminders_enabled=True)
        db.add(p)
        db.flush()
    return p


def local(dt: datetime) -> datetime:
    return as_aware(dt) + timedelta(hours=get_settings().subs_tz_offset_h)


def in_quiet_hours(now: datetime) -> bool:
    s = get_settings()
    a, b = s.subs_quiet_from % 24, s.subs_quiet_to % 24
    h = local(now).hour
    if a == b:
        return False
    return h >= a or h < b if a > b else a <= h < b


def add_notification(db: Session, user_id: uuid.UUID, kind: str, dedupe_key: str, title: str, body: str, url: str, *,
                     channels: list[str], digest: str | None = None, payload: dict | None = None,
                     now: datetime | None = None) -> UserNotification | None:
    """Создаёт уведомление; None — такое уже есть (идемпотентно, в том числе при гонке двух обходов)."""
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    t = UserNotification.__table__
    nid = db.execute(insert(t).values(
        id=uuid.uuid4(), user_id=user_id, kind=kind, dedupe_key=dedupe_key, title=title[:255], body=body, url=url,
        payload=payload or {}, channels=channels, digest=digest, created_at=now or utcnow(),
        delivery="pending" if channels else "done",
    ).on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"]).returning(t.c.id)).scalar_one_or_none()
    return db.get(UserNotification, nid) if nid is not None else None


# ------------------------------------------------------------------ отправка
def _send_push(db: Session, user: User, prefs: NotifyPrefs, n: UserNotification) -> str:
    if not prefs.push_enabled:
        return "off"
    devices = db.scalar(select(PushSubscription.id).where(PushSubscription.user_id == user.id).limit(1))
    try:
        custom = (n.payload or {}).get("push") or {}
        ok = push.send_to_user(db, user.id, custom.get("title") or n.title,
                               custom.get("body") or n.body.split("\n")[0][:180], n.url, f"{n.kind}-{n.id}")
    except Exception:  # noqa: BLE001 — push не должен ломать обход
        log.exception("subs: push")
        return "failed"
    if ok:
        return "sent"
    if devices is None:
        return "no_devices"
    return "failed" if get_isettings().push_enabled else "off_platform"


def compose(lines: list[str], url_path: str) -> tuple[str, str]:
    s = get_settings()
    url = f"{s.public_base_url.rstrip('/')}{url_path}"
    text = "Здравствуйте.\n\n" + "\n".join(lines) + f"\n\nОткрыть в кабинете: {url}\n\n— {s.product_name}"
    body = "".join(f"<p>{_html.escape(x)}</p>" if x else "" for x in lines)
    page = (f"<p>Здравствуйте.</p>{body}<p><a href='{_html.escape(url)}' style='color:#FF0053;font-weight:600'>"
            f"Открыть в кабинете</a></p><p style='color:#8A83D1'>— {_html.escape(s.product_name)}</p>")
    return text, page


def _send_email(user: User, prefs: NotifyPrefs, n: UserNotification, subject: str | None = None) -> str:
    if not prefs.email_enabled:
        return "off"
    if is_demo_mail(user):
        return "demo"
    text, page = compose(n.body.split("\n"), n.url)
    try:
        get_mailer().send(Message(to=user.email, subject=subject or n.title, text=text, html=page))
        return "sent"
    except Exception:  # noqa: BLE001
        log.exception("subs: письмо")
        return "failed"


def dispatch(db: Session, now: datetime, user_ids: list[uuid.UUID] | None = None) -> dict:
    """Отправить созданные, но не отправленные уведомления. В тихие часы живым пользователям — после утра."""
    q = select(UserNotification).where(UserNotification.delivery == "pending").order_by(UserNotification.created_at)
    if user_ids is not None:
        q = q.where(UserNotification.user_id.in_(user_ids))
    stats = {"push": 0, "email": 0, "deferred": 0}
    for n in db.scalars(q.limit(DISPATCH_BATCH)).all():
        user = db.get(User, n.user_id)
        if user is None:
            n.delivery = "done"
            continue
        if in_quiet_hours(now) and not is_demo_mail(user):
            stats["deferred"] += 1
            continue
        prefs = prefs_of(db, user.id)
        n.delivery, n.sent_at = "done", now
        db.commit()  # «отправлено» фиксируем до отправки: сбой не приведёт к дублю
        if "push" in n.channels:
            n.push_state = _send_push(db, user, prefs, n)
            stats["push"] += n.push_state == "sent"
        if "email" in n.channels:
            n.email_state = _send_email(user, prefs, n)
            stats["email"] += n.email_state == "sent"
        db.commit()
    return stats


# ------------------------------------------------------------------ дайджест
def digest_cutoff(now: datetime, force: bool) -> datetime:
    """В утренний дайджест входит всё, что накопилось до сегодняшнего часа рассылки (по Москве); позже — в завтрашний."""
    if force:
        return as_aware(now) + timedelta(seconds=1)
    start = local(now).replace(hour=get_settings().subs_digest_hour, minute=0, second=0, microsecond=0)
    return start - timedelta(hours=get_settings().subs_tz_offset_h)


def _due(prefs: NotifyPrefs, kind: str, now: datetime, force: bool) -> bool:
    last = prefs.last_weekly_at if kind == "weekly" else prefs.last_digest_at
    if not force and local(now).hour < get_settings().subs_digest_hour:
        return False
    if last is None:
        return True
    if kind == "weekly":
        return now - as_aware(last) >= timedelta(days=7) - timedelta(hours=2)
    return local(last).date() < local(now).date()


def _digest_text(db: Session, rows: list[UserNotification], kind: str) -> list[str]:
    """Строки письма: по каждой потребности — новые подходящие, затем приглашения и отклики без ответа."""
    lines: list[str] = []
    top_n = get_settings().subs_top_n
    by_need: dict[str, list[UserNotification]] = {}
    for r in rows:
        if r.kind == "new_match":
            by_need.setdefault(r.payload.get("need_title", ""), []).append(r)
    for title, group in by_need.items():
        refs: dict[str, dict] = {}
        for g in group:
            for x in g.payload.get("rows", []):
                refs[x["ref"]] = x
        lines += [f"По потребности «{title}» новых подходящих: {len(refs)} (топ-{top_n}).",
                  *[f"  {texts.match_line(x)}" for x in refs.values()], ""]
    exp = [r for r in rows if r.kind == "inv_expired"]
    if exp:
        lines += ["Приглашения, срок ответа на которые истёк:", *[f"  {r.body}" for r in exp], ""]
    stale = [r for r in rows if r.kind == "app_stale"]
    if stale:
        lines += ["Отклики без ответа:", *[f"  {r.body}" for r in stale], ""]
    lines.append(texts.digest_footer())
    return lines


def run_digests(db: Session, now: datetime, *, force: bool = False, user_ids: list[uuid.UUID] | None = None) -> dict:
    """Письмо-дайджест работодателю: раз в день (с часа subs_digest_hour по Москве, всё накопленное до него), по подпискам
    «раз в неделю» — раз в неделю. Пусто — письма нет. force — для песочницы жюри: не ждать утра."""
    q = select(UserNotification.user_id).where(UserNotification.digest == "queued").distinct()
    if user_ids is not None:
        q = q.where(UserNotification.user_id.in_(user_ids))
    sent = 0
    for uid in db.scalars(q).all():
        user = db.get(User, uid)
        if user is None or user.role != UserRole.employer:
            continue
        prefs = prefs_of(db, uid)
        queued = db.scalars(select(UserNotification).where(UserNotification.user_id == uid,
                                                           UserNotification.digest == "queued")
                            .order_by(UserNotification.created_at)).all()
        cut = digest_cutoff(now, force)
        queued = [r for r in queued if as_aware(r.created_at) < cut]
        for kind in ("daily", "weekly"):
            rows = [r for r in queued if r.payload.get("freq", "daily") == kind]
            if not rows or not _due(prefs, kind, now, force):
                continue
            day = local(now).strftime("%Y-%m-%d")
            lines = _digest_text(db, rows, kind)
            n = add_notification(db, uid, "digest", f"digest:{kind}:{day}", texts.digest_subject(kind),
                                 "\n".join(lines), "/employer/notifications", channels=["email"],
                                 payload={"items": len(rows), "freq": kind}, now=now)
            for r in rows:
                r.digest = "sent"
            if kind == "weekly":
                prefs.last_weekly_at = now
            else:
                prefs.last_digest_at = now
            for r in rows:
                if r.kind == "new_match" and r.payload.get("sub_id"):
                    sub = db.get(NeedSubscription, uuid.UUID(r.payload["sub_id"]))
                    if sub is not None:
                        sub.last_digest_at = now
            db.commit()
            sent += n is not None
    return {"digests": sent}
