"""Доля повторов заданий между попытками теста (И26): живая по базе и синтетика по протоколу продукта.

Протокол продукта с 09.10 (service.seen_families → bank_engine → exposure.AppCATSession): повтор идёт из следующего
активного субпула (их два — параллельные формы); семейства ВСЕХ прошлых попыток по направлению не берутся ни в основную
часть, ни в дотестирование. Запасной путь, когда новых нет: новые семейства других субпулов, затем — виденные давнее
всего (LRU) с новым вариантом; в дотестировании у порога LRU — без семейств последней попытки. У каждого показа свой
случайный seed варианта (bank_engine.SEED_MIN…SEED_MAX), повтор семейства — всегда новый вариант.
Для сравнения тот же мир считается по протоколу до 09.10 («до»): исключались только семейства последней попытки и
только из дотестирования — третья попытка возвращалась в субпул первой и повторяла большую часть её семейств.

Синтетика: тот же класс сессии и конфигурация, что в продукте (validation/sim.py), истинные параметры заданий =
предкалибровка + ошибка эксперта σ = 0,5, θ ~ N(0, 1), K_f частоты показа — из exposure_k.json. Контрольные
задания (канарейки) в подсчёт не входят. Это модель, не люди. Там же — парная проверка test–retest первых двух
попыток «до» и «после» (одни люди и seed, отдельный генератор на человека): сдвинулись ли цифры /validation.

Пересчёт: ``python -m app.modules.validation.attempts_repeat [--n 200] [--retest-n 400]`` → data/attempts_repeat.json.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "attempts_repeat.json"
SEED = 20261006
COMMAND = "python -m app.modules.validation.attempts_repeat"
WORLD = ("синтетика: θ ~ N(0, 1), истинные параметры = предкалибровка + ошибка эксперта σ = 0,5; "
         "конфигурация теста продукта, 2 субпула, K_f из exposure_k.json")


def _signature(*, seed, config: dict, world: str, command: str, n: int | None = None) -> dict:
    """Подпись мира — та же форма, что validation/signature.py (feat/validation); до слияния — своя копия."""
    try:
        from app.modules.validation.signature import signature  # type: ignore[import-not-found]

        return signature(seed=seed, config=config, world=world, command=command, n=n)
    except ImportError:
        pass
    commit = (os.environ.get("GIT_COMMIT") or "").strip()[:12]
    if not commit:
        try:
            r = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=HERE, capture_output=True, text=True,
                               timeout=5)
            commit = r.stdout.strip() if r.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            commit = ""
    try:
        bank = json.loads((HERE.parents[2] / "assessment_bank" / "BANK_SYNC.json").read_text("utf-8")).get("content_hash")
    except (OSError, ValueError):
        bank = None
    return {"world": world, "seed": seed,
            "config_hash": hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:12],
            "commit": commit or "unknown", "bank": bank, "n": n, "command": command,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


# ------------------------------------------------------------------ подсчёт

def pair_stats(pairs: list[tuple[set, set]]) -> dict:
    """pairs — (семейства ранней попытки, семейства поздней). Доля — от заданий поздней попытки."""
    if not pairs:
        return {"n_pairs": 0, "share_families": None, "share_pairs_with_repeat": None, "mean_repeated": None,
                "max_share": None}
    shares = [len(a & b) / len(b) for a, b in pairs if b]
    rep = [len(a & b) for a, b in pairs]
    tot_b = sum(len(b) for _, b in pairs)
    return {"n_pairs": len(pairs),
            "share_families": round(sum(rep) / tot_b, 4) if tot_b else None,  # пул: все повторы / все задания
            "share_pairs_with_repeat": round(sum(1 for r in rep if r) / len(pairs), 4),
            "mean_repeated": round(sum(rep) / len(pairs), 3),
            "max_share": round(max(shares), 4) if shares else None}


def live(db: Session, limit: int = 5000) -> dict:
    """По базе: последовательные завершённые сессии банка одного пользователя и направления (полный и экспресс;
    дотестирование — продолжение попытки, не повтор). Без канареек."""
    from app.core.enums import TestSessionStatus
    from app.modules.assessment.attempts import attempt_view
    from app.modules.assessment.models import TestSession

    rows = db.scalars(select(TestSession).where(TestSession.status == TestSessionStatus.finished)
                      .order_by(TestSession.finished_at.desc()).limit(limit)).all()
    by: dict[tuple, list] = {}
    for t in rows:
        r = t.result or {}
        if "items" not in (r.get("state") or {}) or not r.get("engine_result"):
            continue
        v = attempt_view(t)
        if v["mode"] == "confirm":
            continue
        by.setdefault((t.user_id, t.direction_id), []).append((t.finished_at, v))
    fam, var = [], []
    users = 0
    for seq in by.values():
        if len(seq) < 2:
            continue
        users += 1
        seq.sort(key=lambda x: x[0])
        for (_, a), (_, b) in zip(seq, seq[1:]):
            fam.append((set(a["families"]), set(b["families"])))
            var.append((set(a["variants"]), set(b["variants"])))
    fs, vs = pair_stats(fam), pair_stats(var)
    return {"n_pairs": fs["n_pairs"], "n_people": users, "families": fs, "variants": vs,
            "conditions": "по базе этого стенда: все завершённые сессии банка заданий (включая демо-песочницы жюри "
                          "и демо-респондентов сида), пары последовательных попыток одного человека в одном "
                          "направлении; полный тест и экспресс, без дотестирования; контрольные задания не считаются"}


def _seen(history: list[list[str]]) -> dict[str, int]:
    """Как service.seen_families: семейство → номер самой поздней попытки с ним (0 — последняя)."""
    return {f: age for age, fams in reversed(list(enumerate(history))) for f in fams}


def _attempts(pool, truth, people, d, cfg, rng, k, n_att: int, protocol: str) -> list[list[set]]:
    """n_att попыток подряд; субпулы — по exposure.choose_subpool (0, 1, 0, 1 …). protocol: after (с 09.10) | before."""
    from app.modules.validation import sim

    n = len(people)
    hist: list[list[list[str]]] = [[] for _ in range(n)]  # по человеку: семейства попыток, последняя первой
    out = []
    for att in range(n_att):
        sp = [att % max(cfg.subpools, 1)] * n
        if protocol == "after":
            r = sim.run_population(pool, truth, people, d, cfg, rng, k=k, subpools=sp, seen=[_seen(h) for h in hist])
        else:
            r = sim.run_population(pool, truth, people, d, cfg, rng, k=k, subpools=sp,
                                   exclude=[set(h[0]) for h in hist] if att else None)
        for j, x in enumerate(r):
            hist[j].insert(0, x["families"])
        out.append([set(x["families"]) for x in r])
    return out


def _pairs(f: list[list[set]]) -> dict[str, list[tuple[set, set]]]:
    n = len(f[0])
    out = {"12": list(zip(f[0], f[1])), "23": list(zip(f[1], f[2])), "13": list(zip(f[0], f[2]))}
    if len(f) > 3:
        out["14"] = list(zip(f[0], f[3]))
        out["4any"] = [(f[0][j] | f[1][j] | f[2][j], f[3][j]) for j in range(n)]
    return out


KEYS = {"12": "second_vs_first", "23": "third_vs_second", "13": "third_vs_first", "14": "fourth_vs_first",
        "4any": "fourth_vs_any_previous"}
RETEST_KEYS = ("r_theta", "icc_theta", "grade_exact_agreement", "grade_kappa_quadratic", "decision_agreement",
               "loa_theta", "mean_items", "extension_share")


def retest_check(n: int = 400, directions: tuple[str, ...] | None = None) -> dict:
    """Test–retest первых двух попыток «до» и «после» парно: те же люди и мир, что в make validate
    (default_rng([20261006, направление, 0])), у каждого человека свой генератор — у второй попытки обеих версий
    одинаковое состояние; разница — только от исключения семейств первой попытки в основной части."""
    import copy

    import numpy as np
    from assessment_bank.simulation import make_population, make_truth

    from app.modules.assessment.exposure import exposure_table
    from app.modules.validation import sim

    cfg = sim.app_config_from_settings()
    pool = sim.make_pool(cfg.subpools)
    k_all = (exposure_table() or {}).get("k", {})
    A1, B0, B1, P, same, per = [], [], [], [], 0, {}
    for i, d in enumerate(directions or sim.DIRECTIONS):
        rng0 = np.random.default_rng([SEED, i, 0])
        truth = make_truth(pool, rng0, misspec=0.5)
        make_population(n, rng0)
        people = make_population(n, rng0)  # как rt_people в validation/__main__
        k = k_all.get(d, {})
        a1, b0, b1 = [], [], []
        for j, p in enumerate(people):
            rng = np.random.default_rng([SEED, i, 2, j])
            a = sim.run_population(pool, truth, [p], d, cfg, rng, k=k, subpools=[0])[0]
            rb = copy.deepcopy(rng)
            b0.append(sim.run_population(pool, truth, [p], d, cfg, rng, k=k, subpools=[1], exclude=[set(a["families"])])[0])
            b1.append(sim.run_population(pool, truth, [p], d, cfg, rb, k=k, subpools=[1],
                                         seen=[{f: 0 for f in a["families"]}])[0])
            a1.append(a)
        same_d = sum(1 for x, y in zip(b0, b1) if x["families"] == y["families"])
        m0, m1 = sim.retest_metrics(people, a1, b0), sim.retest_metrics(people, a1, b1)
        per[d] = {"same_second_attempt": same_d, "before": {q: m0[q] for q in RETEST_KEYS},
                  "after": {q: m1[q] for q in RETEST_KEYS}}
        same += same_d
        A1 += a1; B0 += b0; B1 += b1; P += people
    m0, m1 = sim.retest_metrics(P, A1, B0), sim.retest_metrics(P, A1, B1)
    return {"n_pairs": len(P), "same_second_attempt": same, "same_share": round(same / len(P), 4),
            "before": {q: m0[q] for q in RETEST_KEYS}, "after": {q: m1[q] for q in RETEST_KEYS},
            "directions": per,
            "note": "парно: те же люди, мир и генератор; вторая попытка «после» отличается только у тех, у кого "
                    "дотестирование первой брало семейства второго субпула"}


def simulate(n: int = 200, directions: tuple[str, ...] | None = None, retest_n: int = 400) -> dict:
    """Синтетика: четыре попытки подряд по протоколу продукта («после», с 09.10) и три — по прежнему («до»)
    на одних и тех же людях каждого направления; плюс парная проверка test–retest."""
    import numpy as np
    from assessment_bank.simulation import make_population, make_truth

    from app.modules.assessment.bank_engine import SEED_MAX, SEED_MIN
    from app.modules.assessment.exposure import exposure_table
    from app.modules.validation import sim

    cfg = sim.app_config_from_settings()
    pool = sim.make_pool(cfg.subpools)
    k_all = (exposure_table() or {}).get("k", {})
    dirs = directions or sim.DIRECTIONS
    t0 = time.time()
    per: dict[str, dict] = {}
    agg = {"after": {q: [] for q in KEYS}, "before": {q: [] for q in ("12", "23", "13")}}
    lens = {"after": [[] for _ in range(4)], "before": [[] for _ in range(3)]}
    for i, d in enumerate(dirs):
        rng0 = np.random.default_rng([SEED, i, 0])
        truth = make_truth(pool, rng0, misspec=0.5)
        people = make_population(n, rng0)
        k = k_all.get(d, {})
        f_new = _attempts(pool, truth, people, d, cfg, np.random.default_rng([SEED, i, 26]), k, 4, "after")
        f_old = _attempts(pool, truth, people, d, cfg, np.random.default_rng([SEED, i, 26]), k, 3, "before")
        pn, po = _pairs(f_new), _pairs(f_old)
        n_dir = sum(1 for it in pool if not it.canary and it.block in ("common", d))
        per[d] = {"families_in_bank": n_dir,
                  "after": {KEYS[q]: pair_stats(v) for q, v in pn.items()},
                  "before": {KEYS[q]: pair_stats(v) for q, v in po.items()},
                  "mean_families": [round(float(np.mean([len(x) for x in ff])), 2) for ff in f_new]}
        for q, v in pn.items():
            agg["after"][q] += v
        for q, v in po.items():
            agg["before"][q] += v
        for a, ff in enumerate(f_new):
            lens["after"][a] += [len(x) for x in ff]
        for a, ff in enumerate(f_old):
            lens["before"][a] += [len(x) for x in ff]
    t_rt = time.time()
    rt = retest_check(retest_n, dirs) if retest_n else None
    conf = {"n_per_direction": n, "directions": list(dirs), "subpools": cfg.subpools, "rotation": cfg.rotation,
            "ext_items": cfg.ext_items, "ext_own_first": cfg.ext_own_first, "min_items": cfg.min_items,
            "max_items": cfg.max_items, "stop_rule": cfg.stop_rule, "exposure": cfg.exposure, "attempts": 4,
            "retest_n": retest_n}
    return {
        "pairs": {KEYS[q]: pair_stats(v) for q, v in agg["after"].items()},
        "before": {KEYS[q]: pair_stats(v) for q, v in agg["before"].items()},
        "mean_families": {"after": [round(float(np.mean(x)), 2) for x in lens["after"]],
                          "before": [round(float(np.mean(x)), 2) for x in lens["before"]]},
        "directions": per,
        "retest_check": rt,
        "variants": {"share": 0.0, "by_construction": True, "seed_space": SEED_MAX - SEED_MIN,
                     "note": "вариант — экземпляр семейства с seed генерации (variant_id = семейство:seed); seed "
                             "каждого показа случаен из ~2,1 млрд, а при повторе семейства (LRU) seed прошлых "
                             "показов этому кандидату исключён — вариант всегда новый. Насколько разнятся тексты при "
                             "разных seed (числа, имена, код), зависит от семейства — это проверяет валидатор банка"},
        "protocol": "после (с 09.10): попытки 1–4 — субпулы 0, 1, 0, 1; семейства всех прошлых попыток исключены и из "
                    "основной части, и из дотестирования; нет новых — новые других субпулов, затем LRU (давно "
                    "виденные, новый вариант). До: исключались семейства только последней попытки и только из "
                    "дотестирования",
        "config": conf, "seconds": round(time.time() - t0, 1), "seconds_retest": round(time.time() - t_rt, 1),
        "signature": _signature(seed=SEED, config=conf, world=WORLD, command=COMMAND, n=n * len(dirs)),
    }


def load() -> dict:
    if not OUT.exists():
        return {"missing": True}
    return json.loads(OUT.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Доля повторов заданий между попытками (синтетика)")
    ap.add_argument("--n", type=int, default=200, help="человек на направление")
    ap.add_argument("--retest-n", type=int, default=400, help="пар на направление для проверки test–retest (0 — без)")
    a = ap.parse_args()
    res = simulate(a.n, retest_n=a.retest_n)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    p = res["pairs"]
    b, rt = res["before"], res.get("retest_check") or {}
    print(f"после: 2/1 {p['second_vs_first']['share_families']}; 3/2 {p['third_vs_second']['share_families']}; "
          f"3/1 {p['third_vs_first']['share_families']}; 4/1 {p['fourth_vs_first']['share_families']}; "
          f"4/любая {p['fourth_vs_any_previous']['share_families']} | до: 2/1 {b['second_vs_first']['share_families']}; "
          f"3/1 {b['third_vs_first']['share_families']} | test–retest κw {rt.get('before', {}).get('grade_kappa_quadratic')}"
          f" → {rt.get('after', {}).get('grade_kappa_quadratic')}; {res['seconds']} с → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
