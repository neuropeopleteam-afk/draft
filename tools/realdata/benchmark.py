"""50-text live YandexGPT comparison, plus current local rules regression evidence."""
from __future__ import annotations

from collections import Counter
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/realdata"
sys.path.insert(0, str(ROOT / "backend"))
from app.modules.matching.need_parser import parse_need

FIELDS = ["direction", "grade", "experience_years_min", "work_format", "salary_from", "salary_to"]


def baseline_parser():
    # The stand's deployed parser is base main. Compare LLM and no-LLM on this SAME revision,
    # not an improved local dictionary against a remote older parser.
    def original(path):
        return subprocess.check_output(["git", "-C", str(ROOT), "show",
                                        f"8ef691a:backend/app/modules/{path}"], text=True)
    seed, dictionary, parser = {}, {}, {}
    exec(compile(original("catalog/seed_data.py"), "baseline_seed", "exec"), seed)
    exec(compile(original("catalog/dictionary.py"), "baseline_dictionary", "exec"), dictionary)
    exec(compile(original("matching/need_parser.py"), "baseline_parser", "exec"), parser)
    parser["STACK"] = seed["STACK"]
    for key in ("DESIRED_CUES", "DIRECTION_KEYWORDS", "GRADE_KEYWORDS", "REQUIRED_CUES",
                "WORK_FORMAT_KEYWORDS", "find_key_span", "find_keys", "find_stack", "find_stack_spans"):
        parser[key] = dictionary[key]
    return parser["parse_need"]


def measure(rows, results):
    fields = Counter()
    totals = Counter()
    grade_inferences = 0
    stack_tp = stack_fp = stack_fn = quotes = invalid_quotes = 0
    mismatches = []
    for row, req in zip(rows, results):
        if req is None:
            continue
        for field in FIELDS:
            expected = row["expected"][field]
            if field == "grade" and expected is None:
                grade_inferences += req.get(field) is not None
                continue
            totals[field] += 1
            accepted = row.get("acceptable", {}).get(field, [expected])
            if req.get(field) in accepted:
                fields[field] += 1
            else:
                mismatches.append({"id": row["id"], "field": field, "expected": expected,
                                   "actual": req.get(field), "source_url": row["source_url"]})
        expected = set(row["expected_stack"])
        actual = {i["tag"] for i in req["stack_required"] + req["stack_desired"]}
        stack_tp += len(expected & actual)
        stack_fp += len(actual - expected)
        stack_fn += len(expected - actual)
        evs = list(req["evidence"].values()) + [i.get("evidence") for i in
                                                req["stack_required"] + req["stack_desired"]]
        for ev in evs:
            quotes += 1
            if not ev or row["text"][ev.get("start", 0):ev.get("end", 0)] != ev["quote"]:
                invalid_quotes += 1
    return {"fields": {f: {"correct": fields[f], "n": totals[f],
                          "accuracy": round(fields[f] / max(totals[f], 1), 4)} for f in FIELDS},
            "grade_inferences_on_unspecified": grade_inferences,
            "stack_micro_precision": round(stack_tp / max(stack_tp + stack_fp, 1), 4),
            "stack_micro_recall": round(stack_tp / max(stack_tp + stack_fn, 1), 4),
            "stack_tp_fp_fn": [stack_tp, stack_fp, stack_fn], "quotes": quotes,
            "invalid_quotes": invalid_quotes, "mismatches": mismatches}


def main():
    rows = json.loads((OUT / "vacancies_50.json").read_text())["vacancies"]
    current = [parse_need(row["text"], use_llm=False) for row in rows]
    base_parse = baseline_parser()
    base = [base_parse(row["text"], use_llm=False) for row in rows]
    result = {"corpus_size": len(rows), "annotation": "silver, not expert; exact source excerpts",
              "comparison_note": "LLM and baseline rules: same deployed 8ef691a. Current branch rules reported separately.",
              "baseline_rules": measure(rows, base), "current_rules": measure(rows, current)}
    (OUT / "rules_predictions.json").write_text(json.dumps(current, ensure_ascii=False, indent=2))
    (OUT / "parser_benchmark.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    if "--live" in sys.argv:
        scenario = json.loads((OUT / "stand_probe.json").read_text()).get("scenario")
        with httpx.Client(base_url="https://fsp.neuropeople.pro", timeout=90) as client:
            response = client.post("/api/jury/login", json={"persona": "employer", "scenario": scenario or "new"})
            response.raise_for_status()
            token = response.json()["access_token"]
            old_file = OUT / "live_predictions.json"
            old = {r["id"]: r for r in json.loads(old_file.read_text())} if "--resume" in sys.argv and old_file.exists() else {}
            def query(row):
                previous = old.get(row["id"])
                if previous and previous.get("http_status") == 200:
                    req = previous["requirements"]
                    evs = list(req["evidence"].values()) + [i.get("evidence") for i in
                                                            req["stack_required"] + req["stack_desired"]]
                    if evs and all(ev and row["text"][ev.get("start", 0):ev.get("end", 0)] == ev["quote"]
                                   for ev in evs):
                        return {**previous, "text_sha256": row["text_sha256"]}
                start = time.monotonic()
                try:
                    res = client.post("/api/employer/needs/parse", json={"text": row["text"]},
                                      headers={"Authorization": "Bearer " + token})
                    return {"id": row["id"], "http_status": res.status_code,
                            "elapsed_s": round(time.monotonic() - start, 3), "requirements": res.json(),
                            "source_url": row["source_url"], "text_sha256": row["text_sha256"]}
                except httpx.HTTPError as e:
                    return {"id": row["id"], "error": type(e).__name__, "requirements": None}
            with ThreadPoolExecutor(max_workers=2) as pool:
                live = list(pool.map(query, rows))
        (OUT / "live_predictions.json").write_text(json.dumps(live, ensure_ascii=False, indent=2))
        predictions = [r["requirements"] if r.get("http_status") == 200 else None for r in live]
        result["live"] = measure(rows, predictions)
        result["live"]["http_200"] = sum(r.get("http_status") == 200 for r in live)
        result["live"]["llm_used"] = sum(bool((r or {}).get("llm", {}).get("used")) for r in predictions)
        result["live"]["models"] = "Stand server configured YandexGPT; API returns no secret"
        result["live"]["date"] = "2026-10-07"
        (OUT / "parser_benchmark.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    elif (OUT / "live_predictions.json").exists():
        live = json.loads((OUT / "live_predictions.json").read_text())
        predictions = [r["requirements"] if r.get("http_status") == 200 else None for r in live]
        result["live"] = measure(rows, predictions)
        result["live"].update({"http_200": sum(r.get("http_status") == 200 for r in live),
                               "llm_used": sum(bool((r or {}).get("llm", {}).get("used")) for r in predictions),
                               "date": "2026-10-07", "provider": "Yandex AI Studio"})
        (OUT / "parser_benchmark.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    for method in ("baseline_rules", "current_rules", "live"):
        if method in result:
            print(method, json.dumps({k: v for k, v in result[method].items() if k != "mismatches"}, ensure_ascii=False))
    print(OUT / "parser_benchmark.json")


if __name__ == "__main__":
    main()
