"""Временные учётки для нагрузочного теста (запуск внутри контейнера api):
   python - setup N  → JSON {candidates:[{token}], employers:[{token, needs:[[need_id, version]]}], analysts:[{token}],
                        refs:[...]}
   python - cleanup  → удалить loadtest-*@demo.invalid
Кандидаты нагрузочного теста скрыты от работодателей (visible_to_employers=False), помечены is_demo."""
import json
import sys

from sqlalchemy import delete, select

from app.core.db import SessionLocal, get_engine, utcnow
from app.core.enums import ConsentKind, UserRole
from app.core.legal import CONSENT_VERSION
from app.core.security import create_access_token
from app.modules.auth.models import Consent, User
from app.modules.profiles.models import CandidateProfile, EmployerProfile
from app.modules.profiles.refs import new_public_ref
from app.modules.assessment.models import SurveyResponse
from app.modules.matching.models import EmployerNeed, SelectionVersion

import app.models  # noqa: F401,E402 — все модели в реестре SQLAlchemy

PREFIX = "loadtest-"
get_engine()


def setup(n: int) -> dict:
    dirs = ["backend", "frontend", "data_ml", "qa", "security"]
    out = {"candidates": [], "employers": [], "refs": []}
    with SessionLocal() as db:
        for i in range(n):
            email = f"{PREFIX}{i:03d}@demo.invalid"
            u = db.scalar(select(User).where(User.email == email))
            if u is None:
                u = User(email=email, password_hash="!", role=UserRole.candidate, is_email_verified=True,
                         email_verified_at=utcnow(), is_demo=True)
                db.add(u)
                db.flush()
                for kind in (ConsentKind.processing, ConsentKind.publication):
                    db.add(Consent(user_id=u.id, kind=kind, document_version=CONSENT_VERSION))
                d = dirs[i % len(dirs)]
                db.add(CandidateProfile(user_id=u.id, full_name=f"Нагрузка {i:03d}", privacy={}, visible_to_employers=False,
                                        public_ref=new_public_ref(db), onboarding_completed_at=utcnow(), roles=["developer"],
                                        experience_years=2.0, headline="нагрузочный тест"))
                db.add(SurveyResponse(user_id=u.id, direction_id=d, claimed_grade_id="middle", experience_years=2.0,
                                      answers={"stack": {"python": 2, "sql": 2} if d != "frontend" else {"typescript": 2},
                                               "roles": ["developer"], "loadtest": True}))
                db.flush()
            out["candidates"].append({"token": create_access_token(u.id, "candidate", u.token_version)[0]})
        emps = db.scalars(select(User).where(User.is_demo.is_(True), User.role == UserRole.employer,
                                             User.email.like("demo-employer-%"))).all()
        for e in emps:
            ep = db.get(EmployerProfile, e.id)
            needs = db.execute(select(SelectionVersion.need_id, SelectionVersion.version)
                               .join(EmployerNeed, EmployerNeed.id == SelectionVersion.need_id)
                               .where(EmployerNeed.company_id == ep.company_id)).all() if ep else []
            out["employers"].append({"token": create_access_token(e.id, "employer", e.token_version)[0],
                                     "needs": [[str(a), b] for a, b in needs]})
        # аналитик ФСП (кабинет ФСП) — временная учётка с тем же префиксом, удаляется cleanup
        email = f"{PREFIX}fsp@demo.invalid"
        a = db.scalar(select(User).where(User.email == email))
        if a is None:
            a = User(email=email, password_hash="!", role=UserRole.fsp_analyst, is_email_verified=True,
                     email_verified_at=utcnow(), is_demo=True)
            db.add(a)
            db.flush()
        out["analysts"] = [{"token": create_access_token(a.id, "fsp_analyst", a.token_version)[0]}]
        out["refs"] = [r for (r,) in db.execute(select(CandidateProfile.public_ref).join(User, User.id == CandidateProfile.user_id)
                                                 .where(User.is_demo.is_(True), CandidateProfile.visible_to_employers.is_(True),
                                                        CandidateProfile.current_category_id.is_not(None)).limit(150))]
        db.commit()
    return out


def cleanup() -> dict:
    with SessionLocal() as db:
        n = db.execute(delete(User).where(User.email.like(f"{PREFIX}%@demo.invalid"))).rowcount
        db.commit()
    return {"deleted_users": n}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "setup"
    print(json.dumps(setup(int(sys.argv[2]) if len(sys.argv) > 2 else 40) if cmd == "setup" else cleanup()))
