"""Путь по умолчанию (флаг выкл): прежний guard (main 2877ca9) против нового (отрицания, целые слова) на ответах моделей."""
import importlib.util
import json
import subprocess
import sys

sys.path.insert(0, 'tools/llm')
sys.path.insert(0, 'backend')
OLD = "/tmp/evidence/grader_old.py"  # git show 2877ca9:backend/app/modules/assessment/grader.py > OLD
subprocess.run(f"git show 2877ca9:backend/app/modules/assessment/grader.py > {OLD}", shell=True, check=True)
import evidence_bench as B
spec = importlib.util.spec_from_file_location("grader_old", OLD)
GO = importlib.util.module_from_spec(spec); sys.modules["grader_old"]=GO; spec.loader.exec_module(GO)
from app.modules.assessment import grader as G
from app.modules.llm.client import _extract_json
items, rows = B._items_rows()
tot = {"replies":0,"answers_changed":0,"criteria_changed":0,"quotes_checked":0,"by_model":{}}
for m,f in B.model_files().items():
    for rid,o in B._read(f).items():
        if o.get("error") or rid not in rows: continue
        r=rows[rid]; it=items[r['item']]; ans=B._answer(r)
        d=_extract_json(o.get("text") or "")
        po=GO.parse_reply(d,it['rubric'],ans); pn=G.parse_reply(d,it['rubric'],ans)
        if not po.get('ok'): continue
        tot["replies"]+=1; tot["quotes_checked"]+=len(po["quotes"])
        if abs(po['score']-pn['score'])>1e-9:
            tot["answers_changed"]+=1; tot["by_model"][m]=tot["by_model"].get(m,0)+1
            for cid in pn['criteria']:
                if po['criteria'][cid]!=pn['criteria'][cid]:
                    tot["criteria_changed"]+=1
                    print(m, r['group'], cid, po['criteria'][cid],'→',pn['criteria'][cid],'| Q:',po['quotes'].get(cid,'')[:120])
tot["date"], tot["base"] = __import__("time").strftime("%Y-%m-%d %H:%M"), "main 2877ca9 → ветка feat/evidence-grade"
print(json.dumps(tot, ensure_ascii=False))
open("docs/llm/evidence_v2_guard_diff.json", "w", encoding="utf-8").write(json.dumps(tot, ensure_ascii=False, indent=1) + "\n")
