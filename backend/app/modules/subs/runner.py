"""Фоновый обход подписок и напоминаний: идемпотентный, с кэшем, под арендой между процессами.

Один обход (tick):
1. забрать пометки «кандидат изменился» (subs_dirty);
2. по каждой включённой подписке решить, нужен ли пересчёт: пересчёт — если есть изменившийся кандидат её
   направления, но не чаще раза в subs_min_recompute_s; страховочный пересчёт — раз в subs_full_refresh_h часов;
   иначе подписка не трогается (кэш);
3. вошедшие в топ-10 → уведомление (push — для «сразу») и строка в дайджест;
4. напоминания Н6; 5. письма-дайджесты; 6. отправка накопленного (тихие часы: живым — после утра).
Запуск: фоновый поток в app.main (subs_tick_interval_s), консоль ``python -m app.modules.subs.runner``,
песочница жюри — runner.tick(db, only_employer=…, force=True).
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import logging
import threading
import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal, as_aware, utcnow
from app.modules.auth.models import User
from app.modules.matching.models import EmployerNeed
from app.modules.profiles.models import CandidateProfile, CandidateSpecialization
from app.modules.assessment.models import SurveyResponse
from app.modules.subs import delivery, reminders, service, texts
from app.modules.subs.models import NeedSubEntry, NeedSubscription, SubsDirty, SubsState

log = logging.getLogger(__name__)
LEASE_KEY = "tick"
LEASE_S = 600


# ------------------------------------------------------------------ аренда
def _acquire(db: Session, now: datetime) -> bool:
    if db.get(SubsState, LEASE_KEY) is None:
        if db.get_bind().dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        db.execute(insert(SubsState.__table__).values(key=LEASE_KEY).on_conflict_do_nothing(index_elements=["key"]))
        db.commit()
    r = db.execute(update(SubsState).where(SubsState.key == LEASE_KEY,
                                           (SubsState.lease_until.is_(None)) | (SubsState.lease_until < now))
                   .values(lease_until=now + timedelta(seconds=LEASE_S)))
    db.commit()
    return r.rowcount == 1


def _release(db: Session, now: datetime, stats: dict) -> None:
    db.execute(update(SubsState).where(SubsState.key == LEASE_KEY).values(lease_until=None, last_run_at=now, stats=stats))
    db.commit()


# ------------------------------------------------------------------ пометки
def _directions(db: Session, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, set[str]]:
    out: dict[uuid.UUID, set[str]] = {u: set() for u in user_ids}
    if not user_ids:
        return out
    for uid, d in db.execute(select(CandidateProfile.user_id, CandidateProfile.current_direction_id)
                             .where(CandidateProfile.user_id.in_(user_ids))).all():
        if d:
            out[uid].add(d)
    for uid, d in db.execute(select(CandidateSpecialization.user_id, CandidateSpecialization.direction_id)
                             .where(CandidateSpecialization.user_id.in_(user_ids))).all():
        out[uid].add(d)
    for uid, d in db.execute(select(SurveyResponse.user_id, SurveyResponse.direction_id)
                             .where(SurveyResponse.user_id.in_(user_ids))).all():
        if d:
            out[uid].add(d)
    return out


def _relevant(req_direction: str | None, dirs: dict[uuid.UUID, set[str]]) -> bool:
    if not dirs:
        return False
    if not req_direction:
        return True
    return any(not d or req_direction in d for d in dirs.values())  # направление кандидата неизвестно — на всякий случай


# ------------------------------------------------------------------ подписки
def _notify_entrants(db: Session, sub: NeedSubscription, need: EmployerNeed, now: datetime) -> int:
    """Вошедшие в топ и ещё не оповещённые → одно уведомление на подписку (push — для «сразу») и строка в дайджест."""
    fresh = db.scalars(select(NeedSubEntry).where(NeedSubEntry.sub_id == sub.id, NeedSubEntry.is_new.is_(True),
                                                  NeedSubEntry.in_top.is_(True), NeedSubEntry.notified_at.is_(None))
                       .order_by(NeedSubEntry.rank)).all()
    if not fresh:
        return 0
    prefs = delivery.prefs_of(db, sub.employer_user_id)
    rows = [{**(e.result or {"ref": e.ref}), "rank": e.rank, "score": e.score} for e in fresh]
    key = "match:{}:{}".format(sub.id, hashlib.sha1("|".join(
        sorted(f"{e.candidate_user_id}@{as_aware(e.entered_at).isoformat()}" for e in fresh)).encode()).hexdigest()[:12])
    p_title, p_body = texts.match_push(need.title, len(fresh))
    instant = sub.frequency == "instant" and prefs.push_enabled
    delivery.add_notification(
        db, sub.employer_user_id, "new_match", key, texts.match_title(len(fresh)),
        texts.match_body(need.title, rows, service.top_n()), f"/employer/needs/{need.id}",
        channels=["push"] if instant else [], digest="queued",
        payload={"sub_id": str(sub.id), "need_id": str(need.id), "need_title": need.title,
                 "freq": "weekly" if sub.frequency == "weekly" else "daily",
                 "push": {"title": p_title, "body": p_body},
                 "rows": [{"ref": r["ref"], "rank": r.get("rank"), "score": r.get("score"),
                           "category_id": r.get("category_id"),
                           "card": {"category": ((r.get("card") or {}).get("category"))}} for r in rows]}, now=now)
    for e in fresh:
        e.notified_at = now
    db.commit()
    return len(fresh)


def process_sub(db: Session, sub: NeedSubscription, now: datetime, dirty_dirs: dict[uuid.UUID, set[str]], *,
                force: bool = False) -> dict:
    need = db.get(EmployerNeed, sub.need_id)
    employer = db.get(User, sub.employer_user_id)
    if need is None or employer is None or not service.active_need(need) or not sub.enabled:
        return {"skipped": True}
    s = get_settings()
    age = (now - as_aware(sub.computed_at)).total_seconds() if sub.computed_at else None
    req, filters = service.definition_of(db, need)
    why = None
    if sub.computed_at is None or sub.baseline_at is None:
        why = "first"
    elif sub.definition_hash != service.definition_hash(req, filters):
        why = "definition"  # работодатель уточнил подборку: база сравнения перестраивается тихо
    elif force:
        why = "force"
    elif age is not None and age >= s.subs_full_refresh_h * 3600:
        why = "full"
    elif _relevant(req.get("direction"), dirty_dirs):
        if age is not None and age < s.subs_min_recompute_s:
            return {"cached": True, "throttled": True}  # слишком рано: пометки останутся до следующего обхода
        why = "dirty"
    if why is None:
        return {"cached": True}
    res = service.refresh(db, sub, need, employer, now, rebase=why in ("first", "definition"))
    res["notified"] = _notify_entrants(db, sub, need, now)
    res["why"] = why
    db.commit()
    return res


def tick(db: Session | None = None, now: datetime | None = None, *, force: bool = False,
         only_employer: uuid.UUID | None = None, reminders_on: bool = True) -> dict:
    """Один обход. only_employer + force — для песочницы жюри (без аренды, дайджест без ожидания утра)."""
    own = db is None
    db = db or SessionLocal()
    now = now or utcnow()
    stats: dict = {"recomputed": 0, "cached": 0, "entered": 0, "notified": 0}
    leased = False
    try:
        if only_employer is None:
            if not _acquire(db, now):
                return {"skipped": "lease"}
            leased = True
        dirty = db.execute(select(SubsDirty.user_id, SubsDirty.at)).all()
        throttled = False
        dirty_dirs = _directions(db, [u for u, _ in dirty])
        q = select(NeedSubscription).where(NeedSubscription.enabled.is_(True))
        if only_employer is not None:
            q = q.where(NeedSubscription.employer_user_id == only_employer)
        for sub in db.scalars(q).all():
            try:
                r = process_sub(db, sub, now, dirty_dirs, force=force)
            except Exception:  # noqa: BLE001 — одна подписка не должна останавливать остальные
                db.rollback()
                log.exception("subs: подписка %s", sub.id)
                continue
            if r.get("cached"):
                stats["cached"] += 1
                throttled = throttled or bool(r.get("throttled"))
            elif not r.get("skipped"):
                stats["recomputed"] += 1
                stats["entered"] += len(r.get("entered", []))
                stats["notified"] += r.get("notified", 0)
        if only_employer is None:
            for uid, at in ([] if throttled else dirty):  # только то, что прочитали: изменившееся за время обхода останется
                db.execute(delete(SubsDirty).where(SubsDirty.user_id == uid, SubsDirty.at == at))
            db.commit()
            if reminders_on:
                stats["reminders"] = reminders.run(db, now)
        users = [only_employer] if only_employer is not None else None
        stats["digest"] = delivery.run_digests(db, now, force=force, user_ids=users)
        stats["dispatch"] = delivery.dispatch(db, now, user_ids=users)
        return stats
    finally:
        if leased:
            try:
                _release(db, now, stats)
            except Exception:  # noqa: BLE001
                db.rollback()
        if own:
            db.close()


# ------------------------------------------------------------------ фон и консоль
_started: list[threading.Thread] = []


def start_background(interval_s: int) -> threading.Thread | None:
    """Один фоновый поток на процесс; interval_s <= 0 — выключено (тесты). Между процессами — аренда в subs_state."""
    if interval_s <= 0 or _started:
        return None

    def loop() -> None:
        import time

        time.sleep(min(30, interval_s))
        while True:
            try:
                st = tick()
                if st.get("entered") or st.get("reminders") and any(st["reminders"].values()):
                    log.info("подписки: %s", st)
            except Exception:  # noqa: BLE001
                log.exception("подписки: обход не удался")
            time.sleep(interval_s)

    t = threading.Thread(target=loop, name="subs-tick", daemon=True)
    _started.append(t)
    t.start()
    return t


if __name__ == "__main__":
    from app.core.db import get_engine

    get_engine()
    print(tick())
