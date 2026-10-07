"""Общий слой двух направлений: без зависимости от конкретного движка и набора грейдов."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import as_aware
from app.core.errors import api_error
from app.modules.catalog.seed_data import DIRECTIONS, GRADES
from app.modules.profiles.models import CandidateProfile, CandidateSpecialization

MAX_SPECIALIZATIONS = 2


def legacy_specialization(p: CandidateProfile) -> CandidateSpecialization | None:
    """Read-only переходный путь для старых сидов/интеграций, пишущих current_*."""
    if not p.current_direction_id:
        return None
    provisional = bool(getattr(p, "grade_provisional", False)) and bool(p.current_category_id)
    return CandidateSpecialization(
        user_id=p.user_id, direction_id=p.current_direction_id, is_primary=True,
        grade_id=p.current_grade_id, category_id=p.current_category_id,
        status=("provisional" if provisional else "confirmed") if p.current_category_id else "declared",
        rating_score=p.rating_score, locked_until=p.grade_locked_until,
    )


def ensure_specialization(db: Session, p: CandidateProfile, direction: str) -> CandidateSpecialization:
    # Сериализуем изменения одного профиля в PostgreSQL: лимит два и единственное основное.
    db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == p.user_id).with_for_update())
    rows = list(db.scalars(select(CandidateSpecialization).where(CandidateSpecialization.user_id == p.user_id)))
    if p.current_direction_id and not any(r.direction_id == p.current_direction_id for r in rows):
        legacy = legacy_specialization(p)
        db.add(legacy)
        rows.append(legacy)
        db.flush()
    for r in rows:
        if r.direction_id == direction:
            return r
    if len(rows) >= MAX_SPECIALIZATIONS:
        raise api_error(409, "specialization_limit",
                        "Можно подтвердить два направления. Для теста выберите основное или дополнительное.")
    r = CandidateSpecialization(user_id=p.user_id, direction_id=direction,
                                is_primary=not rows, status="declared")
    db.add(r)
    db.flush()
    return r


def sync_primary(p: CandidateProfile, r: CandidateSpecialization) -> None:
    """Дополнительная категория никогда не затирает основной грейд и его таймер."""
    if r.is_primary:
        p.current_direction_id = r.direction_id
        p.current_grade_id = r.grade_id
        p.current_category_id = r.category_id
        p.grade_locked_until = r.locked_until
        p.rating_score = r.rating_score
        # статус «Junior (предварительно)» основного направления зеркалируется в профиль (старые клиенты, подбор)
        p.grade_provisional = r.status == "provisional" and bool(r.category_id)


def summary(r: CandidateSpecialization, test=None) -> dict:
    v = test.value if test else {}
    return {
        "direction": r.direction_id, "direction_title": DIRECTIONS.get(r.direction_id, r.direction_id),
        "is_primary": r.is_primary, "grade": r.grade_id, "grade_title": GRADES.get(r.grade_id or ""),
        "category_id": r.category_id,
        "category_title": (f"{DIRECTIONS.get(r.direction_id, r.direction_id)} · {GRADES.get(r.grade_id, r.grade_id)}"
                           + (" (предварительно)" if r.status == "provisional" else "")) if r.category_id else None,
        "status": r.status, "provisional": r.status == "provisional" and bool(r.category_id),
        "confirmed_by": "test" if r.status == "confirmed" and (test or r.test_session_id) else None,
        "theta": r.theta if r.theta is not None else v.get("theta"),
        "se": r.theta_se if r.theta_se is not None else v.get("se"),
        "rating_score": r.rating_score,
        "locked_until": as_aware(r.locked_until).isoformat() if r.locked_until else None,
        "test_session_id": str(r.test_session_id) if r.test_session_id else v.get("session_id"),
        "confirmed_at": as_aware(r.confirmed_at).isoformat() if r.confirmed_at else None,
        "test": {
            "theta": v.get("theta"), "se": v.get("se"), "correct": v.get("correct"), "answered": v.get("answered"),
            "date": test.created_at.date().isoformat(), "engine": v.get("engine"), "level": "T1",
        } if test else None,
    }
