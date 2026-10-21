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


_TAIL = {"и", "а", "но", "в", "во", "на", "с", "со", "к", "по", "за", "из", "от", "до", "для", "или", "что", "чтобы", "как",
         "при", "the", "a", "an", "of", "to"}
_GENERIC = {"контекст", "задача", "задание", "ситуация", "кейс", "условие", "сценарий", "вопрос"}
_PAREN = re.compile(r"\([^)]*\)|`[^`]*`|«[^»]*»|\"[^\"]*\"")


def short_title(title: str, max_words: int = 5) -> str:
    """Короткое имя задания для вопроса вслух: без кода, скобок и кавычек, до двоеточия/точки, не длиннее max_words слов.
    «Функция `daily_revenue` (выручка интернет-магазина) считает сумму за календар…» → «Функция считает сумму за календар»."""
    raw = (title or "").strip()
    cut = raw.endswith("…") or raw.endswith("...")
    t = _PAREN.sub(" ", raw.replace("…", " ").replace("...", " "))
    if cut:
        t = t.rsplit(None, 1)[0] if len(t.split()) > 1 else t
    parts = [x for x in re.split(r"[:.;!?—]", t) if x.strip()]
    t = parts[0] if parts else ""
    first = t.strip().lower().split()
    if len(parts) > 1 and (t.strip().lower() in _GENERIC or len(first) <= 1
                           or first[0] in ("вы", "ты", "вам", "вас", "представьте", "допустим")):
        # «Контекст: сервис уведомлений…» → «сервис уведомлений»; «Вы — тимлид платёжного шлюза…» → не «Вы» (А19 21.10)
        t = parts[1]
    w = [x for x in t.split() if any(ch.isalnum() for ch in x)]
    if not w:
        return "задание"
    w = w[:max_words]
    while len(w) > 1 and w[-1].lower() in _TAIL:
        w.pop()
    out = " ".join(w).strip(" ,-")
    return out[:1].upper() + out[1:]


def short_fragment(text: str, max_words: int = 7) -> str:
    """Начало первой фразы письменного ответа — не больше max_words слов, без кода и кавычек (вслух, без длинных цитат)."""
    t = _PAREN.sub(" ", first_sentence(text or "", 400))
    t = re.split(r"[:;—]|,\s", t, maxsplit=1)[0]
    w = [x.strip("«»\"'`") for x in t.split()]
    w = [x for x in w if x and any(ch.isalnum() for ch in x)]
    w = w[:max_words]
    while len(w) > 1 and w[-1].lower() in _TAIL:
        w.pop()
    return " ".join(w).rstrip(" ,.")


def word_count(text: str) -> int:
    return len((text or "").split())
