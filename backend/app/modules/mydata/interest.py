"""Обезличенная отметка интереса: «за неделю карточку посмотрели N работодателей, в M подборках, K зондов».

Что считаем (окно — 7 суток от «сейчас», рядом — предыдущие 7 суток для сравнения):

* N — число различных работодателей (компаний), открывших карточку кандидата (``card_view``). Повторные открытия
  одной компанией в течение 6 часов в событие не пишутся; для N это ничего не меняет — считаются различные компании;
* M — в скольких подборках кандидат оказался в выдаче (``selection``): одна потребность работодателя — одна подборка,
  сколько бы раз он ни уточнял фильтры; плюс лучшее место за неделю;
* K — сколько зондов (коротких задач с вилкой) кандидату отправили (из таблицы ``probes``, отдельных событий нет).

Названия компаний не выдаются никому: кандидат получает только числа. В событии лежит ключ компании (для подсчёта
различных), а не её название. Демо-данные песочниц жюри помечены ``is_demo``-учётками и случайными ключами работодателей.
Поиск (``/api/employer/candidates``) в счётчик не входит: это просмотр списка, а не карточки и не подборки.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
import random
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.db import as_aware, utcnow
from app.modules.invitations.models import Probe
from app.modules.mydata.models import InterestEvent
from app.modules.profiles.models import CandidateProfile

log = logging.getLogger("mydata.interest")

WINDOW_DAYS = 7
CARD_DEDUP = timedelta(hours=6)
KEEP_DAYS = 90
_last_purge: datetime | None = None  # чистка старых событий — не чаще раза в сутки на процесс


# ------------------------------------------------------------------ запись событий (вызывается из кабинета работодателя)

def record_card_view(db: Session, company_id: uuid.UUID, candidate_user_id: uuid.UUID) -> None:
    """Работодатель открыл карточку кандидата. Сбой записи не должен ломать карточку."""
    try:
        since = utcnow() - CARD_DEDUP
        if db.scalar(select(InterestEvent.id).where(
                InterestEvent.candidate_user_id == candidate_user_id, InterestEvent.kind == "card_view",
                InterestEvent.company_key == company_id, InterestEvent.created_at >= since).limit(1)):
            return
        db.add(InterestEvent(candidate_user_id=candidate_user_id, kind="card_view", company_key=company_id))
        db.commit()
    except Exception:  # noqa: BLE001 — счётчик необязателен: карточка важнее
        db.rollback()
        log.warning("interest: card_view не записан", exc_info=True)


def record_selection(db: Session, company_id: uuid.UUID, need_id: uuid.UUID, results: list[dict]) -> None:
    """Версия подборки построена: все кандидаты из её выдачи получают событие «в подборке» (одно в сутки на потребность)."""
    try:
        ranks = {r["ref"]: r.get("rank") for r in results if r.get("ref")}
        if not ranks:
            return
        users = dict(db.execute(select(CandidateProfile.public_ref, CandidateProfile.user_id)
                                .where(CandidateProfile.public_ref.in_(list(ranks)))).all())
        if not users:
            return
        since = utcnow() - timedelta(hours=24)
        have = set(db.scalars(select(InterestEvent.candidate_user_id).where(
            InterestEvent.kind == "selection", InterestEvent.need_key == need_id, InterestEvent.created_at >= since,
            InterestEvent.candidate_user_id.in_(list(users.values())))).all())
        rows = [InterestEvent(candidate_user_id=uid, kind="selection", company_key=company_id, need_key=need_id,
                              rank=min(int(ranks[ref] or 0), 32000) or None)
                for ref, uid in users.items() if uid not in have]
        if rows:
            db.add_all(rows)
        _purge_sometimes(db)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.warning("interest: selection не записан", exc_info=True)


def _purge_sometimes(db: Session) -> None:
    """Старше 90 дней события не нужны: чистим при построении подборки, не чаще раза в сутки (без планировщика)."""
    global _last_purge
    now = utcnow()
    if _last_purge is None or now - _last_purge > timedelta(days=1):
        _last_purge = now
        purge_old(db)


def purge_old(db: Session, days: int = KEEP_DAYS) -> int:
    """События старше срока не нужны для недельной отметки — удаляем (минимизация хранения)."""
    res = db.execute(delete(InterestEvent).where(InterestEvent.created_at < utcnow() - timedelta(days=days)))
    return res.rowcount or 0


# ------------------------------------------------------------------ чтение

def _window(db: Session, user_id: uuid.UUID, start: datetime, end: datetime) -> dict:
    base = (InterestEvent.candidate_user_id == user_id, InterestEvent.created_at >= start, InterestEvent.created_at < end)
    employers = db.scalar(select(func.count(func.distinct(InterestEvent.company_key)))
                          .where(*base, InterestEvent.kind == "card_view")) or 0
    selections = db.scalar(select(func.count(func.distinct(InterestEvent.need_key)))
                           .where(*base, InterestEvent.kind == "selection")) or 0
    best = db.scalar(select(func.min(InterestEvent.rank)).where(*base, InterestEvent.kind == "selection"))
    probes = db.scalar(select(func.count()).select_from(Probe).where(
        Probe.candidate_user_id == user_id, Probe.created_at >= start, Probe.created_at < end)) or 0
    return {"employers": int(employers), "selections": int(selections), "probes": int(probes),
            "best_rank": int(best) if best else None}


def summary(db: Session, user_id: uuid.UUID, now: datetime | None = None) -> dict:
    """Числа за последние 7 суток, предыдущие 7 суток и разбивка по дням (UTC) для мини-диаграммы."""
    now = as_aware(now) or utcnow()
    start, prev_start = now - timedelta(days=WINDOW_DAYS), now - timedelta(days=2 * WINDOW_DAYS)
    cur = _window(db, user_id, start, now + timedelta(seconds=1))
    prev = _window(db, user_id, prev_start, start)
    rows = db.execute(select(InterestEvent.created_at, InterestEvent.kind).where(
        InterestEvent.candidate_user_id == user_id, InterestEvent.created_at >= start)).all()
    days = [(now - timedelta(days=i)).date() for i in range(WINDOW_DAYS - 1, -1, -1)]
    by_day = {d.isoformat(): {"date": d.isoformat(), "views": 0, "selections": 0} for d in days}
    for at, kind in rows:
        d = as_aware(at).date().isoformat()
        if d in by_day:
            by_day[d]["views" if kind == "card_view" else "selections"] += 1
    p = db.get(CandidateProfile, user_id)
    return {
        "period_days": WINDOW_DAYS,
        "employers_viewed": cur["employers"], "selections": cur["selections"], "probes": cur["probes"],
        "best_rank": cur["best_rank"],
        "previous": {"employers_viewed": prev["employers"], "selections": prev["selections"], "probes": prev["probes"]},
        "by_day": list(by_day.values()),
        "visible_to_employers": bool(p and p.visible_to_employers),
        "has_category": bool(p and p.current_category_id),
        "note": ("Названия компаний не показываются: только числа. Карточку считают по различным работодателям, "
                 "подборку — по потребностям (повторное уточнение одной потребности — одна подборка), "
                 "задания с вилкой — отправленные вам за те же 7 суток."),
    }


# ------------------------------------------------------------------ демо-данные песочниц жюри

def seed_demo(db: Session, user_id: uuid.UUID, *, employers: int, selections: int, best_rank: int,
              previous_employers: int = 0, seed: int = 0) -> None:
    """Правдоподобные события за неделю для демо-кандидата (учётка is_demo). Ключи работодателей и потребностей —
    случайные, не связаны с настоящими компаниями; названий нет. Идемпотентно по кандидату: прежние события стираются."""
    rnd = random.Random(f"interest:{seed}:{user_id}")
    db.execute(delete(InterestEvent).where(InterestEvent.candidate_user_id == user_id))
    now = utcnow()
    company_keys = [uuid.UUID(int=rnd.getrandbits(128), version=4) for _ in range(employers + previous_employers)]
    rows: list[InterestEvent] = []
    for i, key in enumerate(company_keys[:employers]):
        rows.append(InterestEvent(candidate_user_id=user_id, kind="card_view", company_key=key,
                                  created_at=now - timedelta(days=rnd.randint(0, 6), hours=rnd.randint(1, 20) + i % 3)))
    for key in company_keys[employers:]:  # прошлая неделя — для сравнения «было / стало»
        rows.append(InterestEvent(candidate_user_id=user_id, kind="card_view", company_key=key,
                                  created_at=now - timedelta(days=rnd.randint(8, 13), hours=rnd.randint(0, 20))))
    for j in range(selections):
        rank = best_rank if j == 0 else best_rank + rnd.randint(1, 14)
        rows.append(InterestEvent(candidate_user_id=user_id, kind="selection", company_key=rnd.choice(company_keys or [uuid.uuid4()]),
                                  need_key=uuid.UUID(int=rnd.getrandbits(128), version=4), rank=rank,
                                  created_at=now - timedelta(days=rnd.randint(0, 6), hours=rnd.randint(1, 22))))
    db.add_all(rows)
    db.flush()
