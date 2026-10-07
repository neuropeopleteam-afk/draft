"""Перевод θ в грейд с порогами и учётом неопределённости оценки.

Пороги на шкале θ — ВРЕМЕННЫЕ (до стандарт-сеттинга с экспертами на пилоте, например
модифицированным методом Ангоффа по семействам): θ ≥ cut[g] → не ниже грейда g.

Правила ТЗ: грейд по результату теста не понижается принудительно. Поэтому решение
формулируется относительно заявленного грейда:
* «подтверждён», если P(θ ≥ cut[заявленный]) ≥ confirm_level;
* иначе — «не подтверждён», предлагается пройти тест на ближайший грейд, который
  подтверждается с той же уверенностью (если такой есть);
* «можно повысить», если P(θ ≥ cut[следующий]) ≥ upgrade_level.

«Предварительный Junior» (нижний порог, решение владельца 06.10). Тест на Junior не подтвердил грейд, но и не
доказал, что уровень ниже: P(θ ≥ cut[junior]) ≥ provisional_level (по умолчанию 0,10 — верхняя граница
одностороннего 90 % интервала θ̂ + 1,28·SE достаёт до порога). Сюда попадают и θ̂ ниже порога с интервалом,
пересекающим порог, и θ̂ выше порога, когда точности не хватило до confirm_level. Такой кандидат получает
категорию «Junior (предварительно)» — это не подтверждённый грейд (assigned остаётся «none»), а отдельный статус:
его можно только подтвердить (дотестированием у порога, работой — зондом или кубком). Правило касается только
теста на нижний грейд: кандидату, заявившему Middle или Senior, Junior не присваивается даже предварительно —
грейд не понижается принудительно, тест на грейд ниже — выбор кандидата.
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
    provisional: bool = False           # «Junior (предварительно)»: не подтверждён, но и не доказанно ниже
    provisional_reason: str | None = None  # uncertain — θ̂ ниже порога, интервал его пересекает; precision — θ̂
    #                                        у порога или выше, но уверенности не хватило до confirm_level
    p_claimed: float | None = None      # P(θ ≥ порога заявленного грейда)


PROVISIONAL_LEVEL = 0.10  # P(θ ≥ cut[junior]) ≥ 0,10 ⇔ θ̂ + 1,28·SE ≥ cut[junior]: «не доказанно ниже»


def provisional_status(theta: float, se: float, claimed: str, confirmed: bool, scale: GradeScale | None = None,
                       provisional_level: float = PROVISIONAL_LEVEL) -> tuple[bool, str | None]:
    """(предварительный?, причина) — только для теста на нижний грейд и только если он не подтверждён."""
    scale = scale or GradeScale()
    if confirmed or claimed != GRADE_ORDER[1]:
        return False, None
    if scale.p_at_least(theta, se, claimed) < provisional_level:
        return False, None
    return True, ("precision" if theta >= scale.cuts[claimed] else "uncertain")


def decide(theta: float, se: float, claimed: str, scale: GradeScale | None = None,
           confirm_level: float = 0.8, upgrade_level: float = 0.9,
           provisional_level: float | None = PROVISIONAL_LEVEL) -> GradeDecision:
    """provisional_level=None — без «предварительного Junior» (прежнее правило, для сравнения до/после)."""
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
    prov, prov_reason = (provisional_status(theta, se, claimed, confirmed, scale, provisional_level)
                         if provisional_level is not None else (False, None))
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
        if prov:
            expl += (f" Уровень ниже порога не доказан (P = {p_claim:.2f} ≥ {provisional_level:.2f}): "
                     "категория Junior присваивается предварительно, её можно подтвердить дотестированием у порога.")
    return GradeDecision(claimed, point, confirmed, assigned, upgrade, retake, probs, expl, prov, prov_reason,
                         round(p_claim, 4))
