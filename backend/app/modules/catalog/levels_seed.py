"""Строки справочника Lead и Principal: грейды и категории «направление · уровень» с рыночными диапазонами.

Только при флаге GRADES_EXT_ENABLED: без флага в БД ничего не добавляется и справочник, подборка, отчёты — прежние
(байт в байт). С флагом — при старте службы (main.lifespan) и командой

    python -m app.modules.catalog.levels_seed

добавляются (идемпотентно, параллельный старт воркеров безопасен) грейды lead/principal и категории для каждого
направления из таблицы directions, для которого есть рыночные данные ниже. Схема БД не меняется — миграции нет
(строки — справочные данные под флагом; категории новых направлений каталога появятся сами, как только в таблице
directions есть направление и здесь — его данные).

Рыночные диапазоны (₽/мес на руки, как анкеты калькулятора; округление до 5 000 ₽, как у остальных категорий,
docs/SALARY_SOURCES.md, раздел «Lead и Principal»):
* Lead — калькулятор зарплат Хабр Карьеры, квалификация Lead: «от» = p25, «до» = p75, медиана, число анкет.
  Backend, Frontend, Data/ML, QA, ИБ — та же выгрузка 05.10.2026, что у прочих категорий
  (docs/data_habr_salary_raw_20261005.json); DevOps, инженер данных, системный аналитик — выгрузка 10.10.2026
  (docs/data_habr_salary_lead_20261010.json).
* Principal — отдельной квалификации у калькулятора нет. Ориентир — верхний квартиль Lead: «от» = p75 Lead,
  «до» = максимум Lead той же выгрузки; медианы и числа анкет нет, источник подписан «оценка».
"""
from __future__ import annotations

from datetime import date
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.catalog.seed_data import ALL_GRADE_LEVEL, ALL_GRADES, GRADES_EXT

log = logging.getLogger("catalog")

GRADE_DESCR = {
    "lead": "Ведёт архитектуру системы и техническую работу команды: ревью дизайна, инциденты и постмортемы, миграции",
    "principal": "Задаёт техническую стратегию нескольких команд: архитектура на годы, крупные миграции, стандарты",
}
HABR_0510 = date(2026, 10, 5)
HABR_1010 = date(2026, 10, 10)
LEAD_SOURCE = "Хабр Карьера, калькулятор зарплат, квалификация Lead (p25–p75)"
PRINCIPAL_SOURCE = ("оценка: верхний квартиль Lead (p75 — максимум), Хабр Карьера; "
                    "квалификации Principal у калькулятора нет")
# направление: (p25, p75, медиана, анкет, максимум, дата выгрузки) — квалификация Lead, ₽/мес, округлено до 5 000
LEAD_MARKET: dict[str, tuple[int, int, int, int, int, date]] = {
    "backend": (345000, 550000, 450000, 890, 675000, HABR_0510),
    "frontend": (330000, 485000, 405000, 294, 600000, HABR_0510),
    "data_ml": (360000, 655000, 485000, 109, 820000, HABR_0510),
    "qa": (220000, 425000, 340000, 134, 540000, HABR_0510),
    "security": (250000, 560000, 400000, 89, 765000, HABR_0510),
    "devops": (335000, 560000, 455000, 114, 685000, HABR_1010),
    "data_eng": (360000, 550000, 435000, 39, 630000, HABR_1010),
    "analyst": (295000, 460000, 375000, 226, 550000, HABR_1010),
}


def market_rows(direction: str, title: str) -> list[dict]:
    """Категории Lead и Principal направления (пусто — рыночных данных нет)."""
    m = LEAD_MARKET.get(direction)
    if m is None:
        return []
    p25, p75, med, n, mx, as_of = m
    return [
        dict(id=f"{direction}.lead", direction_id=direction, grade_id="lead", title=f"{title} · {ALL_GRADES['lead']}",
             market_salary_from=p25, market_salary_to=p75, market_salary_median=med, market_sample_size=n,
             market_source=LEAD_SOURCE, market_as_of=as_of),
        dict(id=f"{direction}.principal", direction_id=direction, grade_id="principal",
             title=f"{title} · {ALL_GRADES['principal']}", market_salary_from=p75, market_salary_to=mx,
             market_salary_median=None, market_sample_size=None, market_source=PRINCIPAL_SOURCE, market_as_of=as_of),
    ]


def ensure(db: Session, force: bool = False) -> dict:
    """Добавить недостающие грейды и категории Lead/Principal. Без флага — ничего (force — для тестов и консоли)."""
    from app.modules.catalog.models import Category, Direction, Grade

    if not (GRADES_EXT or force):
        return {"enabled": False, "grades": 0, "categories": 0}
    added_g = added_c = 0
    for gid in ("lead", "principal"):
        if db.get(Grade, gid) is None:
            try:
                with db.begin_nested():
                    db.add(Grade(id=gid, title=ALL_GRADES[gid], level=ALL_GRADE_LEVEL[gid], description=GRADE_DESCR[gid]))
                added_g += 1
            except IntegrityError:  # другой воркер успел первым
                pass
    have = set(db.scalars(select(Category.id)).all())
    skipped = []
    for d in db.scalars(select(Direction)).all():
        rows = market_rows(d.id, d.title)
        if not rows:
            skipped.append(d.id)
        for r in rows:
            if r["id"] in have:
                continue
            try:
                with db.begin_nested():
                    db.add(Category(**r))
                added_c += 1
            except IntegrityError:
                pass
    db.commit()
    if added_g or added_c:
        log.info("Lead/Principal: добавлено грейдов %s, категорий %s; без рыночных данных: %s", added_g, added_c, skipped)
    return {"enabled": True, "grades": added_g, "categories": added_c, "no_market_data": skipped}


def main() -> int:
    from app.core.db import SessionLocal, get_engine

    get_engine()
    with SessionLocal() as db:
        print(ensure(db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
