"""Нормализация ФИО, дат рождения, спортивных разрядов и вычисление криптографических хэшей (SHA-256).

Соответствие 152-ФЗ:
- В открытый репозиторий никогда не записываются ФИО и даты рождения.
- Поиск в промышленном режиме может выполняться по `key_hash` (SHA-256 от `fio_norm[:birth_year]`)
  и `fio_hash` (SHA-256 от `fio_norm`).
"""

from __future__ import annotations

import hashlib
import re

_WS_RE = re.compile(r"[\s\u00a0]+")
_NON_CYR_RE = re.compile(r"[^а-яa-z0-9\-\s]")
_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-2]\d)\b")
_DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(19[5-9]\d|20[0-2]\d)\b")


def normalize_fio(raw: str | None) -> str:
    """Приводит ФИО к каноническому виду: нижний регистр, `ё` -> `е`, один пробел между словами."""
    if not raw:
        return ""
    s = raw.strip().lower().replace("ё", "е")
    s = _NON_CYR_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def extract_birth_date(raw: str | None) -> tuple[str | None, str | None]:
    """Извлекает дату рождения (YYYY-MM-DD или DD.MM.YYYY) и 4-значный год рождения."""
    if not raw:
        return None, None
    s = str(raw).strip()
    m = _DATE_RE.search(s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}", yyyy
    if re.match(r"^(19[5-9]\d|20[0-2]\d)-\d{2}-\d{2}$", s):
        return s, s[:4]
    ym = _YEAR_RE.search(s)
    if ym:
        return None, ym.group(1)
    return None, None


def compute_key_hash(fio_norm: str, birth_year: str | None = None) -> str:
    """SHA-256 от `fio_norm:birth_year` (если год известен) или от `fio_norm`."""
    base = f"{fio_norm}:{birth_year}" if (fio_norm and birth_year) else fio_norm
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def compute_fio_hash(fio_norm: str) -> str:
    """SHA-256 только от нормализованного ФИО (для поиска без ввода даты рождения)."""
    return hashlib.sha256(fio_norm.encode("utf-8")).hexdigest()


def compute_team_hash(team_name: str | None) -> str | None:
    """SHA-256 от нормализованного названия команды (для командных протоколов без поимённого состава)."""
    if not team_name:
        return None
    norm = _WS_RE.sub(" ", team_name.strip().lower().replace("ё", "е"))
    return hashlib.sha256(f"team:{norm}".encode("utf-8")).hexdigest()


def normalize_rank(raw: str | None, place: int | str | None = None, is_sbornaya: bool = False) -> str | None:
    """Приводит спортивный разряд/звание к стандартным обозначениям ЕВСК (ЗМС, МСМК, МС, КМС, I, II, III)."""
    if raw:
        u = raw.strip().upper().replace("Ё", "Е")
        if "ЗМС" in u:
            return "ЗМС"
        if "МСМК" in u:
            return "МСМК"
        if re.search(r"\bМС\b|МАСТЕР СПОРТА", u):
            return "МС"
        if "КМС" in u or "КАНДИДАТ В МАСТЕРА" in u:
            return "КМС"
        if re.search(r"\b(I|1)\b|ПЕРВЫЙ|1 РАЗРЯД|I РАЗРЯД", u):
            return "I"
        if re.search(r"\b(II|2)\b|ВТОРОЙ|2 РАЗРЯД|II РАЗРЯД", u):
            return "II"
        if re.search(r"\b(III|3)\b|ТРЕТИЙ|3 РАЗРЯД|III РАЗРЯД", u):
            return "III"
        if "ВК" in u or "1К" in u or "2К" in u or "3К" in u:
            return u
    return None
