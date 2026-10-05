"""Модуль catalog: справочник направлений, грейдов, категорий и стек-тегов."""
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Direction(Base):
    __tablename__ = "directions"

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)  # backend, frontend, data_ml, qa, security
    title: Mapped[str] = mapped_column(sa.String(100))
    description: Mapped[str] = mapped_column(sa.Text, default="")
    code_language: Mapped[str] = mapped_column(sa.String(32))  # язык фрагментов кода в заданиях
    sort_order: Mapped[int] = mapped_column(default=0)


class Grade(Base):
    __tablename__ = "grades"

    id: Mapped[str] = mapped_column(sa.String(16), primary_key=True)  # junior, middle, senior
    title: Mapped[str] = mapped_column(sa.String(50))
    level: Mapped[int] = mapped_column(unique=True)  # 1..3, для сравнения «выше/ниже»
    description: Mapped[str] = mapped_column(sa.Text, default="")


class Category(Base):
    """Категория = направление × грейд. Работодатель видит только рыночный диапазон категории."""

    __tablename__ = "categories"
    __table_args__ = (
        sa.UniqueConstraint("direction_id", "grade_id", name="uq_categories_direction_grade"),
        sa.CheckConstraint("market_salary_from <= market_salary_to", name="market_range"),
    )

    id: Mapped[str] = mapped_column(sa.String(48), primary_key=True)  # backend.middle
    direction_id: Mapped[str] = mapped_column(sa.ForeignKey("directions.id"))
    grade_id: Mapped[str] = mapped_column(sa.ForeignKey("grades.id"))
    title: Mapped[str] = mapped_column(sa.String(100))
    market_salary_from: Mapped[int]  # ₽/мес, ориентир
    market_salary_to: Mapped[int]


class StackTag(Base):
    """Стек-тег для опроса. direction_id = NULL — общий блок (алгоритмы, SQL, HTTP, Git, Linux)."""

    __tablename__ = "stack_tags"

    id: Mapped[str] = mapped_column(sa.String(48), primary_key=True)  # python, react, pytest…
    title: Mapped[str] = mapped_column(sa.String(100))
    kind: Mapped[str] = mapped_column(sa.String(24))  # language | framework | tool | db | practice
    direction_id: Mapped[str | None] = mapped_column(sa.ForeignKey("directions.id"), index=True)
    sort_order: Mapped[int] = mapped_column(default=0)
