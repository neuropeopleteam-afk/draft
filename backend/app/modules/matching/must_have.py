"""«Сначала покрывающие обязательное» (Ф2, 08.10): ярусы подборки по числу непокрытых обязательных навыков.

Правило. Обязательный навык потребности покрыт, если он подтверждён заданиями теста (T1, доля ≥ 0,5). Кандидаты идут
ярусами по числу непокрытых обязательных: 0, 1, ≥ 2; внутри яруса — прежний балл match-v1 (веса не менялись). Бонусы
ФСП и зонда не переносят через ярус: они входят в балл, а балл сравнивается только внутри яруса.

«Нет данных» ≠ «не умеет»: навык, который в пуле подборки не покрыт ни у кого (например, тест его не проверяет),
ярус не меняет — сравнивать не с чем. Если обязательных нет или их не покрывает никто — порядок прежний.

Ярус статуса грейда (подтверждён/предварительно → не подтверждён, Р10) старше яруса обязательного: кандидат без
подтверждённого грейда всегда ниже.

Флаги (окружение): MATCH_MUST_FIRST — правило включено (по умолчанию «1»; «0» — прежний порядок match-v1);
MATCH_MUST_DECLARED — засчитывать и заявленное в опросе с самооценкой «уверенно» (3 из 3), если тест навык не
проверял (по умолчанию «0»: на экспертных оценках v1 этот вариант дал nDCG@5 0,837 против 0,860 у варианта «только
T1» и 0,846 у match-v1 — docs/must_have/metrics.json). Заявленное (T0) в балл не входит ни в каком варианте.
"""
from __future__ import annotations

import os
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.catalog.seed_data import tag_title
from app.modules.profiles.facts import Bundle, skill_confirmed

HIGH_SELF_LEVEL = 3  # самооценка опроса: 1 — знаком … 3 — уверенно
MAX_TIER = 2  # ярусы 0, 1, ≥ 2
SHOW_MISSING = 3  # «Не хватает обязательного: …» — до трёх названий


def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "off", "")


def enabled() -> bool:
    return _flag("MATCH_MUST_FIRST", "1")


def declared_counts() -> bool:
    return _flag("MATCH_MUST_DECLARED", "0")


def declared_levels(db: Session, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    """Самооценка заявленных навыков: {user_id: {тег: 1..3}} — из последнего опроса, где тег заявлен."""
    from app.modules.assessment.models import SurveyResponse, SurveyStackTag

    out: dict[uuid.UUID, dict[str, int]] = {}
    if not user_ids:
        return out
    rows = db.execute(select(SurveyResponse.user_id, SurveyStackTag.stack_tag_id, SurveyStackTag.self_level)
                      .join(SurveyStackTag, SurveyStackTag.survey_id == SurveyResponse.id)
                      .where(SurveyResponse.user_id.in_(list(user_ids)))
                      .order_by(SurveyResponse.created_at.desc())).all()
    for uid, tag, lvl in rows:  # от новых к старым: самооценку задаёт последний опрос, где тег заявлен
        out.setdefault(uid, {}).setdefault(tag, int(lvl or 1))
    return out


def coverage(b: Bundle, tag: str, levels: dict[str, int] | None = None) -> str | None:
    """Как покрыт обязательный навык: «t1» — подтверждён тестом; «t0_high» — заявлен «уверенно», тест не проверял
    (только при levels, то есть при MATCH_MUST_DECLARED); None — не покрыт (проверен ниже порога, только заявлен или
    данных нет)."""
    f = b.skills_t1.get(tag)
    if skill_confirmed(f):
        return "t1"
    from app.modules.matching import implied  # W1: подтверждённый фреймворк подтверждает базовый язык
    if f is None and implied.implied_by(b.skills_t1, tag) is not None:  # прямой результат ниже порога не перебивается
        return "t1"
    if levels and f is None and tag in b.stack_t0 and levels.get(tag, 0) >= HIGH_SELF_LEVEL:
        return "t0_high"
    return None


def must_tags(req: dict) -> list[str]:
    return [i["tag"] for i in req.get("stack_required") or [] if isinstance(i, dict) and i.get("tag")]


def available(bundles: list[Bundle], req: dict, levels: dict | None = None) -> set[str]:
    """Обязательные навыки, которые покрыты хотя бы у одного кандидата пула: только они меняют ярус."""
    tags = must_tags(req)
    levels = levels or {}
    out: set[str] = set()
    for b in bundles:
        lv = levels.get(b.profile.user_id)
        out.update(t for t in tags if t not in out and coverage(b, t, lv))
        if len(out) == len(tags):
            break
    return out


def assess(b: Bundle, req: dict, avail: set[str], levels: dict[str, int] | None = None) -> dict:
    """Ярус кандидата и тексты для шапки карточки."""
    tags = must_tags(req)
    cov = {t: coverage(b, t, levels) for t in tags}
    missing = [t for t in tags if not cov[t]]
    counted = [t for t in missing if t in avail]
    titles = [tag_title(t) for t in missing]
    return {"tier": min(len(counted), MAX_TIER), "missing": titles[:SHOW_MISSING],
            "missing_more": max(0, len(titles) - SHOW_MISSING), "missing_total": len(titles),
            "missing_counted": len(counted),
            "declared_high": [tag_title(t) for t in tags if cov[t] == "t0_high"],
            "required_total": len(tags)}


def tiers_for(bundles: list[Bundle], req: dict, levels: dict | None = None, on: bool | None = None) -> dict:
    """{user_id: assess(...)}; при выключенном правиле ярус у всех 0 (тексты «не хватает» остаются)."""
    on = enabled() if on is None else on
    levels = levels or {}
    avail = available(bundles, req, levels)
    out = {}
    for b in bundles:
        a = assess(b, req, avail, levels.get(b.profile.user_id))
        if not on:
            a["tier"] = 0
        out[b.profile.user_id] = a
    return out
