"""Read existing blind cards and model labels; never relabel or modify expert pack."""
from collections import defaultdict
import hashlib
import inspect
import json
from pathlib import Path
import random
import statistics
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from app.core.db import init_engine
from app.core.security import hash_password
from app.modules.catalog.seed_data import STACK
from app.modules.demo.seed import _candidate, DIRECTIONS, GRADES
from app.modules.matching.need_parser import parse_need
from app.modules.matching.ranking import apply_filters, condition_filters, requirement_priority, score_candidate
from app.modules.profiles.facts import load_bundles
from app.modules.profiles.models import CandidateProfile
from app.modules.experts.stats import ndcg_at, precision_at, boot_ci
from app.modules.validation.matching_eval import label
from sqlalchemy import select
from benchmark import baseline_parser

OUT = ROOT / "docs/realdata"
CARD_FILES = [Path("/home/user/workspace/spectrek/.e1work/items_A.json"),
              Path("/tmp/e2/items_A.json"), Path("/tmp/e3/items_A.json")]


def signature(p, theta):
    return p.current_category_id, round(theta, 2), str(p.city), round(float(p.experience_years or 0), 1)


def original_150():
    url = f"sqlite:///{Path(tempfile.mkdtemp(prefix='realdata_expert_')) / 'data.db'}"
    cfg = Config(str(ROOT / "backend/alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend/migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["skip_logging"] = True
    command.upgrade(cfg, "head")
    engine = init_engine(url)
    db = Session(engine)
    rnd = random.Random(20261006)
    pwd = hash_password("Irrelevant-offline-demo")
    idx = 0
    for direction in DIRECTIONS:
        for grade in GRADES:
            flags = [True] * 4 + [False] * 6
            rnd.shuffle(flags)
            for i in range(10):
                idx += 1
                _candidate(db, rnd, idx, direction, grade, pwd, flags[i])
    db.commit()
    profiles = list(db.scalars(select(CandidateProfile)))
    bundles = list(load_bundles(db, [p.user_id for p in profiles]).values())
    return engine, db, bundles


def main():
    items, ratings = {}, defaultdict(list)
    for path in CARD_FILES:
        for item in json.loads(path.read_text())["items"]:
            items[item["id"]] = item
    for coder in ("E1", "E2", "E3"):
        for line in (ROOT.parents[1] / f"reports_0710/experts_{coder}.jsonl").read_text().splitlines():
            row = json.loads(line)
            if row.get("kind", row.get("block")) == "A":
                ratings[row["item_id"]].append(row["value"]["relevance"])
    engine, db, bundles = original_150()
    lookup = {signature(b.profile, b.test.value["theta"]): b for b in bundles}
    by_need = defaultdict(list)
    translations = {"Backend": "backend", "Frontend": "frontend", "Data/ML": "data_ml",
                    "QA": "qa", "Информационная безопасность": "security"}
    for item in items.values():
        c = item["card"]
        direction, grade = c["category"].split(" · ")
        sig = (f"{translations[direction]}.{grade.lower()}", round(c["test"]["theta"], 2),
               str(c["city"]), round(c["experience_years"] or 0, 1))
        b = lookup[sig]
        # Verify the independent reconstruction, not just a weak join on name or ID.
        declared = {STACK[f.key][0] for f in b.t0["stack"]}
        confirmed = {STACK[k][0]: f.value["score"] for k, f in b.skills_t1.items() if f.value["score"] >= 0.5}
        assert declared == set(c["stack_declared"]), item["id"]
        assert confirmed == {f["title"]: f["score"] for f in c["skills_confirmed"]}, item["id"]
        assert b.profile.work_format.value == c["work_format"] and b.profile.relocation == c["relocation"]
        gold = statistics.median(ratings[item["id"]])
        by_need[item["need_id"]].append((item, b, gold))
    rows = []
    base_parse = baseline_parser()
    for nid, pairs in sorted(by_need.items()):
        text = pairs[0][0]["need_text"]
        req = parse_need(text, use_llm=False)
        old_req = base_parse(text, use_llm=False)
        def in_category(b):
            return ((not req["direction"] or b.profile.current_direction_id == req["direction"])
                    and (not req["grade"] or b.profile.current_grade_id == req["grade"]))
        scores = {b.profile.user_id: score_candidate(b, req) for b in bundles}
        old_scores = {b.profile.user_id: score_candidate(b, old_req) for b in bundles}
        # Frozen labeled pool only. Unlabeled candidates must not be assumed irrelevant.
        before = sorted(pairs, key=lambda row: (not in_category(row[1]), -old_scores[row[1].profile.user_id][0],
                                                -(row[1].profile.rating_score or 0), row[0]["id"]))
        allowed = set(b.profile.user_id for b in apply_filters([b for _, b, _ in pairs],
                                                              condition_filters(req, {})))
        mandatory_only = sorted(pairs, key=lambda row: (not in_category(row[1]),
                               requirement_priority(row[1], req), -scores[row[1].profile.user_id][0],
                               -(row[1].profile.rating_score or 0), row[0]["id"]))
        after = sorted([row for row in pairs if in_category(row[1]) and row[1].profile.user_id in allowed],
                       key=lambda row: (requirement_priority(row[1], req), -scores[row[1].profile.user_id][0],
                                        -(row[1].profile.rating_score or 0), row[0]["id"]))
        def metrics(order, gold):
            top = [row[2] if gold else label(row[1], req) for row in order[:5]]
            all_rels = [row[2] if gold else label(row[1], req) for row in pairs]
            return {"p@5": round(precision_at(top), 4), "ndcg@5": round(ndcg_at(top, all_rels), 4)}
        def card_view(row):
            item, b, gold = row
            score, components, reasons = scores[b.profile.user_id]
            return {"item_id": item["id"], "synthetic_index": b.profile.telegram, "card": item["card"],
                    "model_label": gold, "score": score, "components": components,
                    "mandatory_verified": requirement_priority(b, req) == 0, "reasons": reasons}
        gold_by_uid = {b.profile.user_id: rel for _, b, rel in pairs}
        full_before = sorted(bundles, key=lambda b: (not in_category(b), -old_scores[b.profile.user_id][0],
                            -(b.profile.rating_score or 0), b.profile.telegram))[:5]
        full_after = sorted([b for b in bundles if in_category(b)],
                            key=lambda b: (requirement_priority(b, req), -scores[b.profile.user_id][0],
                                           -(b.profile.rating_score or 0), b.profile.telegram))[:5]
        def full_view(order):
            coverage = sum(b.profile.user_id in gold_by_uid for b in order)
            known = [gold_by_uid[b.profile.user_id] for b in order if b.profile.user_id in gold_by_uid]
            return {"top5": [{"synthetic_index": b.profile.telegram,
                              "label": gold_by_uid.get(b.profile.user_id)} for b in order],
                    "labeled_in_top5": coverage, "metrics": {
                        "p@5": round(precision_at(known), 4),
                        "ndcg@5": round(ndcg_at(known, [r[2] for r in pairs]), 4)}
                    if coverage == len(order) else None}
        rows.append({"need": nid, "text": text, "parsed": req, "labeled_candidates": len(pairs),
                     "eligible_after": len(after), "before": metrics(before, True), "after": metrics(after, True),
                     "mandatory_only": metrics(mandatory_only, True),
                     "rules_mandatory_only": metrics(mandatory_only, False),
                     "rules_before": metrics(before, False), "rules_after": metrics(after, False),
                     "top5_before": [card_view(row) for row in before[:5]],
                     "top5_after": [card_view(row) for row in after[:5]],
                     "top5_mandatory_only": [card_view(row) for row in mandatory_only[:5]],
                     "full_150_before": full_view(full_before), "full_150_after": full_view(full_after)})
    summary = {version: {metric: boot_ci([r[version][metric] for r in rows])
                         for metric in ("p@5", "ndcg@5")}
               for version in ("before", "after", "mandatory_only", "rules_before", "rules_after",
                               "rules_mandatory_only")}
    # No fitting or label-derived parameters. Dropping any need cannot change these normative rules.
    loo = [{"held_out": row["need"], "training_needs": [r["need"] for r in rows if r is not row],
            "rule_hash": hashlib.sha256(inspect.getsource(requirement_priority).encode()).hexdigest(),
            "held_out_before": row["before"], "held_out_after": row["mandatory_only"],
            "interpretation": "Fixed ex-ante policy, zero fitted parameters. Not independent confirmation on new labels."}
           for row in rows]
    result = {"n_needs": len(rows), "n_pairs": len(items), "summary": summary, "per_need": rows,
              "leave_one_need_out": loo,
              "source": "Existing E1/E2/E3 blind snapshots and fixed model labels, no production SQL",
              "caveat": "Evaluation restricted to original fully labeled union pool, not new top-5 of all 150/500. "
                        "Unlabeled new candidates cannot be given zero labels. Old ref IDs not changed. "
                        "Insufficient feasible candidates leave empty top-k slots (denominator k)."}
    (OUT / "expert_ranking_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    db.close()
    engine.dispose()
    print(OUT / "expert_ranking_audit.json")
    print(json.dumps(summary, ensure_ascii=False))
    for row in rows:
        print(row["need"], row["before"], row["after"], "eligible", row["eligible_after"])


if __name__ == "__main__":
    main()
