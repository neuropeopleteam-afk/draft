"""Fixed policy comparison on identical 500 profiles; no fitting on relevance labels."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from audit_expert_ranking import original_150
from benchmark import baseline_parser
from app.modules.demo.seed import NEEDS, extend_candidates
from app.modules.validation.matching_eval import evaluate
from app.modules.validation.bench_world import BenchConfig, generate
from app.modules.validation.matching_bench import _parsed, score_world, platform_orders, per_need
import numpy as np


def main():
    engine, db, _ = original_150()
    extend_candidates(db)
    db.commit()
    texts = [t for _, t in NEEDS]
    before = evaluate(db, texts, baseline_order=True)
    after = evaluate(db, texts, baseline_order=False)
    result = {"demo_500": {"before": before["summary"], "after": after["summary"],
                           "product": before["summary"],
                           "per_need_before": before["per_need"], "per_need_after": after["per_need"],
                           "n_pool": after["n_pool"], "n_needs": after["n_needs"]}}
    db.close()
    engine.dispose()
    cfg = BenchConfig(n_needs=50, n_candidates=500)
    world = generate(cfg)
    scored = score_world(world, _parsed(world))
    base_parse = baseline_parser()
    base_scored = score_world(world, [base_parse(n.text, use_llm=False) for n in world.needs])
    original = per_need(world.rel, platform_orders(base_scored))
    old = per_need(world.rel, platform_orders({**scored, "mandatory_gaps":
                                               np.zeros_like(scored["mandatory_gaps"])}))
    new = per_need(world.rel, platform_orders(scored, experimental=True))
    result["hidden_truth_500"] = {"config": cfg.to_dict(),
                                 "before": {k: round(float(v.mean()), 4) for k, v in old.items()},
                                 "after": {k: round(float(v.mean()), 4) for k, v in new.items()},
                                 "original_parser_product": {k: round(float(v.mean()), 4) for k, v in original.items()},
                                 "current_parser_product": {k: round(float(v.mean()), 4) for k, v in old.items()},
                                 "experimental_policy_enabled": False,
                                 "no_fitting": True}
    path = ROOT / "docs/realdata/ranking_guard_500.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k: {m: v[m] for m in ("before", "after")} for k, v in result.items()},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
