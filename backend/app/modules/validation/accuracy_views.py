"""Три прозрачных числа точности грейда (W1) — на одном мире симуляции path_retest / two_stage (seed 20261006).

    make accuracy-views   # cd backend && python -m app.modules.validation.accuracy_views [--n 500] [--workers 2]

Один прогон ``two_stage.run_task`` для двух правил: одна сессия (как в продукте сейчас) и двухэтапное подтверждение у
границы (``assessment.two_stage``, значения по умолчанию: L 0,8, 8 заданий, 15 минут, c₂ 0,45, c↑ 0,9). Истинный θ
кандидата пишется в строки (поле ``theta``), поэтому подмножества считаются по истине, а не по оценке.

Три числа (все — против истинного грейда первой попытки, 5 направлений × 500 кандидатов, модель, не люди):

* а) **вдали от порога**: |θ − ближайший порог| ≥ 0,45 (пороги −1,75 / −1 / 0 / 1), одна сессия. Это кандидаты, у
  которых тест на 15–25 заданий в принципе может различить соседние грейды (SE теста ≈ 0,35–0,45); у порога ошибка
  в соседний грейд неизбежна при любой длине разумного теста.
* б) **без занижения заявки**: заявленный грейд ≥ истинного (тест идёт от заявленного уровня вниз, кандидат, заявивший
  ниже истинного, выше заявки не подтверждается — продукт этого не обещает), двухэтапное подтверждение у границы.
* в) **строгое по всему пулу**: все кандидаты, включая заявивших ниже истинного, одна сессия; рядом — повтор всей
  процедуры (совпадение, κw, ±1 ступень) из data/path_retest.json.

Подмножества заданы до прогона (порог 0,45 и определение «без занижения» — из постановки штаба), числа считаются один
раз и пишутся как есть; доля пула в каждом подмножестве указывается рядом. Результат — data/accuracy_views.json и
docs/validation/ACCURACY_VIEWS.md.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import time

import numpy as np

from app.modules.catalog.seed_data import GRADE_CUTS
from app.modules.validation import path_retest as pr
from app.modules.validation import sim
from app.modules.validation import two_stage as tsim
from app.modules.validation.signature import signature

OUT = tsim.HERE / "data" / "accuracy_views.json"
DOCS_MD = pr.REPO / "docs" / "validation" / "ACCURACY_VIEWS.md"
FAR = 0.45
N_BOOT = 2000
CUTS = tuple(sorted(GRADE_CUTS.values()))


def _ci(x: np.ndarray, seed: int) -> list[float]:
    if not len(x):
        return [0.0, 0.0]
    idx = np.random.default_rng(seed).integers(0, len(x), size=(N_BOOT, len(x)))
    return [round(float(v), 4) for v in np.percentile(x[idx].mean(1), [2.5, 97.5])]


def _block(hit: np.ndarray, mask: np.ndarray, seed: int) -> dict:
    x = hit[mask].astype(float)
    return {"exact": round(float(x.mean()), 4) if len(x) else None, "n": int(mask.sum()),
            "share": round(float(mask.mean()), 4), "exact_ci": _ci(x, seed)}


def compute(rows_one: list[dict], rows_two: list[dict], retest: dict | None) -> dict:
    cat = tsim._cat
    t, c = cat(rows_one, "true"), cat(rows_one, "claimed")
    th = cat(rows_one, "theta").astype(float)
    assert np.array_equal(t, cat(rows_two, "true")) and np.allclose(th, cat(rows_two, "theta").astype(float))
    g1, g2 = cat(rows_one, "l1"), cat(rows_two, "l1")
    dist = np.min(np.abs(th[:, None] - np.array(CUTS)[None, :]), axis=1)
    far = dist >= FAR
    no_under = c >= t
    allm = np.ones_like(t, dtype=bool)
    seed = pr.SEED
    v = {
        "far_from_cut": {**_block(g1 == t, far, seed), "rule": "одна сессия", "threshold": FAR,
                         "over": round(float(np.mean(g1[far] > t[far])), 4),
                         "two_stage": _block(g2 == t, far, seed + 1)},
        "no_under_claim": {**_block(g2 == t, no_under, seed + 2), "rule": "двухэтапное подтверждение у границы",
                           "over": round(float(np.mean(g2[no_under] > t[no_under])), 4),
                           "one_session": _block(g1 == t, no_under, seed + 3)},
        "strict_pool": {**_block(g1 == t, allm, seed + 4), "rule": "одна сессия",
                        "over": round(float(np.mean(g1 > t)), 4),
                        "under": round(float(np.mean((g1 < t) & (g1 > 0))), 4),
                        "none": round(float(np.mean(g1 == 0)), 4),
                        "under_claim_share": round(float(np.mean(c < t)), 4),
                        "two_stage": _block(g2 == t, allm, seed + 5)},
        "under_claim": {**_block(g1 == t, c < t, seed + 6), "rule": "одна сессия (заявили ниже истинного)"},
        "near_cut": {**_block(g1 == t, ~far, seed + 7), "rule": "одна сессия (|θ − порог| < 0,45)"},
    }
    if retest:
        v["strict_pool"]["retest"] = retest
    return v


def run(n: int = 500, workers: int | None = None, write: bool = True) -> dict:
    t0 = time.time()
    pts = [tsim.one_session(), tsim.default_point()]
    step = max(1, -(-n // 4))
    tasks = [(pts, i, d, n, j0, min(n, j0 + step)) for i, d in enumerate(sim.DIRECTIONS) for j0 in range(0, n, step)]
    workers = min(workers or min(8, len(os.sched_getaffinity(0))), len(tasks))
    print(f"задач: {len(tasks)}, кандидатов: {n} на направление, процессов: {workers}", flush=True)
    by: dict[str, list[dict]] = {}
    for r in tsim.run_parallel(tasks, workers, t0):
        by.setdefault(r["key"], []).append(r)
    for rows in by.values():
        rows.sort(key=lambda r: (sim.DIRECTIONS.index(r["direction"]), r["part"]))
    one, two = by[tsim.key(pts[0])], by[tsim.key(pts[1])]
    retest = None
    if pr.OUT.exists():
        tot = json.loads(pr.OUT.read_text(encoding="utf-8"))["total"]
        pg = tot["path_grade"]
        retest = {"exact": pg["exact"], "kappa_w": pg["kappa_w"], "within_1": pg["within_1"],
                  "truth_exact": tot["truth"]["exact"], "source": "data/path_retest.json"}
    views = compute(one, two, retest)
    cfg = sim.app_config_from_settings()
    rep = {"signature": signature(seed=pr.SEED, config={"n": n, "far": FAR, "cuts": CUTS, "points": pts,
                                                        "max_items": cfg.max_items},
                                  n=n * len(sim.DIRECTIONS),
                                  world=f"симуляция всего пути: {len(sim.DIRECTIONS)} направлений × {n} кандидатов",
                                  command="make accuracy-views"),
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "n_per_direction": n, "points": {"one_session": pts[0], "two_stage": pts[1]}, "views": views,
           "two_stage_metrics": tsim.metrics(two, boot=False), "one_session_metrics": tsim.metrics(one, boot=False),
           "caveat": pr.CAVEAT, "seconds": round(time.time() - t0, 1)}
    if write:
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        DOCS_MD.write_text(markdown(rep), encoding="utf-8")
        print(f"→ {OUT.relative_to(pr.REPO)}, {DOCS_MD.relative_to(pr.REPO)} ({rep['seconds']} с)", flush=True)
    return rep


def _p(x) -> str:
    return "—" if x is None else f"{100 * x:.1f} %".replace(".", ",")


def _ci_s(ci) -> str:
    return f"[{_p(ci[0])}; {_p(ci[1])}]"


def _f(x, d=3) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def markdown(rep: dict) -> str:
    v = rep["views"]
    a, b, c, u, nc = v["far_from_cut"], v["no_under_claim"], v["strict_pool"], v["under_claim"], v["near_cut"]
    sig = rep["signature"]
    rt = c.get("retest") or {}
    L = ["# Точность грейда: три прозрачных числа", "",
         f"Симуляция всего пути кандидата (модель, не люди): {sig.get('n')} кандидатов (5 направлений × "
         f"{rep['n_per_direction']}), seed {sig.get('seed')}, код — коммит `{sig.get('commit')}`, банк "
         f"`{sig.get('bank')}`. Пересчёт: `make accuracy-views` ({rep['seconds']:.0f} с).", "",
         f"> {rep['caveat']}", "",
         "| Число | Кто входит | Доля пула | Правило | Точно | 95 % ДИ |", "|---|---|---|---|---|---|",
         f"| а) Вдали от порога | \\|θ − ближайший порог\\| ≥ {_f(FAR, 2)} | {_p(a['share'])} | {a['rule']} | "
         f"**{_p(a['exact'])}** | {_ci_s(a['exact_ci'])} |",
         f"| б) Без занижения заявки | заявленный грейд ≥ истинного | {_p(b['share'])} | {b['rule']} | "
         f"**{_p(b['exact'])}** | {_ci_s(b['exact_ci'])} |",
         f"| в) Строго, весь пул | все, включая {_p(c['under_claim_share'])} заявивших ниже истинного | 100 % | "
         f"{c['rule']} | **{_p(c['exact'])}** | {_ci_s(c['exact_ci'])} |", "",
         f"Повтор всей процедуры (data/path_retest.json): совпадение {_p(rt.get('exact'))}, κw {_f(rt['kappa_w']) if rt else '—'}, "
         f"±1 ступень {_p(rt.get('within_1'))}; точно против истины там же — {_p(rt.get('truth_exact'))}.", "",
         "## Как читать", "",
         f"* а) Вдали от порога — {_p(a['share'])} пула; у остальных {_p(nc['share'])} (|θ − порог| < {_f(FAR, 2)}) "
         f"точность {_p(nc['exact'])}: у порога соседний грейд статистически почти неотличим. Завышение среди «вдали» "
         f"— {_p(a['over'])}; с двухэтапным подтверждением — {_p(a['two_stage']['exact'])}.",
         f"* б) Без занижения заявки — {_p(b['share'])} пула; одна сессия на тех же кандидатах — "
         f"{_p(b['one_session']['exact'])}, завышение с двумя этапами — {_p(b['over'])}. Заявившие ниже истинного "
         f"({_p(u['share'])}) получают точный грейд в {_p(u['exact'])} случаев: тест начинается с заявленного уровня, "
         "выше заявки грейд не подтверждается.",
         f"* в) Строго — весь пул, одна сессия (как в продукте сейчас): точно {_p(c['exact'])}, выше {_p(c['over'])}, "
         f"ниже {_p(c['under'])}, без категории {_p(c['none'])}; с двухэтапным подтверждением — "
         f"{_p(c['two_stage']['exact'])}.",
         "* Подмножества заданы до прогона (порог 0,45 и «заявленный ≥ истинного» — из постановки), числа посчитаны "
         "один раз. Числа а) и б) — условные: они честны только вместе с долей пула и строгим числом в).", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    rep = run(n=a.n, workers=a.workers, write=not a.no_write)
    for k, x in rep["views"].items():
        print(k, x.get("exact"), x.get("share"), x.get("n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
