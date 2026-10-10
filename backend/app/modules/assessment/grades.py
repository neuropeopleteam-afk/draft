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

Отображение θ → категория (Ф3, 08.10) — одно для всех режимов: ``category_level``. Категория — наивысший грейд,
уровень которого доказан с той же уверенностью, что и подтверждение (P(θ ≥ порога) ≥ 0,8), но не выше потолка
по длине теста и погрешности (``ceiling``): меньше ``TOP_MIN_ITEMS`` оценённых заданий или погрешность больше
``TOP_MAX_SE`` — не выше Middle, такая категория — «предварительно». Полный тест и экспресс подтверждают
заявленный грейд, если категория не ниже него (``decide_grade`` — то же правило P ≥ 0,8 плюс тот же потолок),
мини-тест QR (3 задания) берёт категорию напрямую. Поэтому 3 из 3 при θ = +1,01 ± 0,77 и экспресс 7 из 7 при
θ = +1,40 ± 0,72 дают одно и то же — Middle (у мини-теста — предварительно), а не Senior и Middle.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
import math

from assessment_bank.psychometrics import GradeDecision, GradeScale, decide as bank_decide
from assessment_bank.psychometrics.grading import GRADE_ORDER as BANK_GRADES

from app.core.fmt import ru_num, theta_se
from app.modules.catalog.seed_data import GRADE_CUTS, GRADE_ORDER, GRADES, GRADE_START_THETA

CONFIRM_LEVEL = 0.8
UPGRADE_LEVEL = 0.9
GRADE_RU = {"none": "без грейда", **GRADES}
# Потолок категории по длине теста и погрешности: крайний грейд (Senior) — только при ≥ 5 оценённых заданиях
# (экспресс — 5–12, полный — 8–16) и погрешности не больше 0,75; короче или шире — не выше Middle, «предварительно».
TOP_MIN_ITEMS = 5
TOP_MAX_SE = 0.75
SHORT_CEILING = "middle"
PRELIMINARY_MAX_ITEMS = TOP_MIN_ITEMS - 1  # мини-тест QR (3 задания): категория всегда предварительная


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


def _rank(grade: str) -> int:
    return -1 if grade == "none" else GRADE_ORDER.index(grade)


def ceiling(n_items: int | None, se: float | None = None) -> str:
    """Наивысшая категория, которую может дать тест такой длины и точности (None — без ограничения длины)."""
    short = n_items is not None and n_items < TOP_MIN_ITEMS
    wide = se is not None and float(se) > TOP_MAX_SE
    return SHORT_CEILING if short or wide else GRADE_ORDER[-1]


@dataclass(frozen=True)
class CategoryLevel:
    grade: str  # категория: "none" | intern | junior | middle | senior
    proven: str  # наивысший грейд с P(θ ≥ порога) ≥ уровня подтверждения — без потолка
    ceiling: str  # потолок по длине теста и погрешности
    capped: bool  # доказанный уровень выше потолка: категория срезана до потолка
    preliminary: bool  # короткий тест (мини-тест QR): категория предварительная
    p: float  # P(θ ≥ порога категории)


def category_level(theta: float, se: float, n_items: int | None = None,
                   confirm_level: float = CONFIRM_LEVEL) -> CategoryLevel:
    """Единое отображение θ ± SE → категория для всех режимов (полный, экспресс, дотестирование, мини-тест)."""
    proven = "none"
    for g in GRADE_ORDER:  # P(θ ≥ порога) убывает с грейдом: наивысший — последний, где P ≥ уровня
        if p_at_least(theta, se, g) >= confirm_level:
            proven = g
    top = ceiling(n_items, se)
    grade = proven if _rank(proven) <= _rank(top) else top
    return CategoryLevel(grade, proven, top, _rank(proven) > _rank(top),
                         n_items is not None and n_items <= PRELIMINARY_MAX_ITEMS,
                         round(p_at_least(theta, se, grade), 4))


def probabilities(theta: float, se: float) -> dict[str, float]:
    order = ("none",) + GRADE_ORDER
    at_least = [p_at_least(theta, se, g) for g in order] + [0.0]
    return {g: round(at_least[i] - at_least[i + 1], 4) for i, g in enumerate(order)}


def decide_grade(theta: float, se: float, claimed: str, confirm_level: float = CONFIRM_LEVEL,
                 upgrade_level: float = UPGRADE_LEVEL, n_items: int | None = None) -> GradeDecision:
    """Решение по заявленному грейду на полной шкале платформы (см. описание модуля) с потолком категории
    (``ceiling``): грейд выше потолка короткий или слишком неточный тест не подтверждает; уровень ниже, доказанный
    с той же уверенностью, остаётся доступным («пройти тест на …» / «принять уровень ниже»). n_items — число
    оценённых заданий (None — длина не ограничивает, только погрешность)."""
    dec = _decide(theta, se, claimed, confirm_level, upgrade_level)
    top = ceiling(n_items, se)
    if _rank(claimed) > _rank(top) and (dec.confirmed or dec.provisional):
        lvl = category_level(theta, se, n_items, confirm_level)
        retake = lvl.grade if lvl.grade != "none" and _rank(lvl.grade) < _rank(claimed) else None
        expl = (f"Заявленный грейд {claimed} не подтверждён: тест из {n_items or 'малого числа'} заданий с погрешностью "
                f"{ru_num(se)} подтверждает категорию не выше {top}"
                + (f"; можно пройти тест на {retake} или полный тест на {claimed}." if retake
                   else f"; можно пройти полный тест на {claimed}."))
        return replace(dec, confirmed=False, assigned="none", upgrade_available=False, retake_lower=retake,
                       provisional=False, provisional_reason=None, explanation=expl)
    if dec.upgrade_available and _rank(claimed) + 1 > _rank(top):
        dec = replace(dec, upgrade_available=False)
    return dec


def _decide(theta: float, se: float, claimed: str, confirm_level: float, upgrade_level: float) -> GradeDecision:
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
        expl = (f"Заявленный грейд {claimed} подтверждён: P(θ ≥ порога) = {ru_num(p_claim)}"
                f" при θ = {theta_se(theta, se)}.")
        if upgrade:
            expl += f" Результат уверенно выше: можно пройти тест на {GRADE_ORDER[idx + 1]}."
    else:
        expl = (f"Заявленный грейд {claimed} не подтверждён: P(θ ≥ порога) = {ru_num(p_claim)}. "
                "Грейд не понижается принудительно; "
                + (f"можно пройти тест на {retake}." if retake else "можно пройти тест ещё раз после подготовки."))
    return GradeDecision(claimed, point, confirmed, claimed if confirmed else "none", upgrade, retake, probs, expl)


# ---------------------------------------------------------------- позиция внутри уровня (Я22, флаг GRADE_POSITION_ENABLED)
# Полоса грейда — [порог; порог следующего); у Senior сверху порога нет — условная ширина 1 (как у Junior и Middle).
# Половина полосы — граница «нижняя / верхняя часть»; середина — центральная половина полосы. Позиция называется,
# только когда погрешность это позволяет: P(θ по одну сторону середины полосы) ≥ 0,8 — «нижняя» / «верхняя часть»;
# P(θ в центральной половине полосы) ≥ 0,5 — «середина»; иначе — «точнее — после дотестирования». Числа θ не выводятся.
POSITION_LEVEL = 0.8
POSITION_MID_LEVEL = 0.5
POSITION_MAX_SE = 0.6
POSITION_TEXT = {"lower": "нижняя часть уровня", "middle": "середина уровня", "upper": "верхняя часть уровня",
                 "uncertain": "точнее — после дотестирования"}


def _band(grade: str) -> tuple[float, float]:
    i = GRADE_ORDER.index(grade)
    lo = GRADE_CUTS[grade]
    hi = GRADE_CUTS[GRADE_ORDER[i + 1]] if i + 1 < len(GRADE_ORDER) else lo + 1.0
    return lo, hi


def _cdf(x: float, theta: float, se: float) -> float:
    return 0.5 * (1 + math.erf((x - theta) / (max(se, 1e-6) * math.sqrt(2))))


def level_position(theta: float | None, se: float | None, grade: str | None) -> dict | None:
    """Позиция θ̂ внутри полосы присвоенного грейда: lower | middle | upper | uncertain (см. правила выше).
    None — нет грейда или оценки. Текст без чисел θ — для результата кандидата и карточки работодателя."""
    if grade not in GRADE_ORDER or theta is None or se is None:
        return None
    theta, se = float(theta), float(se)
    lo, hi = _band(grade)
    w = hi - lo
    mid = lo + w / 2
    code = "uncertain"
    if se <= POSITION_MAX_SE:
        p_low = _cdf(mid, theta, se)
        p_center = _cdf(lo + 3 * w / 4, theta, se) - _cdf(lo + w / 4, theta, se)
        if p_low >= POSITION_LEVEL:
            code = "lower"
        elif 1 - p_low >= POSITION_LEVEL:
            code = "upper"
        elif p_center >= POSITION_MID_LEVEL:
            code = "middle"
    return {"code": code, "text": POSITION_TEXT[code], "grade": grade, "grade_title": GRADE_RU.get(grade, grade),
            "known": code != "uncertain"}
