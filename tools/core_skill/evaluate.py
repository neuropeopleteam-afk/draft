"""Я1: признак «ядро роли» на экспертной разметке v1 и демо-мире 500 — флаг выкл./вкл., политики.

    cd backend && LLM_DISABLED=1 ../../../.venv/bin/python ../tools/core_skill/evaluate.py [--items путь/items_A_v1.json]

1. Экспертные оценки v1 (пакет A, 10 потребностей, 109 пар, E1–E3 — модель, не люди; эталон пары — медиана):
   порядок размеченного пула как в продукте (категория → ярус обязательного → балл) без признака и с признаком при
   каждой политике; p@5, nDCG@5, nDCG@10, парная разница с бутстреп-ДИ. Кандидаты восстанавливаются по сигнатуре из
   исходных 150 демо-кандидатов с проверкой заявленного и подтверждённого стека (как tools/must_have/evaluate.py).
2. Демо-500, разметка правилами (matching_eval, 17 потребностей × 20): флаг выкл./вкл.
Результат — docs/core_skill/metrics.json. Параметры не подбираются по меткам автоматически.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "realdata"))

from app.modules.catalog.seed_data import STACK  # noqa: E402
from app.modules.experts import stats as S  # noqa: E402
from app.modules.matching import core_skill, must_have  # noqa: E402
from app.modules.matching.need_parser import parse_need  # noqa: E402
from app.modules.matching.ranking import score_candidate  # noqa: E402
from app.modules.validation.matching_eval import selection_categories  # noqa: E402

WS = ROOT.parents[1]
DEFAULT_ITEMS = WS / "reports_0810/musthave_data/items_A_v1.json"
OUT = ROOT / "docs/core_skill/metrics.json"
TRANSLATE = {"Backend": "backend", "Frontend": "frontend", "Data/ML": "data_ml", "QA": "qa",
             "Информационная безопасность": "security"}
POLICIES = [("off", None), ("group", None), ("within", None), ("cap", 5), ("cap", 3), ("penalty", 0.2)]


def _paired(before: list[float], after: list[float]) -> dict:
    d = [a - b for a, b in zip(after, before)]
    return {**S.boot_ci(d), "wilcoxon_p": S.wilcoxon_p(d), "worse_needs": sum(1 for x in d if x < -1e-9),
            "better_needs": sum(1 for x in d if x > 1e-9)}


def _name(pol, val):
    return pol if val is None else f"{pol}_{val}"


def expert_v1(items_path: Path) -> dict:
    from audit_expert_ranking import original_150

    items = {i["id"]: i for i in json.loads(items_path.read_text())}
    ratings: dict[str, list] = defaultdict(list)
    for coder in ("E1", "E2", "E3"):
        for line in (WS / f"reports_0710/experts_{coder}.jsonl").read_text().splitlines():
            row = json.loads(line)
            if row.get("kind", row.get("block")) == "A" and row["item_id"] in items:
                ratings[row["item_id"]].append(row["value"]["relevance"])
    engine, db, bundles = original_150()
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
        must = must_have.tiers_for(in_cat, req, {}, on=True)
        core = core_skill.assess_pool(in_cat, req, on=True)  # доступность — по пулу категорий, как в подборке
        rc = core_skill.role_core(req)
        all_gold = [g for _, _, g in pairs]
        res = {"need": nid, "text": text, "pairs": len(pairs), "relevant": sum(1 for g in all_gold if g >= 2),
               "core": rc and rc["title"], "core_active": bool(core and next(iter(core.values()))["active"]),
               "states": {iid: (core.get(b.profile.user_id) or {}).get("state") for iid, b, _ in pairs}}
        for pol, val in POLICIES:
            old = (core_skill.CAP_PLACE, core_skill.PENALTY)
            if pol == "cap":
                core_skill.CAP_PLACE = val
            if pol == "penalty":
                core_skill.PENALTY = val

            def key(row):
                iid, b, _ = row
                uid = b.profile.user_id
                cat = 0 if ok is None or b.profile.current_category_id in ok else 1
                ck = 0 if pol == "off" else (core.get(uid) or {}).get("key", 0)
                mt = (must.get(uid) or {"tier": 9})["tier"]
                return (cat, *core_skill.sort_key(0, mt, scores[uid], ck, "group" if pol == "off" else pol),
                        -(b.profile.rating_score or 0), iid)

            order = sorted(pairs, key=key)
            if pol == "cap":
                n_in = sum(1 for _, b, _ in order if ok is None or b.profile.current_category_id in ok)
                absent = [bool((core.get(b.profile.user_id) or {}).get("key")) for _, b, _ in order[:n_in]]
                order = [order[:n_in][i] for i in core_skill.cap_positions(absent)] + order[n_in:]
            core_skill.CAP_PLACE, core_skill.PENALTY = old
            g = [x for _, _, x in order]
            res[_name(pol, val)] = {"p@5": round(S.precision_at(g[:5]), 4), "ndcg@5": round(S.ndcg_at(g[:5], all_gold), 4),
                                    "ndcg@10": round(S.ndcg_at(g[:10], all_gold, 10), 4),
                                    "top5": [(iid, x, res["states"][iid]) for iid, _, x in order[:5]]}
        rows.append(res)
    db.close()
    engine.dispose()
    names = [_name(p, v) for p, v in POLICIES]
    summary = {}
    for metric in ("p@5", "ndcg@5", "ndcg@10"):
        summary[metric] = {n: S.boot_ci([r[n][metric] for r in rows]) for n in names}
        for n in names[1:]:
            summary[metric][f"diff_{n}"] = _paired([r["off"][metric] for r in rows], [r[n][metric] for r in rows])
    return {"n_needs": len(rows), "n_pairs": len(items), "raters": "E1, E2, E3 (медиана), модель, не люди",
            "summary": summary, "per_need": rows,
            "caveat": "Оценка на размеченном пуле пакета v1 (объединение топ-5 match-v1, топ-5 BM25 и 2 случайных): "
                      "кандидатов вне пула нельзя считать нерелевантными, поэтому порядок сравнивается внутри пула."}


def demo_rules() -> dict:
    from audit_expert_ranking import original_150
    from app.modules.demo.seed import NEEDS, extend_candidates
    from app.modules.validation.matching_eval import evaluate

    engine, db, _ = original_150()
    extend_candidates(db)
    db.commit()
    texts = [t for _, t in NEEDS]
    out = {"off": evaluate(db, texts, core=False)["summary"]}
    for pol in ("group", "within"):
        out[pol] = evaluate(db, texts, core=True, core_policy=pol)["summary"]
    db.close()
    engine.dispose()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default=str(DEFAULT_ITEMS))
    ap.add_argument("--skip-demo", action="store_true")
    a = ap.parse_args()
    res = {"expert_v1": expert_v1(Path(a.items))}
    s = res["expert_v1"]["summary"]
    for m in ("p@5", "ndcg@5", "ndcg@10"):
        print(m, {k: (v["mean"] if "mean" in v else v) for k, v in s[m].items() if not k.startswith("diff")})
        print("   diff", {k: (v["mean"], v["lo"], v["hi"], v["better_needs"], v["worse_needs"]) for k, v in s[m].items()
                          if k.startswith("diff")})
    if not a.skip_demo:
        res["demo_500_rules"] = demo_rules()
        print("demo-500", json.dumps({k: {m: v[m]["platform"] for m in ("p@5", "ndcg@5", "ndcg@10")}
                                       for k, v in res["demo_500_rules"].items()}, ensure_ascii=False))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("→", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
