"""Статистика по официальным протоколам ФСП без персональных данных — для кабинета ФСП.

Источник — индекс протоколов (``FSP_PROTOCOLS_INDEX``, вне git, 152-ФЗ). Наружу уходят только агрегаты:
число уникальных спортсменов (по хэшу ФИО), результатов, призёров и выполненных нормативов ЕВСК в разрезе
дисциплины, субъекта РФ, федерального округа, года, статуса соревнования и возрастной группы. Группы меньше
``k_min`` человек (по умолчанию 3) скрываются — по ним нельзя узнать конкретного человека.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

DEFAULT_INDEX = "/opt/spectrek_fsp/data_local/fsp_protocols/index_v5.json"  # v5: места восстановлены (place_recover.py)

# 89 субъектов РФ: (официальное имя, федеральный округ, основы для распознавания записи протокола)
SUBJECTS: list[tuple[str, str, tuple[str, ...]]] = [
    ("Белгородская область", "ЦФО", ("белгород",)), ("Брянская область", "ЦФО", ("брянск",)),
    ("Владимирская область", "ЦФО", ("владимир",)), ("Воронежская область", "ЦФО", ("воронеж",)),
    ("Ивановская область", "ЦФО", ("иванов",)), ("Калужская область", "ЦФО", ("калуж",)),
    ("Костромская область", "ЦФО", ("костром",)), ("Курская область", "ЦФО", ("курск",)),
    ("Липецкая область", "ЦФО", ("липец",)), ("Московская область", "ЦФО", ("московская обл", "подмосков")),
    ("Орловская область", "ЦФО", ("орлов", "орёл", "орел")), ("Рязанская область", "ЦФО", ("рязан",)),
    ("Смоленская область", "ЦФО", ("смолен",)), ("Тамбовская область", "ЦФО", ("тамбов",)),
    ("Тверская область", "ЦФО", ("твер",)), ("Тульская область", "ЦФО", ("тульск", "тула")),
    ("Ярославская область", "ЦФО", ("ярослав",)), ("г. Москва", "ЦФО", ("москва",)),
    ("Республика Карелия", "СЗФО", ("карел",)), ("Республика Коми", "СЗФО", ("коми",)),
    ("Архангельская область", "СЗФО", ("архангель",)), ("Вологодская область", "СЗФО", ("вологод",)),
    ("Калининградская область", "СЗФО", ("калининград",)), ("Ленинградская область", "СЗФО", ("ленинград",)),
    ("Мурманская область", "СЗФО", ("мурман",)), ("Новгородская область", "СЗФО", ("новгородская",)),
    ("Псковская область", "СЗФО", ("псков",)), ("Ненецкий автономный округ", "СЗФО", ("ненец",)),
    ("г. Санкт-Петербург", "СЗФО", ("петербург",)),
    ("Республика Адыгея", "ЮФО", ("адыге",)), ("Республика Калмыкия", "ЮФО", ("калмык",)),
    ("Республика Крым", "ЮФО", ("крым",)), ("Краснодарский край", "ЮФО", ("краснодар", "кубан")),
    ("Астраханская область", "ЮФО", ("астрахан",)), ("Волгоградская область", "ЮФО", ("волгоград",)),
    ("Ростовская область", "ЮФО", ("ростов",)), ("г. Севастополь", "ЮФО", ("севастопол",)),
    ("Донецкая Народная Республика", "ЮФО", ("донецк", "днр")), ("Луганская Народная Республика", "ЮФО", ("луганск", "лнр")),
    ("Запорожская область", "ЮФО", ("запорож",)), ("Херсонская область", "ЮФО", ("херсон",)),
    ("Республика Дагестан", "СКФО", ("дагестан",)), ("Республика Ингушетия", "СКФО", ("ингуш",)),
    ("Кабардино-Балкарская Республика", "СКФО", ("кабардин",)), ("Карачаево-Черкесская Республика", "СКФО", ("карачаев",)),
    ("Республика Северная Осетия — Алания", "СКФО", ("осети",)), ("Чеченская Республика", "СКФО", ("чечен",)),
    ("Ставропольский край", "СКФО", ("ставрополь",)),
    ("Республика Башкортостан", "ПФО", ("башк",)), ("Республика Марий Эл", "ПФО", ("марий",)),
    ("Республика Мордовия", "ПФО", ("мордов",)), ("Республика Татарстан", "ПФО", ("татарстан", "казань", "иннополис")),
    ("Удмуртская Республика", "ПФО", ("удмурт",)), ("Чувашская Республика", "ПФО", ("чуваш",)),
    ("Пермский край", "ПФО", ("пермск", "пермь")), ("Кировская область", "ПФО", ("киров",)),
    ("Нижегородская область", "ПФО", ("нижегород", "нижний новгород")), ("Оренбургская область", "ПФО", ("оренбург",)),
    ("Пензенская область", "ПФО", ("пенз",)), ("Самарская область", "ПФО", ("самар",)),
    ("Саратовская область", "ПФО", ("саратов",)), ("Ульяновская область", "ПФО", ("ульянов",)),
    ("Курганская область", "УФО", ("курган",)), ("Свердловская область", "УФО", ("свердлов", "екатеринбург")),
    ("Тюменская область", "УФО", ("тюмен",)), ("Челябинская область", "УФО", ("челяб",)),
    ("Ханты-Мансийский автономный округ — Югра", "УФО", ("ханты", "югра")), ("Ямало-Ненецкий автономный округ", "УФО", ("ямал",)),
    ("Республика Алтай", "СФО", ("республика алтай",)), ("Республика Тыва", "СФО", ("тыва", "тува")),
    ("Республика Хакасия", "СФО", ("хакас",)), ("Алтайский край", "СФО", ("алтайский",)),
    ("Красноярский край", "СФО", ("красноярск",)), ("Иркутская область", "СФО", ("иркут",)),
    ("Кемеровская область — Кузбасс", "СФО", ("кемеров", "кузбасс")), ("Новосибирская область", "СФО", ("новосибир",)),
    ("Омская область", "СФО", ("омск",)), ("Томская область", "СФО", ("томск",)),
    ("Республика Бурятия", "ДФО", ("бурят",)), ("Республика Саха (Якутия)", "ДФО", ("саха(?!лин)", "якут")),
    ("Забайкальский край", "ДФО", ("забайкал",)), ("Камчатский край", "ДФО", ("камчат",)),
    ("Приморский край", "ДФО", ("примор",)), ("Хабаровский край", "ДФО", ("хабаров",)),
    ("Амурская область", "ДФО", ("амур",)), ("Магаданская область", "ДФО", ("магадан",)),
    ("Сахалинская область", "ДФО", ("сахалин",)), ("Еврейская автономная область", "ДФО", ("еврей",)),
    ("Чукотский автономный округ", "ДФО", ("чукот",)),
]
_ORDER = [s for s in SUBJECTS if s[0] != "г. Москва"] + [s for s in SUBJECTS if s[0] == "г. Москва"]  # «Москва» — последней


def normalize_region(raw: str | None) -> tuple[str | None, str | None]:
    """Строка «Субъект РФ» из протокола → (официальное имя, федеральный округ) или (None, None)."""
    t = (raw or "").lower().replace("ё", "е")
    t = re.sub(r"[^\w\s-]", " ", t)
    if not t.strip() or t.strip().startswith("рф"):
        return None, None
    for name, fo, stems in _ORDER:
        if any(re.search(r"\b" + s.replace("ё", "е"), t) for s in stems):
            # «Московская область, г. Пушкино» — область, а не город Москва
            return name, fo
    return None, None


def _index_path(index_path: str | Path | None) -> Path:
    return Path(index_path or os.environ.get("FSP_PROTOCOLS_INDEX") or DEFAULT_INDEX)


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("records", [])


def _records(index_path: str | Path | None) -> list[dict[str, Any]]:
    p = _index_path(index_path)
    if not p.exists():
        return []
    return _load(str(p), p.stat().st_mtime)


def _key(r: dict[str, Any], field: str) -> Any:
    if field == "region":
        return normalize_region(r.get("region"))[0]
    if field == "fo":
        return r.get("fo") or normalize_region(r.get("region"))[1]
    if field == "year":
        return (r.get("date") or "")[:4] or None
    if field == "evsk_rank":
        return r.get("evsk_rank") if r.get("evsk_status") == "fulfilled" else None
    return r.get(field)


def protocol_stats(group_by: Sequence[str] = ("discipline",), *, filters: dict[str, Any] | None = None,
                   k_min: int = 3, index_path: str | Path | None = None,
                   records: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Агрегаты по протоколам (см. модульную документацию). Только обезличенные числа."""
    recs = [r for r in (records if records is not None else _records(index_path)) if r.get("person")]
    if filters:
        recs = [r for r in recs if all(_key(r, k) == v for k, v in filters.items())]
    groups: dict[tuple, dict[str, set]] = defaultdict(lambda: {"athletes": set(), "podium": set(), "kms": set(), "norm": set(), "results": set()})
    for r in recs:
        k = tuple(_key(r, f) for f in group_by)
        g = groups[k]
        h = r.get("fio_hash")
        g["athletes"].add(h)
        g["results"].add((h, r.get("event_id"), r.get("place")))
        try:
            if 1 <= int(r.get("place") or 0) <= 3:
                g["podium"].add(h)
        except (TypeError, ValueError):
            pass
        if r.get("evsk_status") == "fulfilled" and r.get("evsk_rank"):
            g["norm"].add(h)
            if r["evsk_rank"] in ("МС", "КМС"):
                g["kms"].add(h)
    out, suppressed = [], 0
    for k, g in sorted(groups.items(), key=lambda kv: (-len(kv[1]["athletes"]), [str(x) for x in kv[0]])):
        n = len(g["athletes"])
        if n < k_min:
            suppressed += 1
            continue
        out.append({"key": dict(zip(group_by, k)), "athletes": n, "results": len(g["results"]),
                    "podiums": len(g["podium"]), "evsk_norm": len(g["norm"]), "kms_plus": len(g["kms"])})
    return {"source": {"index": _index_path(index_path).name, "records_used": len(recs)},
            "group_by": list(group_by), "k_min": k_min, "groups": out, "suppressed_groups": suppressed}


def regions_summary(k_min: int = 3, *, index_path: str | Path | None = None,
                    records: Iterable[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Карта талантов: по каждому субъекту РФ — спортсмены, нормативы ЕВСК, разбивка по дисциплинам."""
    recs = list(records if records is not None else _records(index_path))
    base = protocol_stats(("region", "fo"), k_min=k_min, records=recs)
    disc = protocol_stats(("region", "discipline"), k_min=k_min, records=recs)
    by_region: dict[str, dict[str, int]] = defaultdict(dict)
    for g in disc["groups"]:
        if g["key"]["region"]:
            by_region[g["key"]["region"]][g["key"]["discipline"]] = g["athletes"]
    rows = []
    for g in base["groups"]:
        reg = g["key"]["region"]
        if not reg:
            continue
        rows.append({"region": reg, "fo": g["key"]["fo"], "athletes": g["athletes"], "podiums": g["podiums"],
                     "evsk_norm": g["evsk_norm"], "kms_plus": g["kms_plus"], "by_discipline": by_region.get(reg, {})})
    return rows


def aggregates(k_min: int = 3, *, index_path: str | Path | None = None,
               records: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Полный снимок для docs/realdata/fsp_protocols/aggregates.json и кабинета ФСП."""
    recs = list(records if records is not None else _records(index_path))
    persons = [r for r in recs if r.get("person")]
    regions_known = {normalize_region(r.get("region"))[0] for r in persons} - {None}
    norm_athletes: dict[str, str] = {}
    order = ["МС", "КМС", "I", "II", "III", "Iю", "IIю", "IIIю"]
    for r in persons:
        if r.get("evsk_status") == "fulfilled" and r.get("evsk_rank") in order:
            h = r["fio_hash"]
            if h not in norm_athletes or order.index(r["evsk_rank"]) < order.index(norm_athletes[h]):
                norm_athletes[h] = r["evsk_rank"]
    by_rank: dict[str, int] = defaultdict(int)
    for v in norm_athletes.values():
        by_rank[v] += 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "k_min": k_min,
        "totals": {
            "records": len(recs),
            "person_results": len(persons),
            "athletes": len({r.get("fio_hash") for r in persons}),
            "events": len({r.get("event_id") for r in recs}),
            "regions": len(regions_known),
            "athletes_with_evsk_norm": len(norm_athletes),
            "athletes_with_evsk_norm_by_rank": dict(by_rank),
            "results_needing_second_result": sum(1 for r in persons if r.get("evsk_status") == "needs_second_result"),
        },
        "by_discipline": protocol_stats(("discipline",), k_min=k_min, records=recs)["groups"],
        "by_year_discipline": protocol_stats(("year", "discipline"), k_min=k_min, records=recs)["groups"],
        "by_event_status": protocol_stats(("event_status",), k_min=k_min, records=recs)["groups"],
        "by_fo": protocol_stats(("fo",), k_min=k_min, records=recs)["groups"],
        "regions": regions_summary(k_min, records=recs),
    }
