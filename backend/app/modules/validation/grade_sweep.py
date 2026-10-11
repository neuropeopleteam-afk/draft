"""Перебор параметров теста ради точности уровня — на симуляции всего пути (path_retest), тот же мир и seed.

    make grade-sweep                       # cd backend && python -m app.modules.validation.grade_sweep [--stage all]
    python -m app.modules.validation.grade_sweep --stage screen --n 500 --workers 8

Что перебирается (по одному от текущей конфигурации, затем сетка по влиятельным):
порог уверенности подтверждения и «уровня ниже» (0,6–0,8), дотестирование у порога (число заданий и запас минут),
минимум и максимум заданий, остановка по SE (se_target) и классификационная остановка (z), абляция «уровень выше в
той же сессии». Правило «Стажёр» (порог −1,75) не меняется — без данных на людях его не трогаем.

Метрики каждой точки (первая попытка против истины, повтор всего пути — против первой попытки):
точно истинный уровень, выше истинного (завышение), ниже (категория есть), без категории, ±1; κw повтора пути
(5 ступеней) с бутстрэп-ДИ; минуты и задания на путь (среднее и 90-й перцентиль), сессий на путь.
Ограничения выбора (карточка Я22): завышение ≤ 6 %, κw повтора ≥ 0,84, время пути ≤ 60 мин (среднее);
цель — максимум точных попаданий. Парето — по (точно ↑, завышение ↓, κw ↑, минуты ↓).

Всё синтетическое (как path_retest): истинные параметры заданий = предкалибровка + ошибка эксперта σ = 0,5, люди —
модель ответов 2PL; это сравнение правил внутри одного мира, а не точность на людях. Результат —
data/grade_sweep.json и docs/validation/GRADE_ACCURACY.md.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import time

import numpy as np

from assessment_bank.psychometrics import CanaryDetector, ExposureControl
from assessment_bank.simulation import make_truth

from app.modules.assessment.exposure import exposure_table
from app.modules.assessment import weak_pool
from app.modules.assessment.grades import CONFIRM_LEVEL, GRADE_ORDER, p_at_least, point_grade
from app.modules.validation import path_retest as pr
from app.modules.validation import sim
from app.modules.validation.signature import signature

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "grade_sweep.json"
DOCS_MD = pr.REPO / "docs" / "validation" / "GRADE_ACCURACY.md"

# ограничения выбора
MAX_OVER = 0.07          # решение владельца 10.10: завышение ≤ 7 % (прежний ориентир ≤ 6 % — выбор отмечен отдельно)
MAX_OVER_STRICT = 0.06
MIN_KAPPA = 0.84
MAX_MINUTES = 60.0
N_BOOT = 1000

PARAMS = ("decision", "confirm_level", "ext_items", "ext_minutes", "min_items", "max_items", "se_target",
          "classify_z", "stop_rule", "award_above", "misspec", "levels", "max_minutes", "exclude_low", "partial",
          "time_weight", "weak_a", "weak_pool", "plus")
# Семейства, слабые по калибровке панелью LLM (модель, не люди): отрицательная дискриминация шага, p = 0/1, a < 0,6,
# a_eff < 0,55, p ≈ угадывание, неизоморфные варианты (банк, ветка feat/bank-core-plus 5493728,
# reports/weak_families.json, поле exclude). Проверка: мир, где их истинная a = weak_a (по умолчанию в пуле — prior
# a ≈ 1,0–1,2), и политика пула weak_pool: keep — как сейчас, exclude — убрать из пула, down — a = WEAK_DOWN_A в пуле.
WEAK_FAMILIES = weak_pool.WEAK_FAMILIES  # один список с продуктом (флаг ASSESSMENT_WEAK_EXCLUDE)
WEAK_DOWN_A = 0.4
# Добор банка у порогов J/M и M/S (17 семейств с исполняемым ключом, prior a = 1,3; банк feat/bank-ext 68ce4cf, в
# продукт ещё не синхронизированы): plus = 1 — пул платформы + эти семейства (снимок предкалибровки —
# data/bank_plus_core.json, `--export-plus <каталог families банка>`); истина для них — та же модель ошибки эксперта.
PLUS_FILE = HERE / "data" / "bank_plus_core.json"
PLUS_FAMILIES = (
    "security.web.ssrf_allowlist_fix", "security.session.fixation_bug", "security.crypto.hmac_canonical_bug",
    "security.access.bulk_owner_check_bug", "security.auth.token_audience_bug", "frontend.state.optimistic_rollback_fix",
    "frontend.js.object_key_order_output", "data_ml.ml.purged_split_fix", "data_ml.metrics.pooled_rate_bug",
    "data_ml.features.lag_window_leak_bug", "data_ml.features.target_encoding_oof_fix", "qa.mock.called_once_bug",
    "qa.mutation.survivors_output", "qa.pytest.fixture_scope_state_bug", "qa.pytest.raises_too_broad_bug",
    "backend.cache.stampede_fix", "common.sql.window_range_ties_output")
OPEN_FORMATS = ("open_answer", "open_book_3step")
PARAM_RU = {"confirm_level": "порог уверенности P", "ext_items": "дотестирование, заданий",
            "ext_minutes": "дотестирование, мин", "min_items": "минимум заданий", "max_items": "максимум заданий",
            "se_target": "остановка по SE", "classify_z": "z классификации", "stop_rule": "правило остановки",
            "award_above": "уровень выше в сессии (P)", "decision": "решение",
            "misspec": "мир: ошибка параметров σ", "levels": "ступеней", "max_minutes": "лимит основной части, мин",
            "exclude_low": "без семейств с низкой информацией (доля)", "partial": "частичный балл: критериев",
            "time_weight": "выбор: информация на минуту (вес)",
            "weak_a": "мир: у 26 слабых по панели семейств истинная a", "weak_pool": "26 слабых семейств в пуле",
            "plus": "добор банка у порогов J/M и M/S (17 семейств)"}
VALUE_RU = {"weak_pool": {"exclude": "26 слабых семейств исключены из пула", "down": "26 слабых семейств в пуле с a = 0,4"},
            "plus": {1: "+ добор банка у порогов J/M и M/S (17 семейств)"}}
DECISION_RU = {"claimed": "заявленный грейд, P ≥ порога уверенности", "point": "по лучшей оценке θ̂ (точечный грейд)"}


def baseline_point() -> dict:
    """Текущая конфигурация платформы (настройки) — точка отсчёта."""
    c = sim.app_config_from_settings()
    return {"decision": "claimed", "misspec": 0.5, "confirm_level": CONFIRM_LEVEL, "ext_items": c.ext_items, "ext_minutes": c.ext_minutes,
            "min_items": c.min_items, "max_items": c.max_items, "se_target": c.se_target,
            "classify_z": c.classify_z, "stop_rule": c.stop_rule, "award_above": None, "levels": 5,
            "max_minutes": c.max_minutes, "exclude_low": 0.0, "partial": 1, "time_weight": c.time_weight,
            "weak_a": 0.0, "weak_pool": "keep", "plus": 0}


def _p(**kw) -> dict:
    return {**baseline_point(), **kw}


def stage_screen() -> list[dict]:
    """По одному параметру от текущей конфигурации (мир σ = 0,5)."""
    pts = [_p()]
    pts += [_p(confirm_level=v) for v in (0.5, 0.55, 0.6, 0.65, 0.7, 0.75)]
    pts += [_p(ext_items=v) for v in (0, 3, 9, 12)]
    pts += [_p(ext_minutes=v) for v in (10, 30)]
    pts += [_p(min_items=v) for v in (6, 10, 12)]
    pts += [_p(max_items=v) for v in (12, 14, 18, 20)]
    pts += [_p(se_target=v) for v in (0.25, 0.30, 0.40, 0.45)]
    pts += [_p(classify_z=v) for v in (1.0, 1.15, 1.44, 1.64)]
    pts += [_p(stop_rule="se")]
    pts += [_p(award_above=v) for v in (0.8, 0.9)]
    pts += [_p(decision="point")]
    return pts


def stage_grid() -> list[dict]:
    """Сетка по влиятельным параметрам: решение × порог уверенности × дотестирование × z × длина."""
    pts = []
    for z in (1.0, 1.28, 1.64):
        for ext in (3, 6, 9):
            for mn, mx in ((8, 16), (6, 14), (10, 18)):
                pts.append(_p(decision="point", classify_z=z, ext_items=ext, min_items=mn, max_items=mx))
                for c in (0.5, 0.6, 0.7):
                    for up in (None, 0.8):
                        pts.append(_p(confirm_level=c, award_above=up, classify_z=z, ext_items=ext,
                                      min_items=mn, max_items=mx))
    return pts


def stage_worlds() -> list[dict]:
    """Мир конкурента (σ = 0,35): Парето-точки мира σ = 0,5 пересчитываются в stage «worlds» отдельно (см. run)."""
    return [_p(misspec=0.35), _p(misspec=0.35, decision="point"), _p(misspec=0.35, confirm_level=0.5)]


def stage_competitor() -> list[dict]:
    """«Яблоко к яблоку» с FSP Talent: 4 ступени (без Стажёра), σ параметров 0,35, 20 заданий, подтверждение при
    P ≥ 0,5 — нашей процедурой (опрос, ротация, детектор, повтор всего пути); рядом — наша текущая и по лучшей оценке."""
    fixed = dict(levels=4, misspec=0.35, min_items=20, max_items=20, ext_items=0, max_minutes=90)
    return [_p(**fixed, confirm_level=0.5), _p(**fixed, decision="point"),
            _p(levels=4, misspec=0.35), _p(levels=4, misspec=0.35, decision="point"),
            _p(levels=4), _p(levels=4, decision="point")]


def stage_pool() -> list[dict]:
    """Без семейств с низкой информацией и частичный балл развёрнутых ответов — от текущей и от «по лучшей оценке»."""
    pts = []
    for dec in ("claimed", "point"):
        pts += [_p(decision=dec, exclude_low=q) for q in (0.1, 0.2, 0.3)]
        pts += [_p(decision=dec, partial=k) for k in (2, 3)]
    return pts


def stage_time() -> list[dict]:
    """Больше заданий за те же 60 минут: выбор по информации на минуту ожидаемого времени и длиннее максимум."""
    pts = []
    for c in (0.6, 0.8):
        for tw in (0.5, 1.0):
            for mx in (16, 20, 24):
                pts.append(_p(confirm_level=c, time_weight=tw, max_items=mx))
    return pts


def stage_refine() -> list[dict]:
    """Уточнение около выбора (P ≥ 0,6) и он же в мире конкурента."""
    return [_p(confirm_level=0.58), _p(confirm_level=0.62), _p(confirm_level=0.6, exclude_low=0.1),
            _p(confirm_level=0.6, ext_items=9), _p(confirm_level=0.6, classify_z=1.0),
            _p(confirm_level=0.6, time_weight=1.0, max_items=20, exclude_low=0.1),
            _p(confirm_level=0.6, misspec=0.35), _p(confirm_level=0.6, misspec=0.35, levels=4),
            _p(confirm_level=0.6, levels=4)]


def stage_weak() -> list[dict]:
    """26 слабых по панели семейств: мир «на деле слабые» (a = 0,4) и мир «как в prior»; политика пула."""
    pts = []
    for cl in (0.6, 0.8):
        pts += [_p(confirm_level=cl, weak_a=0.4, weak_pool=wp) for wp in ("keep", "exclude", "down")]
        pts += [_p(confirm_level=cl, weak_pool=wp) for wp in ("exclude", "down")]
    return pts


def stage_plus() -> list[dict]:
    """Чистка пула вместе с добором сильных семейств у порогов: оба мира (слабые на деле слабые / как в prior)."""
    pts = []
    for wa in (0.0, 0.4):
        pts += [_p(confirm_level=0.6, weak_a=wa, plus=1, weak_pool=wp) for wp in ("keep", "exclude")]
        pts += [_p(confirm_level=cl, weak_a=wa, plus=1, weak_pool="exclude") for cl in (0.55, 0.58)]
        # после синхронизации банка: какой порог держит завышение ≤ 7 % (keep — пул как есть; exclude — с чисткой)
        pts += [_p(confirm_level=cl, weak_a=wa, plus=1, weak_pool=wp) for cl in (0.65, 0.7) for wp in ("keep", "exclude")]
    return pts


STAGES = {"plus": stage_plus, "screen": stage_screen, "time": stage_time, "refine": stage_refine, "weak": stage_weak, "grid": stage_grid, "worlds": stage_worlds, "competitor": stage_competitor,
          "pool": stage_pool}


def key(pt: dict) -> str:
    return ";".join(f"{k}={pt[k]}" for k in PARAMS)


def borderline(grade: str, theta: float, se: float, level: float = 0.8) -> bool:
    """«На границе»: итоговый уровень не доказан с P ≥ 0,8 или следующий не исключён (P > 0,2)."""
    if grade == "none":
        return p_at_least(theta, se, GRADE_ORDER[0]) > 1 - level
    i = GRADE_ORDER.index(grade)
    up = p_at_least(theta, se, GRADE_ORDER[i + 1]) if i + 1 < len(GRADE_ORDER) else 0.0
    return bool(p_at_least(theta, se, grade) < level or up > 1 - level)


# ---------------------------------------------------------------- один (точка, направление)

_CACHE: dict = {}


def _pool(n_subpools: int, plus: int = 0):
    if (n_subpools, plus) not in _CACHE:
        if plus:
            from assessment_bank import load_specs
            from assessment_bank.psychometrics import pool_from_specs
            _CACHE[(n_subpools, plus)] = pool_from_specs(list(load_specs().values()) + plus_specs(),
                                                         n_subpools=max(1, n_subpools))
        else:
            _CACHE[(n_subpools, plus)] = sim.make_pool(n_subpools)
    return _CACHE[(n_subpools, plus)]


def plus_specs() -> list:
    """Семейства добора из снимка data/bank_plus_core.json — в виде, который понимает pool_from_specs."""
    from types import SimpleNamespace as NS

    rows = json.loads(PLUS_FILE.read_text(encoding="utf-8"))["families"]
    return [NS(**{**r, "prior_difficulty": NS(**r["prior_difficulty"])}) for r in rows]


def plus_gates() -> dict[str, frozenset[str]]:
    from app.modules.assessment.skill_map import stack_gate

    out = {s.family_id: stack_gate(s.direction, s.skills) for s in plus_specs()}
    return {f: g for f, g in out.items() if g}


def export_plus(families_dir: str, commit: str) -> Path:
    """Снимок предкалибровки семейств добора из YAML банка (без текстов заданий и генераторов)."""
    import yaml

    want, rows = set(PLUS_FAMILIES), {}
    for path in sorted(Path(families_dir).glob("*/*.yaml")):
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or d.get("family_id") not in want:
            continue
        pr_ = d["prior_difficulty"]
        rows[d["family_id"]] = {
            "family_id": d["family_id"], "direction": d["direction"],
            "block": "common" if d["direction"] == "common" else d["direction"], "format": d["format"],
            "target_grades": list(d["target_grades"]), "canary": bool(d.get("canary", False)),
            "time_limit_s": int(d["time_limit_s"]), "skills": list(d["skills"]),
            "prior_difficulty": {"a": float(pr_["a"]), "b": float(pr_["b"]),
                                 "step_offsets": [float(x) for x in (pr_.get("step_offsets") or [])],
                                 "sigma_variant": float(pr_.get("sigma_variant", 0.3))}}
    miss = sorted(want - set(rows))
    if miss:
        raise SystemExit(f"нет в банке: {miss}")
    PLUS_FILE.write_text(json.dumps({"source": f"банк feat/bank-ext {commit} (добор у порогов J/M и M/S)",
                                     "note": "предкалибровка автора (prior), не калибровка на людях",
                                     "families": [rows[f] for f in PLUS_FAMILIES]}, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    return PLUS_FILE


def low_info_families(pool, q: float) -> set[str]:
    """Доля q семейств каждого блока с наименьшей наибольшей информацией (сумма a_eff² / 4 по частям, предкалибровка)."""
    if q <= 0:
        return set()
    out: set[str] = set()
    for block in sorted({i.block for i in pool}):
        blk = sorted([i for i in pool if i.block == block and not i.canary], key=lambda i: float(np.sum(i.a_eff ** 2)))
        out |= {i.family_id for i in blk[:int(round(q * len(blk)))]}
    return out


def partial_responder(k: int):
    """Частичный балл: у развёрнутых ответов (open_answer, текстовый шаг open_book_3step) итог части — доля из k
    независимых критериев той же трудности (оценка сверху: критерии рубрики на деле связаны)."""
    from assessment_bank.psychometrics.irt import prob

    def factory(person, truth, leak=None):
        def respond(item, rng):
            tf = truth[item.family_id]
            delta = rng.normal(0, tf.sigma)
            p = prob(person.theta, tf.a, tf.mu + delta)
            x = (rng.random(len(tf.mu)) < p).astype(float)
            if item.format in OPEN_FORMATS:
                for j in ([len(p) - 1] if item.format == "open_book_3step" else range(len(p))):
                    x[j] = float((rng.random(k) < p[j]).mean())
            log_t = float(rng.normal(tf.beta_time - person.tau, 1 / tf.alpha_time))
            return x, min(log_t, float(np.log(tf.time_limit_s)))
        return respond
    return factory


def run_task(args: tuple[dict, int, str, int]) -> dict:
    """Путь дважды для кандидатов одного направления при параметрах pt — те же rng, что path_retest.direction_run."""
    pt, i, d, n = args
    pt = {**baseline_point(), **pt}
    base = sim.app_config_from_settings()
    cfg = replace(base, ext_items=int(pt["ext_items"]), ext_minutes=int(pt["ext_minutes"]),
                  min_items=int(pt["min_items"]), max_items=int(pt["max_items"]), se_target=float(pt["se_target"]),
                  classify_z=float(pt["classify_z"]), stop_rule=str(pt["stop_rule"]),
                  max_minutes=int(pt["max_minutes"]), time_weight=float(pt["time_weight"]))
    four = int(pt["levels"]) == 4
    if four:  # 4 ступени, как у FSP Talent: без Стажёра (ниже Junior — без категории)
        cfg = replace(cfg, cuts=tuple(c for g, c in zip(GRADE_ORDER, cfg.cuts) if g != "intern"))
    plus = int(pt.get("plus") or 0)
    pool_all = _pool(cfg.subpools, plus)
    k = (exposure_table() or {}).get("k", {}).get(d, {})
    rng0 = pr._rng(i, 0)
    added = set(PLUS_FAMILIES) if plus else set()
    # истина прежних семейств и кандидаты — из тех же случайных чисел, что без добора (сравнение на тех же людях)
    truth = make_truth([it for it in pool_all if it.family_id not in added], rng0, misspec=float(pt["misspec"]))
    cands = pr.make_candidates(n, d, rng0)
    if plus:
        truth.update(make_truth([it for it in pool_all if it.family_id in added], pr._rng(i, 7),
                                misspec=float(pt["misspec"])))
    if four:
        cands = [replace(c, claimed="junior") if c.claimed == "intern" else c for c in cands]
    if float(pt["weak_a"]) > 0:  # мир: слабые по панели семейства на деле слабые
        truth = {f: (replace(t, a=np.full_like(t.a, float(pt["weak_a"]))) if f in WEAK_FAMILIES else t)
                 for f, t in truth.items()}
    low = low_info_families(pool_all, float(pt["exclude_low"]))
    pool = [it for it in pool_all if it.family_id not in low]
    if pt["weak_pool"] == "exclude":
        pool = [it for it in pool if it.family_id not in WEAK_FAMILIES]
    elif pt["weak_pool"] == "down":
        pool = [replace(it, a=np.full_like(it.a, WEAK_DOWN_A)) if it.family_id in WEAK_FAMILIES else it for it in pool]
    counter = ExposureControl(0.3, k=dict(k))
    det = CanaryDetector()
    rng = pr._rng(i, 1)
    saved, saved_stack = pr.make_responder, pr.stack_excluded
    if int(pt["partial"]) > 1:
        pr.make_responder = partial_responder(int(pt["partial"]))
    if plus:  # фильтр по стеку и для семейств добора (как bank_engine.stack_excluded после синхронизации банка)
        gates = plus_gates()
        pr.stack_excluded = lambda stack: (set(saved_stack(stack))
                                           | {f for f, g in gates.items() if not g <= set(stack or ())})

    def lv(level: int) -> int:
        return max(level - 1, 0) if four else level
    out = {"true": [], "claimed": [], "l1": [], "l2": [], "min1": [], "items1": [], "sess1": [], "status1": [],
           "border1": []}
    try:
        rows = []
        for c in cands:
            hist: list[dict] = []
            rows.append((c, pr.run_path(pool, c, truth, cfg, counter, hist, rng, det, pt["confirm_level"],
                                        pt["award_above"], pt["decision"]),
                         pr.run_path(pool, c, truth, cfg, counter, hist, rng, det, pt["confirm_level"],
                                     pt["award_above"], pt["decision"])))
    finally:
        pr.make_responder, pr.stack_excluded = saved, saved_stack
    for c, r1, r2 in rows:
        out["true"].append(lv(pr.LEVELS.index(point_grade(c.theta))))
        out["claimed"].append(lv(pr.LEVELS.index(c.claimed)))
        out["l1"].append(lv(r1["level"]))
        out["l2"].append(lv(r2["level"]))
        out["min1"].append(sum(t["time_s"] for t in r1["tests"]) / 60)
        out["items1"].append(sum(t["n_items"] for t in r1["tests"]))
        out["sess1"].append(len(r1["tests"]))
        out["status1"].append(r1["status"])
        out["border1"].append(borderline(r1["grade"], r1["tests"][-1]["theta"], r1["tests"][-1]["se"]))
    return {"key": key(pt), "direction": d, "n_excluded": len(low), **out}


def run_parallel(tasks: list, workers: int, t0: float) -> list[dict]:
    """Задачи — в отдельных процессах python (без multiprocessing: на сервере проверок /dev/shm закрыт для записи,
    семафоры не создаются). Каждый процесс берёт свою долю задач и пишет итог в JSON во временный каталог."""
    if workers <= 1 or len(tasks) <= 1:
        return [run_task(t) for t in tasks]
    with tempfile.TemporaryDirectory(prefix="grade_sweep_") as tmp:
        procs = []
        for w in range(workers):
            part = tasks[w::workers]
            if not part:
                continue
            tf, of = Path(tmp) / f"t{w}.json", Path(tmp) / f"o{w}.json"
            tf.write_text(json.dumps(part, ensure_ascii=False), encoding="utf-8")
            env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
            procs.append((subprocess.Popen([sys.executable, "-m", "app.modules.validation.grade_sweep", "--worker",
                                            str(tf), str(of)], cwd=str(pr.REPO / "backend"), env=env), of))
        out = []
        for p, of in procs:
            if p.wait() != 0:
                raise RuntimeError(f"процесс перебора завершился с кодом {p.returncode}")
            out += json.loads(of.read_text(encoding="utf-8"))
        print(f"  задач {len(out)} ({time.time() - t0:.0f} с)", flush=True)
        return out


def _worker(task_file: str, out_file: str) -> int:
    tasks = [tuple(t) for t in json.loads(Path(task_file).read_text(encoding="utf-8"))]
    res = []
    for j, t in enumerate(tasks):
        res.append(run_task(t))
        if (j + 1) % 10 == 0:
            print(f"    [{os.getpid()}] {j + 1}/{len(tasks)}", flush=True)
    Path(out_file).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return 0


# ---------------------------------------------------------------- метрики точки

def metrics(rows: list[dict], boot: bool = True, seed: int = 0) -> dict:
    cat = {k: np.concatenate([np.asarray(r[k]) for r in rows]) for k in ("true", "claimed", "l1", "l2", "min1",
                                                                         "items1", "sess1", "border1")}
    status = [s for r in rows for s in r["status1"]]
    t, g, g2 = cat["true"], cat["l1"], cat["l2"]
    has = g > 0
    under = (g < t) & has
    m = {"n": int(len(t)),
         "exact": float(np.mean(g == t)), "over": float(np.mean(g > t)), "under": float(np.mean(under)),
         "none": float(np.mean(~has)), "within_1": float(np.mean(np.abs(g - t) <= 1)),
         "kappa_true": float(pr.kappa_w(t, g)),
         # из «ниже истинного»: заявил ниже истинного уровня (тест на заявленный грейд выше не поднимает)
         "under_claimed_below": float(np.mean(under & (cat["claimed"] < t))),
         "retest_kappa": float(pr.kappa_w(g, g2)), "retest_exact": float(np.mean(g == g2)),
         "minutes_mean": float(cat["min1"].mean()), "minutes_p90": float(np.percentile(cat["min1"], 90)),
         "minutes_over_60": float(np.mean(cat["min1"] > 60.0)),
         "items_mean": float(cat["items1"].mean()), "sessions_mean": float(cat["sess1"].mean()),
         "borderline": float(np.mean(cat["border1"])),
         "status": {s: round(status.count(s) / len(status), 4) for s in sorted(set(status))}}
    if boot:
        idx = np.random.default_rng(seed).integers(0, len(t), size=(N_BOOT, len(t)))
        m["exact_ci"] = pr._ci(np.array([np.mean(g[i] == t[i]) for i in idx]))
        m["over_ci"] = pr._ci(np.array([np.mean(g[i] > t[i]) for i in idx]))
        m["retest_kappa_ci"] = pr._ci(np.array([pr.kappa_w(g[i], g2[i]) for i in idx]))
    m["feasible"] = bool(m["over"] <= MAX_OVER and m["retest_kappa"] >= MIN_KAPPA and m["minutes_mean"] <= MAX_MINUTES)
    m["feasible_strict"] = bool(m["feasible"] and m["over"] <= MAX_OVER_STRICT)
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}


def pareto(points: list[dict]) -> list[str]:
    """Недоминируемые точки по (точно ↑, завышение ↓, κw повтора ↑, минуты ↓)."""
    def vec(p):
        m = p["metrics"]
        return np.array([m["exact"], -m["over"], m["retest_kappa"], -m["minutes_mean"]])
    vs = [vec(p) for p in points]
    front = []
    for i, v in enumerate(vs):
        dom = any(np.all(w >= v) and np.any(w > v) for j, w in enumerate(vs) if j != i)
        if not dom:
            front.append(points[i]["key"])
    return front


NEAR_EXACT = 0.01


def n_changed(pt: dict) -> int:
    b = baseline_point()
    return sum(1 for k in PARAMS if k != "misspec" and pt.get(k) != b.get(k))


def choose(points: list[dict], base_key: str) -> dict:
    """Лучшая допустимая точка по точности (см. NEAR_EXACT)."""
    base = next((p for p in points if p["key"] == base_key), None)
    if base is None:
        return {"key": None, "better_on_all": False, "reason": "текущей конфигурации нет среди точек"}
    feas = [p for p in points if p["metrics"]["feasible"]]
    if not feas:
        return {"key": base_key, "better_on_all": False, "reason": "нет допустимых точек"}
    best_exact = max(p["metrics"]["exact"] for p in feas)
    # в пределах 1 п. п. от лучшей (≈ половина ширины ДИ — различие не значимо) — проще (меньше изменённых параметров),
    # затем меньше завышение и минуты
    near = [p for p in feas if p["metrics"]["exact"] >= best_exact - NEAR_EXACT]
    best = sorted(near, key=lambda p: (n_changed(p["point"]), p["metrics"]["over"], p["metrics"]["minutes_mean"],
                                       -p["metrics"]["exact"]))[0]
    bm, m = base["metrics"], best["metrics"]
    better = bool(m["exact"] > bm["exact"] and m["feasible"])
    return {"key": best["key"], "point": best["point"], "better_on_all": better,
            "delta_exact": round(m["exact"] - bm["exact"], 4), "delta_over": round(m["over"] - bm["over"], 4),
            "delta_kappa": round(m["retest_kappa"] - bm["retest_kappa"], 4),
            "delta_minutes": round(m["minutes_mean"] - bm["minutes_mean"], 2)}


# ---------------------------------------------------------------- прогон

def run(stages: list[str], n: int = 500, workers: int | None = None, write: bool = True,
        extra: list[dict] | None = None, merge: bool = False) -> dict:
    t0 = time.time()
    pts: list[dict] = []
    for st in stages:
        pts += STAGES[st]()
    pts += extra or []
    pts = [{**baseline_point(), **p} for p in pts]
    seen, uniq = set(), []
    for p in pts:
        if key(p) not in seen:
            seen.add(key(p))
            uniq.append(p)
    old = {}
    if merge and OUT.exists():
        old = {}
        for p in json.loads(OUT.read_text(encoding="utf-8")).get("points", []):
            if p.get("n_per_direction") != n:
                continue
            p["point"] = {**baseline_point(), **p["point"]}  # точки прежних прогонов — без новых параметров
            p["key"] = key(p["point"])
            old[p["key"]] = p
    todo = [p for p in uniq if key(p) not in old]
    tasks = [(p, i, d, n) for p in todo for i, d in enumerate(sim.DIRECTIONS)]
    workers = workers or min(8, len(os.sched_getaffinity(0)))
    print(f"точек: {len(uniq)} (новых {len(todo)}), задач: {len(tasks)}, процессов: {workers}", flush=True)
    by: dict[str, list[dict]] = {}
    for r in run_parallel(tasks, workers, t0):
        by.setdefault(r["key"], []).append(r)
    raw = OUT.with_name("grade_sweep_raw_last.json")  # сырьё последнего прогона — до анализа (не потерять при ошибке)
    raw.write_text(json.dumps({k: v for k, v in by.items()}, ensure_ascii=False), encoding="utf-8")
    points = list(old.values())
    for p in todo:
        k = key(p)
        points.append({"key": k, "point": p, "n_per_direction": n, "metrics": metrics(by[k], seed=pr.SEED)})
    base_key = key(baseline_point())
    front: list[str] = []
    def world(p: dict) -> tuple:  # мир и банк: Парето — внутри одного мира и одного банка
        return (p["point"]["misspec"], p["point"]["weak_a"], int(p["point"].get("plus") or 0))
    for w in sorted({world(p) for p in points}, reverse=True):
        front += pareto([p for p in points if world(p) == w])
    for p in points:
        p["pareto"] = p["key"] in front
    # выбор — только на банке платформы (добор ещё не синхронизирован) и в основном мире
    main_world = [p for p in points if p["point"]["misspec"] == 0.5 and not p["point"]["weak_a"]
                  and not p["point"].get("plus")]
    choice = choose(main_world, base_key)
    strict = [p for p in main_world if p["metrics"]["feasible_strict"] or p["key"] == base_key]
    choice_strict = choose(strict, base_key)
    cfg = sim.app_config_from_settings()
    rep = {"signature": signature(seed=pr.SEED, config={"base": asdict(cfg), "n": n, "stages": stages},
                                  n=n * len(sim.DIRECTIONS),
                                  world=f"симуляция всего пути: {len(sim.DIRECTIONS)} направлений × {n} кандидатов, "
                                        f"точек перебора: {len(points)}",
                                  command="make grade-sweep"),
           "constraints": {"max_over": MAX_OVER, "min_retest_kappa": MIN_KAPPA, "max_minutes_mean": MAX_MINUTES},
           "baseline_key": base_key, "choice": choice, "choice_strict_over_6": choice_strict, "pareto": front,
           "points": points,
           "caveat": pr.CAVEAT, "seconds": round(time.time() - t0, 1)}
    if write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        DOCS_MD.write_text(markdown(rep), encoding="utf-8")
        print(f"→ {OUT.relative_to(pr.REPO)}, {DOCS_MD.relative_to(pr.REPO)} ({rep['seconds']} с)", flush=True)
    return rep


# ---------------------------------------------------------------- для страницы /validation

def _label(pt: dict) -> str:
    return _diff(pt, baseline_point())


def compact(rep: dict) -> dict:
    """Сводка для /validation#grade-accuracy: строки — точки с подписью отличий от прежней конфигурации."""
    pts = {p["key"]: p for p in rep["points"]}
    keep = ("exact", "exact_ci", "over", "under", "none", "within_1", "retest_kappa", "retest_kappa_ci", "retest_exact",
            "minutes_mean", "minutes_p90", "items_mean", "under_claimed_below", "feasible", "borderline")

    def row(p: dict) -> dict:
        return {"label": _label(p["point"]), "point": p["point"], "pareto": p.get("pareto", False),
                **{k: p["metrics"].get(k) for k in keep}}
    base = pts.get(rep["baseline_key"])
    ch = rep.get("choice") or {}
    main = [p for p in rep["points"] if p["point"]["misspec"] == 0.5 and p["point"].get("levels", 5) == 5
            and not p["point"].get("weak_a") and not p["point"].get("plus")]
    front = sorted([p for p in main if p.get("pareto")], key=lambda p: -p["metrics"]["exact"])
    comp = [p for p in rep["points"] if (p["point"].get("levels", 5) == 4 or p["point"]["misspec"] != 0.5)
            and not p["point"].get("weak_a") and not p["point"].get("plus") and p["point"].get("weak_pool", "keep") == "keep"]
    keyrows = [p for p in main if _label(p["point"]) in KEY_ROWS]
    return {"signature": rep["signature"], "constraints": rep["constraints"], "caveat": rep.get("caveat"),
            "baseline": row(base) if base else None,
            "choice": {**ch, "row": row(pts[ch["key"]]) if ch.get("key") in pts else None},
            "key_rows": [row(p) for p in sorted(keyrows, key=lambda p: -p["metrics"]["exact"])],
            "pareto": [row(p) for p in front[:12]],
            "worlds": [row(p) for p in sorted(comp, key=lambda p: (p["point"].get("levels", 5), -p["point"]["misspec"],
                                                                    -p["metrics"]["exact"]))],
            # чистка пула и добор у порогов (флаг ASSESSMENT_WEAK_EXCLUDE): строки двух миров и итог по данным
            "pool": {"rows": [{**row(p), "world_weak": bool(p["point"].get("weak_a")),
                               "plus": bool(p["point"].get("plus"))} for p in pool_rows(rep)],
                     **pool_verdict(rep)},
            "n_points": len(rep["points"])}


KEY_ROWS = ("прежняя конфигурация (P ≥ 0,8, до 10.10)", "порог уверенности P 0,5", "порог уверенности P 0,6", "порог уверенности P 0,7",
            "решение по лучшей оценке θ̂ (точечный грейд)", "дотестирование, заданий 12", "максимум заданий 20",
            "правило остановки se", "уровень выше в сессии (P) 0,8",
            "порог уверенности P 0,6; без семейств с низкой информацией (доля) 0,1",
            "решение по лучшей оценке θ̂ (точечный грейд); частичный балл: критериев 3")


# ---------------------------------------------------------------- документация

def _pc(v, d: int = 1) -> str:
    return "—" if v is None else f"{100 * v:.{d}f} %".replace(".", ",")


def _f(v, d: int = 3) -> str:
    return "—" if v is None else f"{v:.{d}f}".replace(".", ",")


def _diff(pt: dict, base: dict) -> str:
    parts = []
    for k in PARAMS:
        if pt[k] != base[k]:
            v = pt[k]
            if k == "decision":
                parts.append(DECISION_RU.get(v, v) if v != "point" else "решение по лучшей оценке θ̂ (точечный грейд)")
                continue
            if k in VALUE_RU:
                parts.append(VALUE_RU[k].get(v, f"{PARAM_RU[k]} {v}"))
                continue
            v = "нет" if v is None else (str(v).replace(".", ",") if isinstance(v, float) else str(v))
            parts.append(f"{PARAM_RU[k]} {v}")
    return "; ".join(parts) or "прежняя конфигурация (P ≥ 0,8, до 10.10)"


def _row(p: dict, base: dict) -> str:
    m = p["metrics"]
    mark = ("**допустима**" if m["feasible"] else "нет") + (" · Парето" if p.get("pareto") else "")
    return (f"| {_diff(p['point'], base)} | {_pc(m['exact'])} | {_pc(m['over'])} | {_pc(m['under'])} | "
            f"{_pc(m['none'])} | {_f(m['retest_kappa'])} | {_f(m['minutes_mean'], 1)} / {_f(m['minutes_p90'], 0)} | "
            f"{_f(m['items_mean'], 1)} | {mark} |")


POOL_KEYS = ("weak_pool", "plus")


def pool_rows(rep: dict, confirm: float = 0.6) -> list[dict]:
    """Точки «чистка пула / добор у порогов» при пороге confirm в двух мирах: слабые как в prior / на деле слабые."""
    out = []
    for p in rep["points"]:
        pt = p["point"]
        rest = {k: v for k, v in pt.items() if k not in (*POOL_KEYS, "weak_a", "confirm_level")}
        if (pt["confirm_level"] != confirm and not pt.get("plus")) or rest != {
                k: v for k, v in baseline_point().items() if k not in (*POOL_KEYS, "weak_a", "confirm_level")}:
            continue
        out.append(p)
    return sorted(out, key=lambda p: (p["point"]["weak_a"], int(p["point"].get("plus") or 0), p["point"]["confirm_level"],
                                      ("keep", "exclude", "down").index(p["point"]["weak_pool"])))


def pool_verdict(rep: dict) -> dict:
    """Итог чистки пула по данным: «исключить» лучше «оставить» по всем ограничениям в обоих мирах (на банке платформы
    и на банке с добором) и наибольший порог-кандидат для банка с добором, где завышение ≤ MAX_OVER в обоих мирах."""
    rows = pool_rows(rep)

    def get(wa, plus, cl, wp):
        return next((p["metrics"] for p in rows if p["point"]["weak_a"] == wa and int(p["point"].get("plus") or 0) == plus
                     and p["point"]["confirm_level"] == cl and p["point"]["weak_pool"] == wp), None)

    out: dict = {"exclude_better": {}, "plus_best_confirm": None}
    for plus in (0, 1):
        res = []
        for wa in (0.0, 0.4):
            k, e = get(wa, plus, 0.6, "keep"), get(wa, plus, 0.6, "exclude")
            if k and e:
                res.append(e["exact"] >= k["exact"] and e["over"] <= k["over"] and e["retest_kappa"] >= k["retest_kappa"])
        if len(res) == 2:
            out["exclude_better"]["plus" if plus else "platform"] = all(res)
    best = None
    for cl in sorted({p["point"]["confirm_level"] for p in rows if p["point"].get("plus")}):
        for wp in ("keep", "exclude"):
            ms = [get(wa, 1, cl, wp) for wa in (0.0, 0.4)]
            if all(ms) and all(m["feasible"] for m in ms):
                ex = min(m["exact"] for m in ms)
                if best is None or ex > best[2]:
                    best = (cl, wp, ex)
    if best:
        out["plus_best_confirm"] = {"confirm_level": best[0], "weak_pool": best[1]}
    return out


def pool_section(rep: dict, head: list[str], bp: dict) -> list[str]:
    rows = pool_rows(rep)
    if not rows:
        return []
    L = ["## Чистка пула и добор у порогов (флаг `ASSESSMENT_WEAK_EXCLUDE`)", "",
         "26 семейств, слабых по калибровке панелью моделей (модель, не люди), и 17 новых сильных семейств у порогов "
         "J/M и M/S (prior a = 1,3, исполняемый ключ; в продукт попадут с синхронизацией банка). Два мира: слабые "
         "семейства «как в prior» (панель ошиблась) и «на деле слабые» (истинная a = 0,4). Порог уверенности 0,6; для банка с "
         "добором — и другие пороги (какой держит завышение ≤ 7 % после синхронизации банка).", "",
         *head]
    L += [_row(p, bp) for p in rows]
    v = pool_verdict(rep)
    yn = {True: "да", False: "нет"}
    L += ["", "Правило: новое значение по умолчанию — только если лучше по всем ограничениям в обоих мирах. "
          "Флаг `ASSESSMENT_WEAK_EXCLUDE` (assessment/weak_pool.py) по умолчанию выключен.", ""]
    if v["exclude_better"]:
        L += [f"- Исключение лучше «оставить» по точности, завышению и κw в обоих мирах при P 0,6: банк платформы — "
              f"{yn.get(v['exclude_better'].get('platform'), '—')}; банк с добором — {yn.get(v['exclude_better'].get('plus'), '—')}. "
              "Причина «нет» — повтор (κw) и точность: меньше сменных семейств для второй попытки и у порогов."]
    if v["plus_best_confirm"]:
        c = v["plus_best_confirm"]
        L += [f"- После синхронизации банка с добором: наибольшая точность при завышении ≤ 7 % и κw ≥ 0,84 в обоих мирах — "
              f"P {str(c['confirm_level']).replace('.', ',')}, пул «{'исключить' if c['weak_pool'] == 'exclude' else 'оставить'}». "
              "Порог на стенде менять только после пересчёта path-retest на синхронизированном банке."]
    return L + [""]


def markdown(rep: dict) -> str:
    pts = {p["key"]: p for p in rep["points"]}
    base = pts[rep["baseline_key"]]
    bp = base["point"]
    ch = rep["choice"]
    sig = rep["signature"]
    c = rep["constraints"]
    head = ["| Отличие от текущей конфигурации | Точно | Выше | Ниже | Без категории | κw повтора | Минуты (ср. / p90) | "
            "Заданий | Ограничения |", "|---|---|---|---|---|---|---|---|---|"]
    L = ["# Точность уровня: перебор параметров теста (Парето)", "",
         f"Подпись мира: {sig['world']}; seed {sig['seed']}, конфигурация `{sig['config_hash']}`, коммит "
         f"`{sig['commit']}`, банк `{sig['bank']}`. Пересчёт: `{sig['command']}` (этапы screen, competitor, pool, time, "
         "refine — `SWEEP_ARGS=\"--stage <этап> --merge\"`; ≈ 30 мин на 8 ядрах сервера проверок).", "", f"> {rep['caveat']}", "",
         "Точка = вся процедура `make path-retest` (опрос → тест → решение → «уровень ниже» или тест ступенью ниже → "
         "повтор) с изменёнными параметрами; одни и те же кандидаты и ответы (общие случайные числа), поэтому разница "
         "между точками — от правил, а не от шума выборки.", "",
         f"Ограничения выбора: завышение (грейд выше истинного) ≤ {_pc(c['max_over'], 0)}, κw повтора всего пути ≥ "
         f"{_f(c['min_retest_kappa'], 2)}, время пути ≤ {_f(c['max_minutes_mean'], 0)} мин в среднем; цель — максимум "
         "точных попаданий в истинный уровень (первая попытка). Правило «Стажёр» (порог −1,75) не менялось.", "",
         "## Прежняя конфигурация (до 10.10)", "", *head, _row(base, bp), ""]
    m = base["metrics"]
    L += [f"Из «ниже истинного» {_pc(m['under'])} — {_pc(m['under_claimed_below'])} у тех, кто заявил грейд ниже "
          "своего уровня: тест подтверждает заявленный грейд и выше его не поднимает (смена грейда вверх — новым "
          "тестом). Остальное — правило P ≥ 0,8: у самой границы уровня подтверждение требует запаса.", ""]
    if ch.get("point"):
        cm = pts[ch["key"]]["metrics"]
        L += ["## Выбор", "", *head, _row(pts[ch["key"]], bp), "",
              f"- Точно: {_pc(cm['exact'])} {('[' + _pc(cm['exact_ci'][0]) + '; ' + _pc(cm['exact_ci'][1]) + ']') if cm.get('exact_ci') else ''}"
              f" против {_pc(m['exact'])}; завышение {_pc(cm['over'])} (ограничение ≤ {_pc(c['max_over'], 0)}); κw повтора "
              f"{_f(cm['retest_kappa'])} {('[' + _f(cm['retest_kappa_ci'][0]) + '; ' + _f(cm['retest_kappa_ci'][1]) + ']') if cm.get('retest_kappa_ci') else ''}; "
              f"минут на путь {_f(cm['minutes_mean'], 1)}.",
              f"- Лучше текущей по всем ограничениям: {'да' if ch['better_on_all'] else 'нет'}.", ""]
    L += pool_section(rep, head, bp)
    front = [pts[k] for k in rep["pareto"]]
    front.sort(key=lambda p: -p["metrics"]["exact"])
    L += ["## Парето-фронт (недоминируемые по точности, завышению, κw и минутам)", "", *head]
    L += [_row(p, bp) for p in front]
    L += ["", "## Все точки", "", *head]
    L += [_row(p, bp) for p in sorted(rep["points"], key=lambda p: -p["metrics"]["exact"])]
    L += ["", "Полные данные: `backend/app/modules/validation/data/grade_sweep.json`.", ""]
    return "\n".join(L)


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        return _worker(sys.argv[2], sys.argv[3])
    ap = argparse.ArgumentParser(description="Перебор параметров теста ради точности уровня → data/grade_sweep.json")
    ap.add_argument("--stage", default="all", help="screen | grid | all | none")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--points", default=None, help="JSON-файл со списком дополнительных точек (частичные словари)")
    ap.add_argument("--merge", action="store_true", help="дописать к уже посчитанным точкам data/grade_sweep.json")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--export-plus", default=None, metavar="FAMILIES_DIR",
                    help="снимок предкалибровки семейств добора из каталога families банка → data/bank_plus_core.json")
    ap.add_argument("--export-commit", default="?")
    a = ap.parse_args()
    if a.export_plus:
        print("→", export_plus(a.export_plus, a.export_commit))
        return 0
    stages = list(STAGES) if a.stage == "all" else ([] if a.stage == "none" else a.stage.split(","))
    extra = [_p(**e) for e in json.loads(Path(a.points).read_text(encoding="utf-8"))] if a.points else None
    rep = run(stages, a.n, a.workers, not a.no_write, extra, a.merge)
    print("выбор:", json.dumps(rep["choice"], ensure_ascii=False))
    pts = {p["key"]: p for p in rep["points"]}
    for p in sorted(rep["points"], key=lambda p: -p["metrics"]["exact"])[:40]:
        m = p["metrics"]
        print(f"  {m['exact']:.3f} выше {m['over']:.3f} ниже {m['under']:.3f} нет {m['none']:.3f} ±1 {m['within_1']:.3f} "
              f"κw {m['retest_kappa']:.3f} мин {m['minutes_mean']:.1f}/{m['minutes_p90']:.0f} гр {m['borderline']:.2f} "
              f"{'OK' if m['feasible'] else '--'} {_diff(p['point'], baseline_point())}")
    _ = pts
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
