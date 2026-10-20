"""Поиск и автоматическая верификация достижений кандидата по индексу официальных протоколов ФСП России (2025–2026)
и списку кандидатов в спортивные сборные команды РФ на 2026 год.

Соответствие 152-ФЗ:
- Поиск выполняется по криптографическим SHA-256 хешам: ``key_hash`` (ФИО + год рождения), ``fio_hash`` (ФИО),
  ``team_hash`` (команда), а также по прямому совпадению ``fio_norm``, если индекс его содержит.
- Путь к индексу задаётся переменной окружения ``FSP_PROTOCOLS_INDEX`` (по умолчанию ``/data_local/fsp_protocols/index.json``
  с резервным путём ``/opt/spectrek_fsp/data_local/fsp_protocols/index.json``).
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.db import utcnow
from app.core.enums import FspEventLevel, FspLinkSource
from app.modules.catalog.constants import FSP_DISCIPLINES
from app.modules.fsp.models import FspAchievement, FspPassport
from app.modules.profiles.models import CandidateProfile

DEFAULT_PATHS = (
    "/data_local/fsp_protocols/index.json",
    "/opt/spectrek_fsp/data_local/fsp_protocols/index.json",
    "/app/data_local/fsp_protocols/index.json",
    "data_local/fsp_protocols/index.json",
)

DISCIPLINE_MAP = {
    "продуктовое программирование": "product",
    "программирование продуктовое": "product",
    "product": "product",
    "алгоритмическое программирование": "algorithmic",
    "программирование алгоритмическое": "algorithmic",
    "algorithmic": "algorithmic",
    "программирование систем информационной безопасности": "security",
    "информационная безопасность": "security",
    "кибербезопасность": "security",
    "security": "security",
    "программирование робототехники": "robotics",
    "робототехника": "robotics",
    "robotics": "robotics",
    "программирование БАС": "uav",
    "программирование бас": "uav",
    "беспилотные авиационные системы": "uav",
    "uav": "uav",
}
DISCIPLINE_TITLES = {d["id"]: d["title"] for d in FSP_DISCIPLINES}

_WS_RE = re.compile(r"[\s\u00a0]+")
_NON_CYR_RE = re.compile(r"[^а-яa-z0-9\-\s]")
_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-2]\d)\b")
_DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(19[5-9]\d|20[0-2]\d)\b")

_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


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


def _index_path(override: Path | str | None = None) -> Path | None:
    if override:
        p = Path(override)
        return p if p.is_file() else None
    env_path = (os.environ.get("FSP_PROTOCOLS_INDEX") or "").strip()
    candidates = [env_path, *DEFAULT_PATHS] if env_path else list(DEFAULT_PATHS)
    for raw in candidates:
        if not raw:
            continue
        p = Path(raw)
        if p.is_file():
            return p
    return None


def load_index(index_path: Path | str | None = None) -> tuple[bool, list[dict[str, Any]]]:
    p = _index_path(index_path)
    if p is None:
        return False, []
    key = str(p.resolve())
    try:
        mtime = p.stat().st_mtime
        cached = _CACHE.get(key)
        if cached and cached[0] == mtime:
            return True, cached[1]
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            items = [x for x in raw if isinstance(x, dict)]
        elif isinstance(raw, dict):
            for k in ("records", "items", "entries", "protocols", "data"):
                if isinstance(raw.get(k), list):
                    items = [x for x in raw[k] if isinstance(x, dict)]
                    break
            else:
                items = []
        else:
            items = []
        _CACHE[key] = (mtime, items)
        return True, items
    except Exception:  # noqa: BLE001
        return False, []


def _record_key(rec: dict[str, Any], idx: int) -> str:
    if rec.get("key_hash") and rec.get("ekp_no") and rec.get("date"):
        raw = f"{rec.get('key_hash')}:{rec.get('ekp_no')}:{rec.get('date')}:{rec.get('place')}:{rec.get('page')}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    if rec.get("key_hash"):
        return f"{rec['key_hash'][:16]}-{idx}"
    raw = f"{rec.get('fio_norm', '')}|{rec.get('ekp_no', '')}|{rec.get('event_title', '')}|{rec.get('date', '')}|{idx}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _normalize_discipline(raw_disc: str | None) -> tuple[str, str]:
    if not raw_disc:
        return "algorithmic", DISCIPLINE_TITLES["algorithmic"]
    low = raw_disc.strip().lower().replace("ё", "е")
    if low in DISCIPLINE_TITLES:
        return low, DISCIPLINE_TITLES[low]
    for pat, code in DISCIPLINE_MAP.items():
        if pat.lower() in low:
            return code, DISCIPLINE_TITLES.get(code, raw_disc)
    return "algorithmic", raw_disc.strip()


def _format_match(rec: dict[str, Any], idx: int) -> dict[str, Any]:
    code, disc_title = _normalize_discipline(rec.get("discipline"))
    return {
        "record_id": _record_key(rec, idx),
        "key_hash": rec.get("key_hash") or _record_key(rec, idx),
        "discipline": code,
        "discipline_title": rec.get("discipline") or disc_title,
        "event_title": rec.get("event_title") or rec.get("event_name") or "Соревнование ФСП",
        "ekp_no": str(rec.get("ekp_no") or rec.get("evsk_code") or "").strip() or None,
        "date": rec.get("date") or rec.get("event_date"),
        "place": rec.get("place"),
        "rank": rec.get("rank") or rec.get("sport_rank"),
        "team": rec.get("team") or rec.get("team_name"),
        "region": rec.get("region"),
        "pdf_url": rec.get("pdf_url"),
        "page": rec.get("page"),
        "status_title": "Подтверждено по официальному протоколу ФСП",
    }


def verify_candidate_fsp(
    fio: str | None = None,
    birth_date: str | None = None,
    team: str | None = None,
    index_path: Path | str | None = None,
) -> dict[str, Any]:
    """Проверяет достижения кандидата по индексу 18 официальных протоколов ФСП и Списка сборной РФ 2026."""
    available, records = load_index(index_path)
    if not available:
        return {
            "available": False,
            "verified": False,
            "match_type": "none",
            "highest_rank": None,
            "count": 0,
            "achievements": [],
            "matches": [],
            "message": "Проверка недоступна: индекс официальных протоколов ФСП на этом стенде не подключён.",
        }

    fio_norm = normalize_fio(fio) if fio else ""
    _, byear = extract_birth_date(birth_date)
    target_key_hash = compute_key_hash(fio_norm, byear) if fio_norm else None
    target_fio_hash = compute_fio_hash(fio_norm) if fio_norm else None
    target_team_hash = compute_team_hash(team) if team else None
    q_tokens = set(fio_norm.split()) if fio_norm else set()

    matched_pairs: list[tuple[int, dict[str, Any]]] = []
    match_type = "none"

    if target_key_hash and byear:
        for idx, r in enumerate(records):
            if r.get("key_hash") == target_key_hash:
                matched_pairs.append((idx, r))
        if matched_pairs:
            match_type = "exact_key_hash"

    if not matched_pairs and target_fio_hash:
        for idx, r in enumerate(records):
            if r.get("fio_hash") == target_fio_hash or r.get("key_hash") == target_fio_hash:
                matched_pairs.append((idx, r))
            elif r.get("fio_norm") and len(q_tokens) >= 2 and q_tokens.issubset(set(normalize_fio(r.get("fio_norm")).split())):
                matched_pairs.append((idx, r))
        if matched_pairs:
            match_type = "fio_hash"

    if not matched_pairs and target_team_hash:
        for idx, r in enumerate(records):
            if r.get("key_hash") == target_team_hash or (
                r.get("team") and compute_team_hash(r.get("team")) == target_team_hash
            ):
                matched_pairs.append((idx, r))
        if matched_pairs:
            match_type = "team_hash"

    rank_order = {"ЗМС": 7, "МСМК": 6, "МС": 5, "КМС": 4, "I": 3, "II": 2, "III": 1}
    best_rank = None
    best_rank_score = 0
    formatted: list[dict[str, Any]] = []
    for idx, m in matched_pairs:
        rk = m.get("rank")
        if rk and rank_order.get(rk, 0) > best_rank_score:
            best_rank_score = rank_order[rk]
            best_rank = rk
        formatted.append(_format_match(m, idx))

    return {
        "available": True,
        "verified": bool(formatted),
        "match_type": match_type,
        "highest_rank": best_rank,
        "count": len(formatted),
        "total_indexed": len(records),
        "achievements": formatted[:25],
        "matches": formatted[:25],
        "message": (
            f"Найдено подтверждённых записей в официальных протоколах ФСП: {len(formatted)}."
            if formatted
            else "Совпадений в итоговых протоколах ФСП 2025–2026 и списке сборной РФ 2026 не найдено."
        ),
    }


def search_protocols(
    fio: str | None,
    *,
    birth_date: str | None = None,
    team: str | None = None,
    index_path: Path | str | None = None,
) -> dict[str, Any]:
    return verify_candidate_fsp(fio=fio, birth_date=birth_date, team=team, index_path=index_path)


def _parse_date(val: Any) -> date | None:
    if isinstance(val, date):
        return val
    if isinstance(val, str) and len(val) >= 10:
        try:
            return date.fromisoformat(val[:10])
        except ValueError:
            return None
    return None


def confirm_protocol_matches(
    db: Session,
    user_id,
    key_hashes: list[str],
    *,
    consent_employers: bool = True,
    index_path: Path | str | None = None,
) -> dict[str, Any]:
    available, items = load_index(index_path)
    if not available:
        return {
            "available": False,
            "confirmed": 0,
            "message": "Проверка недоступна: индекс официальных протоколов ФСП не подключён.",
        }
    wanted = set(key_hashes)
    chosen = [
        _format_match(rec, idx)
        for idx, rec in enumerate(items)
        if _record_key(rec, idx) in wanted or rec.get("key_hash") in wanted
    ]
    if not chosen:
        return {
            "available": True,
            "confirmed": 0,
            "message": "Выбранные записи протокола не найдены.",
        }
    passport = db.scalar(select(FspPassport).where(FspPassport.user_id == user_id))
    now = utcnow()
    if passport is None:
        passport = FspPassport(
            user_id=user_id,
            link_source=FspLinkSource.registry,
            linked_at=now,
            synced_at=now,
            raw={},
        )
        db.add(passport)
        db.flush()
    else:
        passport.link_source = FspLinkSource.registry
        passport.synced_at = now
    raw = dict(passport.raw or {})
    raw["registry"] = {"mode": "protocol", "demo": False, "source": "fsp-russia.ru", "updated_at": now.isoformat()}
    raw["protocol_verified"] = True
    raw["consent_employers"] = bool(consent_employers)
    passport.raw = raw
    flag_modified(passport, "raw")

    existing_refs = set(
        db.scalars(select(FspAchievement.source_ref).where(FspAchievement.passport_id == passport.id)).all()
    )
    added = 0
    for m in chosen:
        sref = f"protocol:{m['record_id']}"
        if m.get("rank") and not passport.sport_rank:
            passport.sport_rank = str(m["rank"])[:64]
        if sref in existing_refs:
            continue
        place_val = None
        if m.get("place") is not None:
            try:
                place_val = int(re.findall(r"\d+", str(m["place"]))[0])
            except (IndexError, ValueError):
                place_val = None
        res_title = None
        if place_val == 1:
            res_title = "победитель"
        elif place_val in (2, 3):
            res_title = "призёр"
        elif m.get("rank"):
            res_title = f"разряд/звание: {m['rank']}"
        db.add(FspAchievement(
            passport_id=passport.id,
            discipline=m["discipline"],
            event_name=str(m["event_title"])[:255],
            event_level=FspEventLevel.national,
            event_date=_parse_date(m.get("date")),
            place=place_val,
            result_title=res_title,
            team_name=str(m["team"])[:200] if m.get("team") else None,
            verified=True,
            source_ref=sref,
            event_id=str(m.get("ekp_no") or "")[:100] or None,
            evsk_code=str(m.get("ekp_no") or "")[:64] or None,
            sport_rank=str(m.get("rank") or "")[:64] or None,
            team_result={
                "protocol_verified": True,
                "status_title": "Подтверждено по официальному протоколу ФСП",
                "ekp_no": m.get("ekp_no"),
                "pdf_url": m.get("pdf_url"),
                "page": m.get("page"),
                "region": m.get("region"),
                "discipline_title": m.get("discipline_title"),
            },
        ))
        added += 1

    profile = db.get(CandidateProfile, user_id)
    if profile is not None:
        pv = dict(profile.privacy or {})
        pv["show_fsp"] = bool(consent_employers)
        profile.privacy = pv
        flag_modified(profile, "privacy")
    db.flush()
    from app.modules.profiles.facts import refresh_rating

    refresh_rating(db, user_id)
    db.commit()
    return {
        "available": True,
        "confirmed": len(chosen),
        "added": added,
        "consent_employers": bool(consent_employers),
        "message": "Подтверждено по официальному протоколу ФСП.",
    }
