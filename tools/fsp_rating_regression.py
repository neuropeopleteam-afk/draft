"""Парное сравнение ФСП v1/v2 на одном мире: ни истины, ни весов не подстраиваем."""
from pathlib import Path
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.modules.profiles.facts import test_component  # noqa: E402
from app.modules.validation.bench_world import BenchConfig, generate  # noqa: E402
from app.modules.validation.matching_bench import _parsed, score_world, platform_orders, per_need, boot_idx  # noqa: E402

# Замороженная формула profiles/facts.py из базы main 8ef691a — именно то, с чем сравниваем.
LEVEL_WEIGHT = {"international": 1.0, "national": 0.85, "interregional": 0.65, "regional": 0.45, "school": 0.25}
RELEVANCE = {
    "algorithmic": {"backend": .9, "frontend": .6, "data_ml": 1., "qa": .6, "security": .6},
    "product": {"backend": 1., "frontend": 1., "data_ml": .8, "qa": .9, "security": .5},
    "security": {"backend": .5, "frontend": .3, "data_ml": .3, "qa": .4, "security": 1.},
    "robotics": {"backend": .3, "frontend": .3, "data_ml": .5, "qa": .3, "security": .3},
    "uav": {"backend": .3, "frontend": .3, "data_ml": .5, "qa": .3, "security": .3},
}


def legacy_strength(b):
    values = []
    for a in b.achievements:
        if a.verified:
            level = a.event_level.value if hasattr(a.event_level, "value") else a.event_level
            place = a.place or 99
            result = 1 if place == 1 else .85 if place <= 3 else .6 if place <= 10 else .3
            values.append(LEVEL_WEIGHT.get(level, .3) * result *
                          RELEVANCE.get(a.discipline, {}).get(b.profile.current_direction_id or "", .5))
    values.sort(reverse=True)
    return round(min(1., values[0] + .25 * sum(values[1:])), 3) if values else 0.


def run():
    world = generate(BenchConfig())
    current = score_world(world, _parsed(world))
    old = {**current, "comps": current["comps"].copy(), "rating": current["rating"].copy()}
    for i, b in enumerate(current["bundles"]):
        fsp = legacy_strength(b)
        old["comps"][:, i, 3] = fsp
        t = b.test.value if b.test else {}
        old["rating"][i] = round(.65 * test_component(t.get("theta"), t.get("se"), b.profile.current_grade_id) +
                                 .10 * max((f.value.get("score", 0) for f in b.probes_t1), default=0) + .25 * fsp, 4) if b.profile.current_category_id else 0
    before, after = per_need(world.rel, platform_orders(old)), per_need(world.rel, platform_orders(current))
    ix = boot_idx(world.config.n_needs, world.config.seed + 11)
    metrics = {}
    for name in before:
        diff = after[name] - before[name]
        lo, hi = np.percentile(diff[ix].mean(1), [2.5, 97.5])
        metrics[name] = {"before": float(before[name].mean()), "after": float(after[name].mean()),
                         "delta": float(diff.mean()), "paired_ci95": [float(lo), float(hi)]}
    report = {"seed": world.config.seed, "needs": world.config.n_needs, "candidates": world.config.n_candidates,
              "metrics": metrics, "weights_changed": False, "truth_changed": False,
              "interpretation": "Показываем все различия, включая отрицательные. Отсутствие статистически "
                                "различимой потери не равно доказательству абсолютной неухудшаемости."}
    dest = ROOT / "docs" / "validation" / "fsp_rating_regression_0710.json"
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "backend/app/modules/validation/data/fsp_rating_regression_0710.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
