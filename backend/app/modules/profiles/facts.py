"""Факты о кандидате с уровнем доказанности и сборка обезличенной карточки.

T0 — самоописание (опрос, резюме): показывается как «заявлено», используется только в фильтрах.
T1 — подтверждено на платформе (тест, зонд): основа категории и ранжирования.
T2 — подтверждено реестром (паспорт ФСП по дисциплинам ЕВСК): бонус в ранжировании; отсутствие истории
     ФСП — нейтральное состояние (бонуса нет, штрафа нет).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import math
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import as_aware
from app.core.enums import EvidenceLevel, FactSource
from app.modules.catalog.constants import FSP_DISCIPLINES
from app.modules.catalog.dictionary import ROLE_TITLES, SOFT_SKILL_TITLES
from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import DIRECTIONS, GRADES, STACK
from app.modules.fsp.models import FspAchievement, FspPassport
from app.modules.profiles.models import CandidateFact, CandidateProfile

DEFAULT_PRIVACY = {
    "show_city": True, "show_experience": True, "show_work_format": True, "show_roles": True,
    "show_stack": True, "show_soft_skills": True, "show_fsp": True,
}
PRIVACY_TITLES = {
    "show_city": "Город", "show_experience": "Стаж", "show_work_format": "Формат работы", "show_roles": "Роли",
    "show_stack": "Заявленный стек", "show_soft_skills": "Софт-скиллы из резюме", "show_fsp": "Достижения ФСП",
}
WORK_FORMAT_TITLES = {"office": "Офис", "hybrid": "Гибрид", "remote": "Удалённо", "any": "Любой"}
DISCIPLINE_TITLES = {d["id"]: d["title"] for d in FSP_DISCIPLINES}
LEVEL_TITLES = {"school": "школьные", "regional": "региональные", "interregional": "межрегиональные",
                "national": "всероссийские", "international": "международные",
                "platform": "кубок работодателя на платформе"}
LEVEL_WEIGHT = {"international": 1.0, "national": 0.85, "interregional": 0.65, "regional": 0.45, "school": 0.25}
DISCIPLINE_RELEVANCE = {
    "algorithmic": {"backend": 0.9, "frontend": 0.6, "data_ml": 1.0, "qa": 0.6, "security": 0.6},
    "product": {"backend": 1.0, "frontend": 1.0, "data_ml": 0.8, "qa": 0.9, "security": 0.5},
    "security": {"backend": 0.5, "frontend": 0.3, "data_ml": 0.3, "qa": 0.4, "security": 1.0},
    "robotics": {"backend": 0.3, "frontend": 0.3, "data_ml": 0.5, "qa": 0.3, "security": 0.3},
    "uav": {"backend": 0.3, "frontend": 0.3, "data_ml": 0.5, "qa": 0.3, "security": 0.3},
}
GRADE_CUTS = {"junior": -1.0, "middle": 0.0, "senior": 1.0}


def set_t0_facts(db: Session, user_id: uuid.UUID, source: FactSource, *, stack: list[str] | None = None,
                 roles: list[str] | None = None, soft_skills: list[str] | None = None,
                 experience_years: float | None = None) -> None:
    """Перезаписывает факты T0 одного источника (опрос или резюме)."""
    db.execute(delete(CandidateFact).where(CandidateFact.user_id == user_id, CandidateFact.source == source,
                                           CandidateFact.evidence_level == EvidenceLevel.T0))
    for t in stack or []:
        if t in STACK:
            db.add(CandidateFact(user_id=user_id, kind="stack", key=t, title=STACK[t][0], value={},
                                 evidence_level=EvidenceLevel.T0, source=source))
    for r in roles or []:
        if r in ROLE_TITLES:
            db.add(CandidateFact(user_id=user_id, kind="role", key=r, title=ROLE_TITLES[r], value={},
                                 evidence_level=EvidenceLevel.T0, source=source))
    for s in soft_skills or []:
        if s in SOFT_SKILL_TITLES:
            db.add(CandidateFact(user_id=user_id, kind="soft_skill", key=s, title=SOFT_SKILL_TITLES[s], value={},
                                 evidence_level=EvidenceLevel.T0, source=source))
    if experience_years is not None:
        db.add(CandidateFact(user_id=user_id, kind="experience", key="years", title=f"Стаж {experience_years:g} лет",
                             value={"years": float(experience_years)}, evidence_level=EvidenceLevel.T0, source=source))


def fsp_strength(achievements: list[FspAchievement], direction: str | None) -> float:
    """Сила паспорта ФСП для направления, 0..1: лучшее достижение + 25 % остальных, только подтверждённые."""
    vals = []
    for a in achievements:
        if not a.verified:
            continue
        lvl = LEVEL_WEIGHT.get(a.event_level.value if hasattr(a.event_level, "value") else a.event_level, 0.3)
        place = a.place or 99
        res = 1.0 if place == 1 else 0.85 if place <= 3 else 0.6 if place <= 10 else 0.3
        rel = DISCIPLINE_RELEVANCE.get(a.discipline, {}).get(direction or "", 0.5)
        vals.append(lvl * res * rel)
    if not vals:
        return 0.0
    vals.sort(reverse=True)
    return round(min(1.0, vals[0] + 0.25 * sum(vals[1:])), 3)


def achievement_text(a: FspAchievement) -> str:
    lvl = a.event_level.value if hasattr(a.event_level, "value") else a.event_level
    place = a.result_title or (f"{a.place} место" if a.place else "участник")
    year = f", {a.event_date.year}" if a.event_date else ""
    return f"{place.capitalize()}: {a.event_name} ({LEVEL_TITLES.get(lvl, lvl)}, {DISCIPLINE_TITLES.get(a.discipline, a.discipline)}{year})"


def test_component(theta: float | None, se: float | None, grade: str | None) -> float:
    """Сила результата теста относительно порога грейда, 0..1 (сигмоида от запаса над порогом)."""
    if theta is None or grade not in GRADE_CUTS:
        return 0.0
    return round(1 / (1 + math.exp(-1.7 * (theta - GRADE_CUTS[grade]))), 3)


@dataclass
class Bundle:
    """Всё, что известно о кандидате, — одним объектом (загружается пачкой без N+1)."""

    profile: CandidateProfile
    test: CandidateFact | None = None
    skills_t1: dict[str, CandidateFact] = field(default_factory=dict)
    probes_t1: list[CandidateFact] = field(default_factory=list)
    t0: dict[str, list[CandidateFact]] = field(default_factory=lambda: defaultdict(list))
    passport: FspPassport | None = None
    achievements: list[FspAchievement] = field(default_factory=list)

    @property
    def privacy(self) -> dict:
        return {**DEFAULT_PRIVACY, **(self.profile.privacy or {})}

    @property
    def stack_t0(self) -> set[str]:
        return {f.key for f in self.t0.get("stack", [])}

    @property
    def fsp(self) -> float:
        return fsp_strength(self.achievements, self.profile.current_direction_id)

    def strength(self) -> float:
        """Рейтинг внутри категории (только T1/T2): тест 0,65 + зонды 0,10 + ФСП 0,25 (бонус)."""
        t = self.test.value if self.test else {}
        test = test_component(t.get("theta"), t.get("se"), self.profile.current_grade_id)
        probe = max((f.value.get("score", 0) for f in self.probes_t1), default=0.0)
        return round(0.65 * test + 0.10 * probe + 0.25 * self.fsp, 4)


def load_bundles(db: Session, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, Bundle]:
    if not user_ids:
        return {}
    profiles = db.scalars(select(CandidateProfile).where(CandidateProfile.user_id.in_(user_ids))).all()
    out = {p.user_id: Bundle(profile=p) for p in profiles}
    for f in db.scalars(select(CandidateFact).where(CandidateFact.user_id.in_(user_ids))
                        .order_by(CandidateFact.created_at)).all():
        b = out.get(f.user_id)
        if b is None:
            continue
        if f.evidence_level == EvidenceLevel.T0:
            b.t0[f.kind].append(f)
        elif f.kind == "test_result":
            b.test = f  # последний по времени
        elif f.kind == "skill":
            b.skills_t1[f.key] = merge_skill(b.skills_t1.get(f.key), f)  # тест + задания работодателя (И7)
        elif f.kind == "probe":
            b.probes_t1.append(f)
    passports = db.scalars(select(FspPassport).where(FspPassport.user_id.in_(user_ids))).all()
    by_pid = {}
    for p in passports:
        if p.user_id in out:
            out[p.user_id].passport = p
            by_pid[p.id] = out[p.user_id]
    if by_pid:
        for a in db.scalars(select(FspAchievement).where(FspAchievement.passport_id.in_(list(by_pid)))
                            .order_by(FspAchievement.event_date.desc())).all():
            by_pid[a.passport_id].achievements.append(a)
    return out


def refresh_rating(db: Session, user_id: uuid.UUID) -> float | None:
    b = load_bundles(db, [user_id]).get(user_id)
    if b is None:
        return None
    b.profile.rating_score = b.strength() if b.profile.current_category_id else None
    return b.profile.rating_score


def fmt_count(v) -> str:
    """Баллы по навыку: целое — без дробной части; частичный зачёт (шаги, рубрика) — один знак, запятая."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    return str(int(x)) if x.is_integer() else f"{x:.1f}".replace(".", ",")


def integrity_summary(integ: dict | None) -> dict | None:
    """Достоверность результата теста для работодателя (assessment/integrity.py): уровень и причины."""
    from app.modules.assessment.integrity import summary_for_employer

    return summary_for_employer(integ)


def verified_achievements(b: "Bundle") -> list:
    return [a for a in b.achievements if a.verified]


def skill_confirmed(f: CandidateFact | None) -> bool:
    return bool(f and f.value.get("score", 0) >= 0.5)


def merge_skill(prev: CandidateFact | None, f: CandidateFact) -> CandidateFact:
    """Несколько фактов T1 по одному навыку (тест платформы и задания работодателя, И7) — одно слитое значение:
    верные и всего суммируются, score — доля; по источникам — в value["parts"]. Объект не в сессии — только чтение."""
    if prev is None:
        return f
    parts: dict = dict(prev.value.get("parts") or {_origin(prev): _part(prev)})
    parts[_origin(f)] = {k: (parts.get(_origin(f), {}).get(k, 0) + v) for k, v in _part(f).items()}
    correct = sum(x["correct"] for x in parts.values())
    total = sum(x["total"] for x in parts.values())
    m = CandidateFact(user_id=f.user_id, kind="skill", key=f.key, title=f.title,
                      value={**prev.value, **f.value, "correct": correct, "total": total,
                             "score": round(correct / total, 4) if total else 0.0, "parts": parts},
                      evidence_level=EvidenceLevel.T1, source=f.source, source_ref=getattr(f, "source_ref", None),
                      weight=getattr(f, "weight", None))
    pc, fc = getattr(prev, "created_at", None), getattr(f, "created_at", None)
    m.created_at = max(as_aware(pc), as_aware(fc)) if pc and fc else fc
    return m


def _origin(f: CandidateFact) -> str:
    """Источник факта по навыку: тест или задание работодателя (И7). Терпит лёгкие объекты бенчмарка без source_ref."""
    ref = getattr(f, "source_ref", None) or ""
    return (getattr(f, "value", None) or {}).get("origin") or ("assignment" if ref.startswith("assignment:") else "test")


def _part(f: CandidateFact) -> dict:
    v = getattr(f, "value", None) or {}
    try:
        return {"correct": float(v.get("correct") or 0), "total": float(v.get("total") or 0)}
    except (TypeError, ValueError):
        return {"correct": 0.0, "total": 0.0}


def skill_evidence_text(f: CandidateFact) -> str:
    """«Подтверждено заданиями теста: 2 из 3», с заданием работодателя — «… и заданием работодателя (3 из 3)»."""
    v = getattr(f, "value", None) or {}
    parts = v.get("parts") or {_origin(f): _part(f)}
    names = {"test": "заданиями теста", "assignment": "заданием работодателя"}
    if len(parts) == 1:
        k, x = next(iter(parts.items()))
        return f"Подтверждено {names.get(k, k)}: {fmt_count(x['correct'])} из {fmt_count(x['total'])}"
    return "Подтверждено " + " и ".join(f"{names.get(k, k)} ({fmt_count(x['correct'])} из {fmt_count(x['total'])})"
                                        for k, x in parts.items())



def _uniq(facts: list) -> list:
    """Один факт на ключ: опрос и резюме могут заявить одно и то же (берём первый — из опроса)."""
    seen: set = set()
    out = []
    for f in facts:
        if f.key not in seen:
            seen.add(f.key)
            out.append(f)
    return out

def card(b: Bundle, categories: dict[str, Category], *, rank: int | None = None, rank_total: int | None = None,
         include_hidden: bool = False) -> dict:
    """Обезличенная карточка для работодателя. ФИО, контакты и минимум зарплаты сюда не попадают никогда."""
    p, pv = b.profile, b.privacy
    cat = categories.get(p.current_category_id or "")
    t = b.test.value if b.test else None
    show = (lambda k: include_hidden or pv.get(k, True))
    return {
        "ref": p.public_ref,
        "category": {"id": cat.id, "title": cat.title} if cat else None,
        "direction": p.current_direction_id,
        "direction_title": DIRECTIONS.get(p.current_direction_id or "", None),
        "grade": p.current_grade_id,
        "grade_title": GRADES.get(p.current_grade_id or "", None),
        "rating_score": p.rating_score,
        "rank_in_category": rank,
        "category_size": rank_total,
        "test": {
            "level": "T1", "theta": t.get("theta"), "se": t.get("se"), "correct": t.get("correct"),
            "answered": t.get("answered"), "engine": t.get("engine"), "date": b.test.created_at.date().isoformat(),
            "integrity": integrity_summary(t.get("integrity")),
        } if t else None,
        "skills_confirmed": [
            {"tag": k, "title": STACK.get(k, (k,))[0], "score": f.value.get("score"), "level": "T1"}
            for k, f in sorted(b.skills_t1.items()) if skill_confirmed(f)
        ],
        "probes": [{"title": f.title, "score": f.value.get("score"), "verdict": f.value.get("verdict"), "level": "T1"}
                   for f in b.probes_t1],
        "fsp": ({
            "linked": b.passport is not None, "level": "T2" if verified_achievements(b) else None,
            "source": b.passport.link_source.value if b.passport else None,
            "strength": b.fsp,
            "achievements": [{"text": achievement_text(a), "discipline": a.discipline, "verified": a.verified}
                             for a in verified_achievements(b)[:5]],
            "unverified_count": sum(1 for a in b.achievements
                                    if not a.verified and not (a.source_ref or "").startswith("cup:")),
        } if show("show_fsp") else {"linked": None, "hidden": True}),
        "stack_declared": [{"tag": f.key, "title": f.title, "level": "T0", "source": f.source.value}
                           for f in _uniq(b.t0.get("stack", []))] if show("show_stack") else None,
        "roles": [f.title for f in _uniq(b.t0.get("role", []))] if show("show_roles") else None,
        "soft_skills": [f.title for f in _uniq(b.t0.get("soft_skill", []))] if show("show_soft_skills") else None,
        "experience_years": float(p.experience_years) if (p.experience_years is not None and show("show_experience")) else None,
        "work_format": p.work_format.value if show("show_work_format") else None,
        "city": p.city if show("show_city") else None,
        "relocation": p.relocation if show("show_city") else None,
        "market_range": {"from": cat.market_salary_from, "to": cat.market_salary_to,
                         "median": cat.market_salary_median} if cat else None,
        "is_demo": None,
    }
