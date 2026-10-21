"""Классификационный адаптивный тест у порогов грейдов, последовательный критерий Вальда (SPRT) и трёхзначный вердикт.

Реализует три ключевые механики этапа 3 плана (ошибки C1, C2, C3, C4):
1. Отбор заданий у ближайшего порога грейда (классификационный CAT), а не в точечной оценке θ̂ (C2).
2. Подтверждение заявленного грейда последовательным тестом отношения правдоподобия (SPRT) с остановкой, как только
   накопленное логарифмическое отношение правдоподобия LLR пересекает порог ±A = ±ln((1 − α)/α) (C3).
3. Трёхзначный вердикт по заявленному грейду (C1):
   - ``confirmed`` («Подтверждён») — уверенное подтверждение (LLR ≥ +A или высокая апостериорная вероятность P(θ ≥ порога));
   - ``not_confirmed`` («Не подтверждён») — уверенный отказ (LLR ≤ −A и низкая апостериорная вероятность);
   - ``needs_followup`` («Нужен доп. этап») — оценка попала в зону неопределённости у порога (|LLR| < A): вместо
     случайного угадывания у границы назначается короткий 15-минутный дополнительный этап (до 8 заданий) строго у
     спорного порога грейда.
4. Доля практических заданий (код и развёрнутые ответы с автопроверкой: ``find_bug``, ``predict_output``,
   ``choose_fix``, ``open_answer``, ``open_book_3step``) — не менее трети сессии при наличии таких семейств в пуле.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence

import numpy as np

from app.modules.assessment.grades import GRADE_RU, p_at_least as _p_at_least_base
from app.modules.catalog.seed_data import ALL_GRADE_CUTS as GRADE_CUTS, GRADE_ORDER


def p_at_least(theta: float, se: float, grade: str) -> float:
    cut = GRADE_CUTS.get(grade)
    if cut is None:
        return _p_at_least_base(theta, se, grade)
    return 0.5 * (1.0 + math.erf((float(theta) - float(cut)) / (max(float(se), 1e-6) * math.sqrt(2.0))))

CODE_OPEN_FORMATS: frozenset[str] = frozenset({
    "find_bug",
    "predict_output",
    "choose_fix",
    "open_answer",
    "open_book_3step",
    "incident_sim",
})
SENIOR_PLUS_GRADES: frozenset[str] = frozenset({"senior", "lead", "principal"})
INCIDENT_STAGE_A: float = 1.45  # дискриминативность боевого этапа (симулятор инцидента + рубрика, c = 0)
INCIDENT_PASS_SCORE: float = 0.65

# Параметры SPRT по умолчанию (выбраны кросс-валидацией на обучающей половине зёрен, проверены на отложенной)
DEFAULT_ALPHA: float = 0.02
DEFAULT_DELTA: float = 0.35
DEFAULT_MIN_ITEMS_SPRT: int = 6
DEFAULT_CODE_OPEN_SHARE: float = 1.0 / 3.0
DEFAULT_FOLLOWUP_MINUTES: int = 15
DEFAULT_FOLLOWUP_ITEMS: int = 8
HONEST_A_CAP: float = 1.6  # защита от некалиброванных a = 3.0 до завершения калибровки на людях

VERDICT_TITLES: dict[str, str] = {
    "confirmed": "Подтверждён",
    "not_confirmed": "Не подтверждён",
    "needs_followup": "Нужен доп. этап",
    "needs_oral_defense": "Нужен доп. этап / устная защита",
}


def sprt_bound(alpha: float = DEFAULT_ALPHA) -> float:
    """Порог Вальда A = ln((1 − α) / α) для симметричного последовательного критерия."""
    a = min(max(float(alpha), 1e-4), 0.45)
    return float(math.log((1.0 - a) / a))


def item_guessing(fmt: str, n_options: int = 4) -> float:
    """Параметр угадывания c: 0 для кодовых и открытых заданий, 1/K для тестовых вопросов с выбором варианта."""
    if fmt in CODE_OPEN_FORMATS:
        return 0.0
    return 1.0 / max(int(n_options), 4)


def p_item(theta: float | np.ndarray, a: float | np.ndarray, b: float | np.ndarray, c: float = 0.0) -> float | np.ndarray:
    """Вероятность верного ответа по 2PL/3PL с защитой от численного переполнения."""
    z = np.clip(a * (theta - b), -30.0, 30.0)
    p2 = 1.0 / (1.0 + np.exp(-z))
    return c + (1.0 - c) * p2


def step_llr(
    x: float | Sequence[float],
    a: Sequence[float],
    b: Sequence[float],
    cut: float,
    *,
    fmt: str = "mcq_concept",
    delta: float = DEFAULT_DELTA,
    a_cap: float = HONEST_A_CAP,
) -> float:
    """Вклад одного оценённого задания в логарифмическое отношение правдоподобия LLR у порога ``cut``.

    Проверяется гипотеза H₁: θ ≥ cut + δ против H₀: θ ≤ cut − δ.
    """
    xs = np.atleast_1d(np.asarray(x, dtype=float))
    aa = np.clip(np.atleast_1d(np.asarray(a, dtype=float)), 0.2, a_cap)
    bb = np.atleast_1d(np.asarray(b, dtype=float))
    c = item_guessing(fmt)
    total = 0.0
    n = min(len(xs), len(aa), len(bb))
    for j in range(n):
        xj = float(xs[j])
        if not math.isfinite(xj):
            continue
        p_hi = float(np.clip(p_item(cut + delta, aa[j], bb[j], c), 1e-6, 1.0 - 1e-6))
        p_lo = float(np.clip(p_item(cut - delta, aa[j], bb[j], c), 1e-6, 1.0 - 1e-6))
        total += xj * math.log(p_hi / p_lo) + (1.0 - xj) * math.log((1.0 - p_hi) / (1.0 - p_lo))
    return float(total)


def nearest_cut(theta: float, cuts: Sequence[float] = ()) -> float:
    """Ближайший порог грейда к текущей оценке θ̂ для классификационного отбора заданий (C2)."""
    cs = tuple(cuts) if cuts else tuple(GRADE_CUTS[g] for g in GRADE_ORDER)
    if not cs:
        return float(theta)
    return float(min(cs, key=lambda c: abs(float(theta) - float(c))))


def select_target_cut(
    theta: float,
    se: float,
    claimed_grade: str | None = None,
    cuts: Sequence[float] = (),
    uncertain: Sequence[float] = (),
) -> float:
    """Целевая точка максимальной информации для классификационного адаптивного теста:
    1) если есть неопределённые пороги внутри доверительного интервала — ближайший из них (или порог заявленного грейда,
       если он среди неопределённых);
    2) иначе — ближайший порог шкалы грейдов к текущей оценке θ̂.
    """
    claimed_cut = GRADE_CUTS.get(claimed_grade or "")
    if uncertain:
        if claimed_cut is not None and any(abs(float(c) - float(claimed_cut)) < 1e-6 for c in uncertain):
            return float(claimed_cut)
        return float(uncertain[0])
    if claimed_cut is not None and abs(float(theta) - float(claimed_cut)) <= 1.5 * max(float(se), 0.25):
        return float(claimed_cut)
    return nearest_cut(theta, cuts)


def filter_code_open_pool(
    cands: list,
    n_scored: int,
    n_code_open: int,
    target_share: float = DEFAULT_CODE_OPEN_SHARE,
) -> list:
    """Обеспечивает долю ≥ ``target_share`` (по умолчанию ≥ 1/3) кодовых и открытых заданий с автопроверкой в сессии.

    Если к шагу ``n_scored + 1`` доля выданных кодовых/открытых заданий отстаёт от ``target_share`` (например, каждое
    третье задание: позиции 3, 6, 9, 12, 15), и в доступном пуле ``cands`` есть задания форматов ``CODE_OPEN_FORMATS``,
    выбор ограничивается ими. На остальных шагах движок свободно выбирает наиболее информативное задание (включая
    быстрые кодовые задания ``find_bug``, ``predict_output``, ``choose_fix`` с ``a = 1,3``).
    """
    if not cands or target_share <= 0.0:
        return cands
    want_code = ((n_scored + 1) % 3 == 0) or (n_code_open < int(math.floor((n_scored + 1) * target_share)))
    if not want_code:
        return cands
    co = [i for i in cands if getattr(i, "format", None) in CODE_OPEN_FORMATS]
    return co if co else cands


# ---------------------------------------------------------------------------------------------------------------
# Поправка №2 протокола (А4, 21.10 вечер): решение по заявленному грейду — SPRT по ответам, без априорного
# стягивания; угадывание — по фактическому числу вариантов; оценка уровня для «уровня по ответам» — WLE (Уорм).
# Одна реализация для продукта (bank_engine, exposure.AppCATSession, two_stage) и симуляции продукта.

OPTION_STEPS: dict[str, tuple[int, ...] | None] = {"mcq_concept": None, "choose_fix": None,
                                                   "open_book_3step": (0, 1), "incident_sim": (0, 1)}


def verdict_params() -> dict:
    """Параметры решения по заявленному грейду из настроек (app.core.config)."""
    from app.core.config import get_settings

    s = get_settings()
    return {"rule": str(getattr(s, "assessment_verdict_rule", "posterior") or "posterior"),
            "delta": float(getattr(s, "assessment_sprt_delta", DEFAULT_DELTA)),
            "alpha": float(getattr(s, "assessment_sprt_alpha", DEFAULT_ALPHA)),
            "beta": float(getattr(s, "assessment_sprt_beta", 0.10)),
            "actual_k": bool(getattr(s, "assessment_guess_actual_k", False)),
            "point_estimator": str(getattr(s, "assessment_point_estimator", "wle") or "wle"),
            "upgrade_rule": str(getattr(s, "assessment_upgrade_rule", "sprt") or "sprt")}


def sprt_on() -> bool:
    return verdict_params()["rule"] == "sprt"


def guess_parts(fmt: str, n_parts: int, step_options: Sequence[int] | None = None, code_lines: int | None = None,
                actual: bool = True) -> np.ndarray:
    """Угадывание c по частям задания. Части с выбором варианта — 1/K (K — число вариантов шага; без данных — 4);
    «строка с ошибкой» — 1/число строк кода (actual); вывод программы и развёрнутый ответ — 0.
    actual=False — прежнее правило: c = 1/4 у частей с выбором, 0 у остальных."""
    n = max(1, int(n_parts))
    c = np.zeros(n)
    steps = OPTION_STEPS.get(fmt, ())
    idx = range(n) if steps is None else [j for j in steps if j < n]
    for j in idx:
        k = 4
        if actual and step_options is not None and j < len(step_options) and step_options[j]:
            k = int(step_options[j])
        c[j] = 1.0 / max(2, k)
    if actual and fmt == "find_bug" and code_lines:
        c[:] = 1.0 / max(2, int(code_lines))
    return c


def public_guess(fmt: str, n_parts: int, public: dict | None, actual: bool = True) -> np.ndarray:
    """c по частям для выданного варианта (публичная часть задания: варианты по шагам, строки кода)."""
    pub = public or {}
    opts = pub.get("options") or []
    if fmt in ("open_book_3step", "incident_sim"):
        per = [sum(1 for o in opts if int(o.get("step", 0) or 0) == j + 1) for j in range(max(1, int(n_parts)))]
    else:
        per = [len(opts)] * max(1, int(n_parts))
    lines = pub.get("code_lines")
    if lines is None and pub.get("code"):
        lines = len(str(pub.get("code")).splitlines())
    return guess_parts(fmt, n_parts, per, lines, actual=actual)


def llr3(x: Sequence[float], a: Sequence[float], b: Sequence[float], c: Sequence[float], cut: float,
         delta: float = DEFAULT_DELTA, a_cap: float = HONEST_A_CAP) -> float:
    """Вклад задания в LLR у порога cut (3PL с угадыванием c по частям): H₁ θ = cut + δ против H₀ θ = cut − δ."""
    xs = np.atleast_1d(np.asarray(x, dtype=float))
    aa = np.clip(np.atleast_1d(np.asarray(a, dtype=float)), 0.2, a_cap)
    bb = np.atleast_1d(np.asarray(b, dtype=float))
    cc = np.atleast_1d(np.asarray(c, dtype=float))
    n = min(len(xs), len(aa), len(bb))
    if len(cc) < n:
        cc = np.concatenate([cc, np.zeros(n - len(cc))])
    total = 0.0
    for j in range(n):
        xj = float(xs[j])
        if not math.isfinite(xj):
            continue
        p1 = float(np.clip(p_item(cut + delta, aa[j], bb[j], float(cc[j])), 1e-6, 1 - 1e-6))
        p0 = float(np.clip(p_item(cut - delta, aa[j], bb[j], float(cc[j])), 1e-6, 1 - 1e-6))
        total += xj * math.log(p1 / p0) + (1.0 - xj) * math.log((1.0 - p1) / (1.0 - p0))
    return float(total)


def sprt_bounds(alpha: float, beta: float) -> tuple[float, float]:
    """Границы Вальда: верхняя ln((1 − β)/α) — «подтверждён», нижняя ln(β/(1 − α)) — «не подтверждён»."""
    a = min(max(float(alpha), 1e-4), 0.45)
    b = min(max(float(beta), 1e-4), 0.45)
    return float(math.log((1.0 - b) / a)), float(math.log(b / (1.0 - a)))


def sprt_status(llr: float, alpha: float, beta: float) -> str:
    up, lo = sprt_bounds(alpha, beta)
    if llr >= up:
        return "confirmed"
    if llr <= lo:
        return "not_confirmed"
    return "needs_followup"


_WLE_GRID = np.linspace(-5.0, 6.0, 1101)


def wle(x: Sequence[float], a: Sequence[float], b: Sequence[float], c: Sequence[float]) -> tuple[float, float]:
    """Оценка уровня Уорма (WLE) для 3PL по частям: корень S(θ) + H(θ)/(2I(θ)) = 0 (S — производная логарифма
    правдоподобия, I — информация, H = Σ P'P''/(PQ)); без априорного распределения, конечна и при всех верных /
    всех неверных. Несколько корней — с наибольшим ℓ(θ) + ½ ln I(θ). SE = 1/√I(θ̂)."""
    xs = np.asarray(x, dtype=float)
    m = np.isfinite(xs)
    xs = xs[m]
    if not len(xs):
        return 0.0, 1.0
    aa = np.asarray(a, dtype=float)[m]
    bb = np.asarray(b, dtype=float)[m]
    cc = np.asarray(c, dtype=float)[m]
    t = _WLE_GRID[:, None]
    sg = 1.0 / (1.0 + np.exp(-np.clip(aa[None, :] * (t - bb[None, :]), -30, 30)))
    p = np.clip(cc[None, :] + (1 - cc[None, :]) * sg, 1e-9, 1 - 1e-9)
    q = 1.0 - p
    d1 = (1 - cc[None, :]) * aa[None, :] * sg * (1 - sg)
    d2 = d1 * aa[None, :] * (1 - 2 * sg)
    info = (d1 * d1 / (p * q)).sum(axis=1)
    score = ((xs[None, :] - p) * d1 / (p * q)).sum(axis=1)
    h = (d1 * d2 / (p * q)).sum(axis=1)
    f = score + h / (2.0 * np.maximum(info, 1e-12))
    ll = (xs[None, :] * np.log(p) + (1 - xs[None, :]) * np.log(q)).sum(axis=1) + 0.5 * np.log(np.maximum(info, 1e-12))
    roots = np.where((f[:-1] > 0) & (f[1:] <= 0))[0]
    if len(roots):
        k = int(max(roots, key=lambda i: ll[i]))
        f0, f1 = f[k], f[k + 1]
        th = float(_WLE_GRID[k] + (_WLE_GRID[k + 1] - _WLE_GRID[k]) * (f0 / (f0 - f1) if f0 != f1 else 0.5))
    else:
        th = float(_WLE_GRID[int(np.argmax(ll))])
    sgv = 1.0 / (1.0 + np.exp(-np.clip(aa * (th - bb), -30, 30)))
    pv = np.clip(cc + (1 - cc) * sgv, 1e-9, 1 - 1e-9)
    d1v = (1 - cc) * aa * sgv * (1 - sgv)
    iv = float((d1v * d1v / (pv * (1 - pv))).sum())
    return th, float(1.0 / math.sqrt(iv)) if iv > 1e-9 else 9.99


def point_grade(theta: float, order: Sequence[str]) -> str:
    """«Уровень по ответам»: наивысший уровень шкалы направления, порог которого не выше θ̂."""
    out = "none"
    for g in order:
        cut = GRADE_CUTS.get(g)
        if cut is not None and float(theta) >= float(cut):
            out = g
    return out


def product_grade(status: str, point: str, claimed: str, order: Sequence[str], *, upgrade: str = "point",
                  next_up: bool = False) -> str:
    """Уровень, который продукт показывает по итогам теста: «уровень по ответам», согласованный с вердиктом —
    подтверждён → заявленный, выше — по правилу upgrade (point — по оценке уровня; sprt — на ступень выше, только если
    SPRT у следующего порога уверенно «выше» (next_up); none — не выше заявленного); не подтверждён → уровень по
    ответам, но ниже заявленного; доп. этап — уровень по ответам как есть (с пометкой «предварительно»)."""
    seq = ["none"] + [g for g in order]
    r = seq.index(point) if point in seq else 0
    rc = seq.index(claimed) if claimed in seq else r
    if status == "confirmed":
        if upgrade == "none":
            r = rc
        elif upgrade == "sprt":
            r = min(rc + 1, len(seq) - 1) if next_up else rc
        else:
            r = max(r, rc)
    elif status == "not_confirmed":
        r = min(r, max(0, rc - 1))
    return seq[r]


def next_grade(claimed: str, order: Sequence[str]) -> str | None:
    seq = list(order)
    return seq[seq.index(claimed) + 1] if claimed in seq and seq.index(claimed) + 1 < len(seq) else None


def items_llr_wle(items: Iterable[dict], lookup: dict, cut: float, delta: float, actual: bool = True,
                  extra_cuts: Sequence[float] = ()) -> tuple:
    """LLR у порога cut и WLE по выполненным оцениваемым заданиям состояния сессии (те же a_eff, b и c, что в
    отборе): (llr, θ̂_WLE, SE, число частей с ответом[, {доп. порог: llr}])."""
    items = list(items)
    if extra_cuts:
        base = items_llr_wle(items, lookup, cut, delta, actual)
        more = {float(c2): items_llr_wle(items, lookup, float(c2), delta, actual)[0] for c2 in extra_cuts}
        return (*base, more)
    llr = 0.0
    X, A, B, C = [], [], [], []
    for it in items:
        if it.get("canary") or not it.get("done", True):
            continue
        if (it.get("appeal") or {}).get("status") in ("under_review", "excluded"):
            continue
        xs = [np.nan if v is None else float(v) for v in (it.get("x") or [])]
        if not xs or all(not math.isfinite(v) for v in xs):
            continue
        pi = lookup.get(it.get("family_id"))
        if pi is not None:
            aa, bb = np.asarray(pi.a_eff, dtype=float), np.asarray(pi.b, dtype=float)
        else:
            snap = it.get("pool") or {}
            aa = np.asarray(snap.get("a") or [1.0] * len(xs), dtype=float)
            bb = np.asarray(snap.get("b") or [cut] * len(xs), dtype=float)
        cc = public_guess(str(it.get("format") or ""), len(xs), it.get("public"), actual=actual)
        n = min(len(xs), len(aa), len(bb))
        llr += llr3(xs[:n], aa[:n], bb[:n], cc[:n], cut, delta)
        X += xs[:n]
        A += list(aa[:n])
        B += list(bb[:n])
        C += list(cc[:n])
    th, se = wle(X, A, B, C) if X else (0.0, 9.99)
    return float(llr), float(th), float(se), int(sum(1 for v in X if math.isfinite(v)))


@dataclass(frozen=True)
class ThreeValuedVerdict:
    status: str              # confirmed | not_confirmed | needs_followup
    title: str               # Подтверждён | Не подтверждён | Нужен доп. этап
    confident: bool          # True для confirmed и not_confirmed, False для needs_followup
    claimed_grade: str
    assigned_grade: str
    llr: float
    threshold_a: float
    alpha: float
    delta: float
    cut: float
    p_claimed: float
    n_scored: int
    code_open_count: int
    code_open_share: float
    followup_needed: bool
    followup_minutes: int
    followup_items: int
    followup_cut_grade: str
    explanation: str
    incident_stage: dict | None = None
    suspicious_flagged: bool = False
    suspicious_reasons: tuple[str, ...] = ()
    oral_defense_required: bool = False
    integrity_followup: dict | None = None
    theta: float | None = None
    se: float | None = None

    def as_dict(self) -> dict:
        out = {
            "status": self.status,
            "title": self.title,
            "confident": self.confident,
            "claimed_grade": self.claimed_grade,
            "claimed_grade_title": GRADE_RU.get(self.claimed_grade, self.claimed_grade),
            "assigned_grade": self.assigned_grade,
            "assigned_grade_title": GRADE_RU.get(self.assigned_grade, self.assigned_grade),
            "llr": round(self.llr, 3),
            "threshold_a": round(self.threshold_a, 3),
            "alpha": self.alpha,
            "delta": self.delta,
            "cut": round(self.cut, 3),
            "p_claimed": round(self.p_claimed, 4),
            "theta": round(self.theta, 4) if self.theta is not None else None,
            "se": round(self.se, 4) if self.se is not None else None,
            "n_scored": self.n_scored,
            "code_open_count": self.code_open_count,
            "code_open_share": round(self.code_open_share, 3),
            "suspicious_flagged": self.suspicious_flagged,
            "suspicious_reasons": list(self.suspicious_reasons),
            "followup": {
                "needed": self.followup_needed,
                "minutes": self.followup_minutes,
                "items": self.followup_items,
                "cut_grade": self.followup_cut_grade,
                "cut_grade_title": GRADE_RU.get(self.followup_cut_grade, self.followup_cut_grade),
                "cut": round(self.cut, 3),
                "incident_recommended": self.claimed_grade in SENIOR_PLUS_GRADES,
                "oral_defense_required": self.oral_defense_required,
                "kind": (self.integrity_followup or {}).get("followup_kind") or ("oral_defense" if self.oral_defense_required else ("stage2" if self.followup_needed else None)),
            },
            "explanation": self.explanation,
            # плоские поля для карточки работодателя (profiles/facts.verdict_summary читает их с верхнего уровня):
            # «рекомендована устная защита» и вид доп. этапа — те же значения, что в followup
            "oral_defense_required": self.oral_defense_required,
            "followup_kind": (self.integrity_followup or {}).get("followup_kind") or ("oral_defense" if self.oral_defense_required else ("stage2" if self.followup_needed else None)),
            "integrity_oral": bool((self.integrity_followup or {}).get("integrity_oral")),
        }
        if self.incident_stage is not None:
            out["incident_stage"] = self.incident_stage
        return out


def evaluate_integrity_followup(
    integrity_dict: dict | None,
    scored_items: list[dict] | None = None,
    *,
    decoy_hits: int = 0,
) -> dict:
    """Единый контур античита А6 + разрыва форм теста А4 (``integrity_followup``).

    Использует ``integrity_followup(integrity, decoy_hits=...)`` из ``app.modules.proctor.rules`` или
    ``app.modules.assessment.grader`` (А6) через ``getattr``, а до слияния ветки А6 — совместимую заглушку с тем же
    контрактом и порогом ``threshold_points = 2``. Добавляет фактор ``"form_gap"`` в ``triggered_factors`` по тому же
    правилу накопления баллов риска.
    """
    from app.modules.assessment import integrity as integ_mod

    integ = dict(integrity_dict or {})
    sig = dict(integ.get("signals") or {})
    fg = integ_mod.format_gap_logits(scored_items or []) if scored_items is not None else None
    if fg and fg.get("flagged") and not sig.get("format_gap_flag"):
        sig["format_gap"] = fg["gap_logits"]
        sig["format_gap_flag"] = True
        sig["theta_mcq"] = fg["theta_mcq"]
        sig["theta_code"] = fg["theta_code"]
        integ["signals"] = sig
        integ["points"] = int(integ.get("points") or 0) + int(fg.get("points") or 1)
        rs = list(integ.get("reasons") or [])
        if fg.get("employer_reason") and fg["employer_reason"] not in rs:
            rs.append(fg["employer_reason"])
        integ["reasons"] = rs

    ext_fn = None
    try:
        from app.modules.proctor import rules as proctor_rules
        ext_fn = getattr(proctor_rules, "integrity_followup", None)
    except Exception:
        ext_fn = None
    if ext_fn is None:
        try:
            from app.modules.assessment import grader as grader_mod
            ext_fn = getattr(grader_mod, "integrity_followup", None)
        except Exception:
            ext_fn = None

    decoy_n = int(decoy_hits or sig.get("ai_mark_items") or 0)
    if callable(ext_fn):
        res = dict(ext_fn(integ, decoy_hits=decoy_n))
    else:
        pts = int(integ.get("points") or 0)
        threshold = 2
        factors: list[str] = []
        if sig.get("lz_flag") or (isinstance(sig.get("lz"), (int, float)) and float(sig["lz"]) < -2.0):
            factors.append("person_fit")
        if (sig.get("fast_correct") or 0) >= 2 or (sig.get("instant_correct") or 0) >= 1 or (sig.get("fast_text_items") or 0) >= 1 or sig.get("preknowledge_flagged"):
            factors.append("time_anomaly")
        if (sig.get("focus_lost_items") or 0) >= 2 or (sig.get("hidden_s") or 0) >= 30 or (sig.get("fs_exits") or 0) >= 2:
            factors.append("focus_lost")
        if (sig.get("paste_items") or 0) >= 1 or (sig.get("not_typed_items") or 0) >= 1 or (sig.get("even_rhythm_items") or 0) >= 1:
            factors.append("paste_origin")
        if decoy_n > 0 or (sig.get("copy_items") or 0) >= 1 or (sig.get("printscreen_items") or 0) >= 1:
            factors.append("copy_decoy")
        if integ.get("camera"):
            factors.append("camera")
        if sig.get("format_gap_flag") or (fg and fg.get("flagged")):
            factors.append("form_gap")
        decoy_hit = bool(decoy_n > 0 or sig.get("preknowledge_flagged"))
        needs = bool(pts >= threshold or decoy_hit)
        emp_view = integ_mod.summary_for_employer(integ) or {}
        cand_view = integ_mod.candidate_view(integ) or {}
        res = {
            "honesty_index": round(max(0.0, min(1.0, 1.0 - 0.15 * pts - (0.25 if decoy_hit else 0.0))), 3),
            "risk_points": pts,
            "threshold_points": threshold,
            "needs_followup_stage": needs,
            "followup_kind": ("oral_defense" if (decoy_hit or pts >= 3 or "form_gap" in factors or "person_fit" in factors) else "stage2") if needs else None,
            "triggered_factors": factors,
            "decoy_hit": decoy_hit,
            "employer_reason_ru": "; ".join(emp_view.get("reasons") or []),
            "candidate_reason_ru": "; ".join(cand_view.get("reasons") or []),
        }

    # Гарантируем, что "form_gap" присутствует в triggered_factors единым путём, если разрыв форм сработал
    tf = list(res.get("triggered_factors") or [])
    if (sig.get("format_gap_flag") or (fg and fg.get("flagged"))) and "form_gap" not in tf:
        tf.append("form_gap")
        res["triggered_factors"] = tf
        res["risk_points"] = max(int(res.get("risk_points") or 0), int(fg.get("points") or 1) if fg else 1)
        if int(res["risk_points"]) >= int(res.get("threshold_points") or 2) or (fg and fg["gap_logits"] > integ_mod.FORMAT_GAP_WARN):
            res["needs_followup_stage"] = True
            if not res.get("followup_kind"):
                res["followup_kind"] = "oral_defense"
        if fg and fg.get("employer_reason") and fg["employer_reason"] not in (res.get("employer_reason_ru") or ""):
            res["employer_reason_ru"] = (
                f"{res['employer_reason_ru']}; {fg['employer_reason']}" if res.get("employer_reason_ru") else fg["employer_reason"]
            )
    if fg is not None:
        res["format_gap"] = fg
    return res


def incident_theta_update(
    theta: float,
    se: float,
    claimed_grade: str,
    incident: dict | None,
    *,
    delta: float = DEFAULT_DELTA,
) -> tuple[float, float, float, dict | None]:
    """Включает результат «Боевого этапа» (разбор инцидента на симуляторе + рубрика, А9) для Senior/Lead/Principal
    как независимое высокоинформативное свидетельство у порога заявленного старшего грейда.

    Возвращает ``(theta_post, se_post, llr_delta, normalized_incident_dict)``.
    """
    if not incident or incident.get("status", "completed") != "completed":
        return float(theta), float(se), 0.0, None
    raw_score = incident.get("score")
    if raw_score is None:
        act = incident.get("actions_score")
        rub = incident.get("rubric_score")
        if act is not None and rub is not None:
            raw_score = 0.5 * float(act) + 0.5 * float(rub)
        elif act is not None:
            raw_score = float(act)
        elif rub is not None:
            raw_score = float(rub)
        else:
            return float(theta), float(se), 0.0, None
    score = float(np.clip(float(raw_score), 0.0, 1.0))
    target_g = str(incident.get("target_grade") or claimed_grade or "senior")
    cut = float(GRADE_CUTS.get(target_g, GRADE_CUTS.get(claimed_grade, 1.0)))
    a_inc = float(incident.get("a", INCIDENT_STAGE_A))
    # Вклад в LLR последовательного теста у порога старшего грейда (c = 0, открытое практическое задание)
    llr_delta = step_llr([score], [a_inc], [cut], cut, fmt="open_book_3step", delta=delta)
    # Байесовское обновление (нормальное приближение EAP с информацией Фишера I = a² · p · (1 − p))
    th0, se0 = float(theta), max(float(se), 0.10)
    p_exp = float(p_item(th0, a_inc, cut, 0.0))
    info = max(a_inc * a_inc * p_exp * (1.0 - p_exp), 0.25)
    prec0 = 1.0 / (se0 * se0)
    prec1 = prec0 + info
    th1 = float(np.clip(th0 + (a_inc * (score - p_exp)) / prec1, -4.0, 4.5))
    se1 = float(math.sqrt(1.0 / prec1))
    points_gpcm = int(incident.get("points_gpcm") if incident.get("points_gpcm") is not None else round(4.0 * score))
    passed = bool(incident["passed"]) if incident.get("passed") is not None else (score >= INCIDENT_PASS_SCORE)
    norm = {
        "scenario_id": incident.get("scenario_id") or "incident_default",
        "target_grade": target_g,
        "status": "completed",
        "score": round(score, 3),
        "points_gpcm": int(np.clip(points_gpcm, 0, 4)),
        "actions_score": round(float(incident["actions_score"]), 3) if incident.get("actions_score") is not None else None,
        "rubric_score": round(float(incident["rubric_score"]), 3) if incident.get("rubric_score") is not None else None,
        "criteria": dict(incident.get("criteria") or {}),
        "mttr_s": incident.get("mttr_s"),
        "time_spent_s": incident.get("time_spent_s"),
        "passed": passed,
        "llr_delta": round(llr_delta, 3),
        "theta_before": round(th0, 4),
        "se_before": round(se0, 4),
        "theta_after": round(th1, 4),
        "se_after": round(se1, 4),
        "summary_ru": incident.get("summary_ru") or (
            f"Боевой этап (разбор инцидента): балл {round(100 * score)} % ({points_gpcm}/4 GPCM) — "
            + ("порог старшего грейда подтверждён." if passed else "результат ниже порога старшего грейда.")
        ),
    }
    return th1, se1, llr_delta, norm


def _integrity_oral_on() -> bool:
    try:
        from app.core.config import get_settings

        return bool(get_settings().integrity_oral)
    except Exception:  # noqa: BLE001 — без настроек (чистая симуляция) флаг выключен
        return False


def compute_verdict(
    done_items: Iterable[dict],
    lookup: dict,
    claimed_grade: str,
    theta: float,
    se: float,
    *,
    confirmed: bool,
    assigned_grade: str = "none",
    mode: str = "full",
    alpha: float = DEFAULT_ALPHA,
    delta: float = DEFAULT_DELTA,
    boundary_level: float = 0.80,
    incident_stage: dict | None = None,
    suspicious: bool | dict | None = None,
    followup_items: int = DEFAULT_FOLLOWUP_ITEMS,
    followup_minutes: int = DEFAULT_FOLLOWUP_MINUTES,
    sprt_state: dict | None = None,
    beta: float | None = None,
) -> ThreeValuedVerdict:
    """Вычисляет статистику SPRT и трёхзначный вердикт по завершённым заданиям сессии (с учётом Боевого этапа А9 и сигналов античита А6).

    sprt_state (поправка №2, ASSESSMENT_VERDICT_RULE=sprt) — {"llr", "status", ...} из ``items_llr_wle`` по ответам
    сессии (3PL, угадывание по варианту): решение — только SPRT, без апостериорной вероятности с априорным N(0; 1)."""
    cut = float(GRADE_CUTS.get(claimed_grade, 0.0))
    A = sprt_bound(alpha)
    # Исключаем задания, находящиеся на апелляции со статусом under_review или excluded
    scored = [
        it for it in done_items
        if not it.get("canary")
        and it.get("done", True)
        and (it.get("appeal") or {}).get("status") not in ("under_review", "excluded")
    ]
    llr = 0.0
    code_open = 0
    for it in scored:
        fmt = str(it.get("format") or "mcq_concept")
        if fmt in CODE_OPEN_FORMATS:
            code_open += 1
        xs = [v for v in (it.get("x") or []) if v is not None]
        if not xs:
            continue
        pi = lookup.get(it.get("family_id"))
        if pi is not None:
            aa, bb = pi.a_eff, pi.b
        else:
            pool_snap = it.get("pool") or {}
            aa = pool_snap.get("a") or [1.0]
            bb = pool_snap.get("b") or [cut]
        llr += step_llr(xs, aa, bb, cut, fmt=fmt, delta=delta)

    inc_norm = None
    if incident_stage is None:
        # Если в сессии было выдано и завершено семейство формата incident_sim (А3/А9), формируем сводку боевого этапа
        inc_it = next((it for it in reversed(scored) if it.get("format") == "incident_sim" and any(v is not None for v in (it.get("x") or []))), None)
        if inc_it is not None:
            xs_inc = [float(v) for v in (inc_it.get("x") or []) if v is not None]
            act_sc = float(np.mean(xs_inc[:2])) if len(xs_inc) >= 2 else (xs_inc[0] if xs_inc else 0.0)
            rub_sc = float(xs_inc[2]) if len(xs_inc) > 2 else act_sc
            tot_sc = float(np.mean(xs_inc)) if xs_inc else 0.0
            pts_gpcm = int(round(4.0 * tot_sc))
            passed_inc = tot_sc >= INCIDENT_PASS_SCORE
            inc_norm = {
                "scenario_id": inc_it.get("family_id") or "incident_sim",
                "target_grade": claimed_grade if claimed_grade in SENIOR_PLUS_GRADES else "senior",
                "status": "completed",
                "score": round(tot_sc, 3),
                "points_gpcm": pts_gpcm,
                "actions_score": round(act_sc, 3),
                "rubric_score": round(rub_sc, 3),
                "criteria": dict(((inc_it.get("grading") or [None, None, None])[-1] or {}).get("criteria") or {}),
                "mttr_s": inc_it.get("time_s"),
                "time_spent_s": inc_it.get("time_s"),
                "passed": passed_inc,
                "llr_delta": 0.0,
                "theta_before": inc_it.get("theta_before"),
                "se_before": None,
                "theta_after": round(float(theta), 4),
                "se_after": round(float(se), 4),
                "summary_ru": (
                    f"Боевой этап (симулятор инцидента): балл {round(100 * tot_sc)} % ({pts_gpcm}/4 GPCM) — "
                    + ("порог старшего грейда подтверждён." if passed_inc else "результат ниже порога старшего грейда.")
                ),
            }
    llr_inc_applied = 0.0
    if incident_stage is not None:
        theta, se, llr_inc, inc_norm = incident_theta_update(
            theta, se, claimed_grade, incident_stage, delta=delta
        )
        if inc_norm is not None:
            llr += llr_inc
            llr_inc_applied = float(llr_inc)
            code_open += 1

    sprt_rule = sprt_state is not None
    if sprt_rule:  # поправка №2: LLR — 3PL по ответам сессии (+ вклад боевого этапа, если он был)
        llr = float(sprt_state.get("llr", 0.0)) + llr_inc_applied
        A = sprt_bounds(alpha, beta if beta is not None else alpha)[0]
    n_scored = len(scored) + (1 if (incident_stage is not None and inc_norm is not None) else 0)
    co_share = (code_open / n_scored) if n_scored > 0 else 0.0
    p_claim = float(p_at_least(theta, se, claimed_grade)) if claimed_grade in GRADE_CUTS else (1.0 if confirmed else 0.0)
    if inc_norm is not None and p_claim >= 0.60 and inc_norm.get("passed"):
        confirmed = True
        if assigned_grade in ("none", None):
            assigned_grade = claimed_grade

    # Разбор признака подозрительной попытки от античита (А6) и разрыва форм теста (А4/А6):
    # единый механизм через evaluate_integrity_followup (не автоматический бан, а перевод в доп. этап / устную защиту).
    # Важно (Р27): в поля вердикта, отдаваемые кандидату (suspicious_reasons, explanation), идут только общие категории
    # candidate_view («Поведение во время теста», «Признаки использования подсказок»), без названий сигналов и порогов.
    integ_input = suspicious.get("integrity") if isinstance(suspicious, dict) and isinstance(suspicious.get("integrity"), dict) else (
        suspicious if isinstance(suspicious, dict) and "signals" in suspicious else {}
    )
    ifrel = evaluate_integrity_followup(integ_input, scored)
    susp_flagged = bool(ifrel.get("needs_followup_stage"))
    susp_reasons: list[str] = []
    if ifrel.get("candidate_reason_ru"):
        for part_r in str(ifrel["candidate_reason_ru"]).split("; "):
            if part_r and part_r not in susp_reasons and "Замечаний к самостоятельности" not in part_r:
                susp_reasons.append(part_r)
    if isinstance(suspicious, dict):
        # Решение «доп. этап» — только правило А6 (2+ сигнала или ловушка → доп. этап, без бана): одиночный
        # level == "low", preknowledge_flagged или lz < −2 сами по себе попытку не помечают (решение 21.10).
        # Явный флаг вызывающего (flagged/suspicious) — это уже итог правила, его уважаем.
        if suspicious.get("flagged") is True or suspicious.get("suspicious") is True:
            susp_flagged = True
            ifrel["needs_followup_stage"] = True
            if not ifrel.get("followup_kind"):
                ifrel["followup_kind"] = "oral_defense"
        if susp_flagged and not susp_reasons:
            susp_reasons.append("Признаки использования подсказок")
    elif bool(suspicious):
        susp_flagged = True
        ifrel["needs_followup_stage"] = True
        if not ifrel.get("followup_kind"):
            ifrel["followup_kind"] = "oral_defense"
        if not susp_reasons:
            susp_reasons.append("Признаки использования подсказок")

    # Экспериментальный флаг INTEGRITY_ORAL (по умолчанию выкл., на стенде не включён): одиночная низкая достоверность
    # (level «low», ≥ 3 балла; это НЕ правило А6 «2+ признака», см. config.integrity_oral) → грейд не подтверждается
    # сразу, итог решает короткий устный этап (без бана). Симуляции продукта принудительно идут с флагом 0.
    low_integrity_oral = False
    if _integrity_oral_on() and str((integ_input or {}).get("level") or "") == "low":
        low_integrity_oral = True
        susp_flagged = True
        ifrel["needs_followup_stage"] = True
        ifrel["followup_kind"] = "oral_defense"
        ifrel["integrity_oral"] = True

    # Трёхзначный вердикт (А4, 21.10) — то же правило, что у категории продукта и второго этапа, без отдельной логики:
    # P = P(θ ≥ порога заявленного грейда) по итоговой оценке и её погрешности; L — уровень уверенности второго этапа
    # (ASSESSMENT_TWO_STAGE_LEVEL, 0,8; полоса (1 − L; L) — граница, где предлагается второй этап, two_stage.boundary):
    #   «подтверждён»     — категория присвоена (P ≥ ASSESSMENT_CONFIRM_LEVEL) и P ≥ L;
    #   «не подтверждён»  — категория не присвоена и P ≤ 1 − L;
    #   «нужен доп. этап» — всё между: короткий второй этап у этой границы, итог — по ответам обеих сессий.
    # Это последовательная проверка гипотезы «уровень не ниже заявленного» в байесовской форме: тест идёт, пока
    # апостериорные шансы не выйдут за L : (1 − L); статистика Вальда (llr) считается и отдаётся для прозрачности,
    # в решении не участвует. Второй этап, дотестирование и Боевой этап — решение окончательное (как у категории).
    # Сигналы античита (А6: разрыв форм, предзнание, person-fit, низкая достоверность) — не бан: доп. этап / устная защита.
    level = float(boundary_level)
    if sprt_rule:
        status = sprt_status(llr, alpha, beta if beta is not None else alpha)
        confirmed = status == "confirmed"
        if status == "confirmed" and assigned_grade in ("none", None):
            assigned_grade = claimed_grade
    elif mode in ("refine", "confirm") or inc_norm is not None:
        status = "confirmed" if confirmed else "not_confirmed"
    elif confirmed and p_claim >= level:
        status = "confirmed"
    elif not confirmed and p_claim <= 1.0 - level:
        status = "not_confirmed"
    else:
        status = "needs_followup"
    oral_required = bool(susp_flagged and status != "not_confirmed")
    # поправка №2: после второго этапа (или боевого) решение по-прежнему не принято → устная защита, без монетки
    final_stage_undecided = bool(sprt_rule and status == "needs_followup" and (mode in ("refine", "confirm") or inc_norm is not None))
    if final_stage_undecided:
        oral_required = True
    if oral_required:
        status = "needs_followup"

    followup_needed = status == "needs_followup"
    g_title = GRADE_RU.get(claimed_grade, claimed_grade)
    p_pct = round(100 * p_claim)
    lv_pct = round(100 * level)
    title_str = VERDICT_TITLES["needs_oral_defense"] if oral_required else VERDICT_TITLES[status]
    if sprt_rule and final_stage_undecided and not susp_flagged:
        expl = (f"Даже после дополнительного этапа ответы остаются у самой границы уровня {g_title}: заданий "
                "недостаточно для уверенного решения. Решение примет короткая устная защита — разговор по одному из "
                "ваших ответов. Автоматического отказа нет.")
    elif sprt_rule and status == "confirmed":
        expl = (f"Уровень {g_title} подтверждён: ответы уверенно показывают уровень не ниже {g_title} (решение "
                "принято, как только ответов стало достаточно).")
    elif sprt_rule and status == "not_confirmed" and not oral_required:
        expl = (f"Уровень {g_title} не подтверждён: ответы уверенно показывают уровень ниже {g_title}. "
                "Принудительного понижения нет: уровень по ответам можно принять без нового теста или повторить тест "
                "после подготовки.")
    elif sprt_rule and status == "needs_followup" and not oral_required:
        inc_hint = (" Для Senior и выше доп. этап может включать разбор инцидента."
                    if claimed_grade in SENIOR_PLUS_GRADES else "")
        expl = (f"Ответы — у самой границы уровня {g_title}: этой сессии мало для уверенного решения. Нужен короткий "
                f"дополнительный этап у этой границы (до {followup_items} заданий, до {followup_minutes} минут); итог — "
                f"по ответам обеих частей вместе.{inc_hint}")
    elif oral_required and low_integrity_oral:
        expl = (f"Для подтверждения уровня {g_title} — короткий устный разговор с Настей: по ответам этой попытки "
                "результат предварительный, итог решит устный этап. Автоматических блокировок и понижения нет.")
    elif oral_required:
        reasons_txt = f" ({'; '.join(susp_reasons)})" if susp_reasons else ""
        expl = (
            f"Нужен дополнительный этап по уровню {g_title}{reasons_txt}. Автоматических блокировок нет: чтобы снять "
            "сомнения в самостоятельности, пройдите короткую устную защиту одного из ответов или дополнительный этап "
            "у порога уровня."
        )
    elif status == "confirmed":
        expl = (f"Уровень {g_title} подтверждён: вероятность, что ваш уровень не ниже {g_title}, — {p_pct} % "
                f"(уверенное решение — от {lv_pct} %).")
    elif status == "needs_followup":
        inc_hint = (" Для Senior и выше второй этап может включать разбор инцидента."
                    if claimed_grade in SENIOR_PLUS_GRADES else "")
        expl = (f"Ответы — у самой границы уровня {g_title}: вероятность {p_pct} %, между {100 - lv_pct} % и {lv_pct} %, "
                f"одной сессии мало для уверенного решения. Короткий второй этап у этой границы (до {followup_items} "
                f"заданий, до {followup_minutes} минут) решит вопрос; итог — по ответам обеих сессий вместе.{inc_hint}")
    else:
        expl = (f"Уровень {g_title} не подтверждён: вероятность {p_pct} % (уверенное решение «нет» — до "
                f"{100 - lv_pct} %). Принудительного понижения нет; если тест уверенно доказал уровень ниже, его можно "
                "принять без нового теста.")
    if inc_norm is not None and inc_norm.get("summary_ru"):
        expl += " " + str(inc_norm["summary_ru"])

    return ThreeValuedVerdict(
        theta=float(theta),
        se=float(se),
        status=status,
        title=title_str,
        confident=(status != "needs_followup"),
        claimed_grade=claimed_grade,
        assigned_grade=assigned_grade if (confirmed and not oral_required) else ("none" if assigned_grade == claimed_grade else assigned_grade),
        llr=llr,
        threshold_a=A,
        alpha=alpha,
        delta=delta,
        cut=cut,
        p_claimed=p_claim,
        n_scored=n_scored,
        code_open_count=code_open,
        code_open_share=co_share,
        followup_needed=followup_needed,
        followup_minutes=followup_minutes,
        followup_items=followup_items,
        followup_cut_grade=claimed_grade,
        explanation=expl,
        incident_stage=inc_norm,
        suspicious_flagged=susp_flagged,
        suspicious_reasons=tuple(susp_reasons),
        oral_defense_required=oral_required,
        integrity_followup=ifrel,
    )


# ---------------------------------------------------------------------------------------------------------------
# Инцидент «Полигона» как доп. этап у спорного порога Senior / Lead / Principal (решение владельца 21.10; интерфейс
# согласован с А9). Правило объединения записано заранее и объяснимо: инцидент — три независимые оцениваемые части
# (меры, код, обоснование), каждая — как практическое задание у порога проверяемого грейда с различающей силой
# INCIDENT_STAGE_A (априорная, как у практических заданий банка; на людях не откалибрована). Байесовское обновление
# оценки уровня из основной части (нормальное априорное N(θ̂, SE)) на сетке; итог — «подтверждён», если вероятность
# уровня не ниже проверяемого после обновления ≥ порога итога второго этапа (ASSESSMENT_TWO_STAGE_CONFIRM — то же
# правило, что у короткого второго этапа заданиями). Признаки обмана в инциденте (правило А6: 2+ сигнала или ловушка)
# → «нужна устная защита», не бан.
INCIDENT_GRADES: frozenset[str] = frozenset({"senior", "lead", "principal"})
INCIDENT_FOLLOWUP_MINUTES_DEFAULT: int = 30
INCIDENT_RULE_RU = ("Вклад практического этапа — по заранее записанному правилу (три части: меры, код, обоснование — "
                    "как три практических задания у порога); на людях ещё не откалиброван.")


def incident_for_direction(direction: str | None) -> dict | None:
    """Шаблон инцидента «Полигона» для направления (каталог А9, только чтение)."""
    if not direction:
        return None
    try:
        from app.modules.warroom.catalog import BASE_SCENARIOS
    except Exception:
        return None
    for scn in BASE_SCENARIOS:
        if scn.get("direction") == direction:
            return scn
    return None


def attach_incident_followup(verdict: dict | None, *, attempt_id: str, direction: str | None) -> dict | None:
    """П. 1 интерфейса: вердикт «нужен доп. этап» у порога Senior+ при наличии инцидента направления → доп. этап —
    инцидент «Полигона» (followup_kind="incident", followup_url). Иначе — как раньше: короткий блок заданий."""
    if not isinstance(verdict, dict) or verdict.get("status") != "needs_followup":
        return verdict
    v = dict(verdict)
    if v.get("oral_defense_required"):
        v.setdefault("followup_kind", "oral_defense")
        return v
    grade = v.get("followup_cut_grade") or v.get("claimed_grade")
    scn = incident_for_direction(direction) if grade in INCIDENT_GRADES else None
    if scn is None:
        v["followup_kind"] = "stage2"
        return v
    v.update(followup_kind="incident", followup_url=f"/warroom?followup={attempt_id}#architecture",
             followup_minutes=int(scn.get("minutes") or INCIDENT_FOLLOWUP_MINUTES_DEFAULT),
             followup_incident_id=scn.get("id"), followup_incident_title=scn.get("title"))
    return v


def _incident_parts(stage: dict) -> list[float]:
    parts = [stage.get(k) for k in ("measures_ok", "code_ok", "justification_ok")]
    if all(p is None for p in parts):
        sc = stage.get("score")
        return [float(np.clip(float(sc), 0.0, 1.0))] * 3 if sc is not None else []
    return [1.0 if bool(p) else 0.0 for p in parts if p is not None]


def _posterior_on_grid(theta: float, se: float, xs: list[float], a: float, cut: float) -> tuple[float, float, float]:
    grid = np.linspace(-5.0, 5.5, 421)
    logp = -0.5 * ((grid - theta) / max(se, 0.10)) ** 2
    pr = 1.0 / (1.0 + np.exp(-a * (grid - cut)))
    for x in xs:
        logp = logp + x * np.log(pr + 1e-12) + (1.0 - x) * np.log(1.0 - pr + 1e-12)
    w = np.exp(logp - logp.max())
    w /= w.sum()
    m = float((w * grid).sum())
    sd = float(math.sqrt(max(1e-9, (w * (grid - m) ** 2).sum())))
    p_ge = float(w[grid >= cut].sum())
    return m, sd, p_ge


def _incorporate_incident_verdict(verdict: dict, stage: dict) -> dict:
    from app.core.config import get_settings

    v = dict(verdict or {})
    st = dict(stage or {})
    grade = v.get("followup_cut_grade") or v.get("claimed_grade") or "senior"
    cut = float(GRADE_CUTS.get(grade, v.get("cut", 1.0)))
    theta = float(v.get("theta", cut) if v.get("theta") is not None else cut)
    se = float(v.get("se", 0.4) if v.get("se") is not None else 0.4)
    p0 = float(v.get("p_claimed") if v.get("p_claimed") is not None else 0.5)
    xs = _incident_parts(st)
    th1, se1, p1 = _posterior_on_grid(theta, se, xs, INCIDENT_STAGE_A, cut)
    level = float(get_settings().assessment_two_stage_confirm)
    integ = st.get("integrity") if isinstance(st.get("integrity"), dict) else {}
    ifrel = evaluate_integrity_followup(integ, None) if integ else {"needs_followup_stage": False}
    g_title = GRADE_RU.get(grade, grade)
    title_inc = st.get("title") or v.get("followup_incident_title") or "разбор инцидента"
    ok = lambda k: ("да" if st.get(k) else "нет") if st.get(k) is not None else "—"  # noqa: E731
    parts_ru = f"меры — {ok('measures_ok')}, код — {ok('code_ok')}, обоснование — {ok('justification_ok')}"
    if ifrel.get("needs_followup_stage"):
        status = "needs_followup"
        expl = (f"Нужна устная защита по уровню {g_title}: в практическом этапе «{title_inc}» есть признаки "
                "несамостоятельной работы. Автоматической блокировки нет — короткий разговор об этом решении снимет вопрос.")
    elif p1 >= level:
        status = "confirmed"
        expl = (f"Подтверждён: тест у порога {g_title} был спорным (вероятность {round(100 * p0)} %), практический этап "
                f"«{title_inc}»: {parts_ru}; итог по обоим этапам — {round(100 * p1)} % (решение — от "
                f"{round(100 * level)} %). {INCIDENT_RULE_RU}")
    else:
        status = "not_confirmed"
        expl = (f"Не подтверждён: тест у порога {g_title} был спорным (вероятность {round(100 * p0)} %), практический "
                f"этап «{title_inc}»: {parts_ru}; итог по обоим этапам — {round(100 * p1)} % (решение — от "
                f"{round(100 * level)} %). Принудительного понижения нет. {INCIDENT_RULE_RU}")
    title = VERDICT_TITLES["needs_oral_defense"] if status == "needs_followup" else VERDICT_TITLES[status]
    v.update(status=status, title=title, confident=status != "needs_followup", explanation=expl, explanation_ru=expl,
             p_before=round(p0, 4), p_claimed=round(p1, 4), theta_after=round(th1, 4), se_after=round(se1, 4),
             mode="refine", followup_needed=status == "needs_followup", followup_applied=True,
             oral_defense_required=status == "needs_followup", rule_ru=INCIDENT_RULE_RU,
             followup_kind="oral_defense" if status == "needs_followup" else None,
             incident_stage={"incident_id": st.get("incident_id"), "score": st.get("score"), "passed": st.get("passed"),
                             "measures_ok": st.get("measures_ok"), "code_ok": st.get("code_ok"),
                             "justification_ok": st.get("justification_ok"), "minutes": st.get("minutes"),
                             "attempt_id": st.get("attempt_id"), "parts_scored": xs,
                             "summary_ru": f"Практический этап «{title_inc}»: {parts_ru}.",
                             "integrity_followup": ifrel if integ else None})
    return v


def incorporate_incident_stage(*args, **kwargs):
    """Две формы (совместимость):
    - incorporate_incident_stage(verdict: dict, stage: dict) -> dict — итог доп. этапа-инцидента (интерфейс 21.10);
    - incorporate_incident_stage(theta, se, claimed_grade, incident) -> (θ, SE, ΔLLR, норм. словарь) — прежняя форма
      (предпросмотр «Полигона»), то же, что incident_theta_update."""
    if len(args) == 2 and isinstance(args[0], dict) and isinstance(args[1], dict):
        return _incorporate_incident_verdict(args[0], args[1])
    if "verdict" in kwargs and "stage" in kwargs:
        return _incorporate_incident_verdict(kwargs["verdict"], kwargs["stage"])
    return incident_theta_update(*args, **kwargs)
