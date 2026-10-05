"""Модели Раша и 2PL: вероятность ответа, информация, оценка θ и калибровка заданий.

Шкала: логистическая (без множителя 1,7), θ ~ N(0, 1) в популяции калибровки.

* :func:`estimate_theta` — EAP (по умолчанию), MAP или MLE с SE; пропуски — ``nan``;
  допускаются дробные баллы 0..1 (например, оценка шага по рубрике), они входят в
  правдоподобие как «квазибиномиальные».
* :func:`fit_mml` — маргинальное максимальное правдоподобие (EM Бока — Эйткин) по матрице
  ответов с пропусками (адаптивный тест даёт разреженную матрицу). Для 2PL — слабые
  априорные распределения (log a ~ N(0, 0,5²), b ~ N(0, 2²)), то есть по сути байесовская
  модальная оценка: при малых выборках это стабилизирует параметры.
* :func:`item_fit` — infit/outfit (Раш), точечно-бисериальная корреляция с остатком теста.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import optimize, special, stats

GRID = np.linspace(-5.0, 5.0, 121)
LOGIT_TO_PROBIT = 1.702


def prob(theta, a, b):
    """P(x=1 | θ) для 2PL; theta скаляр → (n_items,), вектор → (len(theta), n_items)."""
    theta = np.asarray(theta, dtype=float)
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if theta.ndim == 0:
        return special.expit(a * (theta - b))
    return special.expit(a * (theta[:, None] - b[None, :]))


def item_information(theta, a, b):
    p = prob(theta, a, b)
    return np.asarray(a, dtype=float) ** 2 * p * (1.0 - p)


def test_information(theta, a, b) -> float:
    return float(np.sum(item_information(theta, a, b)))


@dataclass
class ThetaEstimate:
    theta: float
    se: float
    method: str
    n: int


def _loglik_grid(x, a, b, grid):
    p = np.clip(prob(grid, a, b), 1e-12, 1 - 1e-12)
    return (x * np.log(p) + (1.0 - x) * np.log1p(-p)).sum(axis=1)


def estimate_theta(x, a, b, method: str = "eap", prior_mean: float = 0.0,
                   prior_sd: float = 1.0, grid: np.ndarray = GRID) -> ThetaEstimate:
    """Оценка способности по ответам x (0..1 или nan) на задания с параметрами a, b."""
    x = np.asarray(x, dtype=float)
    a = np.broadcast_to(np.asarray(a, dtype=float), x.shape)
    b = np.broadcast_to(np.asarray(b, dtype=float), x.shape)
    mask = ~np.isnan(x)
    n = int(mask.sum())
    if n == 0:
        return ThetaEstimate(prior_mean, prior_sd, method, 0)
    x, a, b = x[mask], a[mask], b[mask]
    if method == "eap":
        lp = _loglik_grid(x, a, b, grid) + stats.norm.logpdf(grid, prior_mean, prior_sd)
        w = np.exp(lp - lp.max())
        w /= w.sum()
        m = float(np.dot(w, grid))
        sd = float(np.sqrt(np.dot(w, (grid - m) ** 2)))
        return ThetaEstimate(m, sd, "eap", n)
    if method == "map":
        th = prior_mean
        for _ in range(50):
            p = special.expit(a * (th - b))
            grad = np.sum(a * (x - p)) - (th - prior_mean) / prior_sd ** 2
            info = np.sum(a ** 2 * p * (1 - p)) + 1.0 / prior_sd ** 2
            step = grad / info
            th = float(np.clip(th + step, -6, 6))
            if abs(step) < 1e-6:
                break
        p = special.expit(a * (th - b))
        return ThetaEstimate(th, float(1 / np.sqrt(np.sum(a ** 2 * p * (1 - p)) + 1 / prior_sd ** 2)),
                             "map", n)
    if method == "mle":
        def nll(t):
            p = np.clip(special.expit(a * (t - b)), 1e-12, 1 - 1e-12)
            return -np.sum(x * np.log(p) + (1 - x) * np.log1p(-p))
        res = optimize.minimize_scalar(nll, bounds=(-5, 5), method="bounded")
        th = float(res.x)
        info = float(np.sum(item_information(th, a, b)))
        return ThetaEstimate(th, float(1 / np.sqrt(max(info, 1e-9))), "mle", n)
    raise ValueError(f"неизвестный метод {method}")


def eap_batch(X: np.ndarray, a, b, prior_sd: float = 1.0, grid: np.ndarray = GRID):
    """EAP и апостериорное SD для матрицы ответов (N, J) с пропусками nan."""
    X = np.asarray(X, dtype=float)
    R = ~np.isnan(X)
    X0 = np.nan_to_num(X)
    p = np.clip(prob(grid, a, b), 1e-12, 1 - 1e-12)  # (G, J)
    ll = X0 @ np.log(p).T + (R - X0) @ np.log1p(-p).T  # (N, G)
    ll += stats.norm.logpdf(grid, 0, prior_sd)[None, :]
    w = np.exp(ll - ll.max(axis=1, keepdims=True))
    w /= w.sum(axis=1, keepdims=True)
    m = w @ grid
    sd = np.sqrt(np.maximum(w @ grid ** 2 - m ** 2, 0))
    return m, sd


# --------------------------------------------------------------------------- калибровка
@dataclass
class CalibrationResult:
    model: str
    a: np.ndarray
    b: np.ndarray
    se_a: np.ndarray
    se_b: np.ndarray
    pop_sd: float
    n_iter: int
    converged: bool
    loglik: float
    n_obs: np.ndarray
    item_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"model": self.model, "pop_sd": self.pop_sd, "n_iter": self.n_iter,
                "converged": self.converged, "loglik": self.loglik,
                "items": [{"id": i, "a": float(a), "b": float(b), "se_a": float(sa),
                           "se_b": float(sb), "n": int(n)} for i, a, b, sa, sb, n in
                          zip(self.item_ids or range(len(self.a)), self.a, self.b, self.se_a,
                              self.se_b, self.n_obs)]}


def _quadrature(n_quad: int):
    nodes, weights = np.polynomial.hermite_e.hermegauss(n_quad)
    return nodes, weights / weights.sum()


def fit_mml(X: np.ndarray, model: str = "2pl", n_quad: int = 41, max_iter: int = 500,
            tol: float = 1e-4, prior_b_sd: float = 2.0, prior_loga_sd: float = 0.5,
            item_ids: list[str] | None = None) -> CalibrationResult:
    """Калибровка Раша (a ≡ 1, σ_θ оценивается) или 2PL (θ ~ N(0,1)) методом EM.

    X — матрица (люди × задания), значения 0/1 (или доли 0..1), пропуски — nan.
    """
    if model not in ("rasch", "2pl"):
        raise ValueError("model: rasch | 2pl")
    X = np.asarray(X, dtype=float)
    R = (~np.isnan(X)).astype(float)
    X0 = np.nan_to_num(X)
    N, J = X.shape
    n_obs = R.sum(axis=0)
    if np.any(n_obs == 0):
        raise ValueError("есть задания без ответов")
    nodes, w = _quadrature(n_quad)
    pv = np.clip((X0.sum(0) + 0.5) / (n_obs + 1.0), 0.02, 0.98)
    a = np.ones(J)
    b = -special.logit(pv) * (1.0 if model == "rasch" else 0.8)
    pop_sd = 1.0
    converged, it, ll_total = False, 0, -np.inf
    for it in range(1, max_iter + 1):
        q = nodes * pop_sd if model == "rasch" else nodes
        p = np.clip(special.expit(a[None, :] * (q[:, None] - b[None, :])), 1e-10, 1 - 1e-10)
        logl = X0 @ np.log(p).T + (R - X0) @ np.log1p(-p).T + np.log(w)[None, :]  # (N, Q)
        mx = logl.max(axis=1, keepdims=True)
        post = np.exp(logl - mx)
        sums = post.sum(axis=1, keepdims=True)
        ll_total = float(np.sum(np.log(sums) + mx))
        post /= sums
        nq = post.T @ R    # (Q, J)
        rq = post.T @ X0   # (Q, J)
        a_old, b_old, sd_old = a.copy(), b.copy(), pop_sd
        for _ in range(8):  # скоринг Фишера для всех заданий сразу
            pq = np.clip(special.expit(a[None, :] * (q[:, None] - b[None, :])), 1e-10, 1 - 1e-10)
            resid = rq - nq * pq
            wq = nq * pq * (1 - pq)
            if model == "rasch":
                g_b = -np.sum(resid, axis=0) - b / prior_b_sd ** 2
                h_bb = np.sum(wq, axis=0) + 1 / prior_b_sd ** 2
                b = np.clip(b + g_b / h_bb, -6, 6)
                continue
            d = q[:, None] - b[None, :]
            g_a = np.sum(resid * d, axis=0) - (np.log(a) / prior_loga_sd ** 2 + 1) / a
            g_b = -a * np.sum(resid, axis=0) - b / prior_b_sd ** 2
            h_aa = np.sum(wq * d * d, axis=0) + 1 / (prior_loga_sd ** 2 * a ** 2)
            h_bb = a ** 2 * np.sum(wq, axis=0) + 1 / prior_b_sd ** 2
            h_ab = -a * np.sum(wq * d, axis=0)
            det = h_aa * h_bb - h_ab ** 2
            det = np.where(np.abs(det) < 1e-10, 1e-10, det)
            da = (h_bb * g_a - h_ab * g_b) / det
            db = (h_aa * g_b - h_ab * g_a) / det
            a = np.clip(a + np.clip(da, -0.5, 0.5), 0.15, 4.0)
            b = np.clip(b + np.clip(db, -1.0, 1.0), -6, 6)
        if model == "rasch":
            # σ_θ: апостериорный второй момент (среднее θ закреплено в 0)
            m2 = float(np.sum(post * (nodes[None, :] * pop_sd) ** 2) / N)
            pop_sd = float(np.clip(np.sqrt(m2), 0.2, 4.0))
        delta = max(np.max(np.abs(a - a_old)), np.max(np.abs(b - b_old)), abs(pop_sd - sd_old))
        if delta < tol:
            converged = True
            break
    # приближённые SE (информация полных данных на последнем шаге)
    q = nodes * pop_sd if model == "rasch" else nodes
    pq = special.expit(a[None, :] * (q[:, None] - b[None, :]))
    wq = nq * pq * (1 - pq)
    if model == "rasch":
        se_b = 1 / np.sqrt(np.sum(wq, axis=0) + 1 / prior_b_sd ** 2)
        se_a = np.zeros(J)
    else:
        d = q[:, None] - b[None, :]
        h_aa = np.sum(wq * d * d, axis=0) + 1 / (prior_loga_sd ** 2 * a ** 2)
        h_bb = a ** 2 * np.sum(wq, axis=0) + 1 / prior_b_sd ** 2
        h_ab = -a * np.sum(wq * d, axis=0)
        det = np.maximum(h_aa * h_bb - h_ab ** 2, 1e-10)
        se_a, se_b = np.sqrt(h_bb / det), np.sqrt(h_aa / det)
    return CalibrationResult(model, a, b, se_a, se_b, pop_sd, it, converged, ll_total, n_obs,
                             list(item_ids) if item_ids else [])


def item_fit(X: np.ndarray, theta: np.ndarray, a, b) -> dict[str, np.ndarray]:
    """Infit/outfit MNSQ и точечно-бисериальная корреляция задания с остатком теста."""
    X = np.asarray(X, dtype=float)
    R = ~np.isnan(X)
    p = prob(theta, a, b)
    var = p * (1 - p)
    resid = np.where(R, np.nan_to_num(X) - p, 0.0)
    z2 = np.where(R, resid ** 2 / np.maximum(var, 1e-9), 0.0)
    nobs = np.maximum(R.sum(0), 1)
    outfit = z2.sum(0) / nobs
    infit = (resid ** 2).sum(0) / np.maximum(np.where(R, var, 0).sum(0), 1e-9)
    total = np.nansum(X, axis=1)
    pbis = np.full(X.shape[1], np.nan)
    for j in range(X.shape[1]):
        m = R[:, j]
        if m.sum() > 5:
            rest = total[m] - X[m, j]
            xj = X[m, j]
            if np.std(xj) > 0 and np.std(rest) > 0:
                pbis[j] = float(np.corrcoef(xj, rest)[0, 1])
    return {"infit": infit, "outfit": outfit, "point_biserial": pbis}
