"""Слой хранения: движок SQLAlchemy 2, базовый класс моделей, сессии."""
from collections.abc import Iterator
from datetime import UTC, datetime
from enum import Enum
import uuid

import sqlalchemy as sa
from sqlalchemy import JSON, MetaData, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings

# Единые имена ограничений — Alembic генерирует предсказуемые миграции.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# JSONB в PostgreSQL, обычный JSON в SQLite (тесты).
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict: JSONType, list: JSONType}


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_aware(dt: datetime | None) -> datetime | None:
    """SQLite возвращает «наивные» даты — приводим к UTC для сравнений."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def str_enum(enum_cls: type[Enum], name: str) -> sa.Enum:
    """Перечисление как VARCHAR + CHECK: переносимо между PostgreSQL и SQLite."""
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


_engine: Engine | None = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def init_engine(url: str | None = None) -> Engine:
    global _engine
    url = url or get_settings().database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        # timeout — ожидание снятия блокировки файла (по умолчанию 5 с): фоновые потоки (подготовка песочницы жюри,
        # лента заданий, подписки) пишут параллельно с запросами, и локальный стенд на SQLite ловил «database is locked»
        kwargs = {"connect_args": {"check_same_thread": False, "timeout": 30}}
    _engine = create_engine(url, **kwargs)
    SessionLocal.configure(bind=_engine)
    return _engine


def get_engine() -> Engine:
    return _engine or init_engine()


def get_db() -> Iterator[Session]:
    get_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
