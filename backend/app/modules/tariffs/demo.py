"""Демо тарифов (Я29): тарифы у демо-компаний «Демо: …», три вымышленных партнёра ФСП, демо-счета и демо-наймы.

* партнёры ФСП: «Демо: КиберЩит», «Демо: ПромИИ», «Демо: ЭдТех Лаб» (вымышленные компании демо-стенда);
* «Найм» с демо-счётом: «Демо: ФинТех Север», «Демо: ГородДанные», «Демо: Ритейл Платформа», «Демо: МедИнфо»;
* остальные — «Старт» (строки нет);
* демо-наймы: часть принятых приглашений демо-истории кабинета ФСП (app.fsp_cabinet.demo) получает исход «вышел на
  работу» — модель, не люди (note = MARK), чтобы блок «Польза для ФСП» показывал наймы.

Песочницы жюри не трогает: их тарифы — значения по умолчанию (plans.JURY_DEFAULTS), личные ссылки работают как прежде.
Запуск: python -m app.modules.tariffs.demo [--reset | --delete]. Вход жюри вызывает ensure() сам (только при флаге).
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import random

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, as_aware, get_engine, utcnow
from app.core.enums import InvitationStatus
from app.modules.hiring.models import HiringOutcome
from app.modules.invitations.models import Invitation
from app.modules.profiles.models import Company
from app.modules.tariffs import service as svc
from app.modules.tariffs.models import CompanyTariff, DemoInvoice

MARK = "демо-найм (модель, не люди)"
PARTNERS = {"Демо: КиберЩит": "Демо: спонсорский пакет «Кубок ФСП по информационной безопасности»",
            "Демо: ПромИИ": "Демо: спонсорский пакет «Чемпионат России по продуктовому программированию»",
            "Демо: ЭдТех Лаб": "Демо: партнёр региональных соревнований ФСП"}
HIRE = ("Демо: ФинТех Север", "Демо: ГородДанные", "Демо: Ритейл Платформа", "Демо: МедИнфо")
HIRED_SHARE = 0.45  # доля принятых демо-приглашений с исходом «вышел на работу» (модель)


def has_demo(db: Session) -> bool:
    return db.scalar(select(CompanyTariff.company_id).where(CompanyTariff.is_demo.is_(True)).limit(1)) is not None


def _demo_companies(db: Session) -> dict[str, Company]:
    return {c.name: c for c in db.scalars(select(Company).where(Company.is_demo.is_(True),
                                                               Company.name.like("Демо: %"))).all()}


def has_demo_hires(db: Session) -> bool:
    return db.scalar(select(HiringOutcome.id).where(HiringOutcome.note == MARK).limit(1)) is not None


def seed(db: Session, rng_seed: int = 20261011) -> dict:
    comps = _demo_companies(db)
    out = {"partners": 0, "hire": 0, "invoices": 0, "hired": 0}
    if not comps:
        return out
    now = utcnow()
    today = svc.today_msk()
    for name, note in PARTNERS.items():
        c = comps.get(name)
        if c is None:
            continue
        r = svc.ensure_row(db, c)
        r.plan, r.fsp_partner, r.is_demo = "hire", True, True
        r.partner_since, r.partner_note = now - timedelta(days=120), note
        out["partners"] += 1
    for name in HIRE:
        c = comps.get(name)
        if c is None:
            continue
        r = svc.ensure_row(db, c)
        r.plan, r.is_demo, r.plan_since = "hire", True, now - timedelta(days=20)
        db.add(DemoInvoice(company_id=c.id, number=f"Д-ДЕМО-{c.id.hex[:8].upper()}", plan="hire",
                           amount_rub=None, vat_rub=None,  # цена «по запросу» — счёт без суммы
                           period_from=today - timedelta(days=20), period_to=today + timedelta(days=10), status="demo",
                           created_at=now - timedelta(days=20)))
        out["hire"] += 1
        out["invoices"] += 1
    db.flush()
    out["hired"] = seed_hires(db, comps, rng_seed)
    return out


def seed_hires(db: Session, comps: dict[str, Company] | None = None, rng_seed: int = 20261011) -> int:
    """Демо-наймы: принятые приглашения демо-истории (в т. ч. партнёров) — детерминированно."""
    comps = comps if comps is not None else _demo_companies(db)
    made = 0
    rnd = random.Random(rng_seed)
    ids = {c.id for c in comps.values()}
    have = set(db.scalars(select(HiringOutcome.invitation_id)).all())
    for inv in db.scalars(select(Invitation).where(Invitation.company_id.in_(ids),
                                                   Invitation.status == InvitationStatus.accepted)
                          .order_by(Invitation.created_at, Invitation.id)).all():
        if inv.id in have or rnd.random() >= HIRED_SHARE:
            continue
        at = (as_aware(inv.responded_at) or as_aware(inv.created_at)) + timedelta(days=rnd.uniform(10, 25))
        db.add(HiringOutcome(invitation_id=inv.id, company_id=inv.company_id, candidate_user_id=inv.candidate_user_id,
                             outcome="hired", start_date=(at + timedelta(days=14)).date(), note=MARK, created_at=at))
        made += 1
    db.commit()
    return made


def delete_demo(db: Session) -> dict:
    n_h = db.execute(delete(HiringOutcome).where(HiringOutcome.note == MARK)).rowcount
    ids = list(db.scalars(select(CompanyTariff.company_id).where(CompanyTariff.is_demo.is_(True))).all())
    n_i = db.execute(delete(DemoInvoice).where(DemoInvoice.company_id.in_(ids),
                                               DemoInvoice.number.like("Д-ДЕМО-%"))).rowcount if ids else 0
    n_t = db.execute(delete(CompanyTariff).where(CompanyTariff.is_demo.is_(True))).rowcount
    db.commit()
    return {"tariffs": n_t, "invoices": n_i, "hired": n_h}


def ensure(db: Session) -> dict | None:
    """Досоздать демо тарифов, если флаг включён и демо ещё нет (дёшево: один запрос). Ошибки — вызывающему."""
    if not svc.enabled():
        return None
    if not has_demo(db):
        return seed(db)
    if not has_demo_hires(db):  # история приглашений кабинета ФСП появилась позже или пересеяна (--reset)
        return {"hired": seed_hires(db)}
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Демо тарифов: партнёры ФСП, «Найм» с демо-счетами, демо-наймы")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--delete", action="store_true")
    a = ap.parse_args()
    get_engine()
    with SessionLocal() as db:
        if a.delete or a.reset:
            print("Удалено:", delete_demo(db))
            if a.delete:
                return
        print("Создано:", seed(db) if not has_demo(db) else "демо уже есть")


if __name__ == "__main__":
    main()
