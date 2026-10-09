"""Подписка на потребность: условия подборки, пересчёт топ-10 с кэшем, «новые подходящие», отметка «просмотрено».

Идемпотентность: кандидат попадает в «новые» один раз (строка need_sub_entries уникальна по паре подписка–кандидат),
повторный пересчёт на тех же данных ничего не меняет. Вход в топ после возврата считается новым, только если
кандидат отсутствовал в топе не меньше REENTRY_DAYS дней. Условия подборки (требования и фильтры) сменились —
база сравнения перестраивается тихо, без уведомлений.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import as_aware, utcnow
from app.core.enums import NeedStatus
from app.modules.auth.models import User
from app.modules.jury import scope as jury_scope
from app.modules.matching import ranking
from app.modules.matching.models import EmployerNeed, SelectionVersion
from app.modules.profiles.models import CandidateProfile
from app.modules.subs.models import FREQUENCIES, NeedSubEntry, NeedSubscription

REENTRY_DAYS = 7
_IGNORED_REQ = {"evidence", "review", "bias", "suggested_text", "coverage", "llm", "method", "salary_net"}


def top_n() -> int:
    return max(1, int(get_settings().subs_top_n))


def sandbox_of(email: str | None) -> str | None:
    """Песочница жюри по почте работодателя: подборка считается по её кандидатам, как в запросе работодателя."""
    persona, sid = jury_scope.parse(email)
    return sid or None


def definition_of(db: Session, need: EmployerNeed) -> tuple[dict, dict]:
    """Условия подборки подписки — последняя версия подборки (то, что работодатель сейчас смотрит и уточняет)."""
    v = db.scalar(select(SelectionVersion).where(SelectionVersion.need_id == need.id)
                  .order_by(SelectionVersion.version.desc()).limit(1))
    if v is None:
        return dict(need.requirements or {}), {}
    return dict(v.requirements or need.requirements or {}), dict(v.filters or {})


def definition_hash(req: dict, filters: dict) -> str:
    core = {k: v for k, v in req.items() if k not in _IGNORED_REQ}
    raw = json.dumps({"req": core, "filters": filters, "algo": ranking.ALGORITHM_VERSION}, sort_keys=True,
                     ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode()).hexdigest()


def get_sub(db: Session, need_id: uuid.UUID) -> NeedSubscription | None:
    return db.scalar(select(NeedSubscription).where(NeedSubscription.need_id == need_id))


def compute_top(db: Session, need: EmployerNeed, employer: User) -> tuple[list[dict], str]:
    req, filters = definition_of(db, need)
    with jury_scope.use(sandbox_of(employer.email)):
        sel = ranking.build_selection(db, req, filters, limit=top_n())
    return sel["results"], definition_hash(req, filters)


def refresh(db: Session, sub: NeedSubscription, need: EmployerNeed, employer: User, now: datetime, *,
            rebase: bool = False) -> dict:
    """Пересчитать топ-10 подписки и сравнить с прежним. rebase — всё, что в топе сейчас, считать уже известным."""
    results, dh = compute_top(db, need, employer)
    rebase = rebase or sub.baseline_at is None or sub.definition_hash != dh
    refs = [r["ref"] for r in results]
    uid_by_ref = dict(db.execute(select(CandidateProfile.public_ref, CandidateProfile.user_id)
                                 .where(CandidateProfile.public_ref.in_(refs))).all()) if refs else {}
    entries = {e.candidate_user_id: e for e in db.scalars(select(NeedSubEntry).where(NeedSubEntry.sub_id == sub.id)).all()}
    entered, left, current = [], [], set()
    for r in results:
        uid = uid_by_ref.get(r["ref"])
        if uid is None:
            continue
        current.add(uid)
        e = entries.get(uid)
        if e is None:
            e = NeedSubEntry(sub_id=sub.id, candidate_user_id=uid, ref=r["ref"], in_top=True, is_new=not rebase,
                             rank=r["rank"], score=r["score"], result=r, first_seen_at=now, entered_at=now,
                             seen_at=now if rebase else None, notified_at=now if rebase else None)
            db.add(e)
            entries[uid] = e
            if not rebase:
                entered.append(e)
            continue
        if not e.in_top:  # вернулся в топ
            away = now - as_aware(e.left_at) if e.left_at else timedelta(days=REENTRY_DAYS)
            e.in_top, e.entered_at, e.left_at = True, now, None
            if not rebase and away >= timedelta(days=REENTRY_DAYS):
                e.is_new, e.seen_at, e.notified_at = True, None, None
                entered.append(e)
        e.rank, e.score, e.result = r["rank"], r["score"], r
    for uid, e in entries.items():
        if e.in_top and uid not in current:
            e.in_top, e.left_at, e.is_new, e.rank = False, now, False, None
            left.append(e.ref)
    new_top = [{"ref": r["ref"], "rank": r["rank"], "score": r["score"]} for r in results]
    changed = [x["ref"] for x in new_top] != [x["ref"] for x in (sub.top or [])]
    sub.top, sub.computed_at, sub.definition_hash = new_top, now, dh
    if sub.baseline_at is None or rebase:
        sub.baseline_at = now
    db.flush()
    return {"entered": [e.ref for e in entered], "left": left, "changed": changed, "rebased": rebase}


def subscribe(db: Session, need: EmployerNeed, user: User, *, enabled: bool = True, frequency: str | None = None,
              now: datetime | None = None) -> NeedSubscription:
    """Включить, выключить или изменить подписку. Первое включение и повторное после выключения — база сравнения
    «кто в топе сейчас» (ничто из этого не считается новым)."""
    now = now or utcnow()
    if frequency is not None and frequency not in FREQUENCIES:
        raise ValueError("frequency")
    sub = get_sub(db, need.id)
    was_on = bool(sub and sub.enabled)
    if sub is None:
        sub = NeedSubscription(need_id=need.id, employer_user_id=user.id, enabled=enabled,
                               frequency=frequency or "instant", top=[])
        db.add(sub)
        db.flush()
    else:
        sub.enabled = enabled
        if frequency is not None:
            sub.frequency = frequency
    if enabled and not was_on:
        refresh(db, sub, need, user, now, rebase=True)
        for e in db.scalars(select(NeedSubEntry).where(NeedSubEntry.sub_id == sub.id, NeedSubEntry.is_new.is_(True))).all():
            e.is_new = False  # повторное включение: прежние отметки «новый» не переносим
    db.commit()
    return sub


def new_cutoff(now: datetime | None = None) -> datetime:
    return (now or utcnow()) - timedelta(days=get_settings().subs_new_ttl_days)


def new_entries(db: Session, sub: NeedSubscription, now: datetime | None = None) -> list[NeedSubEntry]:
    rows = db.scalars(select(NeedSubEntry).where(NeedSubEntry.sub_id == sub.id, NeedSubEntry.in_top.is_(True),
                                                 NeedSubEntry.is_new.is_(True))
                      .order_by(NeedSubEntry.rank)).all()
    cut = new_cutoff(now)
    return [e for e in rows if as_aware(e.entered_at) >= cut]


def new_counts(db: Session, user_id: uuid.UUID, now: datetime | None = None) -> dict[uuid.UUID, int]:
    """need_id → число новых подходящих по подпискам работодателя (без вызова пересчёта)."""
    q = (select(NeedSubscription.need_id, func.count(NeedSubEntry.id))
         .join(NeedSubEntry, NeedSubEntry.sub_id == NeedSubscription.id)
         .where(NeedSubscription.employer_user_id == user_id, NeedSubscription.enabled.is_(True),
                NeedSubEntry.in_top.is_(True), NeedSubEntry.is_new.is_(True),
                NeedSubEntry.entered_at >= new_cutoff(now)).group_by(NeedSubscription.need_id))
    return {k: v for k, v in db.execute(q).all()}


def mark_seen(db: Session, sub: NeedSubscription, refs: list[str] | None = None, now: datetime | None = None) -> int:
    now = now or utcnow()
    n = 0
    for e in db.scalars(select(NeedSubEntry).where(NeedSubEntry.sub_id == sub.id, NeedSubEntry.is_new.is_(True))).all():
        if refs is None or e.ref in refs:
            e.is_new, e.seen_at = False, now
            n += 1
    db.commit()
    return n


def sub_out(db: Session, need: EmployerNeed, sub: NeedSubscription | None, now: datetime | None = None) -> dict:
    """Состояние подписки для кабинета: настройки, когда проверено, новые подходящие (обезличенные строки подборки)."""
    base = {"need_id": str(need.id), "need_status": need.status.value, "top_n": top_n(),
            "frequencies": [{"id": k, "title": v} for k, v in FREQUENCIES.items()]}
    if sub is None:
        return {**base, "exists": False, "enabled": False, "frequency": "instant", "new_count": 0, "new": [],
                "new_refs": [], "in_top": 0, "computed_at": None, "baseline_at": None}
    items = new_entries(db, sub, now) if sub.enabled else []
    return {**base, "exists": True, "enabled": sub.enabled, "frequency": sub.frequency,
            "frequency_title": FREQUENCIES[sub.frequency], "new_count": len(items),
            "new": [{**(e.result or {"ref": e.ref}), "rank": e.rank, "score": e.score,
                     "entered_at": as_aware(e.entered_at).isoformat()} for e in items],
            "new_refs": [e.ref for e in items], "in_top": len(sub.top or []),
            "computed_at": as_aware(sub.computed_at).isoformat() if sub.computed_at else None,
            "baseline_at": as_aware(sub.baseline_at).isoformat() if sub.baseline_at else None}


def active_need(need: EmployerNeed) -> bool:
    return need.status == NeedStatus.active
