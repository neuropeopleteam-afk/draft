"""Демо взаимного подбора в песочнице жюри: интересы Марии, Ильи и Артёма, отзывы по первой потребности, ссылка
руководителю с двумя отметками. Сбой не ломает сид жюри (как кубки и задания)."""
from __future__ import annotations

from datetime import timedelta
import hashlib
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.modules.matching.models import SelectionVersion
from app.modules.mutual.models import CandidatePreference, SelectionFeedback, SelectionShare, ShareReaction
from app.modules.mutual.service import SHARE_TTL_DAYS
from app.modules.profiles.models import CandidateProfile

log = logging.getLogger(__name__)

PREFS = {  # персона → (готовность, интересы по стеку, задачи)
    "maria": ("active", ["python", "fastapi", "postgresql", "kafka"], ["payments", "highload"]),
    "ilya": ("open", ["python", "fastapi", "redis"], ["integrations"]),
    "artem": ("active", ["python", "django"], ["new_product"]),
}


def seed_jury_mutual(db: Session, eu, needs: list, maria: CandidateProfile, ilya: CandidateProfile,
                     artem: CandidateProfile) -> dict:
    try:
        return _seed(db, eu, needs, maria, ilya, artem)
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("jury: demo mutual matching failed")
        return {}


def _seed(db: Session, eu, needs: list, maria, ilya, artem) -> dict:
    for p, key in ((maria, "maria"), (ilya, "ilya"), (artem, "artem")):
        st, tags, tasks = PREFS[key]
        db.merge(CandidatePreference(user_id=p.user_id, offers_status=st, interest_tags=tags, interest_tasks=tasks,
                                     salary_signal=True, updated_at=utcnow()))
    db.flush()
    if not needs:
        db.commit()
        return {"prefs": 3}
    need = needs[0]
    v = db.scalar(select(SelectionVersion).where(SelectionVersion.need_id == need.id, SelectionVersion.version == 1))
    refs = [r["ref"] for r in (v.results if v else [])]
    profiles = {p.public_ref: p for p in db.scalars(select(CandidateProfile).where(CandidateProfile.public_ref.in_(refs)))}
    fb = []
    if maria.public_ref in refs:
        fb.append((maria.public_ref, "fit", None, "Сильный FastAPI и подтверждённый PostgreSQL"))
    # «не подходит»: первый в выдаче, кто хочет только офис (потребность — удалённо); иначе — последний в выдаче
    office = next((r for r in refs if r != maria.public_ref and profiles.get(r) is not None
                   and profiles[r].work_format.value == "office"), None)
    other = office or next((r for r in reversed(refs) if r not in (maria.public_ref, ilya.public_ref)), None)
    if other:
        fb.append((other, "unfit", "format" if office else "skill",
                   "Хочет только офис, у нас удалёнка" if office else "Нет опыта с Redis"))
    for ref, verdict, reason, comment in fb:
        db.add(SelectionFeedback(need_id=need.id, version=1, candidate_ref=ref, verdict=verdict, reason=reason,
                                 comment=comment, created_by=eu.id))
    share = None
    if v:
        share = SelectionShare(need_id=need.id, version=1, label="Руководитель команды платежей (демо)",
                               token_hash=hashlib.sha256(secrets.token_urlsafe(24).encode()).hexdigest(),
                               created_by=eu.id, expires_at=utcnow() + timedelta(days=SHARE_TTL_DAYS), views=1,
                               last_viewed_at=utcnow())
        db.add(share)
        db.flush()
        marks = [(maria.public_ref, "interesting", "Зовём на техинтервью: платежи — её профиль")]
        if ilya.public_ref in refs:
            marks.append((ilya.public_ref, "interesting", "Посмотреть интеграции с банками на интервью"))
        if other:
            marks.append((other, "no", "Не подходит по формату"))
        for ref, verdict, comment in marks:
            if ref in refs:
                db.add(ShareReaction(share_id=share.id, candidate_ref=ref, verdict=verdict, comment=comment,
                                     author="Руководитель платежей"))
    db.commit()
    return {"prefs": 3, "feedback": len(fb), "share": bool(share)}
