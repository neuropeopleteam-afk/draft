"""Аудит подбора глазами жюри (И18): 40 потребностей → разбор без LLM, первая версия подборки, топ-5 с объяснениями.

Тот же путь, что у работодателя в интерфейсе: parse_need → (подтвердить всё) → build_selection с пустыми фильтрами.
Запуск (локальная SQLite с демо-миром, LLM выключена):
  cd backend && DATABASE_URL=sqlite:////tmp/match/demo.db LLM_DISABLED=1 python ../tools/jury_match/audit.py OUT.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.db import SessionLocal, get_engine  # noqa: E402
from app.modules.catalog.seed_data import STACK  # noqa: E402
from app.modules.matching import ranking  # noqa: E402
from app.modules.matching.need_parser import parse_need  # noqa: E402

try:
    from app.modules.matching import whatif  # noqa: E402  (появляется в этапе 2)
except ImportError:  # pragma: no cover
    whatif = None


def short_req(req: dict) -> dict:
    return {
        "direction": req.get("direction"), "grade": req.get("grade"),
        "required": [i["tag"] for i in req.get("stack_required") or []],
        "desired": [i["tag"] for i in req.get("stack_desired") or []],
        "experience": req.get("experience_years_min"), "work_format": req.get("work_format"),
        "work_formats": req.get("work_formats"), "city": req.get("city"),
        "salary": [req.get("salary_from"), req.get("salary_to")], "net": req.get("salary_net"),
        "coverage": (req.get("coverage") or {}).get("role"),
        "hint": req.get("hint"),
        "unknown": req.get("unknown_terms"),
    }


def short_result(r: dict) -> dict:
    c = r["card"]
    stack = [f"{x['requirement'].split(': ', 1)[-1]}={x['level']}" for x in r["reasons"]
             if x["requirement"].startswith(("Обязательно", "Желательно"))]
    other = [x["text"] for x in r["reasons"] if x["requirement"] in ("Формат работы", "Город присутствия")
             and x["status"] == "mismatch"]
    head = r["reasons"][0]["text"] if r["reasons"] else ""
    return {"ref": r["ref"], "score": r["score"], "category": (c.get("category") or {}).get("title")
            or (c.get("claimed") or {}).get("title"), "status": r.get("grade_status"),
            "city": c.get("city"), "format": c.get("work_format"), "stack": stack, "mismatch": other,
            "head": head[:160]}


def main(out: str) -> None:
    needs = json.loads((ROOT / "tools/jury_match/needs_40.json").read_text())["needs"]
    rows = []
    get_engine()
    with SessionLocal() as db:
        for n in needs:
            t0 = time.perf_counter()
            req = parse_need(n["text"], use_llm=False)
            t1 = time.perf_counter()
            sel = ranking.build_selection(db, req, {})
            t2 = time.perf_counter()
            row = {"id": n["id"], "kind": n["kind"], "text": n["text"], "req": short_req(req),
                   "bias": [b.get("quote") for b in req.get("bias") or []],
                   "total": sel["total_matched"], "confirmed": sel["confirmed_matched"],
                   "provisional": sel["provisional_matched"], "unconfirmed": sel["unconfirmed_matched"],
                   "categories": [(c["id"], c["relation"], c["count"]) for c in sel["categories"]],
                   "top5": [short_result(r) for r in sel["results"][:5]],
                   "ms_parse": round(1000 * (t1 - t0), 1), "ms_select": round(1000 * (t2 - t1), 1)}
            if whatif is not None:
                t3 = time.perf_counter()
                w = whatif.what_if(db, req, {})
                row["whatif"] = {"shown": w.get("shown"), "strict": w.get("strict"), "cuts": w.get("cuts", [])[:2],
                                 "options": [(o["kind"], o["text"], o["gain"]) for o in w.get("options", [])[:3]]}
                row["ms_whatif"] = round(1000 * (time.perf_counter() - t3), 1)
            rows.append(row)
    Path(out).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    for r in rows:
        q = r["req"]
        print(f"{r['id']} {q['direction']}/{q['grade']} req={q['required']} des={q['desired']} exp={q['experience']} "
              f"wf={q['work_format']}{q['work_formats'] or ''} city={q['city']} sal={q['salary']} cov={q['coverage']} "
              f"| total={r['total']} conf={r['confirmed']} prov={r['provisional']} unc={r['unconfirmed']} "
              f"| {r['ms_parse']}+{r['ms_select']} мс")
        for t in r["top5"]:
            print(f"    {t['ref']} {t['score']:.3f} {t['category']} [{t['status']}] {t['city']}/{t['format']} "
                  f"{' '.join(t['stack'])} {'; '.join(t['mismatch'])}")
        if r.get("whatif"):
            print("    what-if:", r["whatif"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/match/audit.json")
