"""Факты о кандидате с уровнем доказанности и сборка обезличенной карточки.

T0 — самоописание (опрос, резюме): показывается как «заявлено», используется только в фильтрах.
T1 — подтверждено на платформе (тест, зонд): основа категории и ранжирования.
T2 — подтверждено реестром (паспорт ФСП по дисциплинам ЕВСК): бонус в ранжировании; отсутствие истории
     ФСП — нейтральное состояние (бонуса нет, штрафа нет).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
import math
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import as_aware
from app.core.enums import EvidenceLevel, FactSource
from app.core.fmt import theta_se
from app.modules.catalog.constants import FSP_DISCIPLINES
from app.modules.catalog.dictionary import ROLE_TITLES, SOFT_SKILL_TITLES
from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import DIRECTIONS, GRADE_CUTS, GRADES, STACK, category_title
from app.modules.fsp.models import FspAchievement, FspPassport
from app.modules.profiles.models import CandidateFact, CandidateProfile, CandidateSpecialization
from app.modules.profiles.specializations import legacy_specialization, summary, sync_primary
from app.modules.fsp.rating import details as fsp_rating

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
# «Junior (предварительно)» ниже подтверждённого при прочих равных: −0,05 к рейтингу в категории и к скору подбора
# (вес одного зонда; задан до бенчмарка и на нём не подбирался — см. app.modules.assessment.provisional)
PROVISIONAL_PENALTY = 0.05
# Единая модель статуса грейда (видео организаторов №6, решение Р10): подтверждён / предварительно / не подтверждён.
# «Не подтверждён» — опрос пройден, теста нет или он не подтвердил заявленный грейд: кандидат виден работодателю
# со статусом «грейд не подтверждён (заявлен …)», в подборке и поиске — всегда ниже подтверждённых и предварительных.
GRADE_STATUS_TITLES = {"confirmed": "подтверждён", "provisional": "предварительно", "unconfirmed": "не подтверждён"}
GRADE_STATUS_ORDER = {"confirmed": 0, "provisional": 0, "unconfirmed": 1}  # ярус в выдаче: предварительный — штрафом


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
    """Направление сохранено в сигнатуре для совместимости, но не влияет на вес ФСП."""
    return fsp_rating(achievements)["strength"]


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
    specializations: dict[str, CandidateSpecialization] = field(default_factory=dict)
    tests_by_direction: dict[str, CandidateFact] = field(default_factory=dict)
    skills_by_direction: dict[str, dict[str, CandidateFact]] = field(default_factory=dict)
    probes_by_direction: dict[str, list[CandidateFact]] = field(default_factory=dict)
    selected_direction: str | None = None
    # последний опрос (заявленные направление и грейд) и последняя завершённая попытка теста — для статуса
    # «не подтверждён (заявлен …)»; у кандидата с категорией не используются
    survey: object | None = None
    last_attempt: object | None = None

    @property
    def specialization(self):
        return self.specializations.get(self.direction)

    @property
    def direction(self):
        return self.selected_direction or self.profile.current_direction_id

    @property
    def grade(self):
        r = self.specialization
        return r.grade_id if r else self.profile.current_grade_id if self.direction == self.profile.current_direction_id else None

    @property
    def category_id(self):
        r = self.specialization
        return r.category_id if r else self.profile.current_category_id if self.direction == self.profile.current_direction_id else None

    @property
    def rating(self):
        r = self.specialization
        return r.rating_score if r else self.profile.rating_score if self.direction == self.profile.current_direction_id else None

    def for_direction(self, direction: str | None):
        if not direction:
            return self
        return replace(self, selected_direction=direction, test=self.tests_by_direction.get(direction),
                       skills_t1=self.skills_by_direction.get(direction, {}),
                       probes_t1=self.probes_by_direction.get(direction, []))

    @property
    def privacy(self) -> dict:
        return {**DEFAULT_PRIVACY, **(self.profile.privacy or {})}

    @property
    def stack_t0(self) -> set[str]:
        return {f.key for f in self.t0.get("stack", [])}

    @property
    def fsp(self) -> float:
        return fsp_strength(self.achievements, self.direction)

    @property
    def provisional(self) -> bool:
        """Категория выбранного направления «предварительно» (тест на Junior не подтвердил грейд, но и не доказал
        уровень ниже): статус специализации; для старых профилей без строки специализации — зеркало профиля."""
        r = self.specialization
        if r is not None:
            return r.status == "provisional" and bool(r.category_id)
        return bool(getattr(self.profile, "grade_provisional", False) and self.category_id)

    @property
    def unconfirmed(self) -> bool:
        """Грейд не подтверждён: категории выбранного направления нет (опрос пройден, теста нет или он не подтвердил
        грейд)."""
        return not self.category_id

    @property
    def grade_status(self) -> str:
        return "unconfirmed" if self.unconfirmed else "provisional" if self.provisional else "confirmed"

    @property
    def claimed(self) -> tuple[str | None, str | None]:
        """Заявленные (опрос) направление и грейд — для кандидата без категории."""
        sv = self.survey
        if sv is None:
            return None, None
        return getattr(sv, "direction_id", None), getattr(sv, "claimed_grade_id", None)

    def strength(self) -> float:
        """Рейтинг внутри категории (только T1/T2): тест 0,65 + зонды 0,10 + ФСП 0,25 (бонус);
        «предварительно» — −0,05 (ниже подтверждённого при прочих равных)."""
        t = self.test.value if self.test else {}
        test = test_component(t.get("theta"), t.get("se"), self.grade)
        probe = max((f.value.get("score", 0) for f in self.probes_t1), default=0.0)
        pen = PROVISIONAL_PENALTY if self.provisional else 0.0
        return round(max(0.0, 0.65 * test + 0.10 * probe + 0.25 * self.fsp - pen), 4)


def load_bundles(db: Session, user_ids: list[uuid.UUID], *, direction: str | None = None,
                 category_ids: list[str] | None = None) -> dict[uuid.UUID, Bundle]:
    if not user_ids:
        return {}
    profiles = db.scalars(select(CandidateProfile).where(CandidateProfile.user_id.in_(user_ids))).all()
    out = {p.user_id: Bundle(profile=p) for p in profiles}
    for r in db.scalars(select(CandidateSpecialization).where(CandidateSpecialization.user_id.in_(user_ids))):
        out[r.user_id].specializations[r.direction_id] = r
    for b in out.values():
        if b.profile.current_direction_id not in b.specializations:
            r = legacy_specialization(b.profile)
            if r:
                b.specializations[r.direction_id] = r
    # Старые факты не имеют value.direction: направление восстанавливается по сессии, не по последнему тесту.
    from app.modules.assessment.models import TestSession
    session_directions = {f"test_session:{t.id}": t.direction_id for t in db.scalars(
        select(TestSession).where(TestSession.user_id.in_(user_ids)))}
    from app.modules.invitations.models import Probe
    from app.modules.matching.models import EmployerNeed
    from app.cup.models import Cup, CupEntry

    probe_directions = {f"probe:{pid}": d for pid, d in db.execute(
        select(Probe.id, EmployerNeed.direction_id).outerjoin(EmployerNeed, EmployerNeed.id == Probe.need_id)
        .where(Probe.candidate_user_id.in_(user_ids))) if d}
    probe_directions.update({f"cup:{cid}": category.split(".")[0] for cid, category in db.execute(
        select(Cup.id, Cup.category_id).join(CupEntry, CupEntry.cup_id == Cup.id)
        .where(CupEntry.candidate_user_id.in_(user_ids)).distinct())})
    from app.modules.assignments.models import Assignment, AssignmentAttempt
    probe_directions.update({f"assignment:{aid}": d for aid, d in db.execute(
        select(AssignmentAttempt.id, Assignment.direction_id).join(Assignment, Assignment.id == AssignmentAttempt.assignment_id)
        .where(AssignmentAttempt.candidate_user_id.in_(user_ids))) if d})
    for f in db.scalars(select(CandidateFact).where(CandidateFact.user_id.in_(user_ids))
                        .order_by(CandidateFact.created_at)).all():
        b = out.get(f.user_id)
        if b is None:
            continue
        if f.evidence_level == EvidenceLevel.T0:
            b.t0[f.kind].append(f)
        elif f.kind == "test_result":
            d = f.value.get("direction") or session_directions.get(f.source_ref) or f.key.split(".")[0]
            b.tests_by_direction[d] = f
        elif f.kind == "skill":
            d = (f.value.get("direction") or session_directions.get(f.source_ref)
                 or probe_directions.get(f.source_ref) or b.profile.current_direction_id)
            sk = b.skills_by_direction.setdefault(d, {})
            sk[f.key] = merge_skill(sk.get(f.key), f)  # тест + задания работодателя (И7) — одно слитое значение
        elif f.kind == "probe":
            d = f.value.get("direction") or probe_directions.get(f.source_ref) or b.profile.current_direction_id
            b.probes_by_direction.setdefault(d, []).append(f)
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
    for uid, b in list(out.items()):
        primary = next((r.direction_id for r in b.specializations.values() if r.is_primary), b.profile.current_direction_id)
        proven = [r for r in b.specializations.values() if r.category_id]
        default = primary
        if proven and not (b.specializations.get(primary) and b.specializations[primary].category_id):
            default = sorted(proven, key=lambda r: (not r.is_primary, r.direction_id))[0].direction_id
        selected = direction or default
        if category_ids:
            eligible = [r for r in b.specializations.values() if r.category_id in category_ids
                        and (not direction or r.direction_id == direction)]
            if eligible:
                selected = sorted(eligible, key=lambda r: (not r.is_primary, -(r.rating_score or 0), r.direction_id))[0].direction_id
        out[uid] = b.for_direction(selected)
    _load_claims(db, out)
    return out


def _load_claims(db: Session, out: dict) -> None:
    """Последний опрос и последняя завершённая попытка теста — только кандидатам без категории (статус
    «не подтверждён (заявлен …)»); остальным они не нужны."""
    from app.core.enums import TestSessionStatus
    from app.modules.assessment.models import SurveyResponse, TestSession

    ids = [uid for uid, b in out.items() if not b.category_id]
    if not ids:
        return
    for sv in db.scalars(select(SurveyResponse).where(SurveyResponse.user_id.in_(ids))
                         .order_by(SurveyResponse.created_at.desc())).all():
        if out[sv.user_id].survey is None:
            out[sv.user_id].survey = sv
    for ts in db.scalars(select(TestSession).where(TestSession.user_id.in_(ids),
                                                   TestSession.status == TestSessionStatus.finished)
                         .order_by(TestSession.created_at.desc())).all():
        if out[ts.user_id].last_attempt is None:
            out[ts.user_id].last_attempt = ts


def grade_status(b: "Bundle") -> dict:
    """Единая модель статуса грейда для карточки, подборки, поиска, сравнения, PDF и объяснения «почему».

    confirmed — категория присвоена тестом; provisional — «Junior (предварительно)» (вероятность уровня не ниже
    Junior в карточке); unconfirmed — категории нет: заявленный грейд из опроса и исход последней попытки теста.
    """
    from app.modules.assessment import provisional as prov

    st = b.grade_status
    p = b.profile
    out = {"status": st, "title": GRADE_STATUS_TITLES[st], "tier": GRADE_STATUS_ORDER[st],
           "grade": b.grade, "grade_title": GRADES.get(b.grade or "") or None,
           "direction": b.direction, "claimed_grade": None, "claimed_direction": None,
           "claimed_category_id": None, "claimed_title": None, "attempt": None, "p_pct": None, "text": ""}
    t = b.test.value if b.test else None
    if st == "confirmed":
        by = prov.confirmed_by(t)
        out["text"] = "Грейд подтверждён тестом" + (f" ({by['title']})" if by and by.get("by") in ("probe", "cup") else "")
        return out
    if st == "provisional":
        inf = prov.info(t) or {}
        out["p_pct"] = inf.get("p_pct")
        out["text"] = inf.get("text") or "Junior предварительно"
        return out
    d, g = b.claimed
    la = b.last_attempt
    out.update({"claimed_grade": g, "claimed_direction": d,
                "claimed_category_id": f"{d}.{g}" if d and g else None,
                "claimed_title": category_title(f"{d}.{g}") if d and g else None})
    if la is not None:
        out["attempt"] = {"grade": la.claimed_grade_id, "grade_title": GRADES.get(la.claimed_grade_id, la.claimed_grade_id),
                          "direction": la.direction_id, "theta": la.theta,
                          "se": la.theta_se, "at": la.finished_at.date().isoformat() if la.finished_at else None}
        how = (f"тест на {GRADES.get(la.claimed_grade_id, la.claimed_grade_id)} не подтвердил грейд"
               + (f" (θ = {theta_se(la.theta, la.theta_se)})" if la.theta is not None and la.theta_se is not None else ""))
    else:
        how = "тест не пройден"
    out["text"] = (f"Грейд не подтверждён (заявлен {GRADES.get(g, g) if g else '—'}): {how}. "
                   "В подборке и поиске — ниже всех подтверждённых")
    return out


def refresh_rating(db: Session, user_id: uuid.UUID) -> float | None:
    b = load_bundles(db, [user_id]).get(user_id)
    if b is None:
        return None
    for r in b.specializations.values():
        r.rating_score = b.for_direction(r.direction_id).strength() if r.category_id else None
        sync_primary(b.profile, r)
    if not b.specializations:
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



def freshness_summary(skills: dict) -> dict | None:
    from app.modules.profiles.freshness import summary

    ok = {k: f for k, f in skills.items() if skill_confirmed(f)}  # как и «подтверждённые навыки» карточки: слабые не показываем
    return summary(ok, limit=8) if ok else None


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
    from app.modules.assessment import provisional as prov

    p, pv = b.profile, b.privacy
    cat = categories.get(b.category_id or "")
    t = b.test.value if b.test else None
    show = (lambda k: include_hidden or pv.get(k, True))
    from app.modules.fsp.youth import employment_safety

    is_prov = b.provisional and cat is not None
    status = grade_status(b)
    cd, cg = b.claimed
    return {
        "ref": p.public_ref,
        "category": {"id": cat.id, "title": prov.title(cat.title, is_prov), "provisional": is_prov} if cat else None,
        # единая модель статуса: подтверждён / предварительно / не подтверждён (+ заявленное из опроса)
        "status": status,
        "claimed": ({"direction": cd, "grade": cg, "category_id": f"{cd}.{cg}",
                     "title": category_title(f"{cd}.{cg}")} if cat is None and cd and cg else None),
        "direction": b.direction,
        "direction_title": DIRECTIONS.get(b.direction or "", None),
        "grade": b.grade,
        "grade_title": prov.title(GRADES.get(b.grade or "", None), is_prov),
        # «Junior (предварительно)»: уровень доказанности (вероятность уровня не ниже Junior), причина, попытки
        "provisional": (prov.info(t) or {"text": "Junior предварительно"}) if is_prov else None,
        "confirmed_by": prov.confirmed_by(t),
        "rating_score": b.rating,
        "specializations": [summary(r, b.tests_by_direction.get(r.direction_id))
                            for r in sorted(b.specializations.values(), key=lambda r: (not r.is_primary, r.direction_id))],
        "rank_in_category": rank,
        "category_size": rank_total,
        "test": {
            "level": "T1", "theta": t.get("theta"), "se": t.get("se"), "correct": t.get("correct"),
            "answered": t.get("answered"), "engine": t.get("engine"), "date": b.test.created_at.date().isoformat(),
            "integrity": integrity_summary(t.get("integrity")),
            # экспресс-тест жюри (5–7 заданий, интервал шире) и принятый уровень ниже — видны работодателю честно
            "mode": t.get("mode", "full"), "accepted_lower": bool(t.get("accepted_lower")), "grade": t.get("grade"),
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
            "rating": fsp_rating(b.achievements),
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
        "employment_safety": employment_safety(p),
        "freshness": freshness_summary(b.skills_t1),  # К5: когда подтверждены навыки T1 (порядок подбора не меняет)
    }
