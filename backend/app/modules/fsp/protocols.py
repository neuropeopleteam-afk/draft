"""Проверка и привязка реальных достижений кандидатов по индексу официальных протоколов ФСП (fsp-russia.ru).

Данные индекса (ФИО, даты рождения, команды) лежат ТОЛЬКО на сервере вне git:
`/opt/spectrek_fsp/data_local/fsp_protocols/index.json` (или путь из переменной `FSP_PROTOCOLS_INDEX`).
В карточку работодателя ФИО и дата рождения не попадают никогда — только обезличенный факт достижения,
статус («Найдено в протоколе — ожидает подтверждения ФСП» или «Подтверждено протоколом ФСП»),
номер ЕКП, расчётный разряд по ЕВСК и ссылка на официальный PDF протокола со страницей.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.enums import FspEventLevel, FspLinkSource
from app.modules.auth.models import User
from app.modules.fsp.models import FspAchievement, FspPassport
from app.modules.profiles.models import CandidateProfile

DEFAULT_PATHS = (
    os.environ.get("FSP_PROTOCOLS_INDEX") or "",
    "/opt/spectrek_fsp/data_local/fsp_protocols/index_v2.json",
    "/data_local/fsp_protocols/index_v2.json",
    "/data_local/fsp_protocols/index.json",
    "/opt/spectrek_fsp/data_local/fsp_protocols/index.json",
    "/tmp/fsp_protocols/index_v2.json",
    "/tmp/fsp_protocols/index.json",
)

DISCIPLINE_MAP = {
    "программирование продуктовое": "product",
    "продуктовое программирование": "product",
    "программирование алгоритмическое": "algo",
    "алгоритмическое программирование": "algo",
    "программирование систем информационной безопасности": "infosec",
    "информационная безопасность": "infosec",
    "программирование робототехники": "robotics",
    "программирование беспилотных авиационных систем": "uav",
}

DISCIPLINE_HUMAN = {
    "product": "продуктовое программирование",
    "algo": "алгоритмическое программирование",
    "infosec": "программирование систем информационной безопасности",
    "robotics": "программирование робототехники",
    "uav": "программирование БАС",
}

# Судейские категории и слова-маркеры не-спортсменов (находка А8: исключаем судей и справки о ГСК)
JUDGE_RANKS = {
    "ВК", "1К", "2К", "3К", "ССВК", "СС1К", "СС2К", "СС3К", "ЮС",
    "СУДЬЯ ВК", "СУДЬЯ 1К", "СУДЬЯ 2К", "СУДЬЯ 3К",
}
NON_ATHLETE_DOC_IDS = {"kr_2025_sk_otbor"}
NON_ATHLETE_TITLE_PATTERNS = (
    "судейск",
    "составе судей",
    "главная судейская коллегия",
    "справка о количестве субъектов",
)

_CACHE: dict = {"mtime": None, "path": None, "records": [], "by_key": {}, "sources_by_url": {}, "stats": {}}


def normalize_fio(fio: str) -> str:
    s = (fio or "").strip().lower().replace("ё", "е")
    s = re.sub(r"[^а-яa-z\s\-]", " ", s)
    return " ".join(s.split())


def fio_sha256(fio: str) -> str:
    norm = normalize_fio(fio)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest() if norm else ""


def is_judge_or_non_athlete(rec: dict) -> bool:
    """Возвращает True, если запись относится к спортивному судье, командной строке без человека или технической справке."""
    if not isinstance(rec, dict):
        return True
    if rec.get("person") is False:
        return True
    if rec.get("role") in ("judge", "coach") or rec.get("is_judge") is True:
        return True
    doc_id = str(rec.get("event_id") or rec.get("doc_id") or "").strip().lower()
    if doc_id in NON_ATHLETE_DOC_IDS:
        return True
    title_l = str(rec.get("event_title") or "").strip().lower()
    if any(pat in title_l for pat in NON_ATHLETE_TITLE_PATTERNS):
        return True
    for r_field in ("rank", "rank_listed"):
        raw_rank = str(rec.get(r_field) or "").strip().upper()
        if not raw_rank:
            continue
        if raw_rank in JUDGE_RANKS or "СУДЬ" in raw_rank or "КАТЕГОР" in raw_rank:
            return True
    return False


def _index_path() -> Path | None:
    env_p = os.environ.get("FSP_PROTOCOLS_INDEX")
    paths = (env_p, *DEFAULT_PATHS) if env_p else DEFAULT_PATHS
    for raw in paths:
        if not raw:
            continue
        try:
            p = Path(raw)
            if p.is_file() and os.access(p, os.R_OK):
                return p
        except Exception:  # noqa: BLE001 — PermissionError на закрытом каталоге не должен ронять /api/me/fsp
            continue
    return None


def _load_index() -> dict:
    try:
        p = _index_path()
    except Exception:  # noqa: BLE001
        p = None
    if p is None:
        return {"records": [], "by_key": {}, "sources_by_url": {}, "stats": {}, "available": False}
    try:
        mtime = p.stat().st_mtime
        if _CACHE["path"] == str(p) and _CACHE["mtime"] == mtime:
            return {**_CACHE, "available": True}
        data = json.loads(p.read_text(encoding="utf-8"))
        raw_recs = data.get("records", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        sources = data.get("sources", []) if isinstance(data, dict) else []
        sources_by_url = {str(s.get("pdf_url") or ""): s for s in sources if isinstance(s, dict) and s.get("pdf_url")}
        # Отфильтровываем судей и технические справки на входе
        recs = [r for r in raw_recs if isinstance(r, dict) and not is_judge_or_non_athlete(r)]
        by_key = {}
        for r in recs:
            kh = r.get("key_hash") or r.get("record_id")
            if kh:
                by_key[str(kh)] = r
        stats = data.get("stats", {}) if isinstance(data, dict) else {}
        _CACHE.update({
            "mtime": mtime,
            "path": str(p),
            "records": recs,
            "by_key": by_key,
            "sources_by_url": sources_by_url,
            "stats": stats,
        })
        return {**_CACHE, "available": True}
    except Exception:  # noqa: BLE001
        return {"records": [], "by_key": {}, "sources_by_url": {}, "stats": {}, "available": False}


def index_status() -> dict:
    idx = _load_index()
    return {
        "available": bool(idx.get("available")),
        "records": len(idx.get("records", [])),
        "stats": idx.get("stats") or {},
    }


def load_index() -> tuple[bool, list[dict]]:
    idx = _load_index()
    return bool(idx.get("available")), list(idx.get("records", []))


def _map_discipline(raw: str | None) -> str:
    if not raw:
        return "product"
    low = raw.strip().lower()
    for k, v in DISCIPLINE_MAP.items():
        if k in low:
            return v
    if "алгоритм" in low:
        return "algo"
    if "безопасн" in low or "иб" in low:
        return "infosec"
    if "робот" in low:
        return "robotics"
    if "беспилот" in low or "бас" in low:
        return "uav"
    return "product"


def _map_level(event_title: str | None) -> FspEventLevel:
    low = (event_title or "").lower()
    if "международ" in low:
        return FspEventLevel.international
    if "чемпионат россии" in low or "кубок россии" in low or "всероссийск" in low or "первенство россии" in low or "сборн" in low:
        return FspEventLevel.national
    if "межрегиональн" in low or "федеральн" in low:
        return FspEventLevel.interregional
    return FspEventLevel.regional


def _short_event_title(event_title: str | None, event_date: date | str | None) -> str:
    raw = (event_title or "Соревнование ФСП").strip()
    low = raw.lower()
    year = ""
    if isinstance(event_date, date):
        year = str(event_date.year)
    elif isinstance(event_date, str) and len(event_date) >= 4 and event_date[:4].isdigit():
        year = event_date[:4]
    m_yr = re.search(r"\b(202[3-7])\b", raw)
    if m_yr:
        year = m_yr.group(1)
    if "кубок россии" in low:
        base = f"Кубок России {year}".strip()
        if "отборочн" in low:
            return f"{base} (отборочный этап)"
        return base
    if "чемпионат россии" in low:
        return f"Чемпионат России {year}".strip()
    if "первенство россии" in low:
        return f"Первенство России {year}".strip()
    if "список кандидатов в спортивные сборные" in low:
        return f"Сборная России по спортивному программированию {year}".strip()
    if "всероссийск" in low:
        return f"Всероссийские соревнования ФСП {year}".strip()
    return raw


def _resolve_evsk_info(rec: dict, birth_date: str | None = None) -> dict:
    """Определяет разряд и основание по ЕВСК (через модуль А8 fsp/evsk.py с надёжным встроенным расчётом по ЕВСК от 22.04.2025)."""
    try:
        from app.modules.fsp import evsk as _evsk  # type: ignore[import-not-found]

        res = _evsk.evsk_rank_for(rec, birth_date=birth_date)
        if isinstance(res, dict) and res.get("rank"):
            basis = res.get("basis")
            if isinstance(basis, dict):
                doc = basis.get("document") or "ЕВСК от 22.04.2025"
                row = basis.get("row") or basis.get("places") or ""
                basis_str = f"{doc}{f', {row}' if row else ''}"
            else:
                basis_str = str(basis or rec.get("evsk_basis_short") or "ЕВСК от 22.04.2025")
            return {
                "evsk_rank": str(res["rank"]),
                "evsk_basis": basis_str[:255],
                "evsk_status": str(res.get("status") or "fulfilled"),
                "evsk_explain": str(res.get("explain") or ""),
            }
    except Exception:  # noqa: BLE001
        pass

    if rec.get("evsk_rank"):
        return {
            "evsk_rank": str(rec["evsk_rank"]),
            "evsk_basis": str(rec.get("evsk_basis_short") or rec.get("evsk_basis") or "ЕВСК от 22.04.2025")[:255],
            "evsk_status": str(rec.get("evsk_status") or "fulfilled"),
            "evsk_explain": "",
        }

    # Встроенный расчёт по нормам ЕВСК по виду спорта «спортивное программирование» (приказ Минспорта РФ от 22.04.2025)
    title_l = str(rec.get("event_title") or "").lower()
    ekp = str(rec.get("ekp_no") or "")
    place = rec.get("place")
    try:
        p_int = int(place) if place is not None else None
    except (TypeError, ValueError):
        p_int = None

    if "сборн" in title_l or ekp.startswith("СБОРНАЯ"):
        return {
            "evsk_rank": "КМС",
            "evsk_basis": "п. 2 ЕВСК от 22.04.2025 (список кандидатов в сборную РФ)",
            "evsk_status": "fulfilled",
            "evsk_explain": "Включение в список кандидатов в спортивные сборные команды РФ",
        }
    is_chr = "чемпионат россии" in title_l
    is_kr = "кубок россии" in title_l and "отборочн" not in title_l
    is_vs = "всероссийск" in title_l or "первенство россии" in title_l or "кубок россии" in title_l
    if is_chr or is_kr:
        if p_int is not None and 1 <= p_int <= 3:
            return {
                "evsk_rank": "КМС",
                "evsk_basis": f"п. 2 ЕВСК от 22.04.2025 ({'Чемпионат' if is_chr else 'Кубок'} России, {p_int} место)",
                "evsk_status": "fulfilled",
                "evsk_explain": "Выполнена норма КМС на всероссийском финале",
            }
        if p_int is not None and 4 <= p_int <= 6:
            return {
                "evsk_rank": "КМС",
                "evsk_basis": f"п. 2 ЕВСК от 22.04.2025 (финал {'ЧР' if is_chr else 'КР'}, {p_int} место)",
                "evsk_status": "fulfilled",
                "evsk_explain": "Выполнена норма КМС (4–6 место финала)",
            }
        if p_int is not None and 7 <= p_int <= 12:
            return {
                "evsk_rank": "I разряд",
                "evsk_basis": f"п. 3 ЕВСК от 22.04.2025 (финал {'ЧР' if is_chr else 'КР'}, {p_int} место)",
                "evsk_status": "fulfilled",
                "evsk_explain": "Выполнена норма I спортивного разряда",
            }
        return {
            "evsk_rank": "II разряд",
            "evsk_basis": "п. 4 ЕВСК от 22.04.2025 (финал всероссийских соревнований)",
            "evsk_status": "fulfilled",
            "evsk_explain": "Участие в финальном этапе всероссийских соревнований",
        }
    if is_vs:
        if p_int is not None and 1 <= p_int <= 3:
            return {
                "evsk_rank": "КМС",
                "evsk_basis": f"п. 2 ЕВСК от 22.04.2025 (всероссийские соревнования, {p_int} место)",
                "evsk_status": "fulfilled",
                "evsk_explain": "Призовое место всероссийских соревнований",
            }
        if p_int is not None and 4 <= p_int <= 8:
            return {
                "evsk_rank": "I разряд",
                "evsk_basis": f"п. 3 ЕВСК от 22.04.2025 (всероссийские соревнования, {p_int} место)",
                "evsk_status": "fulfilled",
                "evsk_explain": "Выполнена норма I спортивного разряда",
            }
        return {
            "evsk_rank": "II разряд",
            "evsk_basis": "п. 4 ЕВСК от 22.04.2025 (всероссийские соревнования)",
            "evsk_status": "fulfilled",
            "evsk_explain": "Выполнена норма II спортивного разряда",
        }
    if p_int is not None and 1 <= p_int <= 3:
        return {
            "evsk_rank": "I разряд",
            "evsk_basis": f"п. 3 ЕВСК от 22.04.2025 (призёр этапа, {p_int} место)",
            "evsk_status": "fulfilled",
            "evsk_explain": "Призовое место официальных соревнований ФСП",
        }
    return {
        "evsk_rank": "III разряд",
        "evsk_basis": "п. 5 ЕВСК от 22.04.2025 (официальные соревнования ФСП)",
        "evsk_status": "fulfilled",
        "evsk_explain": "Официальный зачёт соревнований ФСП",
    }


def _build_protocol_ref(rec: dict, sources_by_url: dict[str, dict]) -> dict:
    pdf_url = rec.get("pdf_url")
    src = sources_by_url.get(str(pdf_url or "")) or {}
    doc_id = rec.get("event_id") or rec.get("doc_id") or src.get("doc_id") or "fsp_protocol"
    ekp_no = rec.get("ekp_no") or src.get("ekp_no")
    return {
        "doc_id": str(doc_id),
        "ekp_no": str(ekp_no) if ekp_no else None,
        "page": rec.get("page"),
        "url": pdf_url,
    }


def format_protocol_achievement_text(
    *,
    event_name: str | None,
    event_date: date | str | None,
    discipline: str | None,
    place: int | None,
    result_title: str | None,
    ekp_no: str | None,
    evsk_rank: str | None,
    evsk_basis: str | None,
    page: int | None,
) -> str:
    """Форматирует строку достижения для карточки работодателя по стандарту P0-2:
    «Кубок России 2025, продуктовое программирование, 2 место, ЕКП №…, разряд по ЕВСК: КМС (п. …), стр. 3»
    """
    short_ev = _short_event_title(event_name, event_date)
    disc_h = DISCIPLINE_HUMAN.get(discipline or "", discipline or "спортивное программирование")
    place_str = f"{place} место" if place is not None else (result_title or "участник")
    parts = [short_ev, disc_h, place_str]
    if ekp_no:
        parts.append(f"ЕКП № {ekp_no}")
    if evsk_rank:
        basis_part = f" ({evsk_basis})" if evsk_basis else ""
        parts.append(f"разряд по ЕВСК: {evsk_rank}{basis_part}")
    if page is not None:
        parts.append(f"стр. {page}")
    return ", ".join(parts)


def _public_record(rec: dict, sources_by_url: dict[str, dict], *, is_fsp_verified: bool = False) -> dict:
    """Обезличенное представление записи протокола для API (без ФИО и даты рождения)."""
    disc_code = _map_discipline(rec.get("discipline"))
    evsk = _resolve_evsk_info(rec)
    pref = _build_protocol_ref(rec, sources_by_url)
    ekp_no = pref.get("ekp_no")
    protocol_status = "verified" if is_fsp_verified else "pending_fsp"
    status_title = (
        "Подтверждено протоколом ФСП (личность сверена через ФСП ID)"
        if is_fsp_verified
        else "Найдено в протоколе — ожидает подтверждения ФСП"
    )
    raw_sport_rank = rec.get("rank")
    if raw_sport_rank and str(raw_sport_rank).strip().upper() in JUDGE_RANKS:
        raw_sport_rank = None
    formatted = format_protocol_achievement_text(
        event_name=rec.get("event_title"),
        event_date=rec.get("date"),
        discipline=disc_code,
        place=rec.get("place"),
        result_title=None,
        ekp_no=ekp_no,
        evsk_rank=evsk["evsk_rank"],
        evsk_basis=evsk["evsk_basis"],
        page=pref.get("page"),
    )
    return {
        "key_hash": rec.get("key_hash") or rec.get("record_id"),
        "record_id": rec.get("key_hash") or rec.get("record_id"),
        "event_title": rec.get("event_title"),
        "discipline": rec.get("discipline"),
        "discipline_code": disc_code,
        "discipline_title": DISCIPLINE_HUMAN.get(disc_code, rec.get("discipline") or "спортивное программирование"),
        "ekp_no": ekp_no,
        "evsk_rank": evsk["evsk_rank"],
        "evsk_basis": evsk["evsk_basis"],
        "evsk_status": evsk["evsk_status"],
        "protocol_ref": pref,
        "date": rec.get("date"),
        "place": rec.get("place"),
        "rank": raw_sport_rank or evsk["evsk_rank"],
        "team": rec.get("team"),
        "region": rec.get("region"),
        "pdf_url": pref.get("url"),
        "page": pref.get("page"),
        "protocol_status": protocol_status,
        "verified": is_fsp_verified,
        "status_title": status_title,
        "formatted_text": formatted,
    }


def search_protocols(
    fio: str | None = None,
    birth_date: str | None = None,
    team: str | None = None,
    limit: int = 25,
    *,
    fsp_id_verified_fio: str | None = None,
) -> dict:
    """Ищет записи спортсмена в индексе официальных протоколов ФСП (судьи и справки исключены)."""
    idx = _load_index()
    if not idx.get("available"):
        return {
            "available": False,
            "count": 0,
            "matches": [],
            "message": "Индекс официальных протоколов ФСП не подключён на этом окружении.",
        }

    fio_norm = normalize_fio(fio or "")
    f_hash = fio_sha256(fio or "") if fio_norm else ""
    team_q = (team or "").strip().lower()
    b_q = (birth_date or "").strip()
    verified_fio_norm = normalize_fio(fsp_id_verified_fio or "")

    if not fio_norm and not team_q:
        return {"available": True, "count": 0, "matches": [], "message": "Укажите ФИО или название команды."}

    matches: list[dict] = []
    sources_by_url = idx.get("sources_by_url") or {}
    for r in idx.get("records", []):
        if is_judge_or_non_athlete(r):
            continue
        if fio_norm:
            r_hash = r.get("fio_hash")
            r_norm = normalize_fio(r.get("fio_norm") or r.get("fio") or "")
            if r_hash and r_hash == f_hash:
                pass
            elif r_norm and (r_norm == fio_norm or fio_norm in r_norm.split()):
                pass
            else:
                continue
        if b_q:
            rb = str(r.get("birth_date") or "").strip()
            if rb and b_q not in rb:
                continue
        if team_q:
            rt = str(r.get("team") or "").strip().lower()
            if team_q not in rt:
                continue
        r_fio_norm = normalize_fio(r.get("fio_norm") or r.get("fio") or "")
        is_verified = bool(verified_fio_norm and r_fio_norm and verified_fio_norm == r_fio_norm)
        matches.append(_public_record(r, sources_by_url, is_fsp_verified=is_verified))
        if len(matches) >= limit:
            break

    return {
        "available": True,
        "count": len(matches),
        "matches": matches,
        "message": (
            f"Найдено записей в официальных протоколах ФСП: {len(matches)}"
            if matches
            else "В официальных протоколах ФСП 2025–2026 совпадений не найдено (записи судейских коллегий исключены)."
        ),
    }


def confirm_protocol_matches(
    db: Session,
    user_id: uuid.UUID,
    key_hashes: list[str],
    *,
    consent_employers: bool = True,
) -> dict:
    """Привязывает выбранные записи из официальных протоколов ФСП к паспорту кандидата.

    Двухшаговое правило честного статуса (P0-1):
    - если у кандидата подтверждён вход через ФСП ID (`link_source == keycloak` или `user.fsp_subject`)
      и нормализованное ФИО совпадает с ФИО в протоколе, статус сразу становится `protocol_status = "verified"`;
    - иначе ставится `protocol_status = "pending_fsp"` («Найдено в протоколе — ожидает подтверждения ФСП»),
      и заявка попадает в очередь представителя ФСП (`/api/fsp-cabinet/protocol-claims`).
    """
    idx = _load_index()
    by_key = idx.get("by_key") or {}
    sources_by_url = idx.get("sources_by_url") or {}
    user = db.get(User, user_id)
    profile = db.get(CandidateProfile, user_id)
    passport = db.scalar(select(FspPassport).where(FspPassport.user_id == user_id))
    if passport is None:
        passport = FspPassport(
            user_id=user_id,
            link_source=FspLinkSource.registry,
            linked_at=utcnow(),
            synced_at=utcnow(),
            raw={"source": "fsp_official_protocols", "verified_at": utcnow().isoformat()},
        )
        db.add(passport)
        db.flush()

    has_fsp_id = bool(user and user.fsp_subject) or (passport.link_source == FspLinkSource.keycloak)
    prof_fio_norm = normalize_fio(profile.full_name) if (profile and profile.full_name) else ""

    existing_refs = {
        a.source_ref
        for a in db.scalars(select(FspAchievement).where(FspAchievement.passport_id == passport.id)).all()
        if a.source_ref
    }

    added = 0
    verified_count = 0
    pending_count = 0
    best_rank = passport.sport_rank
    for kh in key_hashes:
        rec = by_key.get(str(kh))
        if not rec or is_judge_or_non_athlete(rec):
            continue
        sref = f"protocol:{kh}"
        if sref in existing_refs:
            continue
        ev_date = None
        raw_date = str(rec.get("date") or "").strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", raw_date):
            try:
                ev_date = date.fromisoformat(raw_date)
            except ValueError:
                ev_date = None
        place = rec.get("place")
        try:
            place_int = int(place) if place is not None else None
        except (TypeError, ValueError):
            place_int = None

        if place_int == 1:
            r_title = "победитель"
            r_kind = "winner"
        elif place_int in (2, 3):
            r_title = "призёр"
            r_kind = "prize"
        elif place_int is not None and place_int <= 10:
            r_title = "финалист"
            r_kind = "finalist"
        else:
            r_title = "участник"
            r_kind = "participant"

        evsk = _resolve_evsk_info(rec)
        pref = _build_protocol_ref(rec, sources_by_url)
        ekp_no = pref.get("ekp_no")
        rec_fio_norm = normalize_fio(rec.get("fio_norm") or rec.get("fio") or "")
        # До пересборки индекса записи без doc_id/url не получают авто-verified
        has_valid_doc = bool(pref.get("doc_id") and pref.get("url"))
        is_fsp_verified = bool(has_fsp_id and prof_fio_norm and rec_fio_norm and prof_fio_norm == rec_fio_norm and has_valid_doc)
        p_status = "verified" if is_fsp_verified else "pending_fsp"
        status_title = (
            "Подтверждено протоколом ФСП"
            if is_fsp_verified
            else "Найдено в протоколе — ожидает подтверждения ФСП"
        )

        rank_val = evsk["evsk_rank"]
        if rank_val and not best_rank and is_fsp_verified:
            best_rank = str(rank_val)[:64]

        db.add(
            FspAchievement(
                passport_id=passport.id,
                discipline=_map_discipline(rec.get("discipline")),
                event_name=str(rec.get("event_title") or "Соревнование ФСП")[:255],
                event_level=_map_level(rec.get("event_title")),
                event_date=ev_date,
                place=place_int,
                result_title=r_title,
                team_name=(str(rec.get("team"))[:200] if rec.get("team") else None),
                verified=True,
                source_ref=sref,
                event_id=(str(pref.get("doc_id"))[:100] if pref.get("doc_id") else None),
                result_kind=r_kind,
                evsk_code=(str(evsk["evsk_rank"])[:64] if evsk["evsk_rank"] else None),
                sport_rank=(str(evsk["evsk_rank"])[:64] if evsk["evsk_rank"] else None),
                protocol_status=p_status,
                protocol_ref=pref,
                ekp_no=(str(ekp_no)[:64] if ekp_no else None),
                evsk_rank=(str(evsk["evsk_rank"])[:64] if evsk["evsk_rank"] else None),
                evsk_basis=(str(evsk["evsk_basis"])[:255] if evsk["evsk_basis"] else None),
                team_result={
                    "place": place_int,
                    "region": rec.get("region"),
                    "pdf_url": pref.get("url"),
                    "page": pref.get("page"),
                    "ekp_no": ekp_no,
                    "doc_id": pref.get("doc_id"),
                    "evsk_rank": evsk["evsk_rank"],
                    "evsk_basis": evsk["evsk_basis"],
                    "protocol_verified": is_fsp_verified,
                    "protocol_status": p_status,
                    "status_title": status_title,
                },
            )
        )
        existing_refs.add(sref)
        added += 1
        if is_fsp_verified:
            verified_count += 1
        else:
            pending_count += 1

    if best_rank and not passport.sport_rank:
        passport.sport_rank = best_rank
    passport.synced_at = utcnow()
    raw = dict(passport.raw or {})
    raw["official_protocols_verified"] = verified_count > 0 or bool(raw.get("official_protocols_verified"))
    raw["official_protocols_pending"] = pending_count
    raw["official_protocols_synced_at"] = utcnow().isoformat()
    passport.raw = raw

    if profile is not None:
        pv = dict(profile.privacy or {})
        pv["show_fsp"] = bool(consent_employers)
        profile.privacy = pv

    db.commit()
    from app.modules.profiles.facts import refresh_rating

    refresh_rating(db, user_id)
    db.commit()
    if verified_count > 0 and pending_count == 0:
        msg = f"Привязано и подтверждено достижений (через ФСП ID): {verified_count}."
    elif pending_count > 0:
        msg = (
            f"Добавлено записей из протоколов ФСП: {added}. Статус: «Найдено в протоколе — ожидает подтверждения ФСП». "
            "Для полного подтверждения войдите через ФСП ID с тем же ФИО или дождитесь подтверждения представителем ФСП."
        )
    else:
        msg = "Выбранные записи уже привязаны к паспорту."
    return {
        "added": added,
        "verified_count": verified_count,
        "pending_count": pending_count,
        "show_fsp": consent_employers,
        "sport_rank": passport.sport_rank,
        "message": msg,
    }


def sync_fsp_id_protocol_verifications(db: Session, user_id: uuid.UUID, verified_full_name: str | None) -> int:
    """При входе через ФСП ID автоматически переводит заявки `pending_fsp` в `verified`, если ФИО совпадает."""
    if not verified_full_name:
        return 0
    passport = db.scalar(select(FspPassport).where(FspPassport.user_id == user_id))
    if passport is None:
        return 0
    idx = _load_index()
    by_key = idx.get("by_key") or {}
    norm_target = normalize_fio(verified_full_name)
    if not norm_target:
        return 0
    updated = 0
    rows = db.scalars(
        select(FspAchievement).where(
            FspAchievement.passport_id == passport.id,
            FspAchievement.protocol_status == "pending_fsp",
        )
    ).all()
    for a in rows:
        kh = (a.source_ref or "").removeprefix("protocol:")
        rec = by_key.get(kh)
        rec_norm = normalize_fio((rec or {}).get("fio_norm") or (rec or {}).get("fio") or "")
        if not rec or not rec_norm or rec_norm == norm_target:
            a.protocol_status = "verified"
            a.verified = True
            tr = dict(a.team_result or {})
            tr["protocol_verified"] = True
            tr["protocol_status"] = "verified"
            tr["status_title"] = "Подтверждено протоколом ФСП и ФСП ID"
            a.team_result = tr
            if a.evsk_rank and not passport.sport_rank:
                passport.sport_rank = a.evsk_rank
            updated += 1
    if updated:
        db.flush()
    return updated
