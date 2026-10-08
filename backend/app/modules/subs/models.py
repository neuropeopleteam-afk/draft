"""Таблицы подписок и уведомлений. Все внешние ключи — с каскадом: удаление пользователя, компании или потребности
(в том числе песочницы жюри) убирает связанные строки."""
from datetime import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, utcnow

FREQUENCIES = {
    "instant": "Сразу push и раз в день письмо-дайджест",
    "daily": "Только письмо-дайджест раз в день",
    "weekly": "Только письмо-дайджест раз в неделю",
}


class NeedSubscription(UUIDPk, Timestamps, Base):
    """Подписка работодателя на потребность: потребность остаётся активной, платформа следит за её топ-10."""

    __tablename__ = "need_subscriptions"
    __table_args__ = (
        sa.UniqueConstraint("need_id", name="uq_need_subscriptions_need_id"),
        sa.CheckConstraint("frequency IN ('instant', 'daily', 'weekly')", name="frequency"),
    )

    need_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("employer_needs.id", ondelete="CASCADE"))
    employer_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    enabled: Mapped[bool] = mapped_column(default=True, server_default=sa.true())
    frequency: Mapped[str] = mapped_column(sa.String(16), default="instant", server_default="instant")
    # Кто был в топе на момент подписки или смены условий подборки — не «новый»
    baseline_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Отпечаток условий (требования, фильтры, версия алгоритма): сменился — тихая перестройка базы сравнения
    definition_hash: Mapped[str | None] = mapped_column(sa.String(40))
    # Кэш топ-10: [{ref, rank, score}] — по нему видно, пересчёт что-то изменил или нет
    top: Mapped[list] = mapped_column(default=list)
    computed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_digest_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class NeedSubEntry(UUIDPk, Base):
    """Кандидат, побывавший в топ-10 подписки: когда вошёл, где сейчас, видел ли его работодатель."""

    __tablename__ = "need_sub_entries"
    __table_args__ = (sa.UniqueConstraint("sub_id", "candidate_user_id", name="uq_need_sub_entries_pair"),)

    sub_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("need_subscriptions.id", ondelete="CASCADE"), index=True)
    candidate_user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    ref: Mapped[str] = mapped_column(sa.String(16))
    in_top: Mapped[bool] = mapped_column(default=True)
    is_new: Mapped[bool] = mapped_column(default=False)  # вошёл после подписки и ещё не просмотрен
    rank: Mapped[int | None]
    score: Mapped[float | None]
    result: Mapped[dict | None]  # строка подборки (карточка и объяснения) на последнем пересчёте
    first_seen_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    entered_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    left_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    seen_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class UserNotification(UUIDPk, Base):
    """Уведомление в кабинете: то, что ушло (или уйдёт) в push и письме. dedupe_key делает создание идемпотентным."""

    __tablename__ = "user_notifications"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_user_notifications_dedupe"),
        sa.Index("ix_user_notifications_user_created", "user_id", "created_at"),
        sa.Index("ix_user_notifications_delivery", "delivery"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(sa.String(32))
    dedupe_key: Mapped[str] = mapped_column(sa.String(160))
    title: Mapped[str] = mapped_column(sa.String(255))
    body: Mapped[str] = mapped_column(sa.Text, default="")
    url: Mapped[str] = mapped_column(sa.String(255), default="/")
    payload: Mapped[dict] = mapped_column(default=dict)
    channels: Mapped[list] = mapped_column(default=list)  # что отправлять сразу: push, email
    delivery: Mapped[str] = mapped_column(sa.String(16), default="pending")  # pending | done
    digest: Mapped[str | None] = mapped_column(sa.String(16))  # queued | sent — вошло ли в дайджест
    push_state: Mapped[str | None] = mapped_column(sa.String(16))
    email_state: Mapped[str | None] = mapped_column(sa.String(16))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class NotifyPrefs(Base):
    """Настройки уведомлений пользователя (общие для подписок и напоминаний)."""

    __tablename__ = "notify_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    push_enabled: Mapped[bool] = mapped_column(default=True, server_default=sa.true())
    email_enabled: Mapped[bool] = mapped_column(default=True, server_default=sa.true())
    reminders_enabled: Mapped[bool] = mapped_column(default=True, server_default=sa.true())
    last_digest_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_weekly_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class SubsDirty(Base):
    """Кандидат изменился (тест, грейд, навык, видимость): подписки в его направлении пересчитает ближайший обход.
    Без внешнего ключа: строка не должна мешать удалению пользователя и не может уронить основную операцию."""

    __tablename__ = "subs_dirty"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow, index=True)
    reason: Mapped[str] = mapped_column(sa.String(32), default="")


class SubsState(Base):
    """Служебное: аренда обхода между процессами и сведения о последнем запуске."""

    __tablename__ = "subs_state"

    key: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    lease_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    stats: Mapped[dict | None]
