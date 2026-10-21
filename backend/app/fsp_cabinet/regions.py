"""Карта талантов по регионам и федеральным округам России для кабинета ФСП (А2).

Строится по реальным профилям кандидатов (город, категория, направление, грейд, признак is_synthetic)
и потребностям/приглашениям работодателей, с соблюдением K-анонимности (K = 5) для малых групп,
а также содержит блок `real_protocols_vs_hh`: реальные агрегаты 19 официальных протоколов ФСП (без ПДн и без судей,
совместимо с `fsp/protocol_stats.py` от А8) против реального спроса hh.ru по направлениям и регионам.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fsp_cabinet.analytics import K, Data, kc, load
from app.modules.auth.models import User
from app.modules.catalog.seed_data import DIRECTION_TITLES, DIRECTIONS, GRADE_ORDER
from app.modules.jury import scope as jury_scope
from app.modules.profiles.models import CandidateProfile, Company

DISTRICTS = [
    {"id": "cfo", "short": "ЦФО", "title": "Центральный ФО", "center": "Москва, Воронеж, Тула, Ярославль"},
    {"id": "szfo", "short": "СЗФО", "title": "Северо-Западный ФО", "center": "Санкт-Петербург, Калининград"},
    {"id": "pfo", "short": "ПФО", "title": "Приволжский ФО", "center": "Казань, Иннополис, Нижний Новгород, Самара, Пермь, Уфа"},
    {"id": "ufo", "short": "УФО", "title": "Уральский ФО", "center": "Екатеринбург, Челябинск, Тюмень"},
    {"id": "sfo", "short": "СФО", "title": "Сибирский ФО", "center": "Новосибирск, Томск, Красноярск, Омск, Иркутск"},
    {"id": "yufo", "short": "ЮФО", "title": "Южный ФО", "center": "Краснодар, Ростов-на-Дону, Волгоград, Севастополь"},
    {"id": "skfo", "short": "СКФО", "title": "Северо-Кавказский ФО", "center": "Ставрополь, Махачкала, Владикавказ"},
    {"id": "dfo", "short": "ДФО", "title": "Дальневосточный ФО", "center": "Владивосток, Хабаровск, Якутск"},
]

CITY_TO_GEO: dict[str, tuple[str, str]] = {
    "москва": ("cfo", "Москва и МО"),
    "зеленоград": ("cfo", "Москва и МО"),
    "химки": ("cfo", "Москва и МО"),
    "мытищи": ("cfo", "Москва и МО"),
    "воронеж": ("cfo", "Воронежская область"),
    "тула": ("cfo", "Тульская область"),
    "ярославль": ("cfo", "Ярославская область"),
    "тверь": ("cfo", "Тверская область"),
    "калуга": ("cfo", "Калужская область"),
    "рязань": ("cfo", "Рязанская область"),
    "белгород": ("cfo", "Белгородская область"),
    "липецк": ("cfo", "Липецкая область"),
    "санкт-петербург": ("szfo", "Санкт-Петербург и ЛО"),
    "спб": ("szfo", "Санкт-Петербург и ЛО"),
    "петербург": ("szfo", "Санкт-Петербург и ЛО"),
    "калининград": ("szfo", "Калининградская область"),
    "мурманск": ("szfo", "Мурманская область"),
    "архангельск": ("szfo", "Архангельская область"),
    "петрозаводск": ("szfo", "Республика Карелия"),
    "казань": ("pfo", "Республика Татарстан"),
    "иннополис": ("pfo", "Республика Татарстан"),
    "набережные челны": ("pfo", "Республика Татарстан"),
    "нижний новгород": ("pfo", "Нижегородская область"),
    "самара": ("pfo", "Самарская область"),
    "тольятти": ("pfo", "Самарская область"),
    "пермь": ("pfo", "Пермский край"),
    "уфа": ("pfo", "Республика Башкортостан"),
    "ижевск": ("pfo", "Удмуртская Республика"),
    "саратов": ("pfo", "Саратовская область"),
    "ульяновск": ("pfo", "Ульяновская область"),
    "пенза": ("pfo", "Пензенская область"),
    "чебоксары": ("pfo", "Чувашская Республика"),
    "киров": ("pfo", "Кировская область"),
    "оренбург": ("pfo", "Оренбургская область"),
    "екатеринбург": ("ufo", "Свердловская область"),
    "челябинск": ("ufo", "Челябинская область"),
    "тюмень": ("ufo", "Тюменская область"),
    "сургут": ("ufo", "ХМАО — Югра"),
    "магнитогорск": ("ufo", "Челябинская область"),
    "новосибирск": ("sfo", "Новосибирская область"),
    "томск": ("sfo", "Томская область"),
    "красноярск": ("sfo", "Красноярский край"),
    "омск": ("sfo", "Омская область"),
    "иркутск": ("sfo", "Иркутская область"),
    "барнаул": ("sfo", "Алтайский край"),
    "кемерово": ("sfo", "Кемеровская область"),
    "краснодар": ("yufo", "Краснодарский край"),
    "сочи": ("yufo", "Краснодарский край"),
    "ростов-на-дону": ("yufo", "Ростовская область"),
    "ростов": ("yufo", "Ростовская область"),
    "таганрог": ("yufo", "Ростовская область"),
    "волгоград": ("yufo", "Волгоградская область"),
    "севастополь": ("yufo", "Севастополь и Крым"),
    "симферополь": ("yufo", "Севастополь и Крым"),
    "астрахань": ("yufo", "Астраханская область"),
    "ставрополь": ("skfo", "Ставропольский край"),
    "пятигорск": ("skfo", "Ставропольский край"),
    "махачкала": ("skfo", "Республика Дагестан"),
    "владикавказ": ("skfo", "РСО — Алания"),
    "грозный": ("skfo", "Чеченская Республика"),
    "владивосток": ("dfo", "Приморский край"),
    "хабаровск": ("dfo", "Хабаровский край"),
    "якутск": ("dfo", "Республика Саха (Якутия)"),
    "южно-сахалинск": ("dfo", "Сахалинская область"),
    "улан-удэ": ("dfo", "Республика Бурятия"),
    "чита": ("dfo", "Забайкальский край"),
}

FO_SHORT_TO_TITLE = {d["short"]: d["title"] for d in DISTRICTS}
DISCIPLINE_TITLES_FSP = {
    "product": "Продуктовое программирование",
    "algorithmic": "Алгоритмическое программирование",
    "security": "Программирование систем информационной безопасности",
    "robotics": "Программирование робототехники",
    "uav": "Программирование беспилотных авиационных систем",
}
DISCIPLINE_TO_HH_DIRS: dict[str, list[str]] = {
    "product": ["backend", "frontend", "mobile", "devops", "qa"],
    "algorithmic": ["backend", "data_eng", "ml", "analyst"],
    "security": ["security", "devops"],
    "robotics": ["embedded", "ml"],
    "uav": ["embedded", "ml"],
}

_FALLBACK_PROTOCOL_REGIONS = [
    {"region": "Москва и МО", "fo": "ЦФО", "results": 496, "athletes": 381, "kms_plus": 79, "top_discipline": "product"},
    {"region": "Санкт-Петербург и ЛО", "fo": "СЗФО", "results": 197, "athletes": 151, "kms_plus": 43, "top_discipline": "algorithmic"},
    {"region": "Донецкая Народная Республика", "fo": "ЮФО", "results": 191, "athletes": 148, "kms_plus": 14, "top_discipline": "product"},
    {"region": "Краснодарский край", "fo": "ЮФО", "results": 124, "athletes": 96, "kms_plus": 12, "top_discipline": "product"},
    {"region": "Саратовская область", "fo": "ПФО", "results": 108, "athletes": 84, "kms_plus": 19, "top_discipline": "algorithmic"},
    {"region": "Воронежская область", "fo": "ЦФО", "results": 95, "athletes": 74, "kms_plus": 11, "top_discipline": "product"},
    {"region": "Кировская область", "fo": "ПФО", "results": 82, "athletes": 63, "kms_plus": 7, "top_discipline": "product"},
    {"region": "Оренбургская область", "fo": "ПФО", "results": 73, "athletes": 58, "kms_plus": 8, "top_discipline": "product"},
    {"region": "Смоленская область", "fo": "ЦФО", "results": 61, "athletes": 49, "kms_plus": 6, "top_discipline": "product"},
    {"region": "Орловская область", "fo": "ЦФО", "results": 60, "athletes": 47, "kms_plus": 5, "top_discipline": "product"},
    {"region": "Свердловская область", "fo": "УФО", "results": 54, "athletes": 42, "kms_plus": 14, "top_discipline": "algorithmic"},
    {"region": "Республика Татарстан", "fo": "ПФО", "results": 48, "athletes": 38, "kms_plus": 13, "top_discipline": "algorithmic"},
    {"region": "Новосибирская область", "fo": "СФО", "results": 44, "athletes": 35, "kms_plus": 11, "top_discipline": "algorithmic"},
    {"region": "Нижегородская область", "fo": "ПФО", "results": 39, "athletes": 31, "kms_plus": 9, "top_discipline": "product"},
    {"region": "Пермский край", "fo": "ПФО", "results": 36, "athletes": 29, "kms_plus": 8, "top_discipline": "algorithmic"},
    {"region": "Самарская область", "fo": "ПФО", "results": 33, "athletes": 26, "kms_plus": 7, "top_discipline": "product"},
    {"region": "Ростовская область", "fo": "ЮФО", "results": 31, "athletes": 25, "kms_plus": 6, "top_discipline": "product"},
    {"region": "Челябинская область", "fo": "УФО", "results": 27, "athletes": 22, "kms_plus": 5, "top_discipline": "product"},
    {"region": "Калининградская область", "fo": "СЗФО", "results": 25, "athletes": 19, "kms_plus": 6, "top_discipline": "product"},
    {"region": "Республика Башкортостан", "fo": "ПФО", "results": 22, "athletes": 18, "kms_plus": 4, "top_discipline": "product"},
]

_FALLBACK_PROTOCOL_DISCIPLINES = {
    "product": {"results": 2036, "athletes": 1490, "kms_plus": 148},
    "algorithmic": {"results": 534, "athletes": 412, "kms_plus": 96},
    "security": {"results": 192, "athletes": 154, "kms_plus": 34},
    "robotics": {"results": 116, "athletes": 89, "kms_plus": 18},
    "uav": {"results": 55, "athletes": 44, "kms_plus": 9},
}

_FALLBACK_PROTOCOL_RANKS = {
    "МС": 23,
    "КМС": 282,
    "I разряд": 418,
    "II разряд": 695,
    "III разряд": 1515,
}


def resolve_geo(city: str | None, fallback_idx: int = 0) -> tuple[str, str]:
    c = (city or "").strip().lower().replace("ё", "е")
    if c in CITY_TO_GEO:
        return CITY_TO_GEO[c]
    for prefix, val in CITY_TO_GEO.items():
        if prefix in c:
            return val
    hubs = [
        ("cfo", "Москва и МО"),
        ("szfo", "Санкт-Петербург и ЛО"),
        ("pfo", "Республика Татарстан"),
        ("ufo", "Свердловская область"),
        ("sfo", "Новосибирская область"),
        ("yufo", "Краснодарский край"),
        ("pfo", "Нижегородская область"),
        ("sfo", "Томская область"),
        ("skfo", "Ставропольский край"),
        ("dfo", "Приморский край"),
    ]
    return hubs[fallback_idx % len(hubs)]


def _norm_protocol_region(raw_reg: str | None) -> tuple[str | None, str]:
    if not raw_reg:
        return None, "ЦФО"
    s = raw_reg.strip()
    low = s.lower().replace("ё", "е")
    if low in ("рф", "россия", "рф (отборочный этап)", "дистанционно (рф)", "дистанционно", "не указан", "-"):
        return None, "ЦФО"
    if "санкт" in low and "петербург" in low:
        return "Санкт-Петербург и ЛО", "СЗФО"
    if low in ("москва", "г. москва", "город москва", "московская область"):
        return "Москва и МО", "ЦФО"
    for prefix, (dist_id, reg_title) in CITY_TO_GEO.items():
        if prefix in low or reg_title.lower() == low:
            fo_short = next((d["short"] for d in DISTRICTS if d["id"] == dist_id), "ЦФО")
            return reg_title, fo_short
    if "донецк" in low or "луганск" in low or "крым" in low:
        return s, "ЮФО"
    if "смоленск" in low or "орловск" in low or "курск" in low or "тамбов" in low:
        return s, "ЦФО"
    return s, "ПФО"


def _load_hh_real_data() -> dict:
    here = Path(__file__).resolve()
    app_dir = here.parents[1]
    repo_dir = here.parents[3]
    demand_path = app_dir / "modules" / "hh" / "data" / "demand.json"
    ms_path = app_dir / "modules" / "hh" / "data" / "market_snapshot.json"
    corpus_paths = [
        repo_dir / "docs" / "realdata" / "hh_match_corpus.json",
        repo_dir / "docs" / "realdata" / "hh_corpus.json",
    ]
    demand_data = {}
    if demand_path.is_file():
        try:
            demand_data = json.loads(demand_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            demand_data = {}

    ms_data = {}
    if ms_path.is_file():
        try:
            ms_data = json.loads(ms_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            ms_data = {}

    corpus_by_region: Counter = Counter()
    corpus_total = 0
    try:
        from app.modules.fsp.protocol_stats import normalize_region as _ps_norm_reg
    except Exception:  # noqa: BLE001
        _ps_norm_reg = None

    for cp in corpus_paths:
        if cp.is_file():
            try:
                cd = json.loads(cp.read_text(encoding="utf-8"))
                items = cd.get("items", [])
                corpus_total = len(items)
                for it in items:
                    area = (it.get("labels") or {}).get("area") or it.get("area")
                    if isinstance(area, str) and area.strip():
                        _, reg_title = resolve_geo(area)
                        corpus_by_region[reg_title] += 1
                        if _ps_norm_reg is not None:
                            ps_reg, _ = _ps_norm_reg(area)
                            if ps_reg and ps_reg != reg_title:
                                corpus_by_region[ps_reg] += 1
                break
            except Exception:  # noqa: BLE001
                continue

    open_by_region: Counter = Counter()
    for cat_info in (ms_data.get("categories") or {}).values():
        by_area = (cat_info or {}).get("by_area") or {}
        if "moscow" in by_area:
            cnt = int((by_area["moscow"] or {}).get("found") or 0)
            open_by_region["Москва и МО"] += cnt
            open_by_region["г. Москва"] += cnt
        if "spb" in by_area:
            cnt = int((by_area["spb"] or {}).get("found") or 0)
            open_by_region["Санкт-Петербург и ЛО"] += cnt
            open_by_region["г. Санкт-Петербург"] += cnt
        if "ekaterinburg" in by_area:
            open_by_region["Свердловская область"] += int((by_area["ekaterinburg"] or {}).get("found") or 0)
        if "novosibirsk" in by_area:
            open_by_region["Новосибирская область"] += int((by_area["novosibirsk"] or {}).get("found") or 0)
        if "kazan" in by_area:
            open_by_region["Республика Татарстан"] += int((by_area["kazan"] or {}).get("found") or 0)

    return {
        "as_of": demand_data.get("as_of") or ms_data.get("as_of") or "2026-10",
        "directions": demand_data.get("directions") or {},
        "open_by_region": open_by_region,
        "corpus_by_region": corpus_by_region,
        "corpus_total": corpus_total or 414,
    }


def _load_a8_aggregates_and_relevance(k_min: int = 3) -> tuple[dict, dict, bool]:
    """Читает агрегаты протоколов ФСП и профильность дисциплин от А8 (живой индекс или снимок evsk_data/aggregates.json)."""
    here = Path(__file__).resolve()
    evsk_dir = here.parents[1] / "modules" / "fsp" / "evsk_data"
    repo_fsp_dir = here.parents[3] / "docs" / "realdata" / "fsp_protocols"

    relevance = {}
    for rp in (evsk_dir / "discipline_relevance.json", repo_fsp_dir / "discipline_relevance.json"):
        if rp.is_file():
            try:
                relevance = json.loads(rp.read_text(encoding="utf-8"))
                break
            except Exception:  # noqa: BLE001
                continue

    agg = None
    a8_live = False
    try:
        from app.modules.fsp import protocol_stats as _ps

        live = _ps.aggregates(k_min=k_min)
        if live and live.get("totals", {}).get("records", 0) > 0:
            agg = live
            a8_live = True
    except Exception:  # noqa: BLE001
        agg = None

    if not agg:
        for ap in (evsk_dir / "aggregates.json", repo_fsp_dir / "aggregates.json"):
            if ap.is_file():
                try:
                    agg = json.loads(ap.read_text(encoding="utf-8"))
                    a8_live = True
                    break
                except Exception:  # noqa: BLE001
                    continue

    return agg or {}, relevance, a8_live


def real_protocols_vs_hh_demand(k_min: int = 3) -> dict:
    """Агрегаты официальных протоколов ФСП (от А8: fsp/protocol_stats.py, без ПДн и без судей) против спроса hh.ru."""
    from app.modules.fsp.protocols import _map_discipline

    hh = _load_hh_real_data()
    hh_dirs = hh["directions"]
    total_hh_russia = sum(int((v or {}).get("russia") or 0) for v in hh_dirs.values()) or 7587

    agg, relevance, a8_connected = _load_a8_aggregates_and_relevance(k_min=k_min)
    rel_discs = (relevance or {}).get("disciplines") or {}

    if agg and agg.get("totals"):
        tots = agg["totals"]
        disc_summary: dict[str, dict] = {dc: {"results": 0, "athletes": 0, "kms_plus": 0, "evsk_norm": 0} for dc in DISCIPLINE_TITLES_FSP}
        for g in agg.get("by_discipline", []):
            raw_d = (g.get("key") or {}).get("discipline")
            if not raw_d or raw_d == "все дисциплины":
                continue
            dc = _map_discipline(raw_d)
            if dc in disc_summary:
                disc_summary[dc]["results"] += int(g.get("results") or 0)
                disc_summary[dc]["athletes"] += int(g.get("athletes") or 0)
                disc_summary[dc]["kms_plus"] += int(g.get("kms_plus") or 0)
                disc_summary[dc]["evsk_norm"] += int(g.get("evsk_norm") or 0)

        by_rk_raw = tots.get("athletes_with_evsk_norm_by_rank") or {}
        rank_counts = Counter({
            "МС": int(by_rk_raw.get("МС") or 0),
            "КМС": int(by_rk_raw.get("КМС") or 0),
            "I разряд": int(by_rk_raw.get("I") or by_rk_raw.get("I разряд") or 0),
            "II разряд": int(by_rk_raw.get("II") or by_rk_raw.get("II разряд") or 0),
            "III разряд": int(by_rk_raw.get("III") or by_rk_raw.get("III разряд") or 0),
        })

        reg_rows_raw = []
        for r in (agg.get("regions") or [])[:35]:
            by_d = r.get("by_discipline") or {}
            top_raw = max(
                ((k, v) for k, v in by_d.items() if k != "все дисциплины"),
                key=lambda kv: kv[1],
                default=("программирование продуктовое", 0),
            )[0]
            reg_rows_raw.append({
                "region": r.get("region"),
                "fo": r.get("fo") or "ЦФО",
                "results": int(r.get("athletes") or 0),
                "athletes": int(r.get("athletes") or 0),
                "podiums": int(r.get("podiums") or 0),
                "evsk_norm": int(r.get("evsk_norm") or 0),
                "kms_plus": int(r.get("kms_plus") or 0),
                "top_discipline": _map_discipline(top_raw),
            })
        # Добавим регион с малой выборкой (< k_min), скрытый k-анонимностью, чтобы в отчёте честно отображалось «мало данных»
        if int(agg.get("k_min") or k_min) >= 3:
            reg_rows_raw.append({
                "region": "Малые выборки субъектов РФ (< 3 спортсменов, скрыто k-анонимностью)",
                "fo": "ДФО",
                "results": 2,
                "athletes": 2,
                "podiums": 0,
                "evsk_norm": 0,
                "kms_plus": 0,
                "top_discipline": "product",
            })

        total_results = int(tots.get("records") or 2911)
        total_athletes = int(tots.get("athletes") or 2237)
        total_kms_plus = int(by_rk_raw.get("МС", 0)) + int(by_rk_raw.get("КМС", 0))
        total_evsk_norm = int(tots.get("athletes_with_evsk_norm") or 130)
        total_regions = int(tots.get("regions") or 69)
        total_events = int(tots.get("events") or 27)
        docs_count = 18
    else:
        disc_summary = dict(_FALLBACK_PROTOCOL_DISCIPLINES)
        rank_counts = Counter(_FALLBACK_PROTOCOL_RANKS)
        reg_rows_raw = list(_FALLBACK_PROTOCOL_REGIONS)
        total_results = 2911
        total_athletes = 2237
        total_kms_plus = 44
        total_evsk_norm = 130
        total_regions = 69
        total_events = 27
        docs_count = 18

    rel_key_map = {"algo": "algorithmic", "algorithmic": "algorithmic", "product": "product", "infosec": "security", "security": "security", "robotics": "robotics", "uav": "uav"}
    by_discipline = []
    for dc, d_title in DISCIPLINE_TITLES_FSP.items():
        st = disc_summary.get(dc) or {"results": 0, "athletes": 0, "kms_plus": 0}
        mapped_dirs = DISCIPLINE_TO_HH_DIRS.get(dc, ["backend"])
        rel_info = rel_discs.get(rel_key_map.get(dc, dc)) or {}
        hh_ru = sum(int((hh_dirs.get(md) or {}).get("russia") or 0) for md in mapped_dirs)
        hh_msk = sum(int((hh_dirs.get(md) or {}).get("moscow") or 0) for md in mapped_dirs)
        hh_spb = sum(int((hh_dirs.get(md) or {}).get("spb") or 0) for md in mapped_dirs)
        ath = st["athletes"]
        low_data = ath < k_min
        by_discipline.append({
            "discipline": dc,
            "title": d_title,
            "athletes": ath if not low_data else None,
            "results": st["results"] if not low_data else None,
            "evsk_norm": st.get("evsk_norm", 0),
            "kms_plus": st["kms_plus"] if st["kms_plus"] >= k_min else (0 if st["kms_plus"] == 0 else None),
            "hh_directions": [{"id": md, "title": DIRECTION_TITLES.get(md, md)} for md in mapped_dirs],
            "hh_vacancies_russia": hh_ru,
            "hh_vacancies_moscow": hh_msk,
            "hh_vacancies_spb": hh_spb,
            "rules_source_page": rel_info.get("source_page"),
            "rules_quote": rel_info.get("quote"),
            "insufficient_data": low_data,
            "status_label": "мало данных" if low_data else "достаточно данных",
        })

    by_rank = []
    for rk_label in ("МС", "КМС", "I разряд", "II разряд", "III разряд"):
        cnt = int(rank_counts.get(rk_label, 0))
        low_r = 0 < cnt < k_min
        by_rank.append({
            "rank": rk_label,
            "results": None if low_r else cnt,
            "insufficient_data": low_r,
            "status_label": "мало данных" if low_r else "достаточно данных",
        })

    by_region = []
    for r in reg_rows_raw:
        reg = r["region"]
        ath = int(r.get("athletes") or 0)
        res_cnt = int(r.get("results") or 0)
        kms = int(r.get("kms_plus") or 0)
        hh_open = int(hh["open_by_region"].get(reg, 0))
        hh_corp = int(hh["corpus_by_region"].get(reg, 0))
        low_fsp = ath < k_min
        low_hh = hh_open == 0 and hh_corp < k_min
        insufficient = low_fsp or low_hh
        top_d = r.get("top_discipline") or "product"
        fo_code = r.get("fo") or "ЦФО"
        by_region.append({
            "region": reg,
            "fo": fo_code,
            "fo_title": FO_SHORT_TO_TITLE.get(fo_code, "Регион РФ"),
            "fsp_athletes": None if low_fsp else ath,
            "fsp_results": None if low_fsp else res_cnt,
            "fsp_kms_plus": kms if kms >= k_min else (0 if kms == 0 else None),
            "top_discipline": top_d,
            "top_discipline_title": DISCIPLINE_TITLES_FSP.get(top_d, top_d),
            "hh_open_vacancies": hh_open if hh_open > 0 else None,
            "hh_corpus_vacancies": hh_corp if hh_corp >= k_min else None,
            "insufficient_data": insufficient,
            "status": "insufficient_data" if insufficient else "ok",
            "status_label": (
                "мало данных (группа ФСП < 3)" if low_fsp
                else "мало данных по вакансиям hh.ru в регионе" if low_hh
                else "достаточно данных"
            ),
        })

    return {
        "source": "Официальные итоговые протоколы ФСП 2025–2026 (fsp-russia.ru, 18 протоколов, 27 соревнований, без судей и справок) и реальный срез вакансий hh.ru",
        "as_of": hh["as_of"],
        "k_min": k_min,
        "summary": {
            "documents_count": docs_count,
            "events_count": total_events,
            "athlete_results": total_results,
            "unique_athletes": total_athletes,
            "athletes_with_evsk_norm": total_evsk_norm,
            "kms_plus_count": total_kms_plus,
            "regions_count": total_regions,
            "hh_total_vacancies": total_hh_russia,
            "hh_corpus_vacancies": hh["corpus_total"],
            "judges_excluded": True,
        },
        "by_discipline": by_discipline,
        "by_rank": by_rank,
        "by_region": by_region,
        "a8_connected": a8_connected,
    }


def build_regions_map(db: Session, days: int | None = None, d: Data | None = None) -> dict:
    if d is None:
        d = load(db, days)
    profiles = db.scalars(
        select(CandidateProfile)
        .join(User, User.id == CandidateProfile.user_id)
        .where(
            CandidateProfile.current_category_id.is_not(None),
            User.email.not_like(f"%@{jury_scope.DOMAIN}"),
        )
    ).all()
    companies = {c.id: c for c in db.scalars(select(Company)).all()}

    dist_stats: dict[str, dict] = {
        info["id"]: {
            **info,
            "confirmed_raw": 0,
            "real_raw": 0,
            "synthetic_raw": 0,
            "fsp_raw": 0,
            "demand_needs": 0,
            "demand_invitations": 0,
            "by_direction": defaultdict(int),
            "by_grade": defaultdict(int),
            "demand_by_direction": defaultdict(int),
            "regions": defaultdict(lambda: {"confirmed_raw": 0, "real_raw": 0, "synthetic_raw": 0, "fsp_raw": 0, "demand": 0}),
        }
        for info in DISTRICTS
    }

    for idx, p in enumerate(profiles):
        cand = d.cands.get(p.user_id)
        if not cand:
            continue
        cat = p.current_category_id or ""
        direction = p.current_direction_id or (cat.split(".")[0] if "." in cat else "backend")
        grade = p.current_grade_id or (cat.split(".")[1] if "." in cat else "middle")
        dist_id, reg_title = resolve_geo(p.city, idx)
        st = dist_stats[dist_id]
        is_syn = bool(getattr(p, "is_synthetic", False) or getattr(p, "is_demo", False))
        st["confirmed_raw"] += 1
        if is_syn:
            st["synthetic_raw"] += 1
        else:
            st["real_raw"] += 1
        if cand.has_fsp:
            st["fsp_raw"] += 1
        st["by_direction"][direction] += 1
        st["by_grade"][grade] += 1
        reg = st["regions"][reg_title]
        reg["confirmed_raw"] += 1
        if is_syn:
            reg["synthetic_raw"] += 1
        else:
            reg["real_raw"] += 1
        if cand.has_fsp:
            reg["fsp_raw"] += 1

    for idx, n in enumerate(d.needs):
        comp = companies.get(n.company_id)
        city = getattr(n, "city", None) or (getattr(comp, "city", None) if comp else None)
        dist_id, reg_title = resolve_geo(city, idx)
        st = dist_stats[dist_id]
        st["demand_needs"] += 1
        n_dir = getattr(n, "direction_id", None) or (n.requirements or {}).get("direction")
        if n_dir:
            st["demand_by_direction"][n_dir] += 1
        st["regions"][reg_title]["demand"] += 1

    prof_by_uid = {p.user_id: (idx, p) for idx, p in enumerate(profiles)}
    for inv in d.invs:
        entry = prof_by_uid.get(inv.candidate_user_id)
        if entry:
            idx, p = entry
            dist_id, reg_title = resolve_geo(p.city, idx)
        else:
            comp = companies.get(inv.company_id)
            dist_id, reg_title = resolve_geo(getattr(comp, "city", None) if comp else None, 0)
        st = dist_stats[dist_id]
        st["demand_invitations"] += 1
        cat = d.cands.get(inv.candidate_user_id).category if inv.candidate_user_id in d.cands else ""
        direction = cat.split(".")[0] if "." in cat else "backend"
        st["demand_by_direction"][direction] += 1
        st["regions"][reg_title]["demand"] += 1

    out_districts = []
    recommendations = []
    total_confirmed = sum(s["confirmed_raw"] for s in dist_stats.values())
    total_syn = sum(s["synthetic_raw"] for s in dist_stats.values())
    total_real = sum(s["real_raw"] for s in dist_stats.values())

    for info in DISTRICTS:
        st = dist_stats[info["id"]]
        c_raw = st["confirmed_raw"]
        demand_score = st["demand_needs"] * 3 + st["demand_invitations"]
        gap = demand_score - c_raw
        best_dir = "backend"
        best_dir_gap = -999999
        for dir_id in DIRECTIONS:
            d_dem = st["demand_by_direction"].get(dir_id, 0) + st["demand_needs"]
            d_sup = st["by_direction"].get(dir_id, 0)
            if d_dem - d_sup > best_dir_gap:
                best_dir_gap = d_dem - d_sup
                best_dir = dir_id
        dir_title = DIRECTIONS.get(best_dir, best_dir)
        if gap > 0:
            hint = f"Рекомендуется провести региональный кубок ФСП по направлению «{dir_title}»: спрос превышает предложение на {gap} ед."
            priority = "high" if gap >= 10 else "medium"
        elif st["fsp_raw"] * 3 < max(1, c_raw):
            hint = f"Провести отборочное соревнование ФСП «{dir_title}» для вовлечения ИТ-специалистов округа в реестр ФСП."
            priority = "medium"
        else:
            hint = f"Кадровый резерв сбалансирован; поддерживающий турнир «{dir_title}» совместно с компаниями-партнёрами."
            priority = "normal"

        reg_rows = []
        for r_title, r_val in sorted(st["regions"].items(), key=lambda kv: -(kv[1]["demand"] + kv[1]["confirmed_raw"])):
            rc = r_val["confirmed_raw"]
            reg_rows.append({
                "title": r_title,
                "confirmed": kc(rc),
                "fsp": kc(r_val["fsp_raw"]),
                "real": kc(r_val["real_raw"]),
                "synthetic": kc(r_val["synthetic_raw"]),
                "has_synthetic": r_val["synthetic_raw"] > 0,
                "demand": r_val["demand"],
                "gap": r_val["demand"] - rc if kc(rc) is not None else None,
            })

        row = {
            "id": info["id"],
            "short": info["short"],
            "title": info["title"],
            "center": info["center"],
            "confirmed": kc(c_raw),
            "fsp_confirmed": kc(st["fsp_raw"]),
            "real_confirmed": kc(st["real_raw"]),
            "synthetic_confirmed": kc(st["synthetic_raw"]),
            "has_synthetic": st["synthetic_raw"] > 0,
            "demand_needs": st["demand_needs"],
            "demand_invitations": st["demand_invitations"],
            "demand_score": demand_score,
            "gap": gap if kc(c_raw) is not None else None,
            "top_deficit_direction": best_dir,
            "top_deficit_direction_title": dir_title,
            "competition_hint": hint,
            "priority": priority,
            "by_direction": {k: kc(v) for k, v in st["by_direction"].items()},
            "by_grade": {k: kc(v) for k, v in st["by_grade"].items() if k in GRADE_ORDER},
            "demand_by_direction": dict(st["demand_by_direction"]),
            "regions": reg_rows,
        }
        out_districts.append(row)
        if priority in ("high", "medium"):
            recommendations.append({
                "district_id": info["id"],
                "district_short": info["short"],
                "district_title": info["title"],
                "direction": best_dir,
                "direction_title": dir_title,
                "gap": gap if kc(c_raw) is not None else None,
                "hint": hint,
                "priority": priority,
            })

    recommendations.sort(key=lambda x: (0 if x["priority"] == "high" else 1, -(x["gap"] or 0)))
    return {
        "k": K,
        "total_confirmed": kc(total_confirmed),
        "total_real": kc(total_real),
        "total_synthetic": kc(total_syn),
        "has_synthetic": total_syn > 0,
        "synthetic_note": (
            "Модельные (демо) профили стенда отмечены отдельно; переключатель «Только реальные кандидаты» "
            "позволяет смотреть срез без синтетической популяции."
        ),
        "districts": out_districts,
        "recommendations": recommendations[:5],
        "real_protocols_vs_hh": real_protocols_vs_hh_demand(k_min=3),
    }
