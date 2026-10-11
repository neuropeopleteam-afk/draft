"""Путь-повтор с 6 уровнями (Стажёр … Senior, Lead, Principal) — симуляция до появления семейств Lead/Principal в банке.

    make grades-ext-sim      # cd backend && GRADES_EXT_ENABLED=1 python -m app.modules.validation.grades_ext_sim

Зачем. Решение владельца 10.10 (вариант Б): 6 уровней. FTT.4 — уровень только по тесту, поэтому до продукта нужно
знать, насколько точно тест различает Senior / Lead / Principal при том банке, который ожидается (≈ 6 общих семейств +
3 на направление: 2 Lead, 1 Principal), и при каких порогах θ.

Как. Тот же путь кандидата и те же функции продукта, что ``path_retest`` (опрос → заявленный уровень → адаптивный тест
на банке с классификационной остановкой, дотестированием у порога, Sympson — Hetter, ротацией субпулов → решение
``grades.decide_grade`` P ≥ 0,8 → «принять уровень ниже» или тест ступенью ниже → повтор с историей), на шкале из
6 уровней (флаг GRADES_EXT_ENABLED). Банку добавлены **модельные** семейства Lead/Principal (не задания банка, а их
параметры): копии самых трудных семейств направления и общего блока (формат, время, число частей) с трудностью
b ~ U(1,8; 2,5) для Lead и U(2,5; 3,1) для Principal и наклоном a (по умолчанию 1,5 — «высокая различающая
способность у границ», цель карточки банка). Истинные параметры = авторские + ошибка эксперта σ = 0,5 (как везде на
/validation). Два мира: «популяция» θ ~ N(0; 1) (как TEST_RETEST) и «верх» θ ~ U(0,5; 3,75) — чтобы по Senior, Lead,
Principal было достаточно кандидатов для чисел по каждому уровню. Всё синтетическое — модель, не люди: проверяется
механика процедуры и порогов, а не качество заданий.

Варианты: пороги Lead/Principal (по умолчанию 2,0 / 2,75 и соседние) и размер банка (ожидаемый и вдвое больше).
Итог — data/grades_ext_sim.json и docs/validation/GRADES_EXT.md. Тяжёлое — на сервере проверок (bin/remote-make).
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import numpy as np

from app.modules.catalog import seed_data

if not seed_data.GRADES_EXT:  # шкала 6 уровней берётся из seed_data при импорте
    raise SystemExit("grades_ext_sim: запускать с GRADES_EXT_ENABLED=1 (make grades-ext-sim)")

from assessment_bank.psychometrics import CanaryDetector, ExposureControl  # noqa: E402
from assessment_bank.simulation import make_truth  # noqa: E402

from app.modules.assessment import grades as grades_mod  # noqa: E402
from app.modules.assessment.exposure import exposure_table  # noqa: E402
from app.modules.assessment.grade_hint import grade_by_years  # noqa: E402
from app.modules.validation import path_retest as pr  # noqa: E402
from app.modules.validation import sim  # noqa: E402
from app.modules.validation.signature import signature  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
OUT = HERE / "data" / "grades_ext_sim.json"
DOCS_MD = REPO / "docs" / "validation" / "GRADES_EXT.md"
SEED = 20261010
LEVELS = ("none",) + seed_data.GRADE_ORDER
LEVEL_RU = {"none": "без категории", **seed_data.ALL_GRADES}
WORLDS = {"pop": "популяция θ ~ N(0; 1)", "top": "верх θ ~ U(0,5; 3,75)"}
# Ожидаемый банк (карточка банка волны 7): общий блок ≈ 6 (4 Lead, 2 Principal), направление — 2 Lead и 1 Principal
BANKS = {"expected": {"own_lead": 2, "own_principal": 1, "common_lead": 4, "common_principal": 2},
         "double": {"own_lead": 4, "own_principal": 2, "common_lead": 8, "common_principal": 4}}
CUT_VARIANTS = {"2.0/3.0": (2.0, 3.0), "2.0/2.75": (2.0, 2.75), "1.75/2.5": (1.75, 2.5), "2.25/3.0": (2.25, 3.0)}
B_RANGE = {"lead": (1.8, 2.5), "principal": (2.5, 3.1)}


# ---------------------------------------------------------------- модельные семейства Lead/Principal

def model_families(pool, directions, bank: dict, a_ext: float, n_subpools: int, rng: np.random.Generator) -> list:
    """Копии самых трудных семейств блока с трудностью уровня Lead/Principal (модель, не банк)."""
    out = []
    blocks = [("common", "common")] + [(d, d) for d in directions]
    for block, label in blocks:
        src = sorted([p for p in pool if p.block == block and not p.canary], key=lambda p: -float(np.mean(p.b)))[:6]
        if not src:
            continue
        for g in ("lead", "principal"):
            n = bank[("common_" if block == "common" else "own_") + g]
            for k in range(n):
                base = src[k % len(src)]
                it = deepcopy(base)
                lo, hi = B_RANGE[g]
                target = float(rng.uniform(lo, hi))
                it.b = np.asarray(base.b, dtype=float) - float(np.mean(base.b)) + target
                it.a = np.full_like(np.asarray(base.a, dtype=float), a_ext)
                it.family_id = f"model.{g}.{label}.{k + 1}"
                it.grades = (g,)
                it.subpool = k % max(1, n_subpools)
                out.append(it)
    return out


# ---------------------------------------------------------------- кандидаты

def make_candidates(n: int, direction: str, world: str, rng: np.random.Generator) -> list[pr.Candidate]:
    out = []
    for _ in range(n):
        th = float(rng.normal()) if world == "pop" else float(rng.uniform(0.5, 3.75))
        tau = float(rng.normal(0, 0.3))
        years = pr.survey_years(th, rng)
        hint = grade_by_years(years, top="principal")
        sg = grades_mod.point_grade(th + float(rng.normal(0, pr.SELF_SD)))
        sg = "intern" if sg == "none" else sg
        if rng.random() < pr.P_FOLLOW_HINT:
            claimed = "intern" if (hint == "junior" and sg == "intern" and years < 0.5) else hint
        else:
            claimed = sg
        stack: list[str] = []
        if rng.random() < 0.4:
            stack.append("docker")
        out.append(pr.Candidate(th, tau, direction, years, hint, sg, claimed, stack))
    return out


# ---------------------------------------------------------------- один рабочий прогон (процесс на направление)

def set_cuts(lead: float, principal: float) -> None:
    for d in (seed_data.GRADE_CUTS, seed_data.ALL_GRADE_CUTS):
        d["lead"], d["principal"] = lead, principal
    for d in (seed_data.GRADE_START_THETA, seed_data.ALL_GRADE_START_THETA):
        d["lead"], d["principal"] = round(lead + 0.4, 2), round(principal + 0.3, 2)  # как ALL_GRADE_START_THETA
    grades_mod.scale.cache_clear()


def patch_ext_sessions(prior_sd: float, no_subpool: bool) -> None:
    """Сессии с заявленным Lead/Principal — как в продукте (bank_engine): своё априорное SD оценки θ
    (GRADES_EXT_PRIOR_SD) и без ротации субпулов (GRADES_EXT_NO_SUBPOOL: трудных семейств мало, как у Стажёра)."""
    from dataclasses import replace

    orig = sim.run_session

    def run_session(pool, direction, responder, cfg, exposure, claimed, subpool, rng, **kw):
        if claimed in seed_data.EXT_GRADE_ORDER:
            cfg2 = replace(cfg)
            base_cat = cfg.cat
            object.__setattr__(cfg2, "cat", lambda: replace(base_cat(), prior_sd=prior_sd))
            cfg = cfg2
            if no_subpool:
                subpool = None
        return orig(pool, direction, responder, cfg, exposure, claimed, subpool, rng, **kw)

    sim.run_session = run_session


def worker(args) -> dict:
    lead, principal = CUT_VARIANTS[args.cuts]
    set_cuts(lead, principal)
    patch_ext_sessions(args.ext_prior_sd, args.ext_subpool == "none")
    cfg = sim.app_config_from_settings()  # пороги CAT — cuts_tuple() после set_cuts
    base = sim.make_pool(cfg.subpools)
    i = sim.DIRECTIONS.index(args.direction)
    rng0 = np.random.default_rng([SEED, i, list(WORLDS).index(args.world), list(BANKS).index(args.bank)])
    extra = model_families(base, sim.DIRECTIONS, BANKS[args.bank], args.a_ext, cfg.subpools,
                           np.random.default_rng([SEED, 77, list(BANKS).index(args.bank)]))
    pool = list(base) + extra
    truth = make_truth(pool, rng0, misspec=0.5)
    cands = make_candidates(args.n, args.direction, args.world, rng0)
    k = (exposure_table() or {}).get("k", {}).get(args.direction, {})
    counter = ExposureControl(0.3, k=dict(k))
    det = CanaryDetector()
    rng = np.random.default_rng([SEED, i, 1, list(WORLDS).index(args.world), list(BANKS).index(args.bank)])
    rows = []
    for c in cands:
        hist: list[dict] = []
        r1 = pr.run_path(pool, c, truth, cfg, counter, hist, rng, det)
        r2 = pr.run_path(pool, c, truth, cfg, counter, hist, rng, det)
        rows.append({"theta": c.theta, "true": LEVELS.index(grades_mod.point_grade(c.theta)), "claimed": c.claimed,
                     "l1": r1["level"], "l2": r2["level"], "s1": r1["status"],
                     "t1": sum(t["time_s"] for t in r1["tests"]) / 60.0, "n1": sum(t["n_items"] for t in r1["tests"]),
                     "se1": r1["tests"][0]["se"], "th1": r1["tests"][0]["theta"],
                     "n_model": sum(1 for f in r1["tests"][0]["families"] if f.startswith("model.")),
                     "conf1": bool(r1["tests"][0]["confirmed"])})
    return {"direction": args.direction, "world": args.world, "cuts": args.cuts, "bank": args.bank, "rows": rows,
            "n_model_families": len(extra), "psd": args.ext_prior_sd, "sp": args.ext_subpool}


# ---------------------------------------------------------------- метрики

def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    true = np.array([r["true"] for r in rows])
    l1, l2 = np.array([r["l1"] for r in rows]), np.array([r["l2"] for r in rows])
    has = l1 > 0
    out = {"n": len(rows),
           "exact": round(float(np.mean(l1 == true)), 3),
           "above": round(float(np.mean(l1 > true)), 3),
           "below": round(float(np.mean((l1 < true) & has)), 3),
           "none": round(float(np.mean(~has)), 3),
           "within_1": round(float(np.mean(np.abs(l1 - true) <= 1)), 3),
           "retest_exact": round(float(np.mean(l1 == l2)), 3),
           "kappa_w_retest": round(pr.kappa_w(l1, l2, k=len(LEVELS)), 3) if len(rows) > 1 else None,
           "kappa_w_true": round(pr.kappa_w(true, l1, k=len(LEVELS)), 3) if len(rows) > 1 else None,
           "minutes_mean": round(float(np.mean([r["t1"] for r in rows])), 1),
           "minutes_p90": round(float(np.percentile([r["t1"] for r in rows], 90)), 1),
           "items_mean": round(float(np.mean([r["n1"] for r in rows])), 1),
           "se_mean": round(float(np.mean([r["se1"] for r in rows])), 3)}
    by = {}
    for lv, name in enumerate(LEVELS):
        m = true == lv
        if m.sum() == 0:
            continue
        g = l1[m]
        by[name] = {"n": int(m.sum()), "exact": round(float(np.mean(g == lv)), 3),
                    "above": round(float(np.mean(g > lv)), 3), "below": round(float(np.mean((g < lv) & (g > 0))), 3),
                    "none": round(float(np.mean(g == 0)), 3),
                    "retest_exact": round(float(np.mean(l1[m] == l2[m])), 3),
                    # куда попали: доли по присвоенным уровням
                    "assigned": {LEVELS[j]: round(float(np.mean(g == j)), 3) for j in range(len(LEVELS)) if np.any(g == j)}}
    out["by_true_level"] = by
    # Сам тест, без поведения в опросе: кандидаты, заявившие ровно свой истинный уровень — доля подтверждения с первой
    # попытки, смещение θ̂ первой сессии, SE и число модельных заданий Lead/Principal в ней
    same = {}
    for lv, name in enumerate(LEVELS):
        rs = [r for r in rows if r["true"] == lv and r["claimed"] == name]
        if len(rs) < 5:
            continue
        same[name] = {"n": len(rs), "confirmed_first": round(float(np.mean([r["conf1"] for r in rs])), 3),
                      "exact": round(float(np.mean([r["l1"] == lv for r in rs])), 3),
                      "bias_theta": round(float(np.mean([r["th1"] - r["theta"] for r in rs])), 3),
                      "se": round(float(np.mean([r["se1"] for r in rs])), 3),
                      "model_items": round(float(np.mean([r["n_model"] for r in rs])), 2)}
    out["claimed_true"] = same
    out["claimed_share"] = {g: round(float(np.mean([r["claimed"] == g for r in rows])), 3) for g in LEVELS[1:]}
    # завышение относительно соседей: присвоен Lead/Principal при истинном ниже
    for g in ("lead", "principal"):
        j = LEVELS.index(g)
        got = l1 == j
        out[f"precision_{g}"] = round(float(np.mean(true[got] == j)), 3) if got.any() else None
        out[f"assigned_{g}"] = int(got.sum())
    return out


def run(n: int, quick: bool, parallel: int, a_ext: float, variants: list[str], banks: list[str],
        worlds: list[str], write: bool = True, merge: bool = False, psds: tuple[float, ...] = (1.0,),
        sps: tuple[str, ...] = ("split",)) -> dict:
    t0 = time.time()
    dirs = sim.DIRECTIONS[:2] if quick else sim.DIRECTIONS
    jobs = [(cv, b, w, d, ps, sp) for cv in variants for b in banks for w in worlds for ps in psds for sp in sps
            for d in dirs]
    tmp = Path(tempfile.mkdtemp(prefix="gext_"))
    procs: list[tuple[subprocess.Popen, Path]] = []
    results = []
    env = {**os.environ, "GRADES_EXT_ENABLED": "1"}
    pending = list(jobs)
    while pending or procs:
        while pending and len(procs) < parallel:
            cv, b, w, d, ps, sp = pending.pop(0)
            out = tmp / f"{cv.replace('/', '_')}_{b}_{w}_{ps}_{sp}_{d}.json"
            p = subprocess.Popen([sys.executable, "-m", "app.modules.validation.grades_ext_sim", "--worker",
                                  "--cuts", cv, "--bank", b, "--world", w, "--direction", d, "--n", str(n),
                                  "--a-ext", str(a_ext), "--ext-prior-sd", str(ps), "--ext-subpool", sp,
                                  "--out", str(out)], env=env)
            procs.append((p, out))
        time.sleep(0.5)
        for p, out in list(procs):
            if p.poll() is not None:
                procs.remove((p, out))
                if p.returncode != 0:
                    raise SystemExit(f"рабочий процесс упал: {out.name} (код {p.returncode})")
                results.append(json.loads(out.read_text()))
                print(f"  готово {out.name} ({time.time() - t0:.0f} с)", flush=True)
    rep = {"variants": {}}
    for cv in variants:
        for b in banks:
            for w in worlds:
                for ps in psds:
                    for sp in sps:
                        rows = [r for x in results if (x["cuts"], x["bank"], x["world"], x["psd"], x["sp"])
                                == (cv, b, w, ps, sp) for r in x["rows"]]
                        key = f"{cv}|{b}|{w}|sd{ps}|{sp}"
                        rep["variants"][key] = {"cuts": dict(zip(("lead", "principal"), CUT_VARIANTS[cv], strict=True)),
                                                "bank": b, "world": w, "prior_sd": ps, "subpool": sp, **summarize(rows)}
    world_cfg = {"n_per_direction": n, "directions": list(dirs), "a_ext": a_ext, "banks": {b: BANKS[b] for b in banks},
                 "b_range": B_RANGE, "misspec": 0.5, "cuts_base": {g: seed_data.ALL_GRADE_CUTS[g] for g in LEVELS[1:5]},
                 "worlds": {w: WORLDS[w] for w in worlds}}
    rep["signature"] = signature(seed=SEED, config=world_cfg, n=n * len(dirs),
                                 world=f"симуляция теста с 6 уровнями: {len(dirs)} направлений × {n} кандидатов на мир; "
                                       "семейства Lead/Principal — модельные (не банк)",
                                 command="make grades-ext-sim" if not quick else
                                 "GRADES_EXT_ENABLED=1 python -m app.modules.validation.grades_ext_sim --quick")
    rep["config"] = world_cfg
    rep["quick"] = quick
    rep["seconds"] = round(time.time() - t0, 1)
    rep["caveat"] = ("Модель, не люди: синтетические кандидаты; семейства Lead/Principal — модельные копии трудных семейств "
                     "банка с заданной трудностью и наклоном; ошибка эксперта σ = 0,5. Числа показывают механику порогов и "
                     "ожидаемого размера банка, а не качество будущих заданий; после семейств Lead/Principal в банке — "
                     "пересчёт на банке (тот же скрипт без модельных семейств — путь-повтор make path-retest с флагом).")
    if write:
        if merge and OUT.exists():  # дописать варианты к прошлому прогону (тот же мир и seed)
            old = json.loads(OUT.read_text(encoding="utf-8"))
            rep["variants"] = {**old.get("variants", {}), **rep["variants"]}
            rep["runs"] = old.get("runs", [old.get("signature")]) + [rep["signature"]]
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        DOCS_MD.write_text(markdown(rep), encoding="utf-8")
    return rep


def _p(v) -> str:
    return "—" if v is None else f"{v * 100:.1f} %".replace(".", ",")


def _n(v, d: int = 1) -> str:
    return "—" if v is None else f"{v:.{d}f}".replace(".", ",")


def markdown(rep: dict) -> str:
    sig = rep["signature"]
    L = ["# Уровни Lead и Principal: путь-повтор с 6 уровнями (симуляция)", "",
         "> " + rep["caveat"], "",
         f"Подпись: {sig.get('world')}; seed {sig.get('seed')}; коммит {sig.get('commit') or '—'}; "
         f"команда `{sig.get('command')}`.", "",
         "Путь кандидата — как в TEST_RETEST.md (те же функции продукта): опрос → заявленный уровень → адаптивный тест "
         "(классификационная остановка, дотестирование у ближайшего порога, в том числе Senior/Lead и Lead/Principal) → "
         "решение P ≥ 0,8 → «принять уровень ниже» или тест ступенью ниже; повтор — с историей первой попытки. "
         "Lead и Principal присваивает только полный тест (не меньше 8 оценённых заданий, SE ≤ 0,6).", "",
         "## Итог по вариантам", "",
         "| Пороги Lead/Principal | Банк | Мир | SD априори (Lead/Principal) | Субпулы | n | Точно | Выше | Ниже | Без кат. | ±1 | Совпадение повтора | κw повтора | "
         "Присвоено Lead (из них верно) | Присвоено Principal (верно) | Мин (ср./p90) |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for v in rep["variants"].values():
        L.append(f"| {_n(v['cuts']['lead'], 2)} / {_n(v['cuts']['principal'], 2)} | {v['bank']} | {v['world']} | "
                 f"{_n(v.get('prior_sd', 1.0))} | {'без ротации' if v.get('subpool') == 'none' else 'ротация'} | {v['n']} | "
                 f"{_p(v['exact'])} | {_p(v['above'])} | {_p(v['below'])} | {_p(v['none'])} | {_p(v['within_1'])} | "
                 f"{_p(v['retest_exact'])} | {_n(v['kappa_w_retest'], 3)} | {v['assigned_lead']} ({_p(v['precision_lead'])}) | "
                 f"{v['assigned_principal']} ({_p(v['precision_principal'])}) | {_n(v['minutes_mean'])} / {_n(v['minutes_p90'])} |")
    L += ["", "## По истинному уровню", ""]
    for key, v in rep["variants"].items():
        L += [f"### Пороги {_n(v['cuts']['lead'], 2)} / {_n(v['cuts']['principal'], 2)}, банк {v['bank']}, "
              f"{WORLDS.get(v['world'], v['world'])}, SD априори {_n(v.get('prior_sd', 1.0))}, "
              f"{'без ротации субпулов' if v.get('subpool') == 'none' else 'ротация субпулов'}", "",
              "| Истинный уровень | n | Точно | Выше | Ниже | Без кат. | Совпадение повтора | Куда попали |", "|---|---|---|---|---|---|---|---|"]
        for lv, b in v.get("by_true_level", {}).items():
            where = ", ".join(f"{LEVEL_RU.get(k, k)} {_p(x)}" for k, x in b["assigned"].items())
            L.append(f"| {LEVEL_RU.get(lv, lv)} | {b['n']} | {_p(b['exact'])} | {_p(b['above'])} | {_p(b['below'])} | "
                     f"{_p(b['none'])} | {_p(b['retest_exact'])} | {where} |")
        L.append("")
        cs = v.get("claimed_true") or {}
        if cs:
            L += ["Заявили свой истинный уровень (качество самого теста, без поведения в опросе):", "",
                  "| Уровень | n | Подтверждён с первой попытки | Итог точно | Смещение θ̂ | SE | Заданий Lead/Principal в сессии |",
                  "|---|---|---|---|---|---|---|"]
            for lv, b in cs.items():
                L.append(f"| {LEVEL_RU.get(lv, lv)} | {b['n']} | {_p(b['confirmed_first'])} | {_p(b['exact'])} | "
                         f"{_n(b['bias_theta'], 2)} | {_n(b['se'], 2)} | {_n(b['model_items'], 1)} |")
            L.append("")
    L += ["Банк «expected» — ожидаемый по карточке банка: общий блок 4 Lead + 2 Principal, направление 2 Lead + 1 Principal; "
          "«double» — вдвое больше. Семейства делятся между двумя субпулами, как и остальные.", ""]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--parallel", type=int, default=max(1, (os.cpu_count() or 2) - 0))
    ap.add_argument("--a-ext", type=float, default=1.5)
    ap.add_argument("--variants", default=",".join(CUT_VARIANTS))
    ap.add_argument("--banks", default=",".join(BANKS))
    ap.add_argument("--worlds", default=",".join(WORLDS))
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--merge", action="store_true", help="дописать варианты к data/grades_ext_sim.json")
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--cuts", default="2.0/3.0")
    ap.add_argument("--bank", default="expected")
    ap.add_argument("--world", default="top")
    ap.add_argument("--direction", default="backend")
    ap.add_argument("--out")
    ap.add_argument("--ext-prior-sd", type=float, default=1.0)
    ap.add_argument("--ext-subpool", default="split", choices=("split", "none"))
    ap.add_argument("--psds", default="1.0", help="варианты априорного SD для заявленных Lead/Principal")
    ap.add_argument("--sps", default="split", help="split | none — субпулы для заявленных Lead/Principal")
    a = ap.parse_args()
    if a.worker:
        res = worker(a)
        Path(a.out).write_text(json.dumps(res), encoding="utf-8")
        return 0
    n = min(a.n, 40) if a.quick else a.n
    rep = run(n, a.quick, a.parallel, a.a_ext, a.variants.split(","), a.banks.split(","), a.worlds.split(","),
              write=not a.no_write, merge=a.merge, psds=tuple(float(x) for x in a.psds.split(",")),
              sps=tuple(a.sps.split(",")))
    for key, v in rep["variants"].items():
        print(f"{key}: точно {v['exact']}, выше {v['above']}, ниже {v['below']}, без {v['none']}, κw {v['kappa_w_retest']}, "
              f"Lead {v['assigned_lead']} ({v['precision_lead']}), Principal {v['assigned_principal']} ({v['precision_principal']})")
    print(f"{rep['seconds']} с")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
