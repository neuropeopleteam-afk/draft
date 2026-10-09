"""Ф2: доказательство качества правила «сначала покрывающие обязательное» — до/после на одних и тех же данных.

    cd backend && ../../.venv/bin/python ../tools/must_have/evaluate.py [--items путь/items_A_v1.json]

Что считается (без подбора параметров по меткам — правило нормативное, ни одного настраиваемого числа):
1. Экспертные оценки v1 (пакет A, 10 потребностей, 109 пар, эксперты E1–E3, эталон пары — медиана): порядок
   размеченного пула до (match-v1) и после (ярусы обязательного) — p@5, nDCG@5, парная разница с бутстреп-ДИ и
   критерием Уилкоксона. Карточки пакета — снимок с сервера (только чтение), кандидаты восстанавливаются по сигнатуре
   из исходных 150 демо-кандидатов с проверкой заявленного и подтверждённого стека (как tools/realdata/audit_expert_ranking).
2. Разметка по правилам на демо-мире 500 (matching_eval, 17 потребностей × 20 кандидатов).
«after» — правило по умолчанию (покрытие = подтверждено тестом, T1); «after_declared» — вариант за флагом
MATCH_MUST_DECLARED (засчитывать и заявленное «уверенно», если тест навык не проверял).
3. Скрытая истина 500 (bench_world, 50 потребностей × 500 кандидатов) — та же, что в ranking_guard.
4. Покрытие обязательного в топ-5 подборки демо-мира 500 (как build_selection): доля карточек топ-5, у которых все
   обязательные подтверждены тестом (T1).
5. Условия потребности по умолчанию на демо-мире 500: сколько кандидатов скрыто условиями формата и города.
Результат — docs/must_have/metrics.json.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "realdata"))

from app.modules.catalog.seed_data import STACK  # noqa: E402
from app.modules.experts import stats as S  # noqa: E402
from app.modules.matching import must_have  # noqa: E402
from app.modules.matching.need_parser import parse_need  # noqa: E402
from app.modules.matching.ranking import score_candidate  # noqa: E402
from app.modules.validation.matching_eval import label, selection_categories  # noqa: E402

WS = ROOT.parents[1]  # /home/user/workspace/spectrek
DEFAULT_ITEMS = WS / "reports_0810/musthave_data/items_A_v1.json"
OUT = ROOT / "docs/must_have/metrics.json"
TRANSLATE = {"Backend": "backend", "Frontend": "frontend", "Data/ML": "data_ml", "QA": "qa",
             "Информационная безопасность": "security"}


def _paired(before: list[float], after: list[float]) -> dict:
    d = [a - b for a, b in zip(after, before)]
    return {**S.boot_ci(d), "wilcoxon_p": S.wilcoxon_p(d), "worse_needs": sum(1 for x in d if x < -1e-9),
            "better_needs": sum(1 for x in d if x > 1e-9)}


def expert_section(items_path: Path) -> dict:
    from audit_expert_ranking import original_150, signature  # noqa: F401  (тот же мир, что у аудита И8)

    items = {i["id"]: i for i in json.loads(items_path.read_text())}
    ratings: dict[str, list] = defaultdict(list)
    for coder in ("E1", "E2", "E3"):
        for line in (WS / f"reports_0710/experts_{coder}.jsonl").read_text().splitlines():
            row = json.loads(line)
            if row.get("kind", row.get("block")) == "A" and row["item_id"] in items:
                ratings[row["item_id"]].append(row["value"]["relevance"])
    engine, db, bundles = original_150()
    levels = must_have.declared_levels(db, [b.profile.user_id for b in bundles])
    lookup = {(b.profile.current_category_id, round(b.test.value["theta"], 2), str(b.profile.city),
               round(float(b.profile.experience_years or 0), 1)): b for b in bundles}
    by_need = defaultdict(list)
    for iid, it in items.items():
        c = it["payload"]["card"]
        direction, grade = c["category"].split(" · ")
        sig = (f"{TRANSLATE[direction]}.{grade.lower()}", round(c["test"]["theta"], 2), str(c["city"]),
               round(c["experience_years"] or 0, 1))
        b = lookup[sig]
        assert {STACK[f.key][0] for f in b.t0["stack"]} == set(c["stack_declared"]), iid
        conf = {STACK[k][0]: f.value["score"] for k, f in b.skills_t1.items() if f.value["score"] >= 0.5}
        assert conf == {s["title"]: s["score"] for s in c["skills_confirmed"]}, iid
        by_need[it["grp"]].append((iid, b, float(statistics.median(ratings[iid]))))
    rows = []
    for nid, pairs in sorted(by_need.items()):
        text = items[pairs[0][0]]["payload"]["need_text"]
        req = parse_need(text, use_llm=False)
        ok = selection_categories(req)
        in_cat = [b for b in bundles if ok is None or b.profile.current_category_id in ok]
        scores = {b.profile.user_id: score_candidate(b, req)[0] for b in bundles}
        # after — правило по умолчанию (только T1); after_declared — вариант за флагом MATCH_MUST_DECLARED
        tiers = {name: must_have.tiers_for(in_cat, req, levels if lv else {}, on=True)
                 for name, lv in (("after", False), ("after_declared", True))}

        def key(row, policy):
            iid, b, _ = row
            uid = b.profile.user_id
            cat = 0 if ok is None or b.profile.current_category_id in ok else 1
            t = 0 if policy == "before" else (tiers[policy].get(uid) or {"tier": 9})["tier"]
            return cat, t, -scores[uid], -(b.profile.rating_score or 0), iid

        all_gold = [g for _, _, g in pairs]
        all_rule = [label(b, req) for _, b, _ in pairs]
        res = {"need": nid, "text": text, "pairs": len(pairs), "relevant": sum(1 for g in all_gold if g >= 2),
               "required": [STACK.get(t, (t,))[0] for t in must_have.must_tags(req)]}
        for policy in ("before", "after", "after_declared"):
            order = sorted(pairs, key=lambda r: key(r, policy))
            top = order[:5]
            res[policy] = {"p@5": round(S.precision_at([g for _, _, g in top]), 4),
                           "ndcg@5": round(S.ndcg_at([g for _, _, g in top], all_gold), 4),
                           "rules_p@5": round(S.precision_at([label(b, req) for _, b, _ in top]), 4),
                           "rules_ndcg@5": round(S.ndcg_at([label(b, req) for _, b, _ in top], all_rule), 4),
                           "top5_gold": [g for _, _, g in top],
                           "top5_tiers": [(tiers["after"].get(b.profile.user_id) or {}).get("tier") for _, b, _ in top],
                           "top5_items": [iid for iid, _, _ in top]}
        rows.append(res)
    db.close()
    engine.dispose()
    summary = {}
    for metric in ("p@5", "ndcg@5", "rules_p@5", "rules_ndcg@5"):
        summary[metric] = {p: S.boot_ci([r[p][metric] for r in rows]) for p in ("before", "after", "after_declared")}
        summary[metric]["diff_after_before"] = _paired([r["before"][metric] for r in rows],
                                                       [r["after"][metric] for r in rows])
        summary[metric]["diff_declared_before"] = _paired([r["before"][metric] for r in rows],
                                                          [r["after_declared"][metric] for r in rows])
    return {"n_needs": len(rows), "n_pairs": len(items), "raters": "E1, E2, E3 (медиана)", "summary": summary,
            "per_need": rows,
            "caveat": "Оценка на размеченном пуле пакета v1 (объединение топ-5 match-v1, топ-5 BM25 и 2 случайных): "
                      "кандидатов вне пула нельзя считать нерелевантными, поэтому порядок сравнивается внутри пула."}


def demo_rules_section() -> dict:
    from audit_expert_ranking import original_150
    from app.modules.demo.seed import NEEDS, extend_candidates
    from app.modules.validation.matching_eval import evaluate

    engine, db, _ = original_150()
    extend_candidates(db)
    db.commit()
    texts = [t for _, t in NEEDS]
    before = evaluate(db, texts, must_first=False)
    after = evaluate(db, texts, must_first=True)
    cov = coverage_top5(db, NEEDS)
    cond = conditions_hidden(db, NEEDS)
    db.close()
    engine.dispose()
    return {"before": before["summary"], "after": after["summary"], "n_pool": after["n_pool"],
            "n_needs": after["n_needs"], "top5_coverage": cov, "conditions": cond}


def conditions_hidden(db, needs) -> list[dict]:
    """Условия потребности по умолчанию на демо-мире: сколько кандидатов категории скрыто и сколько осталось."""
    from app.modules.matching import ranking

    out = []
    for title, text in needs:
        req = parse_need(text, use_llm=False)
        sel = ranking.build_selection(db, req, {})
        out.append({"need": text[:70], "conditions": sel["conditions"]["text"], "hidden": sel["conditions"]["hidden"],
                    "shown": sel["total_matched"]})
    return out


def coverage_top5(db, needs) -> dict:
    """Топ-5 подборки (build_selection, фильтры пустые, как v1) до и после: доля карточек со всем обязательным."""
    import os

    from app.modules.matching import ranking

    out = {"before": {}, "after": {}}
    per = []
    for policy in ("before", "after"):
        os.environ["MATCH_MUST_FIRST"] = "1" if policy == "after" else "0"
        full, full_t1, n = 0, 0, 0
        for title, text in needs:
            req = parse_need(text, use_llm=False)
            if not req.get("stack_required"):
                continue
            sel = ranking.build_selection(db, req, {"conditions_off": True}, limit=5)
            refs = [r["ref"] for r in sel["results"]]
            for r in sel["results"]:
                n += 1
                m = r.get("must") or {}
                full += m.get("missing_total", 1) == 0
                full_t1 += m.get("missing_total", 1) == 0 and not m.get("declared_high")
            if policy == "after":
                per.append({"need": text[:70], "top5_after": refs})
        out[policy] = {"cards": n, "all_required_covered": round(full / max(n, 1), 4),
                       "all_required_t1": round(full_t1 / max(n, 1), 4)}
    os.environ.pop("MATCH_MUST_FIRST", None)
    return out


def hidden_truth_section() -> dict:
    from app.modules.validation.bench_world import BenchConfig, generate
    from app.modules.validation.matching_bench import _parsed, per_need, platform_orders, score_world

    cfg = BenchConfig(n_needs=50, n_candidates=500)
    world = generate(cfg)
    sc = score_world(world, _parsed(world))
    res = {}
    pn = {}
    for policy, flag in (("before", False), ("after", True)):
        o = platform_orders(sc, must_first=flag)
        pn[policy] = per_need(world.rel, o)
        res[policy] = {k: round(float(v.mean()), 4) for k, v in pn[policy].items()}
        res[policy]["top5_all_required_t1"] = round(float(np.mean(
            [sc["must_full"][i, o[i, :5]].mean() for i in range(len(o)) if sc["has_req"][i]])), 4)
    res["diff"] = {k: _paired(list(pn["before"][k]), list(pn["after"][k])) for k in ("p@5", "ndcg@10", "mrr")}
    res["config"] = cfg.to_dict()
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default=str(DEFAULT_ITEMS))
    ap.add_argument("--skip-demo", action="store_true")
    a = ap.parse_args()
    out = {"rule": "Ф2: ярусы по числу непокрытых обязательных (0, 1, ≥2), внутри — балл match-v1",
           "experts_v1": expert_section(Path(a.items))}
    print(json.dumps(out["experts_v1"]["summary"], ensure_ascii=False), flush=True)
    out["hidden_truth_500"] = hidden_truth_section()
    print(json.dumps({k: out["hidden_truth_500"][k] for k in ("before", "after")}, ensure_ascii=False), flush=True)
    if not a.skip_demo:
        out["demo_500_rules"] = demo_rules_section()
        print(json.dumps(out["demo_500_rules"]["top5_coverage"], ensure_ascii=False), flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
