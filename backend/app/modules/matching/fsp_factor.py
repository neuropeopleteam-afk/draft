"""Достижения ФСП в подборе: статус подтверждения, официальный протокол, профильность дисциплины (fsp-v3, 21.10.2026).

Сила ФСП — та же формула, что fsp-v2 (fsp/rating.py: результат × давность × командность; лучший результат 80 %,
остальные — до 20 % с убывающей отдачей), но вклад каждого результата умножается на вес его СТАТУСА:

* ``verified`` — подтверждено: представитель ФСП, вход через ФСП ID с тем же ФИО, реестр (T2) → 1,0;
* ``pending_fsp`` — найдено в официальном протоколе ФСП, кандидат подтвердил, что это он, ФСП ещё не подтвердила
  (защита от присвоения чужого ФИО) → 0,5: сам результат документально существует, личность — пока нет;
* ``declared`` — заявлено в анкете без документа → 0 (самоописание не входит в балл — требование ТЗ);
* ``excluded`` — не достижение: судейская категория (ВК, 1К…3К, «судья») или запись протокола без мероприятия
  (event_id) до пересборки индекса (находка А8 21.10) → 0 и не показывается как достижение.

Отсутствие истории ФСП — штраф 0: компонент просто равен 0, как у всех без ФСП (метрика no_fsp_top5_share).

Профильность дисциплины (флаг FSP_DISCIPLINE_RELEVANCE, по умолчанию выкл.): коэффициент «дисциплина →
направление» из ``docs/realdata/fsp_protocols/discipline_relevance.json`` (А8: дословные определения дисциплин из
правил вида спорта), запасной — fsp/relevance.AFFINITY. Коэффициент ограничен снизу 0,8: дисциплины равны (ответ
организаторов E08), профильность лишь мягко уточняет.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import re
from typing import Any

VERSION = "fsp-v3"
STATUS_WEIGHT = {"verified": 1.0, "pending_fsp": 0.5, "declared": 0.0, "excluded": 0.0}
STATUS_TITLE = {"verified": "подтверждено ФСП", "pending_fsp": "найдено в официальном протоколе ФСП, ждёт подтверждения ФСП",
                "declared": "заявлено кандидатом", "excluded": "не достижение"}
REL_FLOOR = 0.8
POLICY = ("Сила ФСП: результат (победитель 1; призёр 0,85; финалист 0,6; участник 0,15) × давность (не ниже 70 %) × "
          "командность; лучший результат — 80 %, остальные — до 20 %. Вес статуса: подтверждено ФСП — 1,0; найдено в "
          "официальном протоколе и ждёт подтверждения ФСП — 0,5; заявлено без документа — 0. Нет истории ФСП — штраф 0.")

_JUDGE = re.compile(r"(^|\s)(всероссийск\w* категори\w*|вк|[123]\s*-?\s*к|сс\s*вк|сс\s*[123]\s*к)(\s|$)|судь|судейск",
                    re.IGNORECASE)


def _ach_get(a: Any, name: str, default=None):
    if isinstance(a, dict):
        return a.get(name, default)
    return getattr(a, name, default)


def is_judge_record(a: Any) -> bool:
    """Запись о судье (категория ВК/1К/2К/3К или слово «судья») — никогда не достижение."""
    for f in ("sport_rank", "result_title", "result_kind", "role_in_team"):
        v = str(_ach_get(a, f) or "").strip()
        if v and _JUDGE.search(v):
            return True
    tr = _ach_get(a, "team_result") or {}
    return bool(isinstance(tr, dict) and (tr.get("is_judge") or _JUDGE.search(str(tr.get("judge_category") or ""))))


def is_protocol(a: Any) -> bool:
    """Достижение из официального протокола ФСП (индекс А8): protocol_ref, protocol_status или source_ref protocol:."""
    if _ach_get(a, "protocol_ref"):
        return True
    if (_ach_get(a, "protocol_status") or "none") in ("pending_fsp", "verified"):
        return True
    return str(_ach_get(a, "source_ref") or "").startswith("protocol:")


def status(a: Any) -> str:
    """verified | pending_fsp | declared | excluded (см. модуль)."""
    if is_judge_record(a):
        return "excluded"
    ps = _ach_get(a, "protocol_status")
    if is_protocol(a):
        if not (_ach_get(a, "event_id") or (_ach_get(a, "protocol_ref") or {}).get("doc_id")):
            return "excluded"  # запись протокола без мероприятия — до пересборки индекса не считаем
        if ps == "verified":
            return "verified"
        # до миграции А2 (protocol_status) самоподтверждение совпадения ставило verified=True — это «ждёт ФСП»
        return "pending_fsp"
    if ps == "verified" or _ach_get(a, "verified"):
        return "verified"
    return "declared"


def protocol_ref(a: Any) -> dict | None:
    """{doc_id, ekp_no, page, url} — из protocol_ref (А2) или team_result прежних записей; None — не протокол."""
    if not is_protocol(a):
        return None
    pr = dict(_ach_get(a, "protocol_ref") or {})
    tr = _ach_get(a, "team_result") or {}
    if isinstance(tr, dict):
        pr.setdefault("ekp_no", tr.get("ekp_no"))
        pr.setdefault("page", tr.get("page"))
        pr.setdefault("url", tr.get("pdf_url"))
        pr.setdefault("region", tr.get("region"))
    pr.setdefault("ekp_no", _ach_get(a, "ekp_no") or _ach_get(a, "evsk_code"))
    pr.setdefault("doc_id", _ach_get(a, "event_id"))
    return {k: v for k, v in pr.items() if v not in (None, "")}


def protocol_citation(a: Any) -> str:
    """«Кубок России 2025, продуктовое программирование, 2 место, ЕКП № …, стр. 3» — для «почему в топе»."""
    from app.modules.profiles.facts import DISCIPLINE_TITLES

    pr = protocol_ref(a) or {}
    parts = [str(_ach_get(a, "event_name") or "Соревнование ФСП")]
    disc = _ach_get(a, "discipline")
    if disc:
        parts.append(DISCIPLINE_TITLES.get(disc, disc))
    place = _ach_get(a, "place")
    parts.append(f"{place} место" if place else (_ach_get(a, "result_title") or "участник"))
    if pr.get("ekp_no"):
        parts.append(f"ЕКП № {pr['ekp_no']}")
    if pr.get("page"):
        parts.append(f"стр. {pr['page']}")
    rank = _ach_get(a, "evsk_rank")
    if rank:
        parts.append(f"разряд по ЕВСК: {rank}")
    return ", ".join(str(x) for x in parts)


# ---------------------------------------------------------------- профильность дисциплины

def _relevance_path() -> Path:
    env = os.environ.get("FSP_DISCIPLINE_RELEVANCE_JSON")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[4] / "docs/realdata/fsp_protocols/discipline_relevance.json"


@lru_cache(maxsize=4)
def _relevance_table(path: str) -> dict[str, dict[str, float]]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, dict[str, float]] = {}
    for code, d in (raw.get("disciplines") or {}).items():
        dirs = (d or {}).get("directions") or {}
        out[code] = {k: float(v) for k, v in dirs.items() if isinstance(v, (int, float))}
    return out


def relevance_coef(discipline: str | None, direction: str | None) -> tuple[float, str]:
    """(коэффициент 0,8..1,0, источник «правила вида спорта» | «запасная таблица»)."""
    from app.modules.fsp import relevance as rel

    table = _relevance_table(str(_relevance_path()))
    if discipline and direction and discipline in table and direction in table[discipline]:
        return max(REL_FLOOR, min(1.0, table[discipline][direction])), "правила вида спорта"
    return rel.coef(discipline, direction), "запасная таблица"


def relevance_on() -> bool:
    from app.modules.profiles.facts import fsp_relevance_on

    return fsp_relevance_on()


# ---------------------------------------------------------------- сила

def details(achievements: list, *, direction: str | None = None, today: date | None = None,
            relevance: bool | None = None) -> dict:
    """Сила ФСП 0..1 с весом статуса; при одних «подтверждено» и выкл. профильности — то же число, что fsp-v2."""
    from app.modules.fsp.rating import RESULT_WEIGHTS, recency, result_kind, team_factor

    today = today or date.today()
    relevance = relevance_on() if relevance is None else relevance
    events: dict = {}
    counted = {"verified": 0, "pending_fsp": 0, "declared": 0, "excluded": 0}
    for a in achievements or []:
        st = status(a)
        counted[st] += 1
        w = STATUS_WEIGHT[st]
        if w <= 0:
            continue
        key = _ach_get(a, "event_id") or (str(_ach_get(a, "event_name") or "").strip().casefold(), _ach_get(a, "event_date"))
        c, src = relevance_coef(_ach_get(a, "discipline"), direction) if relevance else (1.0, "")
        value = RESULT_WEIGHTS[result_kind(a)] * recency(_ach_get(a, "event_date"), today) * team_factor(a) * w * c
        if key not in events or value > events[key]["value"]:
            events[key] = {"value": value, "status": st, "a": a, "coef": c, "coef_source": src}
    values = sorted((e["value"] for e in events.values()), reverse=True)
    strength = 0.8 * values[0] + 0.2 * (1 - math.exp(-sum(values[1:]))) if values else 0.0
    best = max(events.values(), key=lambda e: e["value"]) if values else None
    return {"version": VERSION, "strength": round(strength, 3), "competitions": len(values), "counted": counted,
            "best": best, "policy": POLICY, "relevance": bool(relevance)}


def has_protocol(achievements: list, statuses=("pending_fsp", "verified")) -> bool:
    """Фильтр fsp_protocol_only: есть результат из официального протокола со статусом из statuses."""
    return any(is_protocol(a) and status(a) in statuses for a in achievements or [])
