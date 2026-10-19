"""Потолок покрытия: доля обязательных навыков вакансии, которые банк направления (разобранного) может подтвердить
напрямую или через implied (фреймворк, который банк проверяет)."""
import json,sys,statistics
sys.path.insert(0,'.'); sys.path.insert(0,'../tools/realdata')
import hh_plus as h
from app.modules.matching import need_parser, implied
from app.modules.matching.coverage import bank_tags
corpus, items, raws = h._load_corpus()
vals=[]; vals_direct=[]
for it in items:
    v=raws.get(it['id'])
    if v is None: continue
    r=need_parser.parse_need(h.text_of(v), use_llm=False)
    req=[s['tag'] for s in r.get('stack_required') or []]
    if not req or not r.get('direction'): continue
    bt=set(bank_tags(r['direction']))
    reach=set(bt)
    for src,tg in implied.IMPLIES.items():
        if src in bt: reach.update(tg)
    vals.append(sum(t in reach for t in req)/len(req)); vals_direct.append(sum(t in bt for t in req)/len(req))
print(json.dumps({"n":len(vals),"ceiling_with_implied":round(statistics.mean(vals),3),"ceiling_direct":round(statistics.mean(vals_direct),3)}))
