"""Иерархический учёт семейств: параметры семейства + разброс трудности вариантов.

Модель «связанных близнецов» (related siblings, Glas & van der Linden, 2003):
вариант v семейства f имеет трудность b_v = μ_f + δ_v, δ_v ~ N(0, σ_f²), общий наклон a_f.
Для нового (ещё не виденного) варианта вероятность верного ответа — маргинальная по δ:

    P(θ) = ∫ σ(a(θ − μ − δ)) φ(δ; 0, σ²) dδ ≈ σ(a_eff (θ − μ)),
    a_eff = a / sqrt(1 + (a σ / 1,702)²)          (пробит-аппроксимация)

То есть разброс вариантов честно «съедает» дискриминативность: чем менее изоморфно
семейство, тем меньше информации даёт один его вариант. Семейства с большим σ
(по умолчанию > 0,5 логита) помечаются к пересмотру или разделению.

Оценка (двухэтапная, приближённая — это фиксируем в отчётах):
1. MML (Раш или 2PL) по столбцам «семейство-часть», объединяя варианты → a_marg, μ;
2. EAP θ людей; для каждого семейства — маргинальное правдоподобие σ по вариантам
   (квадратура Гаусса — Эрмита по δ) и де-аттенюация наклона; δ_v — апостериорные средние.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from scipy import optimize, special

from .irt import LOGIT_TO_PROBIT, eap_batch, fit_mml

NONISOMORPHIC_SIGMA = 0.5


def effective_a(a, sigma):
    a = np.asarray(a, dtype=float)
    return a / np.sqrt(1.0 + (a * np.asarray(sigma, dtype=float) / LOGIT_TO_PROBIT) ** 2)


def marginal_prob(theta, a, mu, sigma, n_quad: int = 21):
    """Точная (квадратурой) маргинальная вероятность верного ответа на новый вариант."""
    nodes, w = np.polynomial.hermite_e.hermegauss(n_quad)
    w = w / w.sum()
    theta = np.asarray(theta, dtype=float)
    z = a * (theta[..., None] - mu - sigma * nodes)
    return special.expit(z) @ w


@dataclass
class FamilyParams:
    item_id: str              # "family_id#part"
    a: float                  # наклон для конкретного варианта (де-аттенюированный)
    mu: float                 # средняя трудность семейства
    sigma: float              # разброс трудности вариантов
    a_marginal: float         # наклон для нового варианта (= effective_a)
    n_variants: int
    n_obs: int
    se_mu: float = float("nan")
    flag_nonisomorphic: bool = False
    source: str = "calibrated"


@dataclass
class HierarchyResult:
    families: dict[str, FamilyParams]
    variant_delta: dict[str, float] = field(default_factory=dict)
    model: str = "2pl"
    theta: np.ndarray | None = None
    converged: bool = True


def _sigma_mle(groups: list[tuple[np.ndarray, np.ndarray]], a: float, mu: float,
               n_quad: int = 21) -> float:
    """σ по маргинальному правдоподобию: groups — [(θ̂ людей, ответы)] по вариантам."""
    nodes, w = np.polynomial.hermite_e.hermegauss(n_quad)
    w = w / w.sum()

    def nll(sig):
        tot = 0.0
        for th, x in groups:
            p = np.clip(special.expit(a * (th[:, None] - mu - sig * nodes[None, :])), 1e-10,
                        1 - 1e-10)
            ll = (x[:, None] * np.log(p) + (1 - x[:, None]) * np.log1p(-p)).sum(0)
            m = ll.max()
            tot += m + np.log(np.dot(np.exp(ll - m), w))
        return -tot

    res = optimize.minimize_scalar(nll, bounds=(0.0, 2.0), method="bounded",
                                   options={"xatol": 1e-3})
    return float(res.x)


def fit_hierarchy(person: np.ndarray, item: np.ndarray, variant: np.ndarray, x: np.ndarray,
                  model: str = "2pl") -> HierarchyResult:
    """Калибровка по «длинной» таблице ответов: (человек, задание-часть, вариант, балл)."""
    person = np.asarray(person)
    item = np.asarray(item)
    variant = np.asarray(variant)
    x = np.asarray(x, dtype=float)
    pids, pidx = np.unique(person, return_inverse=True)
    iids, iidx = np.unique(item, return_inverse=True)
    X = np.full((len(pids), len(iids)), np.nan)
    X[pidx, iidx] = x
    cal = fit_mml(X, model=model, item_ids=list(iids))
    a_m = cal.a if model == "2pl" else np.ones(len(iids))
    th, _ = eap_batch(X, a_m, cal.b, prior_sd=cal.pop_sd if model == "rasch" else 1.0)
    fams: dict[str, FamilyParams] = {}
    deltas: dict[str, float] = {}
    by_item: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for k in range(len(x)):
        by_item[iidx[k]][str(variant[k])].append(k)
    nodes, w = np.polynomial.hermite_e.hermegauss(21)
    w = w / w.sum()
    for j, iid in enumerate(iids):
        groups_idx = by_item[j]
        groups = [(th[pidx[ks]], x[ks]) for ks in groups_idx.values()]
        a_cond, sig = float(a_m[j]), 0.0
        multi = [g for g in groups if len(g[1]) >= 2]
        if len(multi) >= 3:
            for _ in range(3):  # чередуем σ и де-аттенюацию наклона
                sig = _sigma_mle(multi, a_cond, float(cal.b[j]))
                if model == "2pl":
                    denom = 1 - (a_m[j] * sig / LOGIT_TO_PROBIT) ** 2
                    a_cond = float(a_m[j] / np.sqrt(max(denom, 0.25)))
        for vid, ks in groups_idx.items():
            thv, xv = th[pidx[ks]], x[ks]
            if sig <= 1e-6:
                deltas[f"{iid}@{vid}"] = 0.0
                continue
            d = sig * nodes
            p = np.clip(special.expit(a_cond * (thv[:, None] - cal.b[j] - d[None, :])), 1e-10,
                        1 - 1e-10)
            ll = (xv[:, None] * np.log(p) + (1 - xv[:, None]) * np.log1p(-p)).sum(0)
            post = np.exp(ll - ll.max()) * w
            deltas[f"{iid}@{vid}"] = float(np.dot(post, d) / post.sum())
        fams[str(iid)] = FamilyParams(
            item_id=str(iid), a=a_cond, mu=float(cal.b[j]), sigma=sig,
            a_marginal=float(effective_a(a_cond, sig)), n_variants=len(groups_idx),
            n_obs=int(cal.n_obs[j]), se_mu=float(cal.se_b[j]),
            flag_nonisomorphic=sig > NONISOMORPHIC_SIGMA)
    return HierarchyResult(families=fams, variant_delta=deltas, model=model, theta=th,
                           converged=cal.converged)
