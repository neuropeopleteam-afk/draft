"""Демо для «Кабинета ФСП»: учётка аналитика и история приглашений демо-компаний демо-кандидатам.

Основные демо-данные (app.modules.demo.seed) приглашений не содержат, а аналитике нужны офферы с вилками.
Генератор создаёт ~120 приглашений за 31–150 дней до запуска (вне 30-дневного окна повтора — не мешает
живым приглашениям): вероятность приглашения растёт с рейтингом, вилки — вокруг рыночного диапазона
категории с множителем компании, ответ кандидата зависит от вилки и его скрытого минимума. Спрос по
категориям разный, в части категорий приглашённых меньше 5 — видно подавление малых групп.
Позиции помечены «(демо)», удаляются командой --delete.

Запуск: python -m app.fsp_cabinet.demo [--reset | --delete]   (заодно создаёт демо-кубки app.cup.demo)
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import math
import random
import secrets
import threading

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_engine, utcnow
from app.core.enums import InvitationStatus, UserRole
from app.modules.auth.models import User
from app.modules.catalog.models import Category
from app.modules.invitations.models import Invitation, InvitationEvent
from app.modules.matching.models import EmployerNeed
from app.modules.profiles.models import CandidateProfile, Company, EmployerProfile

ANALYST_EMAIL = "fsp-analyst@jury.example.com"
MARK = " (демо)"
DEMAND = {"backend.junior": 7, "backend.middle": 16, "backend.senior": 9, "frontend.junior": 6,
          "frontend.middle": 12, "frontend.senior": 7, "data_ml.junior": 5, "data_ml.middle": 11,
          "data_ml.senior": 6, "qa.junior": 5, "qa.middle": 8, "qa.senior": 3, "security.junior": 2,
          "security.middle": 9, "security.senior": 6}
POSITIONS = {"backend": "Backend-разработчик", "frontend": "Frontend-разработчик", "data_ml": "Data Scientist / ML",
             "qa": "QA-инженер", "security": "Специалист по ИБ"}
GRADE_T = {"junior": "Junior", "middle": "Middle", "senior": "Senior"}
_mx = threading.Lock()


def ensure_analyst(db: Session) -> User:
    u = db.scalar(select(User).where(User.email == ANALYST_EMAIL))
    if u is None:
        from app.core.security import hash_password
        from app.modules.demo.seed import _user

        u = _user(db, ANALYST_EMAIL, UserRole.fsp_analyst, hash_password(secrets.token_urlsafe(24)))
        db.commit()
    return u


def _demo_companies(db: Session) -> list[tuple[Company, User]]:
    out = []
    for c in db.scalars(select(Company).where(Company.is_demo.is_(True), Company.name.like("Демо: %"))
                        .order_by(Company.name)).all():
        ep = db.scalar(select(EmployerProfile).where(EmployerProfile.company_id == c.id))
        u = db.get(User, ep.user_id) if ep else None
        if u:
            out.append((c, u))
    return out


def _fsp_preference(db: Session) -> dict:
    """Модель поведения демо-работодателей (гипотеза, а не вывод): подтверждённые призовые места ФСП повышают шанс
    приглашения сверх рейтинга, участие — немного. На реальных данных кабинет покажет то, что есть."""
    from app.modules.fsp.models import FspAchievement, FspPassport

    out: dict = {}
    for uid, place in db.execute(select(FspPassport.user_id, FspAchievement.place).join(
            FspAchievement, FspAchievement.passport_id == FspPassport.id).where(FspAchievement.verified.is_(True))).all():
        f = 1.9 if (place or 99) <= 3 else 1.35
        out[uid] = max(out.get(uid, 1.0), f)
    return out


def has_demo_invitations(db: Session) -> bool:
    return db.scalar(select(Invitation.id).where(Invitation.position_title.like(f"%{MARK}")).limit(1)) is not None


def seed_invitations(db: Session, rng_seed: int = 20261011) -> int:
    rnd = random.Random(rng_seed)
    comps = _demo_companies(db)
    if not comps:
        return 0
    mult = {c.id: round(0.88 + 0.27 * random.Random(str(c.name)).random(), 3) for c, _ in comps}
    need_dirs: dict = {}
    for n in db.scalars(select(EmployerNeed).where(EmployerNeed.company_id.in_([c.id for c, _ in comps]))).all():
        need_dirs.setdefault(n.company_id, set()).add(n.direction_id)
    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    fsp_pref = _fsp_preference(db)
    now = utcnow()
    made = 0
    for cid, n in DEMAND.items():
        cat = cats.get(cid)
        pool = db.scalars(select(CandidateProfile).join(User, User.id == CandidateProfile.user_id).where(
            CandidateProfile.current_category_id == cid, User.is_demo.is_(True),
            User.email.like("%@demo.invalid"))).all()
        pool = sorted(pool, key=lambda p: str(p.user_id))
        if not pool or cat is None:
            continue
        d = cid.split(".")[0]
        cw = [3.0 if d in need_dirs.get(c.id, ()) else 0.6 for c, _ in comps]
        pw = [math.exp(3.0 * ((p.rating_score or 0.5) - 0.5)) * fsp_pref.get(p.user_id, 1.0) for p in pool]
        used = set()
        for _ in range(n):
            for _try in range(30):
                (c, u), = rnd.choices(comps, weights=cw)
                p, = rnd.choices(pool, weights=pw)
                if (c.id, p.user_id) not in used:
                    break
            else:
                continue
            used.add((c.id, p.user_id))
            m = mult[c.id]
            sf = int(round(cat.market_salary_from * m * rnd.uniform(0.95, 1.12), -4))
            st = sf + int(round((cat.market_salary_to - cat.market_salary_from) * m * rnd.uniform(0.35, 0.75), -4))
            created = now - timedelta(days=rnd.uniform(31, 150))
            inv = Invitation(company_id=c.id, employer_user_id=u.id, candidate_user_id=p.user_id,
                             position_title=f"{POSITIONS[d]} {GRADE_T[cat.grade_id]}{MARK}",
                             offer_description=f"Приглашение от {c.name} (демо-история для аналитики ФСП).",
                             salary_from=sf, salary_to=st, contact_method=f"{c.contact_email or 'hr@demo.invalid'}",
                             evidence=[], status=InvitationStatus.sent, created_at=created, updated_at=created)
            db.add(inv)
            db.flush()
            made += 1
            db.add(InvitationEvent(invitation_id=inv.id, from_status=None, to_status=InvitationStatus.sent,
                                   actor_user_id=u.id, created_at=created))
            r = rnd.random()
            if r < 0.14:
                continue
            seen = created + timedelta(hours=rnd.uniform(2, 60))
            inv.viewed_at = seen
            db.add(InvitationEvent(invitation_id=inv.id, from_status=InvitationStatus.sent,
                                   to_status=InvitationStatus.viewed, actor_user_id=p.user_id, created_at=seen))
            inv.status = InvitationStatus.viewed
            if r < 0.26:
                continue
            ok = p.salary_min_hidden is None or st >= p.salary_min_hidden
            acc = rnd.random() < (0.74 if ok else 0.16)
            resp = seen + timedelta(hours=rnd.uniform(1, 72))
            inv.responded_at = resp
            to = InvitationStatus.accepted if acc else InvitationStatus.declined
            if acc:
                inv.contacts_revealed_at = resp
            else:
                inv.decline_reason = None if ok else "Вилка ниже моих ожиданий"
            db.add(InvitationEvent(invitation_id=inv.id, from_status=InvitationStatus.viewed, to_status=to,
                                   actor_user_id=p.user_id, created_at=resp, note=inv.decline_reason))
            inv.status = to
        db.commit()
    return made


def delete_invitations(db: Session) -> int:
    ids = db.scalars(select(Invitation.id).join(Company, Company.id == Invitation.company_id).where(
        Company.is_demo.is_(True), Invitation.position_title.like(f"%{MARK}"))).all()
    if ids:
        db.execute(delete(InvitationEvent).where(InvitationEvent.invitation_id.in_(ids)))
        db.execute(delete(Invitation).where(Invitation.id.in_(ids)))
        db.commit()
    return len(ids)


def ensure_demo(db: Session) -> dict:
    """Ленивая подготовка демо кабинета ФСП (вход «Войти как ФСП»): аналитик + история приглашений + кубки."""
    from app.cup import demo as cup_demo
    from app.cup.models import Cup

    out = {"analyst": True, "invitations": 0, "cups": []}
    with _mx:
        ensure_analyst(db)
        if not _demo_companies(db):
            return out
        if not has_demo_invitations(db):
            out["invitations"] = seed_invitations(db)
        demo_cup = db.scalar(select(Cup.id).join(Company, Company.id == Cup.company_id).where(
            Cup.is_demo.is_(True), Company.name.like("Демо: %")).limit(1))
        if demo_cup is None:
            out["cups"] = cup_demo.seed_cups(db)["cups"]
    return out


def main() -> None:
    from app.cup import demo as cup_demo

    ap = argparse.ArgumentParser(description="Демо кабинета ФСП и кубков работодателей")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--delete", action="store_true")
    a = ap.parse_args()
    get_engine()
    with SessionLocal() as db:
        if a.reset or a.delete:
            print(f"Удалено демо-кубков: {cup_demo.delete_cups(db)}, демо-приглашений: {delete_invitations(db)}")
        if a.delete:
            return
        print(ensure_demo(db))


if __name__ == "__main__":
    main()
