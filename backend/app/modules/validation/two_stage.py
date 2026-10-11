"""Двухэтапное подтверждение уровня у границы — симуляция «одна сессия / две сессии» (тот же мир и seed, что path_retest).

    make two-stage        # cd backend && python -m app.modules.validation.two_stage [--n 500] [--workers 8]
    python -m app.modules.validation.two_stage --n 40 --workers 1 --no-write   # быстрая проверка механики

Путь первой попытки — ``path_retest.run_path`` (опрос → тест на заявленный грейд → решение при P ≥ 0,6 → «уровень
ниже» или тест ступенью ниже) без изменений. Затем правило продукта ``assessment.two_stage.boundary``: если уровень «на
границе», вторая короткая сессия ``RefineSession`` у выбранного порога (ответы первой сессии перенесены, семейства всех
прошлых сессий не берутся, частота показа — Sympson — Hetter), детектор предзнания по ответам обеих сессий, итог —
``final_grade`` по общей оценке θ̂ обеих сессий. Повтор — вся процедура ещё раз (история — обе сессии первой попытки).

Общие случайные числа: у каждого кандидата свои потоки rng (путь, уточнение, повтор), поэтому первая попытка одинакова во
всех вариантах, а разница между вариантами — только от правила второго этапа. Варианты: порог «на границе» L, число
заданий N и минуты второй сессии, порог подтверждения итога c₂, предлагать ли уточнение тем, у кого уже вероятен
уровень выше заявленного («above»), «итог не ниже первой сессии» (floor, абляция).

Метрики (первая попытка против истины; повтор всей процедуры — против первой попытки): точно, выше (завышение), ниже,
без категории, ±1, κw повтора и совпадение уровня при повторе (5 ступеней), доля кандидатов со вторым этапом, минуты на
путь (всего, второго этапа) — среднее и 90-й перцентиль. Всё синтетическое (модель, не люди): истинные параметры заданий =
предкалибровка + ошибка эксперта σ = 0,5, люди — модель ответов 2PL. Результат — data/two_stage.json и
docs/validation/TWO_STAGE.md.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import numpy as np

from assessment_bank.psychometrics import CanaryDetector, ExposureControl
from assessment_bank.simulation import _timed, make_truth

from app.modules.assessment import two_stage as ts
from app.modules.assessment.bank_engine import stack_excluded
from app.modules.assessment.exposure import exposure_table
from app.modules.assessment.grades import point_grade
from app.modules.catalog.seed_data import GRADE_ORDER
from app.modules.validation import path_retest as pr
from app.modules.validation import sim
from app.modules.validation.signature import signature

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "two_stage.json"
DOCS_MD = pr.REPO / "docs" / "validation" / "TWO_STAGE.md"

# цели волны 8 (общий итог двух сессий) и ограничения выбора
TARGET_EXACT, MAX_OVER, TARGET_RETEST = 0.75, 0.07, 0.85
MIN_KAPPA = 0.84
MAX_REFINE_MIN = 15.0      # вторая сессия 10–15 минут (карточка)
N_BOOT = 1000
LEVELS = pr.LEVELS

PARAMS = ("level", "items", "minutes", "confirm", "confirm_up", "above", "floor")
PARAM_RU = {"level": "«на границе», L", "items": "заданий второго этапа", "minutes": "минут второго этапа",
            "confirm": "подтверждение итога до заявленного c₂", "confirm_up": "подтверждение выше заявленного c↑",
            "above": "уточнение «выше заявленного» при P ≥", "floor": "итог не ниже первой сессии"}


def one_session() -> dict:
    return {"level": 0.0, "items": 0, "minutes": 0, "confirm": 0.6, "confirm_up": 0.9, "above": 0.0, "floor": False}


def default_point() -> dict:
    return {"level": ts.DEFAULT_LEVEL, "items": ts.DEFAULT_ITEMS, "minutes": ts.DEFAULT_MINUTES,
            "confirm": ts.DEFAULT_CONFIRM, "confirm_up": ts.DEFAULT_CONFIRM_UP, "above": ts.DEFAULT_ABOVE,
            "floor": False}


BASE = {"level": 0.8, "items": 8, "minutes": 15, "confirm": 0.5, "confirm_up": 0.9, "above": 0.0, "floor": False}


def _v(**kw) -> dict:
    return {**BASE, **kw}


def stage_main() -> list[dict]:
    """Перебор: L × N × c₂ × «выше заявленного» (минуты 15), затем c₂, c↑, минуты 10, длиннее карточки и абляции."""
    pts = [one_session(), default_point()]
    for lv in (0.7, 0.8, 0.9):
        for n in (6, 8):
            for c in (0.5, 0.6):
                for up in (0.0, 0.8):
                    pts.append(_v(level=lv, items=n, confirm=c, above=up))
    pts += [_v(confirm=c) for c in (0.45, 0.55)]
    pts += [_v(above=0.8, confirm_up=cu) for cu in (0.8, 0.95)] + [_v(above=0.6), _v(above=0.6, confirm_up=0.95)]
    pts += [_v(minutes=10, items=6), _v(minutes=10, items=6, level=0.7), _v(level=0.95), _v(floor=True)]
    pts += [_v(items=10, minutes=20), _v(items=12, minutes=25, level=0.9)]   # длиннее карточки — для Парето
    # второй круг (по первому прогону 11.10): «итог не ниже первой сессии» со строже c₂ и мягче c₂ при разных L
    pts += [_v(floor=True, confirm=c) for c in (0.55, 0.6, 0.65, 0.7)]
    pts += [_v(floor=True, confirm=0.6, level=lv) for lv in (0.7, 0.9)] + [_v(floor=True, confirm=0.6, items=6, minutes=10)]
    pts += [_v(confirm=c, level=lv) for lv in (0.7, 0.9) for c in (0.4, 0.45)] + [_v(confirm=0.4)]
    return pts


def stage_quick() -> list[dict]:
    return [one_session(), default_point(), _v(above=0.8), _v(level=0.9)]


def stage_probe() -> list[dict]:
    return [one_session(), _v(), _v(confirm=0.5), _v(level=0.7), _v(level=0.9), _v(above=0.8), _v(above=0.6),
            _v(items=12, minutes=25, level=0.9)]


STAGES = {"main": stage_main, "quick": stage_quick, "probe": stage_probe}


def key(pt: dict) -> str:
    return ";".join(f"{k}={pt[k]}" for k in PARAMS)


def label(pt: dict) -> str:
    if not pt["items"]:
        return "одна сессия (текущее правило P ≥ 0,6)"
    s = (f"L {pt['level']:g}, {pt['items']} заданий / {pt['minutes']} мин, c₂ {pt['confirm']:g}"
         + (f", выше заявленного при P ≥ {pt['above']:g} (c↑ {pt['confirm_up']:g})" if pt["above"] else "")
         + (", итог не ниже первой" if pt["floor"] else ""))
    return s.replace(".", ",")


# ---------------------------------------------------------------- сессии пути и второй этап

@contextmanager
def capture_sessions(store: list):
    """Сохранить объекты сессий, которые создаёт path_retest.run_path (ответы нужны второму этапу)."""
    orig = sim.run_session

    def wrapped(*a, **kw):
        out = orig(*a, **kw)
        store.append(out)
        return out
    sim.run_session = wrapped
    try:
        yield store
    finally:
        sim.run_session = orig


def run_path(pool, cand, truth, cfg, counter, hist, rng, det) -> tuple[dict, tuple]:
    store: list = []
    with capture_sessions(store):
        path = pr.run_path(pool, cand, truth, cfg, counter, hist, rng, det)
    return path, store[-1]


def refine(pool, cand, truth, cfg: sim.AppConfig, counter, hist: list[dict], rng, det, path: dict, last: tuple,
           pt: dict) -> dict:
    """Второй этап для пути ``path`` (последняя сессия — ``last``) по правилу точки ``pt``; hist дополняется."""
    rec = path["tests"][-1]
    out = {"refined": False, "grade": path["grade"], "kind": None, "minutes": 0.0, "items": 0, "stop": None,
           "families": [], "offered": False}
    if not pt["items"]:
        return out
    b = ts.boundary(rec["theta"], rec["se"], path["grade"], rec["claimed"], level=float(pt["level"]),
                    above=float(pt["above"]))
    if b is None:
        return out
    out["kind"], out["offered"] = b.kind, True
    sess0, res0 = last
    ccfg = replace(cfg.cat(), max_time_s=float(rec["time_s"]), ext_time_s=float(pt["minutes"]) * 60.0,
                   ext_item_time_s=ts.ITEM_TIME_S, ext_items=0)
    seen = {f: age for age, h in reversed(list(enumerate(hist))) for f in h["families"]}
    rs = ts.RefineSession(pool, cand.direction, ccfg, counter, rec["claimed"], rec["subpool"], rng,
                          max_per_format=cfg.max_per_format, seen=seen, exclude=sorted(stack_excluded(cand.stack)),
                          cut=b.cut, n_new=int(pt["items"]), z_stop=ts.stop_z(float(pt["level"])))
    rs.record_prior(res0.administered, sess0.items, float(res0.time_used_s))
    respond = pr.make_responder(pr.Person(cand.theta, cand.tau, rec["claimed"]), truth)
    while True:
        item = rs.next_item()
        if item is None:
            break
        x, log_t = respond(item, rng)
        rs.record(item, x, log_t, time_s=float(np.exp(log_t)))
    res = rs.result()
    theta, se = float(res.theta), float(res.se)
    clean, canary, idx = _timed(rs, res)
    st = det.statistic(clean, canary)
    if st.flagged:
        mask = det.suspicious_mask(clean, st.tau_clean)
        ex = {idx[i] for i in np.flatnonzero(mask)}
        if ex and len(ex) < len(idx):
            theta, se = (float(v) for v in rs.rescore(ex))
    grade = ts.final_grade(theta, se, rec["claimed"], float(pt["confirm"]), float(pt["confirm_up"]))
    if pt["floor"] and LEVELS.index(grade) < LEVELS.index(path["grade"]):
        grade = path["grade"]
    fams = [a.family_id for a in res.administered[len(res0.administered):] if not a.canary]
    hist.insert(0, {"subpool": rec["subpool"], "families": fams})
    out.update(refined=True, grade=grade, minutes=(res.time_used_s - res0.time_used_s) / 60.0, items=rs.n_new,
               stop=rs.stop_reason, families=fams, theta=round(theta, 4), se=round(se, 4))
    return out


def _path_min(path: dict) -> float:
    return sum(t["time_s"] for t in path["tests"]) / 60.0


def run_task(args: tuple) -> list[dict]:
    """Все варианты для кандидатов j0…j1 − 1 одного направления (общие случайные числа по кандидату)."""
    pts, i, d, n, j0, j1 = args
    pts = [{**one_session(), **p} for p in pts]
    cfg = sim.app_config_from_settings()
    pool = sim.make_pool(cfg.subpools)
    k = (exposure_table() or {}).get("k", {}).get(d, {})
    rng0 = pr._rng(i, 0)
    truth = make_truth(pool, rng0, misspec=0.5)
    cands = pr.make_candidates(n, d, rng0)
    counter = ExposureControl(0.3, k=dict(k))
    det = CanaryDetector()
    out = {key(p): {k_: [] for k_ in ("true", "claimed", "l1", "l2", "one1", "one2", "min1", "rmin1", "ritems1",
                                       "ref1", "ref2", "off1", "kind1", "status1", "stop1")} for p in pts}
    for j, c in enumerate(cands):
        if not j0 <= j < j1:
            continue
        h1: list[dict] = []
        p1, s1 = run_path(pool, c, truth, cfg, counter, h1, pr._rng(i, 11, j), det)
        h_base = list(h1)
        p2b, s2b = run_path(pool, c, truth, cfg, counter, h_base, pr._rng(i, 13, j), det)
        for p in pts:
            hist = list(h1)
            r1 = refine(pool, c, truth, cfg, counter, hist, pr._rng(i, 12, j), det, p1, s1, p)
            if r1["refined"]:
                p2, s2 = run_path(pool, c, truth, cfg, counter, hist, pr._rng(i, 13, j), det)
            else:
                p2, s2, hist = p2b, s2b, list(h_base)
            r2 = refine(pool, c, truth, cfg, counter, hist, pr._rng(i, 14, j), det, p2, s2, p)
            o = out[key(p)]
            o["true"].append(LEVELS.index(point_grade(c.theta)))
            o["claimed"].append(LEVELS.index(c.claimed))
            o["l1"].append(LEVELS.index(r1["grade"]))
            o["l2"].append(LEVELS.index(r2["grade"]))
            o["one1"].append(p1["level"])
            o["one2"].append(p2b["level"])
            o["min1"].append(round(_path_min(p1) + r1["minutes"], 3))
            o["rmin1"].append(round(r1["minutes"], 3))
            o["ritems1"].append(r1["items"])
            o["ref1"].append(r1["refined"])
            o["ref2"].append(r2["refined"])
            o["off1"].append(r1["offered"])
            o["kind1"].append(r1["kind"] or "")
            o["status1"].append(p1["status"])
            o["stop1"].append(r1["stop"] or "")
    return [{"key": key(p), "point": p, "direction": d, "part": j0, **out[key(p)]} for p in pts]


def run_parallel(tasks: list, workers: int, t0: float) -> list[dict]:
    """Как grade_sweep.run_parallel: отдельные процессы python (на сервере проверок /dev/shm закрыт для семафоров)."""
    if workers <= 1 or len(tasks) <= 1:
        return [r for t in tasks for r in run_task(t)]
    with tempfile.TemporaryDirectory(prefix="two_stage_") as tmp:
        procs = []
        for w in range(workers):
            part = tasks[w::workers]
            if not part:
                continue
            tf, of = Path(tmp) / f"t{w}.json", Path(tmp) / f"o{w}.json"
            tf.write_text(json.dumps(part, ensure_ascii=False), encoding="utf-8")
            env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
            procs.append((subprocess.Popen([sys.executable, "-m", "app.modules.validation.two_stage", "--worker",
                                            str(tf), str(of)], cwd=str(pr.REPO / "backend"), env=env), of))
        out = []
        for p, of in procs:
            if p.wait() != 0:
                raise RuntimeError(f"процесс симуляции завершился с кодом {p.returncode}")
            out += json.loads(of.read_text(encoding="utf-8"))
        print(f"  задач {len(tasks)} ({time.time() - t0:.0f} с)", flush=True)
        return out


def _worker(task_file: str, out_file: str) -> int:
    tasks = [tuple(t) for t in json.loads(Path(task_file).read_text(encoding="utf-8"))]
    res = []
    for t in tasks:
        res += run_task(t)
        print(f"    [{os.getpid()}] {t[2]} {t[4]}–{t[5]}: готово", flush=True)
    Path(out_file).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return 0


# ---------------------------------------------------------------- метрики

def _cat(rows: list[dict], k: str) -> np.ndarray:
    return np.concatenate([np.asarray(r[k]) for r in rows])


def metrics(rows: list[dict], boot: bool = True, seed: int = 0) -> dict:
    t, g, g2 = _cat(rows, "true"), _cat(rows, "l1"), _cat(rows, "l2")
    o1, o2 = _cat(rows, "one1"), _cat(rows, "one2")
    ref, off = _cat(rows, "ref1").astype(bool), _cat(rows, "off1").astype(bool)
    mins, rmin = _cat(rows, "min1").astype(float), _cat(rows, "rmin1").astype(float)
    kinds = [x for r in rows for x in r["kind1"]]
    has = g > 0
    m = {"n": int(len(t)), "exact": float(np.mean(g == t)), "over": float(np.mean(g > t)),
         "under": float(np.mean((g < t) & has)), "none": float(np.mean(~has)),
         "within_1": float(np.mean(np.abs(g - t) <= 1)), "kappa_true": float(pr.kappa_w(t, g)),
         "retest_exact": float(np.mean(g == g2)), "retest_kappa": float(pr.kappa_w(g, g2)),
         "share_refined": float(np.mean(ref)), "share_offered": float(np.mean(off)),
         "share_refined_retest": float(np.mean(_cat(rows, "ref2").astype(bool))),
         "minutes_mean": float(mins.mean()), "minutes_p90": float(np.percentile(mins, 90)),
         "refine_minutes_mean": float(rmin[ref].mean()) if ref.any() else 0.0,
         "refine_minutes_p90": float(np.percentile(rmin[ref], 90)) if ref.any() else 0.0,
         "refine_items_mean": float(_cat(rows, "ritems1")[ref].mean()) if ref.any() else 0.0,
         "changed": float(np.mean(g != o1)), "up": float(np.mean(g > o1)), "down": float(np.mean(g < o1)),
         # одна сессия на тех же кандидатах (контроль: та же первая попытка во всех вариантах)
         "one_exact": float(np.mean(o1 == t)), "one_over": float(np.mean(o1 > t)),
         "one_retest_exact": float(np.mean(o1 == o2)), "one_retest_kappa": float(pr.kappa_w(o1, o2))}
    m["kinds"] = {kd: round(kinds.count(kd) / len(kinds), 4) for kd in ("keep", "up", "above")}
    for kd in ("keep", "up", "above"):  # точность среди уточнявших по виду границы: до и после
        sel = np.array([x == kd for x in kinds]) & ref
        if sel.any():
            m[f"exact_{kd}"] = [round(float(np.mean(o1[sel] == t[sel])), 4), round(float(np.mean(g[sel] == t[sel])), 4)]
    if boot:
        idx = np.random.default_rng(seed).integers(0, len(t), size=(N_BOOT, len(t)))
        m["exact_ci"] = pr._ci(np.array([np.mean(g[i] == t[i]) for i in idx]))
        m["over_ci"] = pr._ci(np.array([np.mean(g[i] > t[i]) for i in idx]))
        m["retest_exact_ci"] = pr._ci(np.array([np.mean(g[i] == g2[i]) for i in idx]))
        m["retest_kappa_ci"] = pr._ci(np.array([pr.kappa_w(g[i], g2[i]) for i in idx]))
        m["delta_exact_ci"] = pr._ci(np.array([np.mean(g[i] == t[i]) - np.mean(o1[i] == t[i]) for i in idx]))
    m["feasible"] = bool(m["over"] <= MAX_OVER and m["retest_kappa"] >= MIN_KAPPA
                         and m["refine_minutes_p90"] <= MAX_REFINE_MIN + 1e-9)
    m["targets"] = {"exact": m["exact"] >= TARGET_EXACT, "over": m["over"] <= MAX_OVER,
                    "retest": m["retest_exact"] >= TARGET_RETEST}
    return {k_: (round(v, 4) if isinstance(v, float) else v) for k_, v in m.items()}


def pareto(points: list[dict]) -> list[str]:
    """Недоминируемые по (точно ↑, завышение ↓, совпадение при повторе ↑, доля второго этапа ↓, минуты ↓)."""
    def vec(p):
        m = p["metrics"]
        return np.array([m["exact"], -m["over"], m["retest_exact"], -m["share_refined"], -m["minutes_mean"]])
    vs = [vec(p) for p in points]
    return [points[i]["key"] for i, v in enumerate(vs)
            if not any(np.all(w >= v) and np.any(w > v) for j, w in enumerate(vs) if j != i)]


def _better(m: dict, bm: dict) -> bool:
    """Лучше одной сессии по всем ограничениям: точно ↑, завышение ≤ 7 %, совпадение при повторе и κw — не ниже."""
    return bool(m["exact"] > bm["exact"] and m["over"] <= MAX_OVER and m["retest_exact"] >= bm["retest_exact"]
                and m["retest_kappa"] >= bm["retest_kappa"])


def choose(points: list[dict]) -> dict:
    """Среди допустимых (завышение ≤ 7 %, κw ≥ 0,84, второй этап ≤ 15 мин по p90, карточка ≤ 15 мин) — сначала те, что
    лучше одной сессии по всем ограничениям; из них максимум точных, в пределах 1 п. п. — меньше доля второго этапа
    и минуты. Нет таких — лучший допустимый по точности с пометкой better_on_all = false (по умолчанию — одна сессия)."""
    base = next(p for p in points if not p["point"]["items"])
    bm = base["metrics"]
    feas = [p for p in points if p["point"]["items"] and p["metrics"]["feasible"]
            and p["point"]["minutes"] <= MAX_REFINE_MIN]
    if not feas:
        return {"key": None, "better_on_all": False, "reason": "нет допустимых вариантов"}
    good = [p for p in feas if _better(p["metrics"], bm)]
    pool = good or feas
    best_exact = max(p["metrics"]["exact"] for p in pool)
    near = [p for p in pool if p["metrics"]["exact"] >= best_exact - 0.01]
    best = sorted(near, key=lambda p: (p["metrics"]["share_refined"], p["metrics"]["minutes_mean"],
                                       -p["metrics"]["exact"]))[0]
    m = best["metrics"]
    return {"key": best["key"], "point": best["point"], "better_on_all": bool(good), "n_better": len(good),
            "better_keys": [p["key"] for p in good],
            "delta_exact": round(m["exact"] - bm["exact"], 4), "delta_over": round(m["over"] - bm["over"], 4),
            "delta_retest": round(m["retest_exact"] - bm["retest_exact"], 4),
            "delta_kappa": round(m["retest_kappa"] - bm["retest_kappa"], 4),
            "delta_minutes": round(m["minutes_mean"] - bm["minutes_mean"], 2)}


# ---------------------------------------------------------------- прогон

def run(stages: list[str], n: int = 500, workers: int | None = None, write: bool = True, parts: int = 4) -> dict:
    t0 = time.time()
    pts, seen = [], set()
    for st in stages:
        for p in STAGES[st]():
            if key(p) not in seen:
                seen.add(key(p))
                pts.append(p)
    # задача = направление × часть кандидатов (у кандидата свои потоки rng — деление не меняет чисел)
    step = max(1, -(-n // parts))
    tasks = [(pts, i, d, n, j0, min(n, j0 + step)) for i, d in enumerate(sim.DIRECTIONS) for j0 in range(0, n, step)]
    workers = min(workers or min(8, len(os.sched_getaffinity(0))), len(tasks))
    print(f"вариантов: {len(pts)}, задач: {len(tasks)}, кандидатов: {n} на направление, процессов: {workers}", flush=True)
    by: dict[str, list[dict]] = {}
    for r in run_parallel(tasks, workers, t0):
        by.setdefault(r["key"], []).append(r)
    for v in by.values():
        v.sort(key=lambda r: (sim.DIRECTIONS.index(r["direction"]), r["part"]))
    points = [{"key": key(p), "point": p, "label": label(p), "metrics": metrics(by[key(p)], seed=pr.SEED)}
              for p in pts]
    front = pareto(points)
    for p in points:
        p["pareto"] = p["key"] in front
    ch = choose(points)
    cfg = sim.app_config_from_settings()
    rep = {"signature": signature(seed=pr.SEED, config={"base": asdict(cfg), "n": n, "stages": stages,
                                                        "item_time_s": ts.ITEM_TIME_S, "min_new": ts.MIN_NEW},
                                  n=n * len(sim.DIRECTIONS),
                                  world=f"симуляция всего пути и второго этапа: {len(sim.DIRECTIONS)} направлений × "
                                        f"{n} кандидатов, вариантов: {len(points)}",
                                  command="make two-stage"),
           "targets": {"exact": TARGET_EXACT, "max_over": MAX_OVER, "retest_exact": TARGET_RETEST,
                       "min_retest_kappa": MIN_KAPPA, "max_refine_minutes": MAX_REFINE_MIN},
           "defaults": default_point(), "choice": ch, "pareto": front, "points": points,
           "caveat": pr.CAVEAT, "seconds": round(time.time() - t0, 1)}
    if write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        DOCS_MD.write_text(markdown(rep), encoding="utf-8")
        print(f"→ {OUT.relative_to(pr.REPO)}, {DOCS_MD.relative_to(pr.REPO)} ({rep['seconds']} с)", flush=True)
    return rep


# ---------------------------------------------------------------- /validation и документация

def compact(rep: dict) -> dict:
    """Сводка для /validation#two-stage."""
    pts = {p["key"]: p for p in rep["points"]}
    keep = ("exact", "exact_ci", "over", "under", "none", "retest_exact", "retest_exact_ci", "retest_kappa",
            "share_refined", "minutes_mean", "minutes_p90", "refine_minutes_mean", "refine_items_mean", "feasible",
            "targets", "kinds")

    def row(p: dict) -> dict:
        return {"label": p["label"], "point": p["point"], "pareto": p.get("pareto", False),
                **{k: p["metrics"].get(k) for k in keep}}
    base = next(p for p in rep["points"] if not p["point"]["items"])
    ch = rep.get("choice") or {}
    dflt = pts.get(key(rep["defaults"]))
    front = sorted([p for p in rep["points"] if p.get("pareto") and p["point"]["items"]],
                   key=lambda p: -p["metrics"]["exact"])
    return {"signature": rep["signature"], "targets": rep["targets"], "caveat": rep.get("caveat"),
            "one_session": row(base), "default": row(dflt) if dflt else None,
            "choice": {**ch, "row": row(pts[ch["key"]]) if ch.get("key") in pts else None},
            "pareto": [row(p) for p in front[:10]], "n_points": len(rep["points"])}


def _pc(v, d: int = 1) -> str:
    return "—" if v is None else f"{100 * v:.{d}f} %".replace(".", ",")


def _f(v, d: int = 3) -> str:
    return "—" if v is None else f"{v:.{d}f}".replace(".", ",")


def _ci(ci) -> str:
    return "" if not ci else f" [{_pc(ci[0])}; {_pc(ci[1])}]"


HEAD = ("| Вариант | Точно | Выше | Ниже | Без кат. | Повтор: совпало | κw повтора | Второй этап | Мин. всего (ср. / p90) "
        "| Мин. второго этапа | Цели |\n|---|---|---|---|---|---|---|---|---|---|---|")


def _row(p: dict) -> str:
    m = p["metrics"]
    tg = m["targets"]
    goals = " · ".join(n for n, ok in (("точно ≥ 75", tg["exact"]), ("выше ≤ 7", tg["over"]),
                                         ("повтор ≥ 85", tg["retest"])) if ok) or "—"
    return (f"| {p['label']} | {_pc(m['exact'])} | {_pc(m['over'])} | {_pc(m['under'])} | {_pc(m['none'])} "
            f"| {_pc(m['retest_exact'])} | {_f(m['retest_kappa'])} | {_pc(m['share_refined'])} "
            f"| {_f(m['minutes_mean'], 1)} / {_f(m['minutes_p90'], 0)} | {_f(m['refine_minutes_mean'], 1)} | {goals} |")


def markdown(rep: dict) -> str:
    pts = {p["key"]: p for p in rep["points"]}
    base = next(p for p in rep["points"] if not p["point"]["items"])
    dflt = pts.get(key(rep["defaults"]))
    ch = rep["choice"]
    best = pts.get(ch.get("key"))
    sg = rep["signature"]
    L = ["# Двухэтапное подтверждение уровня у границы", "",
         f"Подпись мира: {sg.get('world')}; seed {sg.get('seed')}, конфигурация `{sg.get('config_hash')}`, коммит "
         f"`{sg.get('commit')}`, банк `{(sg.get('bank') or '—')[:16]}`. Пересчёт: `make two-stage`.", "",
         f"> {rep['caveat']} Модель, не люди: числа сравнивают правила внутри одного мира.", "",
         "## Правило", "",
         "1. После основного теста (≤ 60 мин, решение при P ≥ 0,6; итог первой сессии g, заявленный грейд c) уровень "
         "**«на границе»**, если у порогов уровней от g до c включительно (выше g, не выше заявленного) "
         "P(θ ≥ порога) лежит строго между 1 − L и L (то же, что |θ̂ − порог| < z_L · SE); граница — порог с P, "
         "ближайшей к 0,5. Вид: «уровень под вопросом» (порог — уровень g, keep) или «возможно выше» (порог выше g, "
         "не выше c, up). Режим «выше заявленного» (above > 0): если g = c и уровень выше c вероятен с P ≥ above.",
         "2. До уточнения — уровень по первой сессии с пометкой «на границе: можно уточнить» (не выше, чем позволяет "
         "первая сессия).",
         "3. **Уточнение уровня** — отдельная сессия: только короткие задания (≤ 5 мин) с наибольшей информацией у "
         "выбранного порога, без семейств прошлых сессий, частота показа — Sympson — Hetter; не больше N заданий и M минут; "
         "досрочно — когда после 3 новых заданий порог вышел из θ̂ ± z_L · SE.",
         "4. **Итог** — по общей оценке обеих сессий (одна апостериорная θ̂ по всем ответам; детектор предзнания — по всем): "
         "наивысший уровень не выше заявленного с P(θ ≥ порога) ≥ c₂; выше заявленного — только в режиме above и с "
         "P ≥ c↑. Может быть и ниже первой сессии (кроме варианта «итог не ниже первой»). Уровень — только по тесту.", "",
         "Повтор — вся процедура ещё раз (новый субпул, семейства обеих сессий первой попытки не берутся). Общие случайные "
         "числа: первая попытка одинакова во всех вариантах.", "",
         "## Одна сессия / две сессии", "", HEAD, _row(base)]
    if dflt:
        L.append(_row(dflt))
    if best and best is not dflt:
        L.append(_row(best))
    L += ["", f"Цели волны 8 (общий итог двух сессий): точно ≥ {_pc(TARGET_EXACT, 0)}, завышение ≤ {_pc(MAX_OVER, 0)}, "
              f"совпадение при повторе ≥ {_pc(TARGET_RETEST, 0)}.", ""]
    if dflt:
        m, bm = dflt["metrics"], base["metrics"]
        L += [f"- По умолчанию ({dflt['label']}): точно {_pc(m['exact'])}{_ci(m.get('exact_ci'))} против "
              f"{_pc(bm['exact'])} одной сессии (разница{_ci(m.get('delta_exact_ci'))}); завышение {_pc(m['over'])}; "
              f"совпадение при повторе {_pc(m['retest_exact'])}{_ci(m.get('retest_exact_ci'))} против "
              f"{_pc(bm['retest_exact'])}; κw {_f(m['retest_kappa'])} против {_f(bm['retest_kappa'])}.",
              f"- Второй этап нужен {_pc(m['share_refined'])} кандидатов (виды границы: уровень под вопросом "
              f"{_pc(m['kinds'].get('keep'))}, возможно выше {_pc(m['kinds'].get('up'))}, выше заявленного уже вероятен "
              f"{_pc(m['kinds'].get('above'))}); у них в среднем {_f(m['refine_items_mean'], 1)} заданий и "
              f"{_f(m['refine_minutes_mean'], 1)} мин; среднее время на кандидата {_f(m['minutes_mean'], 1)} мин "
              f"(одна сессия — {_f(bm['minutes_mean'], 1)}).",
              f"- Итог изменился у {_pc(m['changed'])} кандидатов: выше {_pc(m['up'])}, ниже {_pc(m['down'])}."]
        for kd, ru in (("keep", "уровень под вопросом"), ("up", "возможно выше"), ("above", "выше заявленного")):
            if m.get(f"exact_{kd}"):
                a, b = m[f"exact_{kd}"]
                L.append(f"  - {ru}: точно до уточнения {_pc(a)}, после {_pc(b)}.")
    L += ["", "## Выбор", ""]
    if best:
        L += [f"- Лучший допустимый вариант: **{best['label']}** — лучше одной сессии по всем ограничениям: "
              f"{'да' if ch['better_on_all'] else 'нет'} (точно {'+' if ch['delta_exact'] >= 0 else ''}"
              f"{_f(100 * ch['delta_exact'], 1)} п. п., завышение {'+' if ch['delta_over'] >= 0 else ''}"
              f"{_f(100 * ch['delta_over'], 1)} п. п., совпадение при повторе {'+' if ch['delta_retest'] >= 0 else ''}"
              f"{_f(100 * ch['delta_retest'], 1)} п. п., минуты {'+' if ch['delta_minutes'] >= 0 else ''}"
              f"{_f(ch['delta_minutes'], 1)}).",
              f"- Лучше одной сессии по всем ограничениям (точно ↑, завышение ≤ 7 %, совпадение при повторе и κw не ниже): "
              f"{ch.get('n_better', 0)} вариантов.",
              "- Допустимы: завышение ≤ 7 %, κw повтора ≥ 0,84, второй этап ≤ 15 мин (90-й перцентиль); выбор — среди "
              "лучших по всем ограничениям максимум точных, в пределах 1 п. п. — меньше доля второго этапа и минуты."]
    else:
        L.append(f"- {ch.get('reason')}")
    feas = [p for p in rep["points"] if p["point"]["items"]]
    if feas:
        bx = max(feas, key=lambda p: p["metrics"]["exact"])
        br = max(feas, key=lambda p: p["metrics"]["retest_exact"])
        hit = [p for p in feas if all(p["metrics"]["targets"].values())]
        L += ["", "## Цели волны и предел", "",
              f"- Все три цели сразу (точно ≥ {_pc(TARGET_EXACT, 0)}, завышение ≤ {_pc(MAX_OVER, 0)}, повтор ≥ "
              f"{_pc(TARGET_RETEST, 0)}) выполняет вариантов: {len(hit)} из {len(feas)}.",
              f"- Наибольшая точность — {_pc(bx['metrics']['exact'])} ({bx['label']}): завышение "
              f"{_pc(bx['metrics']['over'])}, совпадение при повторе {_pc(bx['metrics']['retest_exact'])}.",
              f"- Наибольшее совпадение при повторе — {_pc(br['metrics']['retest_exact'])} ({br['label']}): точно "
              f"{_pc(br['metrics']['exact'])}, завышение {_pc(br['metrics']['over'])}.",
              "- Почему не выше: второй этап — короткие задания (≤ 5 мин) у одного порога; за 10–15 минут их набирается "
              f"в среднем {_f((dflt or bx)['metrics']['refine_items_mean'], 1)}, и общая погрешность уменьшается "
              "ненамного — у кандидатов с θ рядом с порогом решение остаётся близким к случайному. «Ниже» во многом — "
              "недозаявившие (по разбору Я22 в GRADE_ACCURACY.md — около двух третей «ниже»): без режима «выше "
              "заявленного» тест их не поднимает, а с ним растут завышение и расхождение при повторе. Длиннее второй "
              "этап (10–12 заданий, 20–25 мин) прибавляет к точности не больше 1 п. п."]
    L += ["", "## В продукте", "",
          "- Флаг `ASSESSMENT_TWO_STAGE_ENABLED` (по умолчанию выкл.); параметры — `ASSESSMENT_TWO_STAGE_LEVEL` (L), "
          "`_ITEMS` (N), `_MINUTES` (M), `_CONFIRM` (c₂), `_CONFIRM_UP` (c↑), `_ABOVE`, `_FLOOR`; значения по умолчанию — "
          "выбор этого прогона.",
          "- **Решение владельца 11.10 — вариант А:** итог уточнения — уровень по обеим сессиям и может оказаться ниже "
          "уровня первой сессии (кандидата предупреждает текст предложения); значения по умолчанию — выбор этого прогона "
          "(`_FLOOR` false, c₂ 0,45). Вариант «итог не ниже первой» (`_FLOOR` true, c₂ 0,7) остаётся настройкой — "
          "по симуляции он тоже лучше одной сессии, но точнее вариант А.",
          "- Итог полного теста банка «на границе» → блок «На границе X/Y: можно уточнить» и кнопка «Уточнить уровень за "
          "10–M минут»; до уточнения действует уровень по первой сессии. Уточнение — `POST /api/assessment/sessions` "
          "с `mode=refine`: одно на полный тест, правила 90 и 30 дней на него не действуют (та же оценка), лимит сессии — "
          "M + 10 минут.",
          "- Итог уточнения — по ответам обеих сессий (ответы первой переносятся, как в дотестировании Junior); уровень "
          "записывается обычными правилами категории (подтверждение, повышение или понижение); при «без категории» "
          "прежняя категория сохраняется.",
          "- Работодатель (карточка, подборка, поиск — общий статус грейда) видит пометку «на границе X/Y — уточнение "
          "пройдено / не пройдено / не проходил». Уровень — только по тесту.",
          "- Устная защита ответов теста (модуль интервью, `INTERVIEW_ENABLED`) — дополнительное доказательство: уровень "
          "не меняет, меняет пометку — «на границе X/Y — подтверждено устной защитой» или «— требует проверки» (вердикт "
          "модели «подтверждено» / «есть расхождения»; «мало данных» и модельный пример пометку не меняют).",
          "- Экран «Категория и грейд» — то же предложение по последнему полному тесту направления "
          "(`GET /api/assessment/status` → `two_stage`): «можно уточнить» / «продолжить» / итог уточнения.",
          "- Lead и Principal (флаг `GRADES_EXT_ENABLED`, пометка «предварительно» — docs/GRADES_EXT.md): второй этап "
          "предлагается и без границы по правилу выше — у порога своего уровня (Senior/Lead для Lead, Lead/Principal для "
          "Principal); кнопка «Пройти второй этап за 10–M минут» — в пометке «предварительно» (итог теста и «Категория и "
          "грейд»). Тот же второй этап — если заявленный Lead/Principal доказан с P ≥ L, но не присвоен только потолком "
          "одной сессии (погрешность больше `GRADES_EXT_MAX_SE`); итог Lead/Principal после второго этапа — тоже только "
          "при общей погрешности не больше `GRADES_EXT_MAX_SE`. Шкала и итог — только по уровням, которые проверяет банк "
          "направления. Отдельной симуляции двух сессий "
          "для 6 уровней нет (оценка вклада блока трудных заданий — docs/validation/GRADES_EXT_NEED.md), поэтому пометка "
          "«предварительно» у Lead/Principal остаётся и после второго этапа."]
    L += ["", "## Парето (точно ↑, завышение ↓, совпадение при повторе ↑, доля второго этапа ↓, минуты ↓)", "", HEAD]
    L += [_row(p) for p in sorted(rep["points"], key=lambda p: -p["metrics"]["exact"]) if p.get("pareto")]
    L += ["", "## Все варианты", "", HEAD]
    L += [_row(p) for p in sorted(rep["points"], key=lambda p: -p["metrics"]["exact"])]
    L += ["", "Полные данные: `backend/app/modules/validation/data/two_stage.json`.", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--stage", default="main", choices=sorted(STAGES))
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--md-only", action="store_true", help="только docs/validation/TWO_STAGE.md из data/two_stage.json")
    ap.add_argument("--worker", nargs=2, help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.worker:
        return _worker(*a.worker)
    if a.md_only:  # без пересчёта: значения по умолчанию и выбор — по текущему коду (после смены DEFAULT_*)
        rep = json.loads(OUT.read_text(encoding="utf-8"))
        rep["defaults"], rep["choice"] = default_point(), choose(rep["points"])
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        DOCS_MD.write_text(markdown(rep), encoding="utf-8")
        return 0
    rep = run([a.stage], n=a.n, workers=a.workers, write=not a.no_write)
    for p in rep["points"][:6]:
        m = p["metrics"]
        print(f"{p['label']:<60} точно {m['exact']:.3f} выше {m['over']:.3f} повтор {m['retest_exact']:.3f} "
              f"κw {m['retest_kappa']:.3f} 2-й этап {m['share_refined']:.3f} мин {m['minutes_mean']:.1f}")
    print("выбор:", rep["choice"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
