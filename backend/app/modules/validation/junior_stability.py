"""Стабильность статуса «Junior (предварительно)» на симуляции теста платформы (строительные блоки — sim.py).

Вопрос: что меняет статус «предварительно» у порога Junior по сравнению с жёстким правилом «подтверждён / нет»
при одном и том же тесте и одних и тех же людях. Для каждого направления:

* популяция θ ~ N(0, 1) (``make_population``), заявленный грейд — по θ с шумом, «ниже Junior» заявляют Junior;
  истинные параметры заданий = предкалибровка + ошибка эксперта σ = 0,5 (как на /validation);
* сессия — текущая механика платформы (``app_config_from_settings``: классификационная остановка, дотестирование
  у ближайшего порога) и, для сравнения, механика до 06.10 без дотестирования (``LEGACY_SIM``);
* решение по тем же θ̂ и SE: «до» — ``decide`` без предварительного статуса (подтверждён от P = 0,8, иначе отказ);
  «после» — ``decide(provisional_level = 0,10)``: подтверждён / предварительно / отказ;
* подтверждение «предварительно» — короткое дотестирование у порога Junior как в продукте (``_start_confirm``):
  ответы прошлой сессии переносятся в θ, затем до ext_items коротких заданий всего банка направления, кроме уже
  показанных семейств; до CONFIRM_ATTEMPTS попыток; доказанное «ниже» статус не снимает (решение владельца 07.10).

Метрики — по заявившим Junior: доля предварительных; ложные предварительные (истинный θ < −1); ложные отказы
(истинный θ ≥ −1, категории нет) до и после; ложные подтверждения; что остаётся после дотестирования.
Всё синтетическое: проверяется правило решения, а не качество заданий на людях. Запуск: ``make stability``
(или ``python -m app.modules.validation.junior_stability``), результат — data/junior_stability.json → /validation.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import numpy as np

from assessment_bank.psychometrics import CATConfig, ExposureControl, decide
from assessment_bank.psychometrics.grading import PROVISIONAL_LEVEL
from assessment_bank.simulation import make_population, make_responder, make_truth

from app.modules.assessment.exposure import AppCATSession, exposure_table
from app.modules.assessment.provisional import CONFIRM_ATTEMPTS, CONFIRM_LEVEL
from app.modules.validation import sim

OUT = Path(__file__).resolve().parent / "data" / "junior_stability.json"
SEED = 20261007
JUNIOR_CUT = -1.0


def _rng(*parts: int) -> np.random.Generator:
    return np.random.default_rng([SEED, *parts])


def _run_people(pool, truth, people, direction, cfg, rng, k) -> list[tuple[AppCATSession, object]]:
    """Как sim.run_population, но возвращает сессии (нужны ответы для переноса в дотестирование)."""
    out = []
    counter = ExposureControl(0.3, k=dict(k or {}))
    for p in people:
        sp = int(rng.integers(cfg.subpools)) if cfg.subpools > 1 else None
        out.append(sim.run_session(pool, direction, make_responder(p, truth, None), cfg,
                                   counter if cfg.exposure else None, p.claimed, sp, rng))
    return out


def confirm_session(pool, direction, person, truth, prev_sess: AppCATSession, prev_res, cfg: sim.AppConfig,
                    exclude: set[str], rng: np.random.Generator) -> tuple[AppCATSession, object]:
    """Дотестирование у порога Junior как в bank_engine._start_confirm: ответы prev переносятся в θ,
    основная часть считается завершённой, далее — только короткие задания у порога Junior вне exclude."""
    prior = [a for a in prev_res.administered]
    n_prior = sum(1 for a in prior if not a.canary)
    c = CATConfig(min_items=n_prior, max_items=n_prior, se_target=cfg.se_target, max_time_s=prev_res.time_used_s,
                  cuts=(JUNIOR_CUT,), stop_rule="classification", classify_z=cfg.classify_z, select_at=cfg.select_at,
                  exposure="sympson_hetter" if cfg.exposure else "none", ext_items=cfg.ext_items,
                  ext_time_s=cfg.ext_minutes * 60.0, ext_own_first=cfg.ext_own_first)
    own = {a.family_id for a in prior}
    sess = AppCATSession(pool, direction, c, None, "junior", prev_sess.subpool, rng,
                         max_per_format=cfg.max_per_format, exclude_ext=sorted(exclude | own))
    if len(exclude | own) > len(own) and not sess._ext_candidates():  # как в продукте: исключение смягчается
        sess = AppCATSession(pool, direction, c, None, "junior", prev_sess.subpool, rng,
                             max_per_format=cfg.max_per_format, exclude_ext=sorted(own))
    for a in prior:
        it = prev_sess.items[a.family_id]
        sess.record(it, a.x, a.log_t, time_s=float(np.exp(a.log_t)) if a.log_t is not None else None)
    responder = make_responder(person, truth, None)
    while True:
        item = sess.next_item()
        if item is None:
            break
        x, log_t = responder(item, rng)
        sess.record(item, x, log_t, time_s=float(np.exp(log_t)) if log_t is not None else None)
    return sess, sess.result()


def _decisions(people, results, provisional: bool) -> list[str]:
    """confirmed / provisional / rejected для каждого человека по θ̂ и SE его сессии."""
    out = []
    for p, r in zip(people, results, strict=True):
        d = decide(r.theta, r.se, p.claimed, provisional_level=PROVISIONAL_LEVEL if provisional else None)
        out.append("confirmed" if d.confirmed else "provisional" if d.provisional else "rejected")
    return out


def _junior_stats(people, decisions: list[str]) -> dict:
    jun = [(p, d) for p, d in zip(people, decisions, strict=True) if p.claimed == "junior"]
    n = len(jun)
    below = [p.theta < JUNIOR_CUT for p, _ in jun]
    n_below, n_above = sum(below), n - sum(below)
    cnt = {s: sum(1 for _, d in jun if d == s) for s in ("confirmed", "provisional", "rejected")}
    false_conf = sum(1 for (p, d), b in zip(jun, below, strict=True) if d == "confirmed" and b)
    false_prov = sum(1 for (p, d), b in zip(jun, below, strict=True) if d == "provisional" and b)
    false_rej = sum(1 for (p, d), b in zip(jun, below, strict=True) if d == "rejected" and not b)
    return {"n_claimed_junior": n, "n_true_below": n_below, "n_true_junior_or_above": n_above, **cnt,
            "share": {s: round(cnt[s] / max(n, 1), 3) for s in cnt},
            # ложные подтверждения: истинный θ < −1, грейд подтверждён
            "false_confirmed": false_conf, "false_confirmed_share": round(false_conf / max(n_below, 1), 3),
            # ложные предварительные: истинный θ < −1, статус «предварительно» (доля от предварительных)
            "false_provisional": false_prov, "false_provisional_share": round(false_prov / max(cnt["provisional"], 1), 3),
            # ложные отказы: истинный θ ≥ −1, категории нет (доля от истинных Junior и выше, заявивших Junior)
            "false_rejected": false_rej, "false_rejected_share": round(false_rej / max(n_above, 1), 3)}


def direction_block(d: str, i: int, n: int, cfg: sim.AppConfig, pool, k_all: dict) -> dict:
    rng0 = _rng(i, 0)
    truth = make_truth(pool, rng0, misspec=0.5)
    people = make_population(n, rng0)
    k = k_all.get(d, {})
    out: dict = {"n": n, "policies": {}}
    for pid, pcfg in (("app", cfg), ("legacy_sim", sim.LEGACY_SIM)):
        runs = _run_people(pool, truth, people, d, pcfg, _rng(i, 1), k)
        results = [r for _, r in runs]
        before, after = _decisions(people, results, False), _decisions(people, results, True)
        block = {"before": _junior_stats(people, before), "after": _junior_stats(people, after)}
        if pid == "app":
            # дотестирование предварительных: до CONFIRM_ATTEMPTS попыток, «ниже» статус не снимает
            idx = [j for j, (p, s) in enumerate(zip(people, after, strict=True)) if s == "provisional"]
            status = {j: "provisional" for j in idx}
            excl = {j: set(a.family_id for a in results[j].administered) for j in idx}
            last = {j: runs[j] for j in idx}
            attempts: list[dict] = []
            rng_c = _rng(i, 2)
            for att in range(1, CONFIRM_ATTEMPTS + 1):
                new_items = []
                for j in idx:
                    if status[j] != "provisional":
                        continue
                    s2, r2 = confirm_session(pool, d, people[j], truth, last[j][0], last[j][1], cfg, excl[j], rng_c)
                    new_items.append(r2.n_items - last[j][1].n_items)
                    dec = decide(r2.theta, r2.se, "junior", provisional_level=PROVISIONAL_LEVEL)
                    if dec.confirmed:
                        status[j] = "confirmed"
                    excl[j] |= {a.family_id for a in r2.administered}
                    last[j] = (s2, r2)
                still = [j for j in idx if status[j] == "provisional"]
                attempts.append({"attempt": att, "confirmed_total": sum(1 for j in idx if status[j] == "confirmed"),
                                 "still_provisional": len(still),
                                 "still_provisional_true_below": sum(1 for j in still if people[j].theta < JUNIOR_CUT),
                                 "confirmed_true_below": sum(1 for j in idx if status[j] == "confirmed"
                                                             and people[j].theta < JUNIOR_CUT),
                                 "mean_new_items": round(float(np.mean(new_items)), 1) if new_items else 0.0})
            block["confirm"] = {"n_provisional": len(idx), "attempts": attempts}
        out["policies"][pid] = block
    return out


def _sum(blocks: list[dict], path: tuple[str, ...]) -> dict:
    """Сумма счётчиков по направлениям и пересчёт долей."""
    rows = []
    for b in blocks:
        x = b
        for p in path:
            x = x[p]
        rows.append(x)
    keys = ("n_claimed_junior", "n_true_below", "n_true_junior_or_above", "confirmed", "provisional", "rejected",
            "false_confirmed", "false_provisional", "false_rejected")
    t = {k: int(sum(r[k] for r in rows)) for k in keys}
    n = max(t["n_claimed_junior"], 1)
    t["share"] = {s: round(t[s] / n, 3) for s in ("confirmed", "provisional", "rejected")}
    t["false_confirmed_share"] = round(t["false_confirmed"] / max(t["n_true_below"], 1), 3)
    t["false_provisional_share"] = round(t["false_provisional"] / max(t["provisional"], 1), 3)
    t["false_rejected_share"] = round(t["false_rejected"] / max(t["n_true_junior_or_above"], 1), 3)
    return t


def run(n: int = 400, quick: bool = False, write: bool = True) -> dict:
    t0 = time.time()
    cfg = sim.app_config_from_settings()
    pool = sim.make_pool(cfg.subpools)
    k_all = (exposure_table() or {}).get("k", {})
    dirs = sim.DIRECTIONS[:2] if quick else sim.DIRECTIONS
    rep = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "n_per_direction": n,
           "quick": quick, "seed": SEED, "config": asdict(cfg),
           "rule": {"confirm_level": CONFIRM_LEVEL, "provisional_level": PROVISIONAL_LEVEL, "junior_cut": JUNIOR_CUT,
                    "confirm_attempts": CONFIRM_ATTEMPTS, "confirm_ext_items": cfg.ext_items},
           "directions": {}}
    for i, d in enumerate(dirs):
        t = time.time()
        rep["directions"][d] = direction_block(d, i, n, cfg, pool, k_all)
        a = rep["directions"][d]["policies"]["app"]
        print(f"  {d}: заявили Junior {a['after']['n_claimed_junior']}, предварительных {a['after']['provisional']} "
              f"(ложных {a['after']['false_provisional']}), ложные отказы {a['before']['false_rejected']} → "
              f"{a['after']['false_rejected']}; после дотестирования предварительных осталось "
              f"{a['confirm']['attempts'][-1]['still_provisional']} ({round(time.time() - t, 1)} с)", flush=True)
    blocks = list(rep["directions"].values())
    rep["total"] = {pid: {"before": _sum(blocks, ("policies", pid, "before")),
                          "after": _sum(blocks, ("policies", pid, "after"))} for pid in ("app", "legacy_sim")}
    att = [b["policies"]["app"]["confirm"]["attempts"] for b in blocks]
    rep["total"]["app"]["confirm"] = {
        "n_provisional": int(sum(b["policies"]["app"]["confirm"]["n_provisional"] for b in blocks)),
        "attempts": [{"attempt": a + 1,
                      **{k: int(sum(x[a][k] for x in att)) for k in ("confirmed_total", "still_provisional",
                                                                    "still_provisional_true_below", "confirmed_true_below")},
                      "mean_new_items": round(float(np.mean([x[a]["mean_new_items"] for x in att])), 1)}
                     for a in range(CONFIRM_ATTEMPTS)]}
    rep["seconds"] = round(time.time() - t0, 1)
    rep["caveat"] = ("Синтетика: те же люди и те же сессии для «до» и «после», меняется только правило решения; "
                     "качество заданий на людях здесь не проверяется. Истинный уровень ниже порога определяется "
                     "по θ истинному, а не по θ̂.")
    if write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"→ {OUT} ({rep['seconds']} с)")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    run(a.n, a.quick, not a.no_write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
