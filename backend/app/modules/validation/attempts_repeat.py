"""Доля повторов заданий между попытками теста (И26): живая по базе и синтетика по протоколу продукта.

Протокол продукта (service.start_session → bank_engine.start, exposure.choose_subpool): повтор идёт из следующего
активного субпула (их два — параллельные формы), семейства прошлой попытки не попадают в дотестирование; у каждого
показа свой случайный seed варианта (bank_engine.SEED_MIN…SEED_MAX), поэтому тексты и числа заданий новые даже при
повторе семейства. Третья попытка возвращается в субпул первой — повторы семейств с первой попыткой возможны,
это показано честно отдельной строкой.

Синтетика: тот же класс сессии и конфигурация, что в продукте (validation/sim.py), истинные параметры заданий =
предкалибровка + ошибка эксперта σ = 0,5, θ ~ N(0, 1), K_f частоты показа — из exposure_k.json. Контрольные
задания (канарейки) в подсчёт не входят. Это модель, не люди.

Пересчёт: ``python -m app.modules.validation.attempts_repeat [--n 200]`` → data/attempts_repeat.json.
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


def simulate(n: int = 200, directions: tuple[str, ...] | None = None) -> dict:
    """Синтетика: три попытки подряд по протоколу продукта на одних и тех же людях каждого направления."""
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
    agg = {"12": [], "23": [], "13": []}
    for i, d in enumerate(dirs):
        rng0 = np.random.default_rng([SEED, i, 0])
        truth = make_truth(pool, rng0, misspec=0.5)
        people = make_population(n, rng0)
        k = k_all.get(d, {})
        rng = np.random.default_rng([SEED, i, 26])
        sp2 = 1 % max(cfg.subpools, 1)
        r1 = sim.run_population(pool, truth, people, d, cfg, rng, k=k, subpools=[0] * n)
        r2 = sim.run_population(pool, truth, people, d, cfg, rng, k=k, subpools=[sp2] * n,
                                exclude=[set(r["families"]) for r in r1])
        # третья попытка: субпулов два — снова субпул первой; исключаются семейства только прошлой (второй)
        r3 = sim.run_population(pool, truth, people, d, cfg, rng, k=k, subpools=[0] * n,
                                exclude=[set(r["families"]) for r in r2])
        f = [[set(r["families"]) for r in rr] for rr in (r1, r2, r3)]
        pairs = {"12": list(zip(f[0], f[1])), "23": list(zip(f[1], f[2])), "13": list(zip(f[0], f[2]))}
        per[d] = {key: pair_stats(v) for key, v in pairs.items()}
        per[d]["mean_families"] = round(float(np.mean([len(x) for ff in f for x in ff])), 2)  # оценённых, без канареек
        for key, v in pairs.items():
            agg[key] += v
    conf = {"n_per_direction": n, "directions": list(dirs), "subpools": cfg.subpools, "rotation": cfg.rotation,
            "ext_items": cfg.ext_items, "ext_own_first": cfg.ext_own_first, "min_items": cfg.min_items,
            "max_items": cfg.max_items, "stop_rule": cfg.stop_rule, "exposure": cfg.exposure}
    return {
        "pairs": {"second_vs_first": pair_stats(agg["12"]), "third_vs_second": pair_stats(agg["23"]),
                  "third_vs_first": pair_stats(agg["13"])},
        "directions": per,
        "variants": {"share": 0.0, "by_construction": True, "seed_space": SEED_MAX - SEED_MIN,
                     "note": "вариант — экземпляр семейства с seed генерации (variant_id = семейство:seed); seed "
                             "каждого показа случаен из ~2,1 млрд, совпадение варианта практически исключено "
                             "(≈ 5·10⁻¹⁰ на задание повторённого семейства). Насколько разнятся тексты при разных seed "
                             "(числа, имена, код), зависит от семейства — это проверяет валидатор банка, не этот расчёт"},
        "protocol": "попытка 1 — субпул 0; попытка 2 — субпул 1, семейства попытки 1 исключены из дотестирования; "
                    "попытка 3 — снова субпул 0 (субпулов два), исключены семейства попытки 2",
        "config": conf, "seconds": round(time.time() - t0, 1),
        "signature": _signature(seed=SEED, config=conf, world=WORLD, command=COMMAND, n=n * len(dirs)),
    }


def load() -> dict:
    if not OUT.exists():
        return {"missing": True}
    return json.loads(OUT.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Доля повторов заданий между попытками (синтетика)")
    ap.add_argument("--n", type=int, default=200, help="человек на направление")
    a = ap.parse_args()
    res = simulate(a.n)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    p = res["pairs"]
    print(f"2 vs 1: {p['second_vs_first']['share_families']}; 3 vs 2: {p['third_vs_second']['share_families']}; "
          f"3 vs 1: {p['third_vs_first']['share_families']}; {res['seconds']} с → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
