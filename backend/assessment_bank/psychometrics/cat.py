"""Адаптивный тест: выбор по максимуму информации, контроль экспозиции, ротация субпулов.

Единица выбора — семейство (вариант для показа выбирает слой выдачи, см. serving.py).
Информация семейства = сумма информаций его частей (у open_book_3step — три шага) с
маргинальным наклоном a_eff (разброс вариантов уменьшает информацию, см. hierarchical.py).

Ограничения при выборе:
* контентный баланс: доля общего блока ≈ common_share (остальное — направление);
* одно семейство — не более одного раза за тест; лимит времени теста;
* контроль частоты показа — метод Сympson — Hetter: выбранное по информации семейство
  показывается с вероятностью K_f, иначе берётся следующее; K_f калибруются симуляцией
  так, чтобы доля показов каждого семейства не превышала r_max;
* ротация субпулов: семейства разбиты на n_subpools субпулов, сессия получает активный
  субпул (по очереди/по дате); канарейки вставляются на фиксированные позиции и в θ
  не входят.

Остановка: SE(θ) ≤ se_target при n ≥ min_items, либо n = max_items, либо кончился пул
или время. Классификационное правило (``stop_rule="classification"``): сессия заканчивается
и тогда, когда грейд уже определён — ни один порог грейда не попадает в θ̂ ± z·SE
(доверительный интервал у порога, Kingsbury & Weiss, 1983; Eggen & Straetmans, 2000).

Дотестирование у порога (``ext_items > 0``): если после основной части ближайший к θ̂ порог
грейда лежит внутри θ̂ ± z·SE, тест продолжается короткими заданиями, выбранными по информации
в этом пороге (а не в θ̂), пока порог не окажется вне интервала, не наберётся ext_items заданий
или не кончится запас времени ext_time_s. Задания дотестирования берутся из всего банка
направления (субпул после основной части почти исчерпан), кроме семейств прошлой попытки
(``exclude_ext``) и субпулов на карантине (``blocked_subpools``).

Частичный балл (``partial_credit=True``, флаг ASSESSMENT_PARTIAL_CREDIT_ENABLED): части с развёрнутым ответом
(open_answer, текстовый шаг open_book_3step) входят в θ и в информацию при выборе по модели GPCM с баллом 0–4
(``gpcm.py``; балл = round(4 · оценка)); остальные части — 2PL, как без флага.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

import numpy as np

from . import gpcm
from .hierarchical import effective_a
from .irt import estimate_theta, prob


@dataclass
class PoolItem:
    family_id: str
    block: str                 # "common" или направление
    format: str
    grades: tuple[str, ...]
    canary: bool
    a: np.ndarray              # наклоны частей (для конкретного варианта)
    b: np.ndarray              # средние трудности частей
    sigma: np.ndarray          # разброс трудности вариантов по частям
    time_limit_s: float
    beta_time: float           # трудоёмкость (лог-секунды) для модели времени
    alpha_time: float = 1.5
    subpool: int = 0

    @property
    def a_eff(self) -> np.ndarray:
        return effective_a(self.a, self.sigma)

    def information(self, theta: float) -> float:
        p = prob(theta, self.a_eff, self.b)
        return float(np.sum(self.a_eff ** 2 * p * (1 - p)))

    @property
    def text_parts(self) -> list[int]:
        return gpcm.text_parts(self.format, len(self.b))

    def gpcm_part(self, j: int) -> tuple[float, np.ndarray]:
        """Параметры GPCM части j (a_g, ступени) из её 2PL (a_eff, b) — до калибровки на людях."""
        return gpcm.from_2pl(float(self.a_eff[j]), float(self.b[j]))

    def information_pc(self, theta: float) -> float:
        """Информация с частичным баллом: развёрнутые части — GPCM 0–4, остальные — 2PL."""
        tp = self.text_parts
        if not tp:
            return self.information(theta)
        a, b = self.a_eff, self.b
        p = prob(theta, a, b)
        info = a ** 2 * p * (1 - p)
        for j in tp:
            ag, steps = self.gpcm_part(j)
            info[j] = float(gpcm.information(float(theta), ag, steps))
        return float(np.sum(info))


def pool_from_specs(specs: Iterable, params: dict | None = None,
                    n_subpools: int = 1) -> list[PoolItem]:
    """Пул из YAML-спецификаций: по умолчанию — предкалибровка (prior_difficulty).

    params: {family_id: {"a": [...], "b": [...], "sigma": [...]}} — калиброванные значения.
    Субпулы назначаются внутри блока по возрастанию трудности (змейкой), чтобы каждый
    субпул покрывал весь диапазон трудности.
    """
    items: list[PoolItem] = []
    for s in specs:
        pr = s.prior_difficulty
        offsets = np.array(pr.step_offsets or [0.0], dtype=float)
        a = np.full(len(offsets), pr.a)
        b = pr.b + offsets
        sig = np.full(len(offsets), pr.sigma_variant)
        if params and s.family_id in params:
            p = params[s.family_id]
            a, b, sig = (np.asarray(p[k], dtype=float) for k in ("a", "b", "sigma"))
        items.append(PoolItem(s.family_id, s.block, s.format, tuple(s.target_grades), s.canary,
                              a, b, sig, float(s.time_limit_s),
                              float(np.log(0.45 * s.time_limit_s))))
    if n_subpools > 1:
        for block in sorted({i.block for i in items}):
            blk = sorted([i for i in items if i.block == block and not i.canary],
                         key=lambda i: float(np.mean(i.b)))
            for k, it in enumerate(blk):
                r = k % (2 * n_subpools)
                it.subpool = r if r < n_subpools else 2 * n_subpools - 1 - r
    return items


@dataclass
class CATConfig:
    min_items: int = 8
    max_items: int = 20
    se_target: float = 0.35
    common_share: float = 0.4
    canary_positions: tuple[int, ...] = (2, 6, 10)
    exposure: str = "sympson_hetter"     # sympson_hetter | none
    max_time_s: float = 5400.0
    start_theta: dict[str, float] = field(default_factory=lambda: {
        "junior": -0.5, "middle": 0.5, "senior": 1.3})
    estimator: str = "eap"
    prior_sd: float = 1.0
    # --- классификация по грейду (по умолчанию выключена: прежнее поведение)
    cuts: tuple[float, ...] = (-1.0, 0.0, 1.0)   # пороги грейдов на шкале θ (как GradeScale)
    stop_rule: str = "se"                 # se | classification
    classify_z: float = 1.0               # порог «определён», если |θ̂ − порог| ≥ z·SE
    select_at: str = "theta"              # theta | cut — информация в θ̂ или в неопределённом пороге
    cut_after: int = 4                    # select_at="cut": первые cut_after заданий — по θ̂
    time_weight: float = 0.0              # 0 — информация; 1 — информация на единицу ожидаемого времени
    ext_items: int = 0                    # дотестирование у порога: до ext_items заданий сверх основной части
    ext_time_s: float = 1200.0            # запас времени на дотестирование сверх max_time_s
    ext_item_time_s: float = 300.0        # в дотестировании — только задания с лимитом не больше этого
    ext_own_first: bool = False           # дотестирование: сначала свободные задания своего субпула (частота показа)
    partial_credit: bool = False          # развёрнутые части — GPCM 0–4 (ASSESSMENT_PARTIAL_CREDIT_ENABLED)
    partial_credit_select: bool = True    # при partial_credit: выбор задания по информации GPCM (False — по 2PL)


class ExposureControl:
    """Параметры Sympson — Hetter K_f и счётчики выбора/показа."""

    def __init__(self, r_max: float = 0.3, k: dict[str, float] | None = None):
        self.r_max = r_max
        self.k: dict[str, float] = dict(k or {})
        self.reset_counts()

    def reset_counts(self) -> None:
        self.selected: dict[str, int] = {}
        self.administered: dict[str, int] = {}
        self.n_sessions = 0

    def accept(self, fid: str, rng: np.random.Generator) -> bool:
        self.selected[fid] = self.selected.get(fid, 0) + 1
        return rng.random() < self.k.get(fid, 1.0)

    def update(self) -> None:
        """Шаг калибровки SH: K = r_max / P(S), если P(S) > r_max, иначе 1."""
        n = max(self.n_sessions, 1)
        for fid, s in self.selected.items():
            ps = s / n
            self.k[fid] = 1.0 if ps <= self.r_max else self.r_max / ps

    def exposure_rates(self) -> dict[str, float]:
        n = max(self.n_sessions, 1)
        return {f: c / n for f, c in self.administered.items()}


@dataclass
class Administered:
    family_id: str
    x: np.ndarray
    log_t: float | None
    canary: bool
    theta_before: float


@dataclass
class CATResult:
    theta: float
    se: float
    n_items: int
    n_canaries: int
    time_used_s: float
    stop_reason: str
    administered: list[Administered]
    trace: list[tuple[float, float]]


class CATSession:
    def __init__(self, pool: list[PoolItem], direction: str, config: CATConfig | None = None,
                 exposure: ExposureControl | None = None, claimed_grade: str = "middle",
                 subpool: int | None = None, rng: np.random.Generator | None = None, *,
                 exclude_ext: Iterable[str] = (), blocked_subpools: Iterable[int] = (),
                 exclude: Iterable[str] = ()):
        self.cfg = config or CATConfig()
        self.exposure = exposure
        self.rng = rng or np.random.default_rng()
        self.direction = direction
        self.claimed_grade = claimed_grade
        self.subpool = subpool
        everything = [i for i in pool if i.block in ("common", direction)]
        blocked, excl_main = set(blocked_subpools), set(exclude)
        eligible = everything
        if subpool is not None:
            eligible = [i for i in everything if i.canary or i.subpool == subpool]
        elif blocked:
            eligible = [i for i in everything if i.canary or i.subpool not in blocked]
        self.scored_pool = [i for i in eligible if not i.canary and i.family_id not in excl_main]
        self.canary_pool = [i for i in eligible if i.canary]
        excl = set(exclude_ext) | excl_main
        # пул дотестирования: весь банк направления, кроме семейств прошлой попытки и субпулов на карантине
        self.ext_pool = [i for i in everything if not i.canary and i.family_id not in excl
                         and (subpool is None or i.subpool == subpool or i.subpool not in blocked)]
        self.items: dict[str, PoolItem] = {i.family_id: i for i in everything}
        self.administered: list[Administered] = []
        self.used: set[str] = set()
        self.theta = self.cfg.start_theta.get(claimed_grade, 0.0)
        self.se = self.cfg.prior_sd
        self.time_used = 0.0
        self.trace: list[tuple[float, float]] = []
        self.stop_reason = ""
        # дотестирование: номер оцениваемого задания, с которого оно началось, порог и причина остановки основной части
        self.ext_start: int | None = None
        self.ext_cut: float | None = None
        self.ext_reason_before = ""
        if exposure is not None:
            exposure.n_sessions += 1

    # -- состояние
    @property
    def n_scored(self) -> int:
        return sum(1 for a in self.administered if not a.canary)

    @property
    def n_ext(self) -> int:
        return 0 if self.ext_start is None else self.n_scored - self.ext_start

    def _position(self) -> int:
        return len(self.administered) + 1

    # -- классификация относительно порогов грейда
    def uncertain_cuts(self, theta: float | None = None, se: float | None = None) -> list[float]:
        """Пороги внутри θ̂ ± z·SE (по ним грейд ещё не определён), от ближайшего к дальнему."""
        th = self.theta if theta is None else theta
        s = self.se if se is None else se
        z = self.cfg.classify_z
        return sorted((c for c in self.cfg.cuts if abs(th - c) < z * s), key=lambda c: abs(th - c))

    def grade_determined(self) -> bool:
        return not self.uncertain_cuts()

    def is_finished(self) -> bool:
        """Остановка основной части теста."""
        c = self.cfg
        n = self.n_scored
        if n >= c.max_items:
            self.stop_reason = "max_items"
            return True
        if n >= c.min_items and self.se <= c.se_target:
            self.stop_reason = "se_target"
            return True
        if n >= c.min_items and c.stop_rule == "classification" and self.grade_determined():
            self.stop_reason = "classified"
            return True
        if self.time_used >= c.max_time_s:
            self.stop_reason = "time"
            return True
        if not self._candidates():
            self.stop_reason = "pool_exhausted"
            return True
        return False

    def _candidates(self) -> list[PoolItem]:
        left = self.cfg.max_time_s - self.time_used
        return [i for i in self.scored_pool if i.family_id not in self.used
                and i.time_limit_s <= left]

    def _ext_candidates(self) -> list[PoolItem]:
        left = self.cfg.max_time_s + self.cfg.ext_time_s - self.time_used
        lim = min(left, self.cfg.ext_item_time_s)
        return [i for i in self.ext_pool if i.family_id not in self.used and i.time_limit_s <= lim]

    # -- выбор
    def _target(self) -> float:
        """Точка, в которой максимизируется информация задания в основной части."""
        if self.cfg.select_at == "cut" and self.n_scored >= self.cfg.cut_after:
            unc = self.uncertain_cuts()
            if unc:
                return unc[0]
        return self.theta

    def _score(self, item: PoolItem, target: float) -> float:
        pc = self.cfg.partial_credit and self.cfg.partial_credit_select
        info = item.information_pc(target) if pc else item.information(target)
        w = self.cfg.time_weight
        if w:
            info /= (np.exp(item.beta_time) / 120.0) ** w  # ожидаемое время ответа ∝ exp(β)
        return info

    def _pick(self, cands: list[PoolItem], target: float) -> PoolItem:
        cands = sorted(cands, key=lambda i: -self._score(i, target))
        if self.exposure is None or self.cfg.exposure == "none":
            return cands[0]
        for item in cands[:-1]:
            if self.exposure.accept(item.family_id, self.rng):
                return item
        self.exposure.accept(cands[-1].family_id, self.rng)
        return cands[-1]

    def next_item(self) -> PoolItem | None:
        if self.ext_start is None:
            if not self.is_finished():
                return self._next_main()
            if not self._start_extension():
                return None
        return self._next_extension()

    def _next_main(self) -> PoolItem:
        pos = self._position()
        if pos in self.cfg.canary_positions:
            free = [c for c in self.canary_pool if c.family_id not in self.used]
            if free:
                # канарейки по очереди: сначала общий блок, затем направление
                n_can = sum(1 for a in self.administered if a.canary)
                pref = [c for c in free if (c.block == "common") == (n_can % 2 == 0)] or free
                return pref[int(self.rng.integers(len(pref)))]
        cands = self._candidates()
        n_common = sum(1 for a in self.administered if not a.canary and
                       self._block(a.family_id) == "common")
        want_common = n_common < self.cfg.common_share * (self.n_scored + 1)
        blk = [i for i in cands if (i.block == "common") == want_common] or cands
        return self._pick(blk, self._target())

    def _start_extension(self) -> bool:
        """Начать дотестирование, если ближайший порог не определён и есть короткие задания."""
        if self.cfg.ext_items <= 0:
            return False
        unc = self.uncertain_cuts()
        if not unc or not self._ext_candidates():
            return False
        self.ext_start, self.ext_cut, self.ext_reason_before = self.n_scored, unc[0], self.stop_reason
        return True

    def _next_extension(self) -> PoolItem | None:
        if self.n_ext >= self.cfg.ext_items:
            self.stop_reason = "extension_done"
            return None
        unc = self.uncertain_cuts()
        if not unc:
            self.stop_reason = "extension_classified"
            return None
        cands = self._ext_candidates()
        if not cands:
            self.stop_reason = "extension_pool_exhausted"
            return None
        if self.cfg.ext_own_first and self.subpool is not None:
            cands = [i for i in cands if i.subpool == self.subpool] or cands
        return self._pick(cands, unc[0])

    def _block(self, fid: str) -> str:
        it = self.items.get(fid)
        return it.block if it is not None else "common"

    def record(self, item: PoolItem, x: Iterable[float], log_t: float | None = None,
               time_s: float | None = None) -> None:
        x = np.asarray(list(x), dtype=float)
        self.items.setdefault(item.family_id, item)
        self.administered.append(Administered(item.family_id, x, log_t, item.canary, self.theta))
        self.used.add(item.family_id)
        self.time_used += time_s if time_s is not None else item.time_limit_s
        if self.exposure is not None:
            self.exposure.administered[item.family_id] = \
                self.exposure.administered.get(item.family_id, 0) + 1
        if not item.canary:
            self._update_theta()

    def _scored_arrays(self, exclude: set[int] | None = None):
        xs, aa, bb = [], [], []
        for k, adm in enumerate(self.administered):
            if adm.canary:
                continue
            if exclude and k in exclude:
                continue
            it = self.items[adm.family_id]
            xs.append(adm.x)
            aa.append(it.a_eff)
            bb.append(it.b)
        if not xs:
            return np.array([]), np.array([]), np.array([])
        return np.concatenate(xs), np.concatenate(aa), np.concatenate(bb)

    def _pc_arrays(self, exclude: set[int] | None = None):
        """Частичный балл: дихотомические части (x, a, b) и развёрнутые [(балл 0–4, a_g, ступени)]."""
        xs, aa, bb, poly = [], [], [], []
        for k, adm in enumerate(self.administered):
            if adm.canary or (exclude and k in exclude):
                continue
            it = self.items[adm.family_id]
            tp = set(it.text_parts)
            a_eff = it.a_eff
            for j, v in enumerate(np.asarray(adm.x, dtype=float)):
                if j in tp:
                    if not np.isnan(v):
                        ag, steps = it.gpcm_part(j)
                        poly.append((gpcm.points(float(v)), ag, steps))
                    continue
                xs.append(v)
                aa.append(a_eff[j])
                bb.append(it.b[j])
        return np.asarray(xs, dtype=float), np.asarray(aa, dtype=float), np.asarray(bb, dtype=float), poly

    def _estimate(self, exclude: set[int] | None = None, prior_mean: float = 0.0, prior_sd: float | None = None):
        sd = self.cfg.prior_sd if prior_sd is None else prior_sd
        if self.cfg.partial_credit:
            x, a, b, poly = self._pc_arrays(exclude)
            return gpcm.estimate_theta_mixed(x, a, b, poly, prior_mean=prior_mean, prior_sd=sd)
        x, a, b = self._scored_arrays(exclude)
        return estimate_theta(x, a, b, method=self.cfg.estimator, prior_mean=prior_mean, prior_sd=sd)

    def _update_theta(self) -> None:
        est = self._estimate()
        self.theta, self.se = est.theta, est.se
        self.trace.append((self.theta, self.se))

    def rescore(self, exclude: set[int]) -> tuple[float, float]:
        """θ без части ответов (например, подозрительных по детектору предзнания)."""
        est = self._estimate(exclude)
        return est.theta, est.se

    def result(self) -> CATResult:
        return CATResult(self.theta, self.se, self.n_scored,
                         sum(1 for a in self.administered if a.canary), self.time_used,
                         self.stop_reason, list(self.administered), list(self.trace))


Responder = Callable[[PoolItem, np.random.Generator], tuple[np.ndarray, float]]


def run_cat(pool: list[PoolItem], direction: str, responder: Responder,
            config: CATConfig | None = None, exposure: ExposureControl | None = None,
            claimed_grade: str = "middle", subpool: int | None = None,
            rng: np.random.Generator | None = None) -> tuple[CATSession, CATResult]:
    """Провести один адаптивный тест с заданной функцией ответа (симуляция/демо)."""
    rng = rng or np.random.default_rng()
    sess = CATSession(pool, direction, config, exposure, claimed_grade, subpool, rng)
    while True:
        item = sess.next_item()
        if item is None:
            break
        x, log_t = responder(item, rng)
        sess.record(item, x, log_t, time_s=float(np.exp(log_t)) if log_t is not None else None)
    return sess, sess.result()


def calibrate_sympson_hetter(pool: list[PoolItem], direction: str, responder_factory,
                             config: CATConfig, r_max: float = 0.3, n_sessions: int = 400,
                             iterations: int = 6, seed: int = 0,
                             n_subpools: int | None = None) -> tuple[ExposureControl, list[float]]:
    """Итеративная калибровка K_f симуляцией (Sympson & Hetter, 1985)."""
    ctrl = ExposureControl(r_max=r_max)
    history = []
    rng = np.random.default_rng(seed)
    for _ in range(iterations):
        ctrl.reset_counts()
        for s in range(n_sessions):
            theta = float(rng.normal())
            sp = (s % n_subpools) if n_subpools else None
            run_cat(pool, direction, responder_factory(theta), config, ctrl, "middle", sp, rng)
        rates = ctrl.exposure_rates()
        history.append(max(rates.values()) if rates else 0.0)
        ctrl.update()
    return ctrl, history
