"""Перевод θ в грейд с порогами и учётом неопределённости оценки.

Пороги на шкале θ — ВРЕМЕННЫЕ (до стандарт-сеттинга с экспертами на пилоте, например
модифицированным методом Ангоффа по семействам): θ ≥ cut[g] → не ниже грейда g.

Правила ТЗ: грейд по результату теста не понижается принудительно. Поэтому решение
формулируется относительно заявленного грейда:
* «подтверждён», если P(θ ≥ cut[заявленный]) ≥ confirm_level;
* иначе — «не подтверждён», предлагается пройти тест на ближайший грейд, который
  подтверждается с той же уверенностью (если такой есть);
* «можно повысить», если P(θ ≥ cut[следующий]) ≥ upgrade_level.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import stats

GRADE_ORDER: tuple[str, ...] = ("none", "junior", "middle", "senior")


@dataclass(frozen=True)
class GradeScale:
    cuts: dict[str, float] = field(default_factory=lambda: {
        "junior": -1.0, "middle": 0.0, "senior": 1.0})

    def point(self, theta: float) -> str:
        g = "none"
        for grade in GRADE_ORDER[1:]:
            if theta >= self.cuts[grade]:
                g = grade
        return g

    def points(self, theta: np.ndarray) -> np.ndarray:
        cuts = np.array([self.cuts[g] for g in GRADE_ORDER[1:]])
        return np.searchsorted(cuts, np.asarray(theta), side="right")  # 0..3

    def p_at_least(self, theta: float, se: float, grade: str) -> float:
        if grade == "none":
            return 1.0
        return float(1 - stats.norm.cdf((self.cuts[grade] - theta) / max(se, 1e-6)))

    def probabilities(self, theta: float, se: float) -> dict[str, float]:
        at_least = [self.p_at_least(theta, se, g) for g in GRADE_ORDER] + [0.0]
        return {g: round(at_least[i] - at_least[i + 1], 4) for i, g in enumerate(GRADE_ORDER)}


@dataclass
class GradeDecision:
    claimed: str
    point_grade: str
    confirmed: bool
    assigned: str
    upgrade_available: bool
    retake_lower: str | None
    probabilities: dict[str, float]
    explanation: str


def decide(theta: float, se: float, claimed: str, scale: GradeScale | None = None,
           confirm_level: float = 0.8, upgrade_level: float = 0.9) -> GradeDecision:
    scale = scale or GradeScale()
    if claimed not in GRADE_ORDER[1:]:
        raise ValueError("claimed: junior | middle | senior")
    probs = scale.probabilities(theta, se)
    point = scale.point(theta)
    p_claim = scale.p_at_least(theta, se, claimed)
    confirmed = p_claim >= confirm_level
    idx = GRADE_ORDER.index(claimed)
    upgrade = False
    if confirmed and idx + 1 < len(GRADE_ORDER):
        upgrade = scale.p_at_least(theta, se, GRADE_ORDER[idx + 1]) >= upgrade_level
    retake = None
    if not confirmed:
        for g in reversed(GRADE_ORDER[1:idx]):
            if scale.p_at_least(theta, se, g) >= confirm_level:
                retake = g
                break
    assigned = claimed if confirmed else "none"
    if confirmed:
        expl = (f"Заявленный грейд {claimed} подтверждён: P(θ ≥ порога) = {p_claim:.2f}"
                f" при θ = {theta:.2f} ± {se:.2f}.")
        if upgrade:
            expl += f" Результат уверенно выше: можно пройти тест на {GRADE_ORDER[idx + 1]}."
    else:
        expl = (f"Заявленный грейд {claimed} не подтверждён: P(θ ≥ порога) = {p_claim:.2f}. "
                "Грейд не понижается принудительно; "
                + (f"можно пройти тест на {retake}." if retake else
                   "можно пройти тест на грейд ниже после подготовки."))
    return GradeDecision(claimed, point, confirmed, assigned, upgrade, retake, probs, expl)
