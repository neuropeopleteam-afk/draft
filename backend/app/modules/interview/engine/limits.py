"""Лимиты (контракт, раздел 4). Данные о прошлых сессиях и расходах даёт модуль interview из своей БД."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .errors import EngineError
from .settings import get_interview_settings


def check_limits(jury: bool, sandbox_sessions_last_hour: list[dict] | None, spent_today_usd: float,
                 now: datetime | None = None) -> None:
    """sandbox_sessions_last_hour: [{"created_at": datetime, "active": bool}, …] по песочнице жюри за последний час."""
    now = now or datetime.now(timezone.utc)
    if jury and sandbox_sessions_last_hour:
        active = any(s.get("active") for s in sandbox_sessions_last_hour)
        oldest = min((s["created_at"] for s in sandbox_sessions_last_hour if s.get("created_at")), default=now)
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        retry = max(1, int((oldest + timedelta(hours=1) - now).total_seconds()))
        raise EngineError("jury_limit", "В этой песочнице уже идёт сессия интервью" if active
                          else "Режим жюри: не больше одной сессии в час на песочницу", retry_after=retry)
    cap = get_interview_settings().interview_daily_cap_usd
    if cap > 0 and spent_today_usd >= cap:
        raise EngineError("daily_cap", f"Дневной потолок расходов ({cap:g} USD) исчерпан", retry_after=3600)
