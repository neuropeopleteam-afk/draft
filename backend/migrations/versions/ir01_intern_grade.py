"""Грейд «Стажёр» (intern) ниже Junior: справочник грейдов и 5 категорий «направление · Стажёр» с рыночными диапазонами

Revision ID: ir01
Revises: qr01
Create Date: 2026-10-07

Решение владельца 07.10: для начинающих участников ФСП (школьники, студенты) — отдельный грейд ниже Junior.
Рыночные диапазоны — оплата стажировки по калькулятору зарплат Хабр Карьеры, квалификация «Intern»,
та же выгрузка 05.10.2026, что и для остальных категорий (docs/data_habr_salary_raw_20261005.json):
«от» = 25-й перцентиль, «до» = 75-й перцентиль, медиана отдельно, округление до 5 000 ₽, до вычета НДФЛ.
Выборки небольшие (64–258 анкет), диапазоны ориентировочные — см. docs/SALARY_SOURCES.md.

Миграция данных: таблицы ссылаются на grades.id внешним ключом, существующие кандидаты и категории не меняются.
Работает на SQLite и PostgreSQL 16.
"""
from collections.abc import Sequence
from datetime import date

from alembic import op
import sqlalchemy as sa

revision: str = "ir01"
down_revision: str | None = "qr01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRADE = ("intern", "Стажёр", 0, "Начинающий: учится и решает учебные задачи с наставником; стажировка или первая практика")
DIRECTION_TITLES = {"backend": "Backend", "frontend": "Frontend", "data_ml": "Data/ML", "qa": "QA",
                    "security": "Информационная безопасность"}
MARKET_SOURCE = "Хабр Карьера, калькулятор зарплат, квалификация Intern (p25–p75)"
MARKET_AS_OF = date(2026, 10, 5)
# направление: (от = p25, до = p75, медиана, число анкет) — оплата стажировки, ₽/мес до вычета НДФЛ
MARKET = {
    "backend": (45000, 100000, 70000, 258),
    "frontend": (40000, 90000, 65000, 78),
    "data_ml": (65000, 100000, 85000, 89),
    "qa": (45000, 90000, 65000, 159),
    "security": (45000, 95000, 65000, 64),
}

grades = sa.table(
    "grades", sa.column("id", sa.String), sa.column("title", sa.String), sa.column("level", sa.Integer),
    sa.column("description", sa.Text),
)
categories = sa.table(
    "categories",
    sa.column("id", sa.String), sa.column("direction_id", sa.String), sa.column("grade_id", sa.String),
    sa.column("title", sa.String), sa.column("market_salary_from", sa.Integer), sa.column("market_salary_to", sa.Integer),
    sa.column("market_salary_median", sa.Integer), sa.column("market_sample_size", sa.Integer),
    sa.column("market_source", sa.String), sa.column("market_as_of", sa.Date),
)


def upgrade() -> None:
    conn = op.get_bind()
    gid, title, level, descr = GRADE
    if conn.execute(sa.select(grades.c.id).where(grades.c.id == gid)).first() is None:
        op.bulk_insert(grades, [dict(id=gid, title=title, level=level, description=descr)])
    have = {r[0] for r in conn.execute(sa.select(categories.c.id)).all()}
    rows = []
    for d, (lo, hi, med, n) in MARKET.items():
        cid = f"{d}.{gid}"
        if cid in have:
            continue
        rows.append(dict(id=cid, direction_id=d, grade_id=gid, title=f"{DIRECTION_TITLES[d]} · {title}",
                         market_salary_from=lo, market_salary_to=hi, market_salary_median=med, market_sample_size=n,
                         market_source=MARKET_SOURCE, market_as_of=MARKET_AS_OF))
    if rows:
        op.bulk_insert(categories, rows)


def downgrade() -> None:
    gid = GRADE[0]
    conn = op.get_bind()
    # Кандидаты с категорией Стажёра теряют категорию (внешние ключи на grades.id)
    for tbl, cols in (("candidate_profiles", ("current_grade_id",)), ("test_sessions", ("result_grade_id",))):
        t = sa.table(tbl, *(sa.column(c, sa.String) for c in cols))
        for c in cols:
            conn.execute(t.update().where(getattr(t.c, c) == gid).values({c: None}))
    cp = sa.table("candidate_profiles", sa.column("current_category_id", sa.String), sa.column("current_grade_id", sa.String))
    conn.execute(cp.update().where(cp.c.current_category_id.like(f"%.{gid}")).values(current_category_id=None))
    op.execute(categories.delete().where(categories.c.grade_id == gid))
    op.execute(grades.delete().where(grades.c.id == gid))
