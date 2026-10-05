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
или время.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

import numpy as np

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
                 subpool: int | None = None, rng: np.random.Generator | None = None):
        self.cfg = config or CATConfig()
        self.exposure = exposure
        self.rng = rng or np.random.default_rng()
        self.direction = direction
        eligible = [i for i in pool if i.block in ("common", direction)]
        if subpool is not None:
            eligible = [i for i in eligible if i.canary or i.subpool == subpool]
        self.scored_pool = [i for i in eligible if not i.canary]
        self.canary_pool = [i for i in eligible if i.canary]
        self.administered: list[Administered] = []
        self.used: set[str] = set()
        self.theta = self.cfg.start_theta.get(claimed_grade, 0.0)
        self.se = self.cfg.prior_sd
        self.time_used = 0.0
        self.trace: list[tuple[float, float]] = []
        self.stop_reason = ""
        if exposure is not None:
            exposure.n_sessions += 1

    # -- состояние
    @property
    def n_scored(self) -> int:
        return sum(1 for a in self.administered if not a.canary)

    def _position(self) -> int:
        return len(self.administered) + 1

    def is_finished(self) -> bool:
        c = self.cfg
        n = self.n_scored
        if n >= c.max_items:
            self.stop_reason = "max_items"
            return True
        if n >= c.min_items and self.se <= c.se_target:
            self.stop_reason = "se_target"
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

    # -- выбор
    def next_item(self) -> PoolItem | None:
        if self.is_finished():
            return None
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
        blk.sort(key=lambda i: -i.information(self.theta))
        if self.exposure is None or self.cfg.exposure == "none":
            return blk[0]
        for item in blk[:-1]:
            if self.exposure.accept(item.family_id, self.rng):
                return item
        self.exposure.accept(blk[-1].family_id, self.rng)
        return blk[-1]

    def _block(self, fid: str) -> str:
        for i in self.scored_pool:
            if i.family_id == fid:
                return i.block
        return "common"

    def record(self, item: PoolItem, x: Iterable[float], log_t: float | None = None,
               time_s: float | None = None) -> None:
        x = np.asarray(list(x), dtype=float)
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
        idx = 0
        lookup = {i.family_id: i for i in self.scored_pool}
        for k, adm in enumerate(self.administered):
            if adm.canary:
                continue
            if exclude and k in exclude:
                continue
            it = lookup[adm.family_id]
            xs.append(adm.x)
            aa.append(it.a_eff)
            bb.append(it.b)
            idx += 1
        if not xs:
            return np.array([]), np.array([]), np.array([])
        return np.concatenate(xs), np.concatenate(aa), np.concatenate(bb)

    def _update_theta(self) -> None:
        x, a, b = self._scored_arrays()
        est = estimate_theta(x, a, b, method=self.cfg.estimator, prior_sd=self.cfg.prior_sd)
        self.theta, self.se = est.theta, est.se
        self.trace.append((self.theta, self.se))

    def rescore(self, exclude: set[int]) -> tuple[float, float]:
        """θ без части ответов (например, подозрительных по детектору предзнания)."""
        x, a, b = self._scored_arrays(exclude)
        est = estimate_theta(x, a, b, method=self.cfg.estimator, prior_sd=self.cfg.prior_sd)
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
