"""Шкала грейдов платформы поверх психометрики банка: любое число грейдов, банк не меняется.

Банк (``assessment_bank.psychometrics.grading``) знает три грейда (junior, middle, senior) и порождает решение
``decide`` относительно заявленного грейда. Платформа добавляет грейд «Стажёр» (intern) ниже Junior
(``app.modules.catalog.seed_data.GRADE_ORDER`` и ``GRADE_CUTS``) и считает решение так:

* для грейдов, известных банку, — ``assessment_bank.psychometrics.decide`` с порогами платформы (``GradeScale(cuts)``),
  затем вероятности и точечный грейд пересчитываются по полной шкале, а «можно пройти тест на грейд ниже»
  дополняется грейдами платформы (Junior не подтверждён, Стажёр подтверждён с той же уверенностью → intern);
* для грейдов платформы (intern) — то же правило, что у остальных: «подтверждён», если P(θ ≥ cut[intern]) ≥ 0,8;
  «можно повысить», если P(θ ≥ cut[junior]) ≥ 0,9; принудительного понижения нет (ниже Стажёра грейда нет).

Результат везде — ``GradeDecision`` банка, поэтому остальной код (движок, сервис, карточки) един для всех грейдов.
"""
from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
import math

from assessment_bank.psychometrics import GradeDecision, GradeScale, decide as bank_decide
from assessment_bank.psychometrics.grading import GRADE_ORDER as BANK_GRADES

from app.modules.catalog.seed_data import GRADE_CUTS, GRADE_ORDER, GRADES, GRADE_START_THETA

CONFIRM_LEVEL = 0.8
UPGRADE_LEVEL = 0.9
GRADE_RU = {"none": "без грейда", **GRADES}


@lru_cache(maxsize=1)
def scale() -> GradeScale:
    """Шкала с порогами платформы: ключи — все грейды платформы (банк берёт только свои)."""
    return GradeScale(cuts=dict(GRADE_CUTS))


def cuts_tuple() -> tuple[float, ...]:
    return tuple(GRADE_CUTS[g] for g in GRADE_ORDER)


def start_theta() -> dict[str, float]:
    return dict(GRADE_START_THETA)


def _norm_sf(z: float) -> float:
    return 1 - 0.5 * (1 + math.erf(z / math.sqrt(2)))


def p_at_least(theta: float, se: float, grade: str) -> float:
    """P(θ ≥ порога грейда) при θ̂ ~ N(theta, se²)."""
    if grade == "none":
        return 1.0
    return float(_norm_sf((GRADE_CUTS[grade] - theta) / max(se, 1e-6)))


def point_grade(theta: float) -> str:
    g = "none"
    for grade in GRADE_ORDER:
        if theta >= GRADE_CUTS[grade]:
            g = grade
    return g


def probabilities(theta: float, se: float) -> dict[str, float]:
    order = ("none",) + GRADE_ORDER
    at_least = [p_at_least(theta, se, g) for g in order] + [0.0]
    return {g: round(at_least[i] - at_least[i + 1], 4) for i, g in enumerate(order)}


def decide_grade(theta: float, se: float, claimed: str, confirm_level: float = CONFIRM_LEVEL,
                 upgrade_level: float = UPGRADE_LEVEL) -> GradeDecision:
    """Решение по заявленному грейду на полной шкале платформы (см. описание модуля)."""
    if claimed not in GRADE_ORDER:
        raise ValueError(f"claimed: {' | '.join(GRADE_ORDER)}")
    idx = GRADE_ORDER.index(claimed)
    probs = probabilities(theta, se)
    point = point_grade(theta)
    if claimed in BANK_GRADES:
        dec = bank_decide(theta, se, claimed, scale(), confirm_level=confirm_level, upgrade_level=upgrade_level)
        retake, expl = dec.retake_lower, dec.explanation
        if not dec.confirmed and retake is None:
            for g in reversed(GRADE_ORDER[:idx]):  # грейды платформы ниже заявленного (у банка их нет)
                if p_at_least(theta, se, g) >= confirm_level:
                    retake = g
                    expl = expl.replace("можно пройти тест на грейд ниже после подготовки.", f"можно пройти тест на {g}.")
                    break
        return replace(dec, point_grade=point, probabilities=probs, retake_lower=retake, explanation=expl)
    p_claim = p_at_least(theta, se, claimed)
    confirmed = p_claim >= confirm_level
    upgrade = False
    if confirmed and idx + 1 < len(GRADE_ORDER):
        upgrade = p_at_least(theta, se, GRADE_ORDER[idx + 1]) >= upgrade_level
    retake = None
    if not confirmed:
        for g in reversed(GRADE_ORDER[:idx]):
            if p_at_least(theta, se, g) >= confirm_level:
                retake = g
                break
    if confirmed:
        expl = (f"Заявленный грейд {claimed} подтверждён: P(θ ≥ порога) = {p_claim:.2f}"
                f" при θ = {theta:.2f} ± {se:.2f}.")
        if upgrade:
            expl += f" Результат уверенно выше: можно пройти тест на {GRADE_ORDER[idx + 1]}."
    else:
        expl = (f"Заявленный грейд {claimed} не подтверждён: P(θ ≥ порога) = {p_claim:.2f}. "
                "Грейд не понижается принудительно; "
                + (f"можно пройти тест на {retake}." if retake else "можно пройти тест ещё раз после подготовки."))
    return GradeDecision(claimed, point, confirmed, claimed if confirmed else "none", upgrade, retake, probs, expl)
