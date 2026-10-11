"""Нормализация текста и сверка цитат — чистые функции, без моделей."""
from __future__ import annotations

import re

_WORD = re.compile(r"[^0-9a-zа-я]+", re.IGNORECASE)


def normalize(text: str) -> str:
    """Нижний регистр, ё→е, всё кроме букв и цифр — один пробел."""
    return " ".join(_WORD.sub(" ", (text or "").lower().replace("ё", "е")).split())


def stem(word: str, keep: int = 5) -> str:
    """Грубая основа слова: первые 5 знаков (запрос/запроса/запросы → запро). Достаточно для оценки пересечения."""
    return word[:keep]


def words(text: str, min_len: int = 4) -> set[str]:
    return {stem(w) for w in normalize(text).split() if len(w) >= min_len}


def overlap(a: str, b: str, min_len: int = 5) -> float:
    """Доля значимых слов (по грубой основе) текста a, встречающихся в b (0 — нет общего, 1 — все)."""
    wa, wb = words(a, min_len), words(b, min_len)
    if not wa:
        return 0.0
    return len(wa & wb) / len(wa)


def contains(haystack: str, needle: str) -> bool:
    h, n = normalize(haystack), normalize(needle)
    return bool(n) and (f" {n} " in f" {h} ")


def first_sentence(text: str, limit: int = 200) -> str:
    parts = re.split(r"(?<=[.!?…])\s+", (text or "").strip(), maxsplit=1)
    return (parts[0] if parts else "")[:limit].strip()


def excerpt(text: str, limit: int = 400) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"
