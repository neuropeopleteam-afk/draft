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

from app.modules.assessment.grades import GRADE_RU, p_at_least
from app.modules.catalog.seed_data import GRADE_CUTS, GRADE_ORDER

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
    """Обеспечивает долю ≥ 1/3 кодовых и открытых заданий с автопроверкой в сессии.

    Если к шагу ``n_scored + 1`` доля выданных кодовых/открытых заданий отстаёт от ``target_share`` (например, каждое
    третье задание: позиции 3, 6, 9, 12, 15), и в доступном пуле ``cands`` есть задания форматов ``CODE_OPEN_FORMATS``,
    выбор ограничивается ими. Если таких заданий в пуле не осталось — возвращается исходный список ``cands``.
    """
    if not cands or target_share <= 0.0:
        return cands
    want_code = ((n_scored + 1) % 3 == 0) or (n_code_open < int(math.floor((n_scored + 1) * target_share)))
    if not want_code:
        return cands
    co = [i for i in cands if getattr(i, "format", None) in CODE_OPEN_FORMATS]
    return co if co else cands


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
            "n_scored": self.n_scored,
            "code_open_count": self.code_open_count,
            "code_open_share": round(self.code_open_share, 3),
            "followup": {
                "needed": self.followup_needed,
                "minutes": self.followup_minutes,
                "items": self.followup_items,
                "cut_grade": self.followup_cut_grade,
                "cut_grade_title": GRADE_RU.get(self.followup_cut_grade, self.followup_cut_grade),
                "cut": round(self.cut, 3),
                "incident_recommended": self.claimed_grade in SENIOR_PLUS_GRADES,
            },
            "explanation": self.explanation,
        }
        if self.incident_stage is not None:
            out["incident_stage"] = self.incident_stage
        return out


def incorporate_incident_stage(
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
) -> ThreeValuedVerdict:
    """Вычисляет статистику SPRT и трёхзначный вердикт по завершённым заданиям сессии (с учётом Боевого этапа А9)."""
    cut = float(GRADE_CUTS.get(claimed_grade, 0.0))
    A = sprt_bound(alpha)
    scored = [it for it in done_items if not it.get("canary") and it.get("done", True)]
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
    if incident_stage is not None:
        theta, se, llr_inc, inc_norm = incorporate_incident_stage(
            theta, se, claimed_grade, incident_stage, delta=delta
        )
        if inc_norm is not None:
            llr += llr_inc
            code_open += 1

    n_scored = len(scored) + (1 if (incident_stage is not None and inc_norm is not None) else 0)
    co_share = (code_open / n_scored) if n_scored > 0 else 0.0
    p_claim = float(p_at_least(theta, se, claimed_grade)) if claimed_grade in GRADE_CUTS else (1.0 if confirmed else 0.0)
    if inc_norm is not None and p_claim >= 0.60 and inc_norm.get("passed"):
        confirmed = True
        if assigned_grade in ("none", None):
            assigned_grade = claimed_grade

    # Трёхзначный вердикт:
    # - если это уже второй этап (mode == "refine" или "confirm") или пройден Боевой этап инцидента, решение окончательное;
    # - в основном тесте: если |LLR| < A и P(θ ≥ порога) лежит в пограничной полосе (1 − L; L), назначается 15-минутный доп. этап.
    in_grey_zone = (abs(llr) < A) and ((1.0 - boundary_level) < p_claim < boundary_level)
    if mode in ("refine", "confirm") or inc_norm is not None:
        status = "confirmed" if confirmed else "not_confirmed"
    elif in_grey_zone:
        status = "needs_followup"
    elif confirmed and (llr >= 0.0 or p_claim >= boundary_level):
        status = "confirmed"
    elif not confirmed and (llr <= 0.0 or p_claim <= (1.0 - boundary_level)):
        status = "not_confirmed"
    else:
        status = "needs_followup"

    followup_needed = status == "needs_followup"
    g_title = GRADE_RU.get(claimed_grade, claimed_grade)
    p_pct = round(100 * p_claim)
    if status == "confirmed":
        expl = (
            f"Вердикт: уровень {g_title} подтверждён с высокой статистической надёжностью "
            f"(вероятность соответствия {p_pct} %, индекс последовательного теста LLR = {llr:+.2f} при пороге ±{A:.2f})."
        )
    elif status == "needs_followup":
        inc_hint = (
            " Для старших уровней (Senior / Lead / Principal) дополнительный этап можно пройти на интерактивном симуляторе инцидента («Боевой этап»)."
            if claimed_grade in SENIOR_PLUS_GRADES else ""
        )
        expl = (
            f"Вердикт: нужен дополнительный этап у границы уровня {g_title} "
            f"(вероятность {p_pct} %, LLR = {llr:+.2f} внутри интервала [−{A:.2f}; +{A:.2f}]). "
            f"Чтобы исключить случайную ошибку у порога, пройдите короткий {DEFAULT_FOLLOWUP_MINUTES}-минутный "
            f"дополнительный этап (до {DEFAULT_FOLLOWUP_ITEMS} заданий) строго у этой границы.{inc_hint}"
        )
    else:
        expl = (
            f"Вердикт: заявленный уровень {g_title} не подтверждён "
            f"(вероятность соответствия {p_pct} %, LLR = {llr:+.2f}). "
            "Принудительного понижения категории нет; если доказан уровень ниже, его можно принять без нового теста."
        )
    if inc_norm is not None and inc_norm.get("summary_ru"):
        expl += " " + str(inc_norm["summary_ru"])

    return ThreeValuedVerdict(
        status=status,
        title=VERDICT_TITLES[status],
        confident=(status != "needs_followup"),
        claimed_grade=claimed_grade,
        assigned_grade=assigned_grade if confirmed else ("none" if assigned_grade == claimed_grade else assigned_grade),
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
        followup_minutes=DEFAULT_FOLLOWUP_MINUTES,
        followup_items=DEFAULT_FOLLOWUP_ITEMS,
        followup_cut_grade=claimed_grade,
        explanation=expl,
        incident_stage=inc_norm,
    )
