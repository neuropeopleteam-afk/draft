"""Обобщённая модель частичного балла (GPCM, Muraki, 1992) для развёрнутых ответов с баллом 0–4.

Развёрнутый ответ (open_answer, текстовый шаг open_book_3step) оценивается по рубрике: оценки пунктов → взвешенная
сумма 0..1 → балл 0–4 (``points``). В модели 0/1 (2PL) часть задания даёт информацию a²·p·(1 − p) ≤ a²/4 при любом
балле; в GPCM балл k = 0..4 входит в правдоподобие своей категорией:

    P(X = k | θ) ∝ exp(Σ_{v ≤ k} a_g · (θ − δ_v)),  δ_v = b + d_v,

информация — a_g² · Var(X | θ) (больше, чем у 0/1, если промежуточные баллы встречаются).

Параметры GPCM без отдельной калибровки берутся из параметров части в 2PL (``from_2pl``): ступени d_v — шаблон
``OFFSETS`` вокруг трудности b, наклон a_g = r(a) · a подобран так, чтобы ожидаемая доля балла E[X]/4 совпадала с
кривой 2PL P(верно | θ) (наименьшие квадраты по θ ~ N(b; 1)). Тогда шкала θ та же, что у дихотомических заданий, а
дополнительная информация — только от различения промежуточных баллов. После калибровки на людях параметры
заменяются оценёнными.

Дихотомические части (и части с флагом выкл.) — по-прежнему 2PL с дробным баллом как «квазибиномиальным»
(``irt.estimate_theta``). Смешанная оценка θ — ``estimate_theta_mixed`` (EAP на той же сетке, что irt.GRID).
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy import optimize, special, stats

from .irt import GRID, ThetaEstimate

K = 4                                                  # баллы 0..K
OFFSETS = np.array([-0.75, -0.25, 0.25, 0.75])         # ступени вокруг трудности части (шаблон до калибровки)
TEXT_FORMATS = ("open_answer", "open_book_3step")


def text_parts(fmt: str, n_parts: int) -> list[int]:
    """Индексы частей с развёрнутым ответом: open_answer — единственная часть, open_book_3step — последний шаг."""
    if fmt == "open_answer":
        return list(range(n_parts))
    if fmt == "open_book_3step":
        return [n_parts - 1]
    return []


def points(score: float | None, k: int = K) -> int | None:
    """Балл 0–k из оценки 0..1: округление до ближайшего, половина — вверх (0,125 → 1, 0,375 → 2, 0,6667 → 3)."""
    if score is None or (isinstance(score, float) and np.isnan(score)):
        return None
    return int(min(k, max(0, np.floor(float(score) * k + 0.5 + 1e-9))))


def category_probs(theta, a: float, steps) -> np.ndarray:
    """P(X = k | θ), k = 0..K; theta скаляр → (K+1,), вектор → (len(theta), K+1)."""
    th = np.atleast_1d(np.asarray(theta, dtype=float))
    d = np.asarray(steps, dtype=float)
    z = np.concatenate([np.zeros((len(th), 1)), np.cumsum(a * (th[:, None] - d[None, :]), axis=1)], axis=1)
    z -= z.max(axis=1, keepdims=True)
    p = np.exp(z)
    p /= p.sum(axis=1, keepdims=True)
    return p[0] if np.ndim(theta) == 0 else p


def expected_score(theta, a: float, steps) -> np.ndarray:
    p = category_probs(theta, a, steps)
    return p @ np.arange(p.shape[-1])


def information(theta, a: float, steps):
    """Информация Фишера части GPCM: a² · Var(X | θ)."""
    p = category_probs(theta, a, steps)
    k = np.arange(p.shape[-1])
    m = p @ k
    return a * a * np.maximum(p @ (k * k) - m * m, 0.0)


@lru_cache(maxsize=4096)
def _ratio(a: float, offsets: tuple[float, ...]) -> float:
    """r: ожидаемая доля балла GPCM(r·a, b + d) ≈ 2PL(a, b) по θ ~ N(b; 1). Не зависит от b (сдвиг)."""
    th = np.linspace(-4.0, 4.0, 161)
    w = stats.norm.pdf(th)
    target = special.expit(a * th)
    d = np.asarray(offsets)

    def loss(r):
        return float(np.sum(w * (expected_score(th, r * a, d) / len(d) - target) ** 2))

    return float(optimize.minimize_scalar(loss, bounds=(0.05, 4.0), method="bounded", options={"xatol": 1e-4}).x)


def from_2pl(a: float, b: float, offsets=OFFSETS) -> tuple[float, np.ndarray]:
    """Параметры GPCM (a_g, ступени δ) для части с параметрами 2PL (a, b) — без отдельной калибровки."""
    off = tuple(round(float(v), 6) for v in np.asarray(offsets, dtype=float))
    a = round(float(a), 4)
    return _ratio(a, off) * a, float(b) + np.asarray(off)


def sample(theta: float, a: float, steps, rng: np.random.Generator) -> int:
    p = category_probs(float(theta), a, steps)
    return int(rng.choice(len(p), p=p))


def loglik_grid(k: int, a: float, steps, grid: np.ndarray = GRID) -> np.ndarray:
    p = np.clip(category_probs(grid, a, steps)[:, int(k)], 1e-300, 1.0)
    return np.log(p)


def estimate_theta_mixed(x, a, b, poly: list[tuple[int, float, np.ndarray]], prior_mean: float = 0.0,
                         prior_sd: float = 1.0, grid: np.ndarray = GRID) -> ThetaEstimate:
    """EAP по дихотомическим (2PL; x 0..1 или nan) и частям с частичным баллом poly = [(k, a_g, ступени), …]."""
    x = np.asarray(x, dtype=float)
    a = np.broadcast_to(np.asarray(a, dtype=float), x.shape)
    b = np.broadcast_to(np.asarray(b, dtype=float), x.shape)
    mask = ~np.isnan(x)
    n = int(mask.sum()) + len(poly)
    if n == 0:
        return ThetaEstimate(prior_mean, prior_sd, "eap", 0)
    lp = stats.norm.logpdf(grid, prior_mean, prior_sd)
    if mask.any():
        xm, am, bm = x[mask], a[mask], b[mask]
        p = np.clip(special.expit(am[None, :] * (grid[:, None] - bm[None, :])), 1e-12, 1 - 1e-12)
        lp = lp + (xm * np.log(p) + (1.0 - xm) * np.log1p(-p)).sum(axis=1)
    for k, ag, steps in poly:
        lp = lp + loglik_grid(k, ag, steps, grid)
    w = np.exp(lp - lp.max())
    w /= w.sum()
    m = float(np.dot(w, grid))
    sd = float(np.sqrt(max(np.dot(w, (grid - m) ** 2), 0.0)))
    return ThetaEstimate(m, sd, "eap", n)
