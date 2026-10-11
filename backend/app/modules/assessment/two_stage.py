"""Двухэтапное подтверждение уровня у границы (флаг ASSESSMENT_TWO_STAGE_ENABLED, по умолчанию выключен).

Одна сессия теста (≤ 60 мин) заканчивается с погрешностью SE ≈ 0,33–0,40: у кандидатов, чей уровень близко к порогу,
решение по одной сессии — почти монетка (docs/validation/GRADE_ACCURACY.md: потолок одной сессии ≈ 65–74 % точных
попаданий). Двухэтапная схема: после основного теста кандидату «на границе» предлагается **уточнение уровня** —
отдельная короткая сессия (10–15 мин) только из заданий у этой границы, из других семейств (без повторов прошлых сессий,
с контролем частоты показа). Итог считается по ответам обеих сессий вместе (одна общая апостериорная оценка θ), а не
по второй сессии отдельно.

Правила (общие для продукта и симуляции ``app.modules.validation.two_stage``; значения — настройки, выбраны на симуляции):

* **«На границе»** (``boundary``): после сессии с заявленным грейдом c итог g (подтверждён c, принят уровень ниже,
  «предварительно» или без категории), оценка θ̂ ± SE. Рассматриваются пороги уровней от g (от Стажёра, если категории
  нет) до c включительно. Граница есть, если у одного из них P(θ ≥ порога) лежит строго между 1 − L и L
  (L = ``assessment_two_stage_level``; то же, что |θ̂ − порог| < z_L · SE, z_L = Φ⁻¹(L)) — берётся порог с
  вероятностью, ближайшей к 0,5: «keep» — уровень итога под вопросом, «up» — возможно, уровень выше итога (до заявленного).
  Режим «выше заявленного» (``above`` > 0): если на заявленном уровне границы нет и у порога уровня выше заявленного
  P ≥ ``above`` — граница «above» у наивысшего такого порога (тест на заявленный грейд выше его не поднимает).
* **До уточнения** уровень — по первой сессии (не выше, чем позволяет она), с пометкой «на границе: можно уточнить».
* **Вторая сессия** (``RefineSession``): ответы первой сессии перенесены (в θ и в детектор предзнания, заново не
  показываются); новые задания — короткие (лимит ≤ 5 мин), с наибольшей информацией в выбранном пороге, семейства
  прошлых сессий исключены, частота показа — Sympson — Hetter как в основном тесте. Не больше N заданий
  (``assessment_two_stage_items``) и M минут (``assessment_two_stage_minutes``); досрочный стоп, когда после
  ``MIN_NEW`` заданий порог вышел из θ̂ ± z_L · SE.
* **Итог** (``final_grade``): наивысший уровень, доказанный общей оценкой обеих сессий: до заявленного включительно —
  с P ≥ c₂ (``assessment_two_stage_confirm``), выше заявленного — с P ≥ c↑ (``assessment_two_stage_confirm_up``,
  строже: повышение без запаса даёт завышение). Итог может быть и ниже уровня первой сессии, если общая оценка его не
  держит. Уровень — только по тесту (FTT.4).

Всё, что проверено, — на синтетике (модель, не люди): docs/validation/TWO_STAGE.md.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from assessment_bank.psychometrics import PoolItem

from app.modules.assessment.exposure import AppCATSession
from app.modules.assessment.grades import p_at_least
from app.modules.catalog.seed_data import GRADE_CUTS, GRADE_ORDER

# Значения по умолчанию — выбор на симуляции (docs/validation/TWO_STAGE.md); настройки — app.core.config
DEFAULT_LEVEL = 0.8
DEFAULT_ITEMS = 8
DEFAULT_MINUTES = 15
DEFAULT_CONFIRM = 0.6
DEFAULT_CONFIRM_UP = 0.9
DEFAULT_ABOVE = 0.0    # 0 — уточнение «выше заявленного» не предлагается
MIN_NEW = 3            # не меньше 3 новых заданий: подтверждение — новыми ответами, а не одной первой сессией
ITEM_TIME_S = 300.0    # только короткие задания (как дотестирование у порога)


def _z(level: float) -> float:
    """Φ⁻¹(level) без scipy (бисекция по erf): уровень 0,5–0,999."""
    lo, hi = 0.0, 6.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < level:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _rank(grade: str) -> int:
    return -1 if grade in (None, "none") else GRADE_ORDER.index(grade)


@dataclass(frozen=True)
class Boundary:
    grade: str          # уровень первой сессии
    cut_grade: str      # грейд, порог которого уточняется (граница «ниже cut_grade / cut_grade»)
    cut: float          # порог на шкале θ
    p: float            # P(θ ≥ порога) по первой сессии
    kind: str           # up — возможно, уровень выше; keep — уровень первой сессии под вопросом; above — выше уже вероятен

    @property
    def lower(self) -> str:
        i = GRADE_ORDER.index(self.cut_grade)
        return GRADE_ORDER[i - 1] if i > 0 else "none"

    def as_dict(self) -> dict:
        return {"grade": self.grade, "cut_grade": self.cut_grade, "lower": self.lower, "cut": self.cut,
                "p": round(self.p, 4), "kind": self.kind}


def boundary(theta: float | None, se: float | None, grade: str | None, claimed: str | None = None,
             level: float = DEFAULT_LEVEL, above: float = DEFAULT_ABOVE) -> Boundary | None:
    """Граница для уточнения после сессии с заявленным грейдом ``claimed`` и итогом ``grade`` (см. описание модуля)
    или None — уточнять нечего. claimed None — заявленный = итог."""
    if theta is None or se is None:
        return None
    theta, se, grade = float(theta), max(float(se), 1e-6), grade or "none"
    claimed = claimed if claimed in GRADE_ORDER else (grade if grade in GRADE_ORDER else GRADE_ORDER[0])
    lo, hi = max(_rank(grade), 0), _rank(claimed)
    rel = GRADE_ORDER[min(lo, hi):max(lo, hi) + 1]
    probs = {g: p_at_least(theta, se, g) for g in rel}
    band = [g for g in rel if 1 - level < probs[g] < level]
    if band:
        g = min(band, key=lambda x: (abs(probs[x] - 0.5), -_rank(x)))
        kind = "keep" if _rank(g) <= _rank(grade) else "up"
        return Boundary(grade, g, float(GRADE_CUTS[g]), probs[g], kind)
    if above > 0 and _rank(grade) >= _rank(claimed):
        ups = [g for g in GRADE_ORDER if _rank(g) > _rank(claimed) and p_at_least(theta, se, g) >= above]
        if ups:
            g = ups[-1]
            return Boundary(grade, g, float(GRADE_CUTS[g]), p_at_least(theta, se, g), "above")
    return None


def final_grade(theta: float, se: float, claimed: str | None = None, confirm: float = DEFAULT_CONFIRM,
                confirm_up: float = DEFAULT_CONFIRM_UP) -> str:
    """Итог по общей оценке обеих сессий: наивысший уровень с P(θ ≥ порога) ≥ confirm (до заявленного включительно)
    или ≥ confirm_up (выше заявленного). Без потолка длины: вторая сессия добавляет задания к первой."""
    cr = _rank(claimed) if claimed in GRADE_ORDER else len(GRADE_ORDER)
    out = "none"
    for i, g in enumerate(GRADE_ORDER):
        if p_at_least(float(theta), float(se), g) >= (confirm if i <= cr else confirm_up):
            out = g
    return out


def stop_z(level: float) -> float:
    return _z(level)


class RefineSession(AppCATSession):
    """Вторая сессия: перенесённые ответы первой (``record_prior``) + короткие задания у порога ``cut``.

    Выбор — ``CATSession._pick`` по информации в пороге (контроль частоты показа), кандидаты —
    ``AppCATSession._ext_candidates`` (короткие задания всего банка направления без семейств первой сессии, лимиты
    форматов, при исчерпании — давно виденные из прошлых попыток с новым вариантом). Лимит времени — от начала второй
    сессии: cfg.max_time_s = время первой, cfg.ext_time_s = минуты второй.
    """

    def __init__(self, *args, cut: float, n_new: int, min_new: int = MIN_NEW, z_stop: float = 1.28, **kwargs):
        kwargs.setdefault("ext_lru", True)
        super().__init__(*args, **kwargs)
        self.cut, self.n_new_max, self.min_new, self.z_stop = float(cut), int(n_new), int(min_new), float(z_stop)
        self.n_prior = 0
        self.ext_start = 0
        self.ext_cut = self.cut

    def record_prior(self, adms, items: dict[str, PoolItem], time_s: float) -> None:
        """Ответы первой сессии без пересчёта θ на каждом шаге (итог тот же: одна EAP по всем ответам)."""
        for adm in adms:
            self.items.setdefault(adm.family_id, items[adm.family_id])
            self.administered.append(adm)
            self.used.add(adm.family_id)
        self.time_used = float(time_s)
        self.n_prior = self.n_scored
        self.ext_start = self.n_prior
        if self.n_prior:
            self._update_theta()

    @property
    def n_new(self) -> int:
        return self.n_scored - self.n_prior

    def next_item(self) -> PoolItem | None:
        if self.n_new >= self.n_new_max:
            self.stop_reason = "refine_done"
            return None
        if self.n_new >= self.min_new and abs(self.theta - self.cut) >= self.z_stop * self.se:
            self.stop_reason = "refine_classified"
            return None
        cands = self._ext_candidates()
        if not cands:
            self.stop_reason = "refine_pool_exhausted" if self.n_new else "refine_no_items"
            return None
        if self.cfg.ext_own_first and self.subpool is not None:
            cands = [i for i in cands if i.subpool == self.subpool] or cands
        return self._pick(cands, self.cut)

