"""Кабинет ФСП: обезличенная аналитика платформы — только агрегаты.

Правила раскрытия (проверяются tests/test_fsp_cabinet.py):
* ни ФИО, ни почт, ни обезличенных номеров кандидатов, ни текстов потребностей — только числа по группам;
* минимальный размер группы K = 5: число людей от 1 до 4 не показывается («< 5»), 0 показывается;
  доля показывается, только если и числитель, и знаменатель раскрываемы;
* зарплатная ячейка — не меньше K приглашений, K разных кандидатов и двух разных компаний (вилка одной
  компании не раскрывается);
* названия компаний — только у кубков (кубок — публичное мероприятие).

Копии демо жюри (учётки ``…@jury.example.com``, их компании и кубки — app.modules.jury.scope) в аналитику не
входят: сколько бы экспертов жюри ни открыли свою песочницу, цифры кабинета одни и те же.

Источники: приглашения-офферы (вилка «от–до» обязательна), потребности работодателей (структурированные
требования), подтверждённые навыки T1, паспорта ФСП (только verified — T2; кубки платформы считаются отдельно),
кубки работодателей. Связь «ФСП → приглашения» — наблюдательная: рейтинг уже учитывает ФСП, поэтому показан и
коэффициент с поправкой на категорию (наблюдаемое / ожидаемое по доле приглашённых в категории кандидата).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
import statistics
import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.db import as_aware, utcnow
from app.core.enums import EvidenceLevel, InvitationStatus
from app.cup.models import Cup, CupEntry
from app.modules.catalog.constants import FSP_DISCIPLINES
from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import DIRECTIONS, GRADE_ORDER, STACK, category_title, tag_title
from app.modules.fsp.models import FspAchievement, FspPassport
from app.modules.auth.models import User
from app.modules.invitations.models import Invitation
from app.modules.jury import scope as jury_scope
from app.modules.matching.models import EmployerNeed
from app.modules.profiles.models import CandidateFact, CandidateProfile, Company

K = 5
MIN_COMPANIES_SALARY = 2
DISCIPLINE_TITLES = {d["id"]: d["title"] for d in FSP_DISCIPLINES}
LEVEL_ORDER = ["international", "national", "interregional", "regional", "school"]
LEVEL_TITLES = {"international": "Международные", "national": "Всероссийские", "interregional": "Межрегиональные",
                "regional": "Региональные", "school": "Школьные"}
RESULT_ORDER = [("winner", "Победители"), ("prize", "Призёры (2–3 место)"), ("finalist", "Финалисты (4–10)"),
                ("participant", "Участники")]
RANKS = [("ms", "МС / МСМК"), ("kms", "КМС"), ("r1", "I разряд"), ("r2", "II разряд"), ("r3", "III разряд"),
         ("none", "Без разряда")]
ANSWERED = (InvitationStatus.accepted, InvitationStatus.declined)
SEEN = (InvitationStatus.viewed, InvitationStatus.accepted, InvitationStatus.declined)


def kc(n: int) -> int | None:
    """Число людей: 0 или ≥ K — показываем; 1..4 — None («< 5»)."""
    return n if n == 0 or n >= K else None


def kr(num: int, den: int) -> float | None:
    if den < K or kc(num) is None:
        return None
    return round(num / den, 3)


def _rank_bucket(rank: str | None) -> str:
    r = (rank or "").lower()
    if "мс" in r and "кмс" not in r:
        return "ms"
    if "кмс" in r:
        return "kms"
    if r.startswith("iii") or r.startswith("3"):
        return "r3"
    if r.startswith("ii") or r.startswith("2"):
        return "r2"
    if r.startswith("i") or r.startswith("1"):
        return "r1"
    return "none"


def _result_bucket(place: int | None) -> str:
    p = place or 99
    return "winner" if p == 1 else "prize" if p <= 3 else "finalist" if p <= 10 else "participant"


@dataclass
class Cand:
    user_id: uuid.UUID
    category: str
    direction: str
    has_fsp: bool = False
    rank: str = "none"
    disciplines: set = field(default_factory=set)
    best_level: str | None = None
    best_result: str | None = None
    skills: set = field(default_factory=set)
    invitations: list = field(default_factory=list)

    @property
    def invited(self) -> bool:
        return bool(self.invitations)

    @property
    def seen(self) -> bool:
        return any(i.status in SEEN for i in self.invitations)

    @property
    def accepted(self) -> bool:
        return any(i.status == InvitationStatus.accepted for i in self.invitations)


@dataclass
class Data:
    cands: dict[uuid.UUID, Cand]
    invs: list[Invitation]
    needs: list[EmployerNeed]
    categories: dict[str, Category]
    cups: list[Cup]
    entries: list[CupEntry]
    period_days: int | None
    demo_companies: set = field(default_factory=set)


def _jury(db: Session, include_demo: bool = True) -> tuple[set, set]:
    """Учётки демо жюри (общее демо и все песочницы) и компании, которые в аналитику входят: все, кроме компаний
    жюри (а при include_demo=False — и кроме всех демо-компаний и демо-пользователей)."""
    if not include_demo:
        users = set(db.scalars(select(User.id).where(User.is_demo.is_(True))).all())
        cond = Company.is_demo.is_(True)
        if users:
            cond = or_(cond, Company.created_by.in_(users))
        companies = set(db.scalars(select(Company.id)).all())
        return users, companies - set(db.scalars(select(Company.id).where(cond)).all())
    users = set(db.scalars(select(User.id).where(User.email.like(f"%@{jury_scope.DOMAIN}"))).all())
    cond = and_(Company.is_demo.is_(True), Company.name.like("Демо жюри%"))
    if users:
        cond = or_(cond, Company.created_by.in_(users))
    companies = set(db.scalars(select(Company.id)).all())
    return users, companies - set(db.scalars(select(Company.id).where(cond)).all())


def load(db: Session, days: int | None = None, include_demo: bool = True) -> Data:
    since = utcnow() - timedelta(days=days) if days else None
    jury_users, companies = _jury(db, include_demo=include_demo)
    cands: dict[uuid.UUID, Cand] = {}
    pq = select(CandidateProfile).join(User, User.id == CandidateProfile.user_id).where(
        CandidateProfile.current_category_id.is_not(None), User.email.not_like(f"%@{jury_scope.DOMAIN}")
    )
    if not include_demo:
        pq = pq.where(User.is_demo.is_(False), CandidateProfile.is_synthetic.is_(False))
    for p in db.scalars(pq).all():
        cands[p.user_id] = Cand(p.user_id, p.current_category_id, p.current_direction_id or p.current_category_id.split(".")[0])
    pp = {p.id: p for p in db.scalars(select(FspPassport).where(FspPassport.user_id.in_(list(cands)))).all()} if cands else {}
    for p in pp.values():
        cands[p.user_id].rank = _rank_bucket(p.sport_rank)
    if pp:
        for a in db.scalars(select(FspAchievement).where(FspAchievement.passport_id.in_(list(pp)),
                                                         FspAchievement.verified.is_(True))).all():
            if (a.source_ref or "").startswith("cup:"):
                continue
            c = cands[pp[a.passport_id].user_id]
            c.has_fsp = True
            c.disciplines.add(a.discipline)
            lvl = a.event_level.value if hasattr(a.event_level, "value") else a.event_level
            if lvl in LEVEL_ORDER and (c.best_level is None or LEVEL_ORDER.index(lvl) < LEVEL_ORDER.index(c.best_level)):
                c.best_level = lvl
            rb = _result_bucket(a.place)
            order = [r for r, _ in RESULT_ORDER]
            if c.best_result is None or order.index(rb) < order.index(c.best_result):
                c.best_result = rb
    for c in cands.values():
        if not c.has_fsp:
            c.rank = "none"
    if cands:
        for f in db.scalars(select(CandidateFact).where(CandidateFact.user_id.in_(list(cands)),
                                                        CandidateFact.kind == "skill",
                                                        CandidateFact.evidence_level == EvidenceLevel.T1)).all():
            if (f.value or {}).get("score", 0) >= 0.5:
                cands[f.user_id].skills.add(f.key)
    q = select(Invitation)
    if since:
        q = q.where(Invitation.created_at >= since)
    invs = [i for i in db.scalars(q).all() if i.status != InvitationStatus.withdrawn
            and i.company_id in companies and i.candidate_user_id not in jury_users]
    for i in invs:
        if i.candidate_user_id in cands:
            cands[i.candidate_user_id].invitations.append(i)
    nq = select(EmployerNeed)
    if since:
        nq = nq.where(EmployerNeed.created_at >= since)
    needs = [n for n in db.scalars(nq).all() if n.company_id in companies]
    cq = select(Cup).where(Cup.status != "cancelled", Cup.jury_scope.is_(None))
    if not include_demo:
        cq = cq.where(Cup.is_demo.is_(False))
    if since:
        cq = cq.where(Cup.ends_at >= since)
    cups = [c for c in db.scalars(cq).all() if c.company_id in companies]
    entries = [e for e in db.scalars(select(CupEntry).where(CupEntry.cup_id.in_([c.id for c in cups]))).all()
               if e.candidate_user_id not in jury_users] if cups else []
    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    demo = set(db.scalars(select(Company.id).where(Company.is_demo.is_(True))).all())
    return Data(cands, invs, needs, cats, cups, entries, days, demo)


# ------------------------------------------------------------------ разделы

def _pct(xs: list[float], q: float) -> int | None:
    if not xs:
        return None
    s = sorted(xs)
    i = (len(s) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(s) - 1)
    return int(round((s[lo] + (s[hi] - s[lo]) * (i - lo)) / 1000.0) * 1000)


def _salary_cell(invs: list[Invitation]) -> dict:
    n_c = len({i.candidate_user_id for i in invs})
    n_co = len({i.company_id for i in invs})
    ok = len(invs) >= K and n_c >= K and n_co >= MIN_COMPANIES_SALARY
    if not ok:
        return {"offers": kc(len(invs)), "suppressed": True,
                "reason": f"меньше {K} приглашений или кандидатов" if len(invs) < K or n_c < K else "одна компания"}
    mids = [(i.salary_from + i.salary_to) / 2 for i in invs]
    return {"offers": len(invs), "companies": n_co, "suppressed": False,
            "from_p25": _pct([i.salary_from for i in invs], 0.25), "from_median": _pct([i.salary_from for i in invs], 0.5),
            "to_median": _pct([i.salary_to for i in invs], 0.5), "to_p75": _pct([i.salary_to for i in invs], 0.75),
            "mid_median": _pct(mids, 0.5)}


def overview(d: Data) -> dict:
    cands = list(d.cands.values())
    companies = {i.company_id for i in d.invs} | {n.company_id for n in d.needs}
    invited = [c for c in cands if c.invited]
    acc = [c for c in cands if c.accepted]
    n_acc = sum(1 for i in d.invs if i.status == InvitationStatus.accepted)
    n_ans = sum(1 for i in d.invs if i.status in ANSWERED)
    parts = {e.candidate_user_id for e in d.entries}
    return {"candidates": kc(len(cands)), "candidates_fsp": kc(sum(c.has_fsp for c in cands)),
            "fsp_share": kr(sum(c.has_fsp for c in cands), len(cands)),
            "companies_active": len(companies), "needs": len(d.needs), "invitations": len(d.invs),
            "invited_candidates": kc(len(invited)), "accepted_candidates": kc(len(acc)),
            "acceptance_rate": kr(n_acc, n_ans) if n_ans else None, "answered_rate": kr(n_ans, len(d.invs)),
            "cups": len(d.cups), "cup_participants": kc(len(parts)), "k": K, "period_days": d.period_days,
            "demo_share": round(sum(1 for i in d.invs if i.company_id in d.demo_companies) / len(d.invs), 3)
            if d.invs else None}


def demand(d: Data) -> dict:
    by_cat_inv: dict[str, list[Invitation]] = defaultdict(list)
    for i in d.invs:
        c = d.cands.get(i.candidate_user_id)
        if c:
            by_cat_inv[c.category].append(i)
    needs_cat = Counter()
    needs_dir = Counter()
    comp_cat: dict[str, set] = defaultdict(set)
    for n in d.needs:
        if n.direction_id and n.grade_id:
            needs_cat[f"{n.direction_id}.{n.grade_id}"] += 1
            comp_cat[f"{n.direction_id}.{n.grade_id}"].add(n.company_id)
        elif n.direction_id:
            needs_dir[n.direction_id] += 1
    supply = Counter(c.category for c in d.cands.values())
    rows = []
    for cid, cat in sorted(d.categories.items(), key=lambda x: (list(DIRECTIONS).index(x[1].direction_id)
                                                                 if x[1].direction_id in DIRECTIONS else 9, x[1].grade_id)):
        invs = by_cat_inv.get(cid, [])
        invited = {i.candidate_user_id for i in invs}
        acc = {i.candidate_user_id for i in invs if i.status == InvitationStatus.accepted}
        comps = comp_cat[cid] | {i.company_id for i in invs}
        sup = supply.get(cid, 0)
        rows.append({"category_id": cid, "title": cat.title, "direction": cat.direction_id, "grade": cat.grade_id,
                     "needs": needs_cat.get(cid, 0), "companies": len(comps), "invitations": len(invs),
                     "invited_candidates": kc(len(invited)), "supply": kc(sup),
                     "invitations_per_10": round(10 * len(invs) / sup, 1) if sup >= K else None,
                     "invite_rate": kr(len(invited), sup), "accepted_candidates": kc(len(acc)),
                     "accept_rate": kr(len(acc), len(invited)),
                     "market_median": cat.market_salary_median})
    # навыки: потребности (обязательно = 1, желательно = 0,5) и подтверждённые навыки приглашённых
    w = Counter()
    req, des = Counter(), Counter()
    comps: dict[str, set] = defaultdict(set)
    for n in d.needs:
        r = n.requirements or {}
        for it in r.get("stack_required") or []:
            req[it["tag"]] += 1
            w[it["tag"]] += 1.0
            comps[it["tag"]].add(n.company_id)
        for it in r.get("stack_desired") or []:
            des[it["tag"]] += 1
            w[it["tag"]] += 0.5
            comps[it["tag"]].add(n.company_id)
    supply_sk = Counter()
    invited_sk = Counter()
    for c in d.cands.values():
        for s in c.skills:
            supply_sk[s] += 1
            if c.invited:
                invited_sk[s] += 1
    tags = sorted(set(w) | {t for t, _ in invited_sk.most_common(10)}, key=lambda t: (-w.get(t, 0), -invited_sk.get(t, 0)))
    skills = [{"tag": t, "title": tag_title(t), "direction": STACK.get(t, (None, None, None))[2],
               "needs_required": req.get(t, 0), "needs_desired": des.get(t, 0), "demand_weight": w.get(t, 0),
               "companies": len(comps.get(t, ())), "supply_confirmed": kc(supply_sk.get(t, 0)),
               "invited_with_skill": kc(invited_sk.get(t, 0)),
               "invite_rate_with_skill": kr(invited_sk.get(t, 0), supply_sk.get(t, 0))}
              for t in tags[:25]]
    return {"categories": rows, "needs_without_grade": dict(needs_dir), "skills": skills}


def _group(members: list[Cand], cat_rate: dict[str, float], base_rate: float | None) -> dict:
    n = len(members)
    inv = [c for c in members if c.invited]
    acc = [c for c in members if c.accepted]
    out = {"candidates": kc(n), "invited": kc(len(inv)), "invite_rate": kr(len(inv), n),
           "accepted": kc(len(acc)), "accept_rate": kr(len(acc), len(inv)),
           "invitations_per_candidate": round(sum(len(c.invitations) for c in members) / n, 2) if n >= K else None}
    expected = sum(cat_rate.get(c.category, 0.0) for c in members)
    out["lift_vs_no_fsp"] = (round(out["invite_rate"] / base_rate, 2)
                             if out["invite_rate"] is not None and base_rate else None)
    out["adjusted_ratio"] = round(len(inv) / expected, 2) if n >= K and expected > 0 and kc(len(inv)) is not None else None
    return out


def fsp_effect(d: Data) -> dict:
    cands = list(d.cands.values())
    by_cat: dict[str, list[Cand]] = defaultdict(list)
    for c in cands:
        by_cat[c.category].append(c)
    cat_rate = {k: sum(c.invited for c in v) / len(v) for k, v in by_cat.items() if v}
    nofsp = [c for c in cands if not c.has_fsp]
    base = kr(sum(c.invited for c in nofsp), len(nofsp))

    def g(key: str, title: str, members: list[Cand]) -> dict:
        return {"key": key, "title": title, **_group(members, cat_rate, base)}

    fsp = [c for c in cands if c.has_fsp]
    groups = [g("no_fsp", "Без истории ФСП (нейтрально)", nofsp), g("fsp", "С достижениями ФСП (T2)", fsp)]
    disc = [g(dd, DISCIPLINE_TITLES.get(dd, dd), [c for c in fsp if dd in c.disciplines]) for dd in DISCIPLINE_TITLES]
    ranks = [g(k, t, [c for c in fsp if c.rank == k]) for k, t in RANKS]
    results = [g(k, t, [c for c in fsp if c.best_result == k]) for k, t in RESULT_ORDER]
    levels = [g(k, LEVEL_TITLES[k], [c for c in fsp if c.best_level == k]) for k in LEVEL_ORDER]
    # вторичное подавление в разбиениях: одна скрытая группа восстанавливается вычитанием из итога
    for part in (ranks, results, levels):
        _secondary(part, fsp)
    by_dir = []
    for dd, title in DIRECTIONS.items():
        mem = [c for c in cands if c.direction == dd]
        by_dir.append({"direction": dd, "title": title,
                       "fsp": _group([c for c in mem if c.has_fsp], cat_rate, None),
                       "no_fsp": _group([c for c in mem if not c.has_fsp], cat_rate, None)})
    return {"groups": groups, "disciplines": disc, "ranks": ranks, "results": results, "levels": levels,
            "by_direction": by_dir, "base_invite_rate": base}


def _secondary(rows: list[dict], total_members: list[Cand]) -> None:
    hidden = [r for r in rows if r["candidates"] is None]
    if len(hidden) == 1 and kc(len(total_members)) is not None:
        shown = sorted((r for r in rows if r["candidates"]), key=lambda r: r["candidates"])
        if shown:
            victim = shown[0]
            for k in ("candidates", "invited", "invite_rate", "accepted", "accept_rate", "invitations_per_candidate",
                      "lift_vs_no_fsp", "adjusted_ratio"):
                victim[k] = None
            victim["secondary_suppressed"] = True


def salaries(d: Data) -> dict:
    by_cat: dict[str, list[Invitation]] = defaultdict(list)
    by_dir: dict[str, list[Invitation]] = defaultdict(list)
    for i in d.invs:
        c = d.cands.get(i.candidate_user_id)
        if c:
            by_cat[c.category].append(i)
            by_dir[c.direction].append(i)
    rows = []
    for cid, cat in d.categories.items():
        invs = by_cat.get(cid, [])
        cell = _salary_cell(invs)
        acc = _salary_cell([i for i in invs if i.status == InvitationStatus.accepted])
        dec = _salary_cell([i for i in invs if i.status == InvitationStatus.declined])
        row = {"category_id": cid, "title": cat.title, "direction": cat.direction_id, "grade": cat.grade_id, **cell,
               "market_from": cat.market_salary_from, "market_to": cat.market_salary_to,
               "market_median": cat.market_salary_median, "market_source": cat.market_source,
               "accepted_mid_median": acc.get("mid_median"), "declined_mid_median": dec.get("mid_median")}
        if not cell["suppressed"] and cat.market_salary_median:
            row["delta_vs_market_pct"] = round(100 * (cell["mid_median"] / cat.market_salary_median - 1), 1)
        rows.append(row)
    rows.sort(key=lambda r: (list(DIRECTIONS).index(r["direction"]) if r["direction"] in DIRECTIONS else 9,
                             GRADE_ORDER.index(r["grade"]) if r["grade"] in GRADE_ORDER else 9))
    dirs = [{"direction": dd, "title": t, **_salary_cell(by_dir.get(dd, []))} for dd, t in DIRECTIONS.items()]
    return {"categories": rows, "directions": dirs, "rules": {"min_offers": K, "min_candidates": K,
                                                              "min_companies": MIN_COMPANIES_SALARY}}


def _stages(pairs: list[tuple[str, str, int]]) -> list[dict]:
    out = []
    prev = None
    for key, title, n in pairs:
        out.append({"key": key, "title": title, "count": kc(n), "conversion": kr(n, prev) if prev is not None else None})
        prev = n
    return out


def funnel(d: Data) -> dict:
    cands = list(d.cands.values())

    def f(members: list[Cand]) -> list[dict]:
        return _stages([("candidates", "Кандидаты с категорией", len(members)),
                        ("invited", "Получили приглашение", sum(c.invited for c in members)),
                        ("seen", "Открыли приглашение", sum(c.seen for c in members)),
                        ("accepted", "Приняли приглашение", sum(c.accepted for c in members))])

    fsp = [c for c in cands if c.has_fsp]
    inv_by_id = {i.id: i for i in d.invs}
    placed = [e for e in d.entries if e.place is not None]
    cup_inv = [e for e in placed if e.invitation_id]
    cup_acc = [e for e in cup_inv if (inv_by_id.get(e.invitation_id) and
                                      inv_by_id[e.invitation_id].status == InvitationStatus.accepted)]
    cups = _stages([("joined", "Участия в кубках (записи)", len(d.entries)),
                    ("placed", "Решили и получили место", len(placed)),
                    ("invited", "Приглашены по итогам", len(cup_inv)),
                    ("accepted", "Приняли приглашение", len(cup_acc))])
    return {"all": f(cands), "fsp": f(fsp), "no_fsp": f([c for c in cands if not c.has_fsp]), "cups": cups,
            "note": "Воронка «соревнование → приглашение → принятие»: участники соревнований ФСП (T2), кандидаты без "
                    "истории ФСП и участники кубков работодателей на платформе."}


def cups_section(d: Data, db: Session) -> list[dict]:
    from app.cup.service import phase

    by_cup: dict[uuid.UUID, list[CupEntry]] = defaultdict(list)
    for e in d.entries:
        by_cup[e.cup_id].append(e)
    inv_by_id = {i.id: i for i in d.invs}
    out = []
    for cup in sorted(d.cups, key=lambda c: as_aware(c.ends_at), reverse=True):
        es = by_cup.get(cup.id, [])
        comp = db.get(Company, cup.company_id)
        placed = [e for e in es if e.place is not None]
        inv = [e for e in placed if e.invitation_id]
        acc = [e for e in inv if inv_by_id.get(e.invitation_id) and
               inv_by_id[e.invitation_id].status == InvitationStatus.accepted]
        out.append({"id": str(cup.id), "title": cup.title, "company": comp.name if comp else None,
                    "category_id": cup.category_id, "category_title": category_title(cup.category_id),
                    "mode": cup.mode, "phase": phase(cup), "starts_at": as_aware(cup.starts_at).isoformat(),
                    "ends_at": as_aware(cup.ends_at).isoformat(), "salary_from": cup.salary_from, "salary_to": cup.salary_to,
                    "invite_top_n": cup.invite_top_n, "participants": kc(len(es)), "placed": kc(len(placed)),
                    "invited": kc(len(inv)), "accepted": kc(len(acc)),
                    "passport_written": kc(sum(1 for e in placed if e.passport_status == "written")),
                    "passport_pending": kc(sum(1 for e in placed if e.passport_status == "pending_link")),
                    "score_median_pct": (round(100 * statistics.median([e.score for e in placed]))
                                         if len(placed) >= K else None)})
    return out


def report(db: Session, days: int | None = None, include_demo: bool = True) -> dict:
    d = load(db, days, include_demo=include_demo)
    return {"generated_at": utcnow().isoformat(), "k": K, "period_days": days, "overview": overview(d),
            "demand": demand(d), "fsp_effect": fsp_effect(d), "salaries": salaries(d), "funnel": funnel(d),
            "cups": cups_section(d, db), "methodology": METHODOLOGY}


METHODOLOGY = [
    f"Только агрегаты: в ответах нет ФИО, почт, телефонов, обезличенных номеров кандидатов и текстов потребностей.",
    f"Минимальный размер группы — {K}: число людей от 1 до 4 показывается как «< {K}», доля — только если "
    f"раскрываемы и числитель, и знаменатель. В разбиениях (разряды, результаты, уровни) действует вторичное "
    f"подавление: одну скрытую группу нельзя восстановить вычитанием из итога.",
    f"Зарплаты — из приглашений-офферов (вилка «от–до» обязательна по правилам платформы). Ячейка раскрывается при "
    f"{K}+ приглашениях, {K}+ кандидатах и {MIN_COMPANIES_SALARY}+ компаниях; показаны квартили и медиана середины "
    f"вилки, рядом — рыночный диапазон категории (открытые данные рынка, p25–p75).",
    "ФСП — только подтверждённые реестром достижения (T2). Кубки работодателей — мероприятия платформы (T1), "
    "в воронке они отдельной строкой. Отсутствие истории ФСП — нейтральное состояние.",
    "Связь «ФСП → приглашения» наблюдательная: рейтинг внутри категории уже учитывает ФСП (бонус 25 %). "
    "«С поправкой на категорию» = приглашённые / ожидаемые при доле приглашённых в категории каждого кандидата.",
]
