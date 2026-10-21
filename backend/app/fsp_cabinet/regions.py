"""Карта талантов по регионам и федеральным округам России для кабинета ФСП (А2).

Строится по реальным профилям кандидатов (город, категория, направление, грейд, признак is_synthetic)
и потребностям/приглашениям работодателей, с соблюдением K-анонимности (K = 5) для малых групп.
Формирует разрыв «спрос − предложение» и подсказку «где провести соревнование ФСП».
"""
from __future__ import annotations

from collections import defaultdict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fsp_cabinet.analytics import K, Data, kc, load
from app.modules.auth.models import User
from app.modules.catalog.seed_data import DIRECTIONS, GRADE_ORDER
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


def resolve_geo(city: str | None, fallback_idx: int = 0) -> tuple[str, str]:
    c = (city or "").strip().lower().replace("ё", "е")
    if c in CITY_TO_GEO:
        return CITY_TO_GEO[c]
    for prefix, val in CITY_TO_GEO.items():
        if prefix in c:
            return val
    # Если город не указан у модельного кандидата — распределяем детерминированно по опорным ИТ-хабам округов
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

    # Потребности работодателей и приглашения по регионам
    for idx, n in enumerate(d.needs):
        comp = companies.get(n.company_id)
        city = getattr(n, "city", None) or (comp.city if comp else None)
        dist_id, reg_title = resolve_geo(city, idx)
        st = dist_stats[dist_id]
        st["demand_needs"] += 1
        if n.direction:
            st["demand_by_direction"][n.direction] += 1
        st["regions"][reg_title]["demand"] += 1

    prof_by_uid = {p.user_id: (idx, p) for idx, p in enumerate(profiles)}
    for inv in d.invs:
        entry = prof_by_uid.get(inv.candidate_user_id)
        if entry:
            idx, p = entry
            dist_id, reg_title = resolve_geo(p.city, idx)
        else:
            comp = companies.get(inv.company_id)
            dist_id, reg_title = resolve_geo(comp.city if comp else None, 0)
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
        # Спрос выражаем в сопоставимых единицах (потребности * 3 + приглашения)
        demand_score = st["demand_needs"] * 3 + st["demand_invitations"]
        gap = demand_score - c_raw
        # Находим направление с наибольшим дефицитом в округе
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
    }
