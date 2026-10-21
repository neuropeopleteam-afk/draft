"""Кабинет ФСП, блок «Польза для ФСП» (Я29, за TARIFFS_ENABLED): приглашения и наймы участников ФСП по регионам и
направлениям, вклад компаний-партнёров ФСП, доля приглашений с ФСП-бонусом, компании по тарифам.

Те же правила раскрытия, что у остального кабинета (app/fsp_cabinet/analytics.py): только агрегаты, минимальная
группа K = 5 (число людей 1–4 → «< 5», доля — только при раскрываемых числителе и знаменателе), вторичное подавление
в разбиениях, песочницы жюри не входят. Названия компаний показываются только у партнёров ФСП — метка партнёра
публична (видна кандидатам в карточке компании); число людей у отдельного партнёра — тоже по правилу K.

«Участник ФСП» — кандидат с подтверждённым реестром достижением (T2; кубки платформы не в счёт) — ровно те, кому
рейтинг подбора начисляет ФСП-бонус. «Регион» — субъект РФ по городу из профиля кандидата (REGION_OF_CITY).
«Найм» — исход найма «вышел на работу» (app.modules.hiring, HiringOutcome.outcome = hired).
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import as_aware
from app.core.enums import InvitationStatus
from app.fsp_cabinet.analytics import K, Data, cache_get, cache_set, kc, kr, load_cached
from app.modules.catalog.seed_data import DIRECTIONS
from app.modules.hiring.models import HiringOutcome
from app.modules.profiles.models import CandidateProfile, Company

REGION_OF_CITY = {
    "москва": "Москва", "санкт-петербург": "Санкт-Петербург", "казань": "Республика Татарстан",
    "иннополис": "Республика Татарстан", "новосибирск": "Новосибирская область",
    "екатеринбург": "Свердловская область", "нижний новгород": "Нижегородская область", "томск": "Томская область",
    "самара": "Самарская область", "краснодар": "Краснодарский край", "пермь": "Пермский край",
    "ростов-на-дону": "Ростовская область", "уфа": "Республика Башкортостан", "челябинск": "Челябинская область",
    "воронеж": "Воронежская область", "красноярск": "Красноярский край", "омск": "Омская область",
    "владивосток": "Приморский край", "калининград": "Калининградская область", "тюмень": "Тюменская область",
    "ижевск": "Удмуртская Республика", "саратов": "Саратовская область", "волгоград": "Волгоградская область",
    "иркутск": "Иркутская область", "хабаровск": "Хабаровский край", "ярославль": "Ярославская область",
    "тула": "Тульская область", "сочи": "Краснодарский край", "севастополь": "Севастополь",
}
NO_REGION = "Регион не указан"
OTHER = "Другие регионы"


def region_of(city: str | None) -> str:
    c = (city or "").strip().lower().replace("ё", "е")
    if not c:
        return NO_REGION
    return REGION_OF_CITY.get(c, OTHER)


def _row(key: str, title: str, cands: list, invs: list, hired: set, fsp_inv: set) -> dict:
    """Строка разбиения: люди — по правилу K, приглашения (события) — только если раскрыто число приглашённых."""
    fsp = [c for c in cands if c.has_fsp]
    inv_fsp = [i for i in invs if i.id in fsp_inv]
    invited = {i.candidate_user_id for i in inv_fsp}
    acc = {i.candidate_user_id for i in inv_fsp if i.status == InvitationStatus.accepted}
    hrd = {i.candidate_user_id for i in inv_fsp if i.id in hired}
    shown = kc(len(invited)) is not None
    return {"key": key, "title": title, "candidates_fsp": kc(len(fsp)), "invited_fsp": kc(len(invited)),
            "invite_rate_fsp": kr(len(invited), len(fsp)),
            "invitations_fsp": len(inv_fsp) if shown else None, "accepted_fsp": kc(len(acc)),
            "hired_fsp": kc(len(hrd)), "accept_rate_fsp": kr(len(acc), len(invited)),
            "fsp_invite_share": (kr(len(invited), len({i.candidate_user_id for i in invs}))
                                 if invs else None)}


_PEOPLE = ("candidates_fsp", "invited_fsp", "invite_rate_fsp", "invitations_fsp", "accepted_fsp", "hired_fsp",
           "accept_rate_fsp", "fsp_invite_share")


def _secondary(rows: list[dict], total: dict, key: str) -> bool:
    """Если в разбиении скрыта ровно одна группа, а итог раскрыт — скрыть и наименьшую раскрытую (иначе скрытую
    восстановят вычитанием из итога). True — что-то скрыли."""
    hidden = [r for r in rows if r[key] is None]
    if len(hidden) == 1 and total.get(key) is not None:
        shown = sorted((r for r in rows if r[key] is not None), key=lambda r: r[key])
        if shown:
            v = shown[0]
            for k in _PEOPLE:
                v[k] = None
            v["secondary_suppressed"] = True
            return True
    return False


_SUPPRESS_KEYS = ("candidates_fsp", "invited_fsp", "accepted_fsp", "hired_fsp")


def _suppress(rows: list[dict], total: dict) -> None:
    """Вторичное подавление по всем числам людей до устойчивого состояния: скрытая строка по одному числу скрывает
    и остальные, поэтому проверка повторяется, пока ни по одному числу не остаётся ровно одной скрытой группы."""
    for _ in range(len(rows) + 1):
        if not any([_secondary(rows, total, k) for k in _SUPPRESS_KEYS]):
            return


def compute(
    db: Session,
    days: int | None = None,
    d: Data | None = None,
    include_demo: bool = True,
    jury_key: str | None = None,
) -> dict:
    from app.modules.tariffs import plans as P
    from app.modules.tariffs import service as tariffs

    if d is None:
        cached = cache_get("benefit", db, days, include_demo, jury_key=jury_key)
        if isinstance(cached, dict):
            return cached
        d = load_cached(db, days, include_demo=include_demo, jury_key=jury_key)
    fsp_inv = {i.id for i in d.invs if (c := d.cands.get(i.candidate_user_id)) is not None and c.has_fsp}
    inv_ids = [i.id for i in d.invs]
    hired = set(db.scalars(select(HiringOutcome.invitation_id).where(HiringOutcome.invitation_id.in_(inv_ids),
                                                                    HiringOutcome.outcome == "hired")).all()) if inv_ids else set()
    cities = {uid: c.city for uid, c in d.cands.items()}
    cands = list(d.cands.values())
    invs_by_cand: dict = defaultdict(list)
    for i in d.invs:
        if i.candidate_user_id in d.cands:
            invs_by_cand[i.candidate_user_id].append(i)
    total = _row("all", "Все", cands, [i for i in d.invs if i.candidate_user_id in d.cands], hired, fsp_inv)

    # по регионам
    reg_c: dict[str, list] = defaultdict(list)
    for c in cands:
        reg_c[region_of(cities.get(c.user_id))].append(c)
    regions = []
    for reg, members in reg_c.items():
        invs = [i for c in members for i in invs_by_cand.get(c.user_id, [])]
        regions.append(_row(reg, reg, members, invs, hired, fsp_inv))
    regions.sort(key=lambda r: (r["key"] in (OTHER, NO_REGION), -(r["candidates_fsp"] or 0), r["title"]))
    _suppress(regions, total)

    # по направлениям
    dirs = []
    for dd, title in DIRECTIONS.items():
        members = [c for c in cands if c.direction == dd]
        invs = [i for c in members for i in invs_by_cand.get(c.user_id, [])]
        dirs.append(_row(dd, title, members, invs, hired, fsp_inv))
    _suppress(dirs, total)

    # доля приглашений с ФСП-бонусом (события, а не люди: раскрывается, если приглашённых участников ФСП ≥ K или 0)
    n_all = len(d.invs)
    n_fsp = len(fsp_inv)
    share = round(n_fsp / n_all, 3) if n_all >= K and total["invited_fsp"] is not None else None

    # вклад партнёров ФСП (названия — публичная метка партнёра)
    companies = {i.company_id for i in d.invs} | {n.company_id for n in d.needs}
    from app.fsp_cabinet.analytics import _jury
    from app.modules.tariffs.models import CompanyTariff

    allowed = d.allowed_companies or _jury(db, include_demo=include_demo)[1]  # без песочниц жюри; партнёры без активности за период — тоже в списке (нули)
    partner_ids = {cid for cid in companies if tariffs.is_partner(db, cid)} | (
        set(db.scalars(select(CompanyTariff.company_id).where(CompanyTariff.fsp_partner.is_(True))).all()) & allowed)
    partners = []
    comps_map = d.companies_by_id or {}
    for cid in sorted(partner_ids, key=lambda x: ((comps_map.get(x) or db.get(Company, x)).name if (comps_map.get(x) or db.get(Company, x)) else "")):
        comp = comps_map.get(cid) or db.get(Company, cid)
        r = tariffs.row_of(db, cid)
        pinvs = [i for i in d.invs if i.company_id == cid]
        p_fsp = [i for i in pinvs if i.id in fsp_inv]
        n_people = len({i.candidate_user_id for i in p_fsp})
        partners.append({"company_id": str(cid), "name": comp.name if comp else "—", "city": comp.city if comp else None,
                         "partner_since": as_aware(r.partner_since).isoformat() if r and r.partner_since else None,
                         "needs": sum(1 for n in d.needs if n.company_id == cid), "invitations": len(pinvs),
                         "invitations_fsp": len(p_fsp) if kc(n_people) is not None else None,
                         "fsp_invite_share": (round(len(p_fsp) / len(pinvs), 3)
                                              if len(pinvs) >= K and kc(n_people) is not None else None),
                         "accepted": kc(len({i.candidate_user_id for i in pinvs if i.status == InvitationStatus.accepted})),
                         "accepted_fsp": kc(len({i.candidate_user_id for i in p_fsp
                                                 if i.status == InvitationStatus.accepted})),
                         "hired": kc(len({i.candidate_user_id for i in pinvs if i.id in hired})),
                         "hired_fsp": kc(len({i.candidate_user_id for i in p_fsp if i.id in hired}))})
    p_invs = [i for i in d.invs if i.company_id in partner_ids]
    p_fsp = [i for i in p_invs if i.id in fsp_inv]
    p_ok = kc(len({i.candidate_user_id for i in p_fsp})) is not None
    o_fsp = [i for i in d.invs if i.id in fsp_inv and i.company_id not in partner_ids]
    o_ok = kc(len({i.candidate_user_id for i in o_fsp})) is not None
    partners_total = {"companies": len(partner_ids), "invitations": len(p_invs),
                      "invitations_share": round(len(p_invs) / n_all, 3) if n_all >= K else None,
                      "invitations_fsp": len(p_fsp) if p_ok else None,
                      "fsp_share_of_partner_invitations": (round(len(p_fsp) / len(p_invs), 3)
                                                           if len(p_invs) >= K and p_ok else None),
                      "fsp_share_of_other_invitations": (round(len(o_fsp) / (n_all - len(p_invs)), 3)
                                                         if n_all - len(p_invs) >= K and o_ok else None),
                      "hired_fsp": kc(len({i.candidate_user_id for i in p_fsp if i.id in hired}))}
    plans_dist = tariffs.plans_distribution(db, companies)
    out = {"k": K, "period_days": days, "total": total,
            "invitations": n_all, "invitations_with_fsp_bonus": n_fsp if share is not None else None,
            "fsp_bonus_share": share, "hired_total": kc(len({i.candidate_user_id for i in d.invs if i.id in hired})),
            "regions": regions, "directions": dirs, "partners": partners, "partners_total": partners_total,
            "plans": [{"id": p["id"], "title": p["title"], "companies": plans_dist.get(p["id"], 0)} for p in P.PLANS],
            "demo_share": round(sum(1 for i in d.invs if i.company_id in d.demo_companies) / n_all, 3) if n_all else None,
            "methodology": METHODOLOGY}
    cache_set("benefit", db, days, include_demo, out, jury_key=jury_key)
    return out


METHODOLOGY = [
    f"Только агрегаты, минимальная группа {K}: число людей от 1 до 4 — «< {K}», доля — только при раскрываемых "
    "числителе и знаменателе; в разбиениях по регионам и направлениям — вторичное подавление.",
    "Участник ФСП — кандидат с достижением, подтверждённым реестром (T2); именно им рейтинг подбора начисляет "
    "ФСП-бонус. Доля приглашений с ФСП-бонусом — приглашения таким кандидатам среди всех приглашений периода.",
    "Регион — субъект РФ по городу из профиля кандидата; города вне справочника — «Другие регионы».",
    "Найм — исход «вышел на работу», который отметил работодатель после принятого приглашения.",
    "Партнёры ФСП — компании с меткой «Партнёр ФСП» (выдаёт федерация); метка публична, поэтому названия показаны. "
    "Связь «партнёрство → приглашения участникам ФСП» наблюдательная, не причинная.",
]


CSV_COLS = ["раздел", "группа", "участников ФСП", "приглашено участников", "доля приглашённых", "приглашений",
            "приняли", "наняты", "доля участников ФСП среди приглашённых"]


def csv_rows(rep: dict) -> list[list]:
    def cell(v):
        return f"<{K}" if v is None else v

    out = []
    for sect, rows in (("Регион", rep["regions"]), ("Направление", rep["directions"])):
        for r in rows:
            out.append([sect, r["title"], cell(r["candidates_fsp"]), cell(r["invited_fsp"]), cell(r["invite_rate_fsp"]),
                        cell(r["invitations_fsp"]), cell(r["accepted_fsp"]), cell(r["hired_fsp"]),
                        cell(r["fsp_invite_share"])])
    for p in rep["partners"]:
        out.append(["Партнёр ФСП", p["name"], "", "", "", cell(p["invitations_fsp"]), cell(p["accepted_fsp"]),
                    cell(p["hired_fsp"]), cell(p["fsp_invite_share"])])
    t = rep["partners_total"]
    out.append(["Партнёры ФСП — итого", f"компаний: {t['companies']}", "", "", "", cell(t["invitations_fsp"]), "",
                cell(t["hired_fsp"]), cell(t["fsp_share_of_partner_invitations"])])
    out.append(["Все приглашения", f"всего: {rep['invitations']}", "", "", "", cell(rep["invitations_with_fsp_bonus"]),
                "", cell(rep["hired_total"]), cell(rep["fsp_bonus_share"])])
    return out
