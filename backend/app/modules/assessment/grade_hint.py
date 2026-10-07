"""Подсказка грейда на экране выбора грейда — по опросу, резюме и паспорту ФСП (видео организаторов №36).

Только правила, без LLM: стаж из опроса и резюме (разбор резюме — rules/LLM+rules, но здесь берутся уже
извлечённые поля), ключевые слова грейда и роли в резюме, достижения ФСП из реестра. Подсказка необязательна и
объяснима: каждый сигнал показан отдельно с источником; выбор остаётся за кандидатом (обязателен самостоятельный
выбор грейда), а категорию присваивает только тест. Достижения ФСП на грейд не влияют (видео №8) — здесь они лишь
мягкий сигнал «не ниже Middle» при призовом месте на межрегиональном уровне и выше.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import FspEventLevel
from app.modules.assessment.rules import GRADE_LEVEL, GRADE_RU
from app.modules.assessment.service import latest_survey
from app.modules.fsp.models import FspAchievement, FspPassport
from app.modules.profiles.models import CandidateProfile, CandidateResume

_LEVEL_RANK = {FspEventLevel.regional: 1, FspEventLevel.interregional: 2, FspEventLevel.national: 3,
               FspEventLevel.international: 4}
_LEVEL_RU = {FspEventLevel.regional: "региональный", FspEventLevel.interregional: "межрегиональный",
             FspEventLevel.national: "всероссийский", FspEventLevel.international: "международный"}


def grade_by_years(years: float | None) -> str | None:
    if years is None:
        return None
    return "junior" if years < 1.5 else "middle" if years < 4.5 else "senior"


def _years_ru(v: float) -> str:
    n = int(v)
    if abs(v - n) >= 0.25:
        return f"{str(round(v, 1)).replace('.', ',')} года" if v < 5 else f"{str(round(v, 1)).replace('.', ',')} лет"
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} год"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} года"
    return f"{n} лет"


def build_hint(*, survey_years: float | None, resume: dict | None, achievements: list[dict]) -> dict:
    """Чистая функция (покрыта тестами). resume — поля CandidateResume.extracted; achievements —
    [{level: FspEventLevel|str, place: int|None, result_title: str|None, verified: bool}]."""
    votes: dict[str, float] = {g: 0.0 for g in GRADE_LEVEL}
    signals: list[dict] = []

    g_s = grade_by_years(survey_years)
    if g_s:
        votes[g_s] += 2.0
        signals.append({"source": "survey", "title": "Опрос", "grade": g_s,
                        "text": f"Коммерческий стаж {_years_ru(float(survey_years))}: по шкале платформы это {GRADE_RU[g_s]} "
                                "(до 1,5 лет — Junior, 1,5–4,5 — Middle, от 4,5 — Senior)."})
    else:
        signals.append({"source": "survey", "title": "Опрос", "grade": None, "text": "Стаж в опросе не указан."})

    if resume:
        ry = resume.get("experience_years")
        g_r = grade_by_years(float(ry)) if isinstance(ry, (int, float)) else None
        if g_r:
            votes[g_r] += 2.0
            txt = f"Стаж по резюме {_years_ru(float(ry))}: {GRADE_RU[g_r]}."
            if g_s and g_r != g_s:
                txt += f" Расходится с опросом ({GRADE_RU[g_s]}) — уточните стаж."
            signals.append({"source": "resume", "title": "Резюме: стаж", "grade": g_r, "text": txt})
        kw = resume.get("grade_hint")
        if kw in GRADE_LEVEL and not g_r:
            votes[kw] += 1.0
            signals.append({"source": "resume", "title": "Резюме: формулировки", "grade": kw,
                            "text": f"В резюме встречаются слова уровня {GRADE_RU[kw]} (стаж из текста не извлёкся)."})
        roles = {r.get("id") for r in (resume.get("roles") or [])}
        if "team_lead" in roles:
            votes["senior"] += 1.0
            signals.append({"source": "resume", "title": "Резюме: роль", "grade": "senior",
                            "text": "Указан опыт руководства командой — обычно уровень Senior."})
        n_stack = len(resume.get("stack") or [])
        if n_stack:
            signals.append({"source": "resume", "title": "Резюме: стек", "grade": None,
                            "text": f"Технологий из словаря платформы в резюме: {n_stack}. На грейд не влияет — попадёт в тест как стек."})
    else:
        signals.append({"source": "resume", "title": "Резюме", "grade": None,
                        "text": "Резюме не загружено — подсказка только по опросу" + (" и паспорту ФСП." if achievements else ".")})

    verified = [a for a in achievements if a.get("verified")]
    if verified:
        def rank(a):
            lv = a.get("level")
            lv = FspEventLevel(lv) if isinstance(lv, str) else lv
            return _LEVEL_RANK.get(lv, 0)
        best = max(verified, key=lambda a: (rank(a), -(a.get("place") or 99)))
        lv = best.get("level")
        lv = FspEventLevel(lv) if isinstance(lv, str) else lv
        prize = (best.get("place") or 99) <= 3 and rank(best) >= 2
        if prize and (g_s == "junior" or g_s is None):
            votes["middle"] += 1.0
            signals.append({"source": "fsp", "title": "Паспорт ФСП", "grade": "middle",
                            "text": f"Призовое место ({best.get('place')}-е) на {_LEVEL_RU.get(lv, 'соревновании')} уровне, "
                                    f"подтверждённых достижений: {len(verified)}. Сильная база — можно пробовать Middle; "
                                    "на сам грейд достижения не влияют, только на рейтинг."})
        else:
            signals.append({"source": "fsp", "title": "Паспорт ФСП", "grade": None,
                            "text": f"Подтверждённых достижений: {len(verified)} (лучшее — {best.get('result_title') or 'участие'}"
                                    f"{', ' + _LEVEL_RU[lv] + ' уровень' if lv in _LEVEL_RU else ''}). На грейд не влияют — "
                                    "учитываются в рейтинге внутри категории."})
    else:
        signals.append({"source": "fsp", "title": "Паспорт ФСП", "grade": None,
                        "text": "Подтверждённых достижений ФСП нет — нейтрально."})

    total = sum(votes.values())
    if total == 0:
        return {"suggested": None, "confidence": "none", "signals": signals,
                "summary": "Данных для подсказки пока нет: укажите стаж в опросе или загрузите резюме. Выбор грейда — за вами.",
                "note": "Подсказка необязательна. Категорию присваивает только тест."}
    suggested = max(votes, key=lambda g: (votes[g], GRADE_LEVEL[g]))
    share = votes[suggested] / total
    graded = [s for s in signals if s["grade"]]
    confidence = "high" if share >= 0.75 and len(graded) >= 2 else "medium" if share >= 0.5 else "low"
    agree = sum(1 for s in graded if s["grade"] == suggested)
    summary = f"Похоже на {GRADE_RU[suggested]}: за него {agree} из {len(graded)} сигналов."
    if confidence != "high":
        others = sorted({s["grade"] for s in graded if s["grade"] != suggested}, key=lambda g: GRADE_LEVEL[g])
        if others:
            summary += f" Есть доводы и за {', '.join(GRADE_RU[g] for g in others)}."
    summary += " Выбор за вами: тест на грейд ниже можно пройти сразу, на тот же — через 30 дней."
    return {"suggested": suggested, "confidence": confidence, "signals": signals, "summary": summary,
            "votes": votes, "note": "Подсказка необязательна. Категорию присваивает только тест."}


def grade_hint(db: Session, user_id: uuid.UUID) -> dict:
    profile = db.get(CandidateProfile, user_id)
    survey = latest_survey(db, user_id)
    years = None
    if survey is not None and survey.experience_years is not None:
        years = float(survey.experience_years)
    elif profile is not None and profile.experience_years is not None:
        years = float(profile.experience_years)
    resume = db.scalar(select(CandidateResume).where(CandidateResume.user_id == user_id)
                       .order_by(CandidateResume.created_at.desc()).limit(1))
    ach: list[dict] = []
    passport = db.scalar(select(FspPassport).where(FspPassport.user_id == user_id))
    if passport is not None:
        for a in db.scalars(select(FspAchievement).where(FspAchievement.passport_id == passport.id)).all():
            ach.append({"level": a.event_level, "place": a.place, "result_title": a.result_title, "verified": a.verified})
    out = build_hint(survey_years=years, resume=(resume.extracted if resume is not None else None), achievements=ach)
    out["has_resume"] = resume is not None
    out["method"] = "rules"
    return out
