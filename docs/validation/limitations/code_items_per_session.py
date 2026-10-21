import os, sys, json, collections, numpy as np
cfg = sys.argv[1]
if cfg == "final":
    os.environ.update({"ASSESSMENT_CONFIRM_LEVEL":"0.8","ASSESSMENT_MAX_ITEMS":"20","ASSESSMENT_TWO_STAGE_CONFIRM":"0.5","ASSESSMENT_CODE_QUOTA_EXT":"true","ASSESSMENT_GUESSING_3PL":"true","ASSESSMENT_SUBPOOLS":"1","ASSESSMENT_TWO_STAGE_ITEMS":"12","ASSESSMENT_TWO_STAGE_MINUTES":"20","ASSESSMENT_SPRT_DELTA":"0.45","ASSESSMENT_CONTESTED_MAX_ITEMS":"36","ASSESSMENT_CONTESTED_MAX_MINUTES":"105"})
else:
    os.environ["ASSESSMENT_CONFIRM_LEVEL"] = "0.65"
os.environ.update({"GRADES_EXT_ENABLED":"true","ASSESSMENT_TWO_STAGE_ENABLED":"true","CATALOG_EXT_ENABLED":"1","GRADES_EXT_REFINE_ITEMS":"10","GRADES_EXT_REFINE_MINUTES":"25","LLM_DISABLED":"true"})
from app.modules.validation import selfcheck as sc
from app.modules.assessment.sprt import CODE_OPEN_FORMATS
base = sc._engine()
N = int(sys.argv[2]); stack = sys.argv[3].split(",") if len(sys.argv) > 3 else []
tot = collections.Counter(); per = []
for i in range(N):
    eng = sc.SyntheticEngine(base, "level_middle", 0.3, np.random.default_rng(1000 + i))
    st = eng.start(direction="backend", claimed_grade="middle", stack_tags=stack, seed=5000 + i)
    import time
    for _ in range(60):
        if eng.next_item(st) is None: break
        it = eng._current(st)
        for step in range(1, it["parts"] + 1):
            ok = sc._correct(it, step, eng.strategy, eng.theta, eng.rng)
            fb = eng.answer(st, it["token"], sc._answer_for(it, step, ok, eng.rng), None, step=step)
            if not fb.accepted: eng.answer(st, it["token"], "", None, step=step)
        if not it["done"]: break
    eng.finish(st)
    items = [x for x in st["items"] if x["done"] and not x["canary"]]
    c = collections.Counter()
    for x in items:
        has_code = bool((x.get("public") or {}).get("code"))
        lang = x.get("language") or "-"
        c["n"] += 1
        if has_code: c[f"code:{lang}"] += 1
        if x["format"] in CODE_OPEN_FORMATS: c["code_open_fmt"] += 1
    per.append(c); tot.update(c)
def stat(k):
    v = np.array([p.get(k, 0) for p in per]); return {"mean": round(v.mean(), 1), "p90": int(np.percentile(v, 90)), "max": int(v.max())}
keys = sorted({k for p in per for k in p})
print(json.dumps({"cfg": cfg, "N": N, "stack": stack, **{k: stat(k) for k in keys}}, ensure_ascii=False))
