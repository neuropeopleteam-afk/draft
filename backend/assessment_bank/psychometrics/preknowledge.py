"""Детектор предзнания по канареечным заданиям: время ответа + правильность.

Канарейки — семейства, часть вариантов которых мы намеренно «сливаем» (опубликованы
seed 1..canary_pool_size); кандидату канарейка показывается только из опубликованных
вариантов, в грейд не входит. Честный кандидат решает её как обычное задание; читавший
утечку — заметно быстрее и чаще верно.

Модель времени — логнормальная (van der Linden, 2006):
    log T_ij = β_i − τ_j + ε / α_i,   ε ~ N(0, 1),
β_i — трудоёмкость задания (лог-секунды), α_i — точность, τ_j — скорость человека.

Статистика (в духе Sinharay, 2020 — сравнение скорости на скомпрометированных и чистых
заданиях) складывается из двух z:
* z_speed: насколько человек быстрее на канарейках, чем предсказывает его скорость τ̂,
  оценённая по чистым заданиям (с поправкой на ошибку τ̂);
* z_score: насколько он чаще верен на канарейках, чем предсказывает θ̂ по чистым заданиям.
combined = (z_speed + z_score) / √2; флаг — combined > порога и хотя бы одна канарейка
решена верно «аномально быстро». Порог калибруется на честной популяции под заданную
долю ложных срабатываний (по умолчанию 1 %), а не берётся «из нормального закона».
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import stats

DEFAULT_THRESHOLD = 2.33   # номинально ≈1 % ложных срабатываний при нормальности
FAST_Z = -1.645            # «аномально быстро»: остаток времени ниже 5-го процентиля


@dataclass
class TimedResponse:
    x: float          # балл 0..1 (для многошаговых — средний по шагам)
    log_t: float      # логарифм времени ответа, с
    beta: float       # трудоёмкость задания
    alpha: float      # точность модели времени
    p: float = 0.5    # ожидаемая вероятность верного ответа при θ̂ (для канареек)


def estimate_speed(log_t, beta, alpha) -> tuple[float, float]:
    log_t, beta, alpha = (np.asarray(v, dtype=float) for v in (log_t, beta, alpha))
    if log_t.size == 0:
        return 0.0, 1.0
    w = alpha ** 2
    tau = float(np.sum(w * (beta - log_t)) / np.sum(w))
    return tau, float(1 / np.sqrt(np.sum(w)))


def rt_residuals(log_t, beta, alpha, tau) -> np.ndarray:
    return np.asarray(alpha) * (np.asarray(log_t) - (np.asarray(beta) - tau))


def fit_lognormal_rt(logT: np.ndarray, n_iter: int = 50):
    """Калибровка модели времени по матрице log-времён (люди × задания, nan — пропуск)."""
    logT = np.asarray(logT, dtype=float)
    R = ~np.isnan(logT)
    L = np.nan_to_num(logT)
    tau = np.zeros(logT.shape[0])
    beta = np.nanmean(logT, axis=0)
    alpha = np.ones(logT.shape[1])
    for _ in range(n_iter):
        beta = np.sum(np.where(R, L + tau[:, None], 0), 0) / np.maximum(R.sum(0), 1)
        w = alpha[None, :] ** 2 * R
        tau = np.sum(w * (beta[None, :] - L), 1) / np.maximum(w.sum(1), 1e-9)
        tau -= tau.mean()
        resid = np.where(R, L - (beta[None, :] - tau[:, None]), np.nan)
        alpha = 1 / np.maximum(np.nanstd(resid, axis=0), 0.05)
    return beta, alpha, tau


@dataclass
class PreknowledgeResult:
    z_speed: float
    z_score: float
    combined: float
    flagged: bool
    n_canaries: int
    n_fast_correct: int
    tau_clean: float
    details: list[dict] = field(default_factory=list)


class CanaryDetector:
    def __init__(self, threshold: float = DEFAULT_THRESHOLD, fast_z: float = FAST_Z):
        self.threshold = threshold
        self.fast_z = fast_z

    def statistic(self, clean: list[TimedResponse], canary: list[TimedResponse]) -> PreknowledgeResult:
        tau, se_tau = estimate_speed([r.log_t for r in clean], [r.beta for r in clean],
                                     [r.alpha for r in clean])
        if not canary:
            return PreknowledgeResult(0.0, 0.0, 0.0, False, 0, 0, tau)
        z = []
        details = []
        n_fast_correct = 0
        for r in canary:
            zi = r.alpha * (r.log_t - (r.beta - tau)) / np.sqrt(1 + (r.alpha * se_tau) ** 2)
            z.append(zi)
            fast_correct = zi < self.fast_z and r.x >= 0.5
            n_fast_correct += int(fast_correct)
            details.append({"z_time": round(float(zi), 3), "x": r.x, "p": round(r.p, 3),
                            "fast_correct": bool(fast_correct)})
        z_speed = float(-np.sum(z) / np.sqrt(len(z)))
        xs = np.array([r.x for r in canary])
        ps = np.clip(np.array([r.p for r in canary]), 0.02, 0.98)
        z_score = float(np.sum(xs - ps) / np.sqrt(np.sum(ps * (1 - ps))))
        combined = (z_speed + z_score) / np.sqrt(2)
        flagged = bool(combined > self.threshold and n_fast_correct >= 1)
        return PreknowledgeResult(z_speed, z_score, float(combined), flagged, len(canary),
                                  n_fast_correct, tau, details)

    def suspicious_mask(self, responses: list[TimedResponse], tau: float) -> np.ndarray:
        """Ответы «верно и аномально быстро» — исключаются при пересчёте θ у флагнутых."""
        if not responses:
            return np.zeros(0, dtype=bool)
        z = rt_residuals([r.log_t for r in responses], [r.beta for r in responses],
                         [r.alpha for r in responses], tau)
        x = np.array([r.x for r in responses])
        return (z < self.fast_z) & (x >= 0.5)

    @staticmethod
    def calibrate_threshold(honest_combined: np.ndarray, fpr: float = 0.01) -> float:
        """Порог по честной (синтетической или пилотной) популяции под заданную долю FPR."""
        return float(np.quantile(np.asarray(honest_combined), 1 - fpr))


def nominal_fpr(threshold: float) -> float:
    return float(1 - stats.norm.cdf(threshold))
