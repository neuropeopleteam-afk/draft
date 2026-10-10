"""Стоимость: модели — точная цена из usage поставщика, если есть; остальное — оценка по ставкам."""
from __future__ import annotations

from .settings import get_interview_settings


def estimate_cost(kind: str, qty: float) -> float:
    """kind: tts (знаки), stt (секунды), avatar (секунды). Возвращает USD."""
    s = get_interview_settings()
    if qty <= 0:
        return 0.0
    if kind == "tts":
        return round(qty / 1000 * s.interview_price_tts_1000, 6)
    if kind == "stt":
        return round(qty / 60 * s.interview_price_stt_min, 6)
    if kind == "avatar":
        return round(qty / 60 * s.interview_price_avatar_min, 6)
    return 0.0


def llm_cost(usage: dict | None) -> float:
    if not isinstance(usage, dict):
        return 0.0
    c = usage.get("cost")
    try:
        v = float(c)
    except (TypeError, ValueError):
        return 0.0
    return v if v >= 0 else 0.0
