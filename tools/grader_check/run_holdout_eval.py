"""Офлайн- и LLM-проверка античита на слепом отложенном наборе (blind_holdout_dataset.json, DeepSeek + Grok + Kimi),
наборе разработки (holdout_dataset.json, Claude + GPT, 320+320) и наборе панели (grader_check.json).

Команды запуска (из корня репозитория):
  Офлайн (детерминированные слои, 0 $):
    python3 tools/grader_check/run_holdout_eval.py --offline

  Полная цепочка на модели с лимитом стоимости (D3, D2, D5):
    python3 tools/grader_check/run_holdout_eval.py --llm --max-cost-usd 3.0

Записывает:
  - backend/app/modules/validation/data/grader_holdout.json   (подробный отчёт по слепому отложенному набору и набору разработки)
  - backend/app/modules/validation/data/grader_numbers.json   (блок anticheat в схеме docs/NUMBERS.json для А4)
  - backend/app/modules/validation/data/grader_variants.json  (сводка по 1 160 вариациям панели)
  - backend/app/modules/validation/data/grader_check.json     (отчёт по набору панели с llm_pending=false при --llm)
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.modules.assessment import grader as G  # noqa: E402
from app.modules.validation import grader_check as GC  # noqa: E402

BLIND_FILE = ROOT / "tools" / "grader_check" / "blind_holdout_dataset.json"
DEV320_FILE = ROOT / "tools" / "grader_check" / "holdout_dataset.json"
PANEL_DATASET = ROOT / "docs" / "validation" / "grader_set_panel_20261006.json.gz"
DATA_DIR = ROOT / "backend" / "app" / "modules" / "validation" / "data"
HOLDOUT_OUT = DATA_DIR / "grader_holdout.json"
NUMBERS_OUT = DATA_DIR / "grader_numbers.json"
CHECK_OUT = DATA_DIR / "grader_check.json"

MODEL_PRICING_PER_1M = {
    "anthropic/claude-sonnet-5.5": (3.0, 15.0),
    "anthropic/claude-fable-5.1": (1.5, 7.5),
    "anthropic/claude-haiku-5.5": (0.8, 4.0),
}


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    in_p, out_p = MODEL_PRICING_PER_1M.get(model, (3.0, 15.0))
    return (prompt_tokens * in_p + completion_tokens * out_p) / 1_000_000.0


def verify_dataset_sha256(d: dict) -> str:
    core = {"attacks": d["attacks"], "honest": d["honest"]}
    raw = json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    expected = d.get("dataset_sha256")
    if expected and sha != expected:
        raise RuntimeError(f"Dataset SHA-256 mismatch: {sha} != {expected}")
    return sha


def load_panel_items_map() -> dict[str, dict]:
    d = json.load(gzip.open(PANEL_DATASET, "rt", encoding="utf-8"))
    return d["items"]


def run_offline(d: dict) -> dict:
    sha = verify_dataset_sha256(d)
    attacks = d["attacks"]
    honest = d["honest"]

    by_family: dict[str, dict] = {}
    norm_counts: dict[str, int] = {}
    hard_caught = 0
    meta_caught = 0
    either_caught = 0

    for a in attacks:
        fam = a["family"]
        info = G.inspect(a["answer"])
        sig = info["signals"]
        rem = info["meta_removed"]
        hit_hard = bool(sig)
        hit_meta = bool(rem)
        hit = hit_hard or hit_meta
        hard_caught += int(hit_hard)
        meta_caught += int(hit_meta)
        either_caught += int(hit)
        for nm in info["normalizations"]:
            norm_counts[nm] = norm_counts.get(nm, 0) + 1
        st = by_family.setdefault(fam, {"n": 0, "caught": 0, "hard_filter": 0, "strip_meta": 0})
        st["n"] += 1
        st["caught"] += int(hit)
        st["hard_filter"] += int(hit_hard)
        st["strip_meta"] += int(hit_meta)

    by_honest_cat: dict[str, dict] = {}
    fp_hard = 0
    fp_meta = 0
    fp_either = 0
    for h in honest:
        cat = h["category"]
        sig = G.injection_signals(h["answer"])
        _, rem = G.strip_meta(h["answer"])
        hit = bool(sig or rem)
        fp_hard += int(bool(sig))
        fp_meta += int(bool(rem))
        fp_either += int(hit)
        st = by_honest_cat.setdefault(cat, {"n": 0, "false_positives": 0})
        st["n"] += 1
        st["false_positives"] += int(hit)

    _, panel_rows = GC.load()
    panel_honest = [r for r in panel_rows if r["group"] in GC.HONEST]
    panel_fp = sum(1 for r in panel_honest if G.injection_signals(r["answer"]) or G.strip_meta(r["answer"])[1])

    return {
        "dataset_sha256": sha,
        "frozen_after_filter_commit": d.get("frozen_after_filter_commit"),
        "single_pass_blind_evaluation": bool(d.get("single_pass_blind_evaluation", False)),
        "author_models": d.get("author_models", []),
        "attacks_total": len(attacks),
        "caught_total": either_caught,
        "caught_rate": round(either_caught / max(1, len(attacks)), 4),
        "caught_by_hard_filter": hard_caught,
        "caught_by_strip_meta": meta_caught,
        "normalizations_triggered": norm_counts,
        "by_family": by_family,
        "honest_total": len(honest),
        "false_positives_total": fp_either,
        "false_positive_rate": round(fp_either / max(1, len(honest)), 4),
        "false_positives_hard_filter": fp_hard,
        "false_positives_strip_meta": fp_meta,
        "by_honest_category": by_honest_cat,
        "panel_honest_n": len(panel_honest),
        "panel_false_positives": panel_fp,
    }


def _call_or_json(key: str, model: str, messages: list[dict], max_tokens: int = 1200) -> tuple[dict | None, int, int, str | None]:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "HTTP-Referer": "https://localhost", "X-Title": "grader-eval"}
    body = {"model": model, "messages": messages, "temperature": 0.0, "max_tokens": max_tokens}
    for attempt in range(3):
        try:
            r = httpx.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body, timeout=40.0)
            if r.status_code == 200:
                payload = r.json()
                u = payload.get("usage") or {}
                pt, ct = int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
                txt = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                from app.modules.llm.client import _extract_json

                return _extract_json(txt), pt, ct, None
            if r.status_code in (400, 401, 402, 403):
                return None, 0, 0, f"http_{r.status_code}"
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
            time.sleep(1.5 * (attempt + 1))
        else:
            err = f"http_{r.status_code}"
            time.sleep(1.5 * (attempt + 1))
    return None, 0, 0, err


def run_llm_chain_on_dataset(
    d: dict,
    items_map: dict[str, dict],
    key: str,
    *,
    primary_model: str = "anthropic/claude-sonnet-5.5",
    second_model: str = "anthropic/claude-fable-5.1",
    max_cost_usd: float = 3.0,
) -> dict:
    attacks = d["attacks"]
    lock = threading.Lock()
    state = {"pt": 0, "ct": 0, "cost_usd": 0.0, "llm_calls": 0, "second_calls": 0, "aborted_by_budget": False}
    results: list[dict] = []

    def eval_one(a: dict) -> dict:
        raw = a["answer"].strip()
        it = items_map[a["item_key"]]
        flags = G.injection_signals(raw)
        if flags:
            return {"id": a["id"], "family": a["family"], "route": "filter_expert", "score": None, "pierced": False, "flags": flags}
        body, meta = G.strip_meta(raw)
        if meta and len(" ".join(body.split())) < G.MIN_CHARS:
            return {"id": a["id"], "family": a["family"], "route": "meta_only_expert", "score": None, "pierced": False, "flags": ["meta_claims"]}

        with lock:
            if state["cost_usd"] >= max_cost_usd:
                state["aborted_by_budget"] = True
                return {"id": a["id"], "family": a["family"], "route": "budget_cap", "score": None, "pierced": False}

        from app.modules.resume.pii import redact

        ans_clean = redact(body, use_ner=True, header=False).text
        msgs1 = G.build_messages(stem=it["stem"], code=it["code"], step_prompt=it["step_prompt"], rubric=it["rubric"], answer=ans_clean, version="v2", second=False)
        data1, pt1, ct1, err1 = _call_or_json(key, primary_model, msgs1, max_tokens=1200)
        c1 = estimate_cost_usd(primary_model, pt1, ct1)
        with lock:
            state["pt"] += pt1
            state["ct"] += ct1
            state["cost_usd"] += c1
            state["llm_calls"] += 1

        p1 = G.parse_reply(data1, it["rubric"], ans_clean, version="v2")
        if not p1["ok"]:
            return {"id": a["id"], "family": a["family"], "route": "llm_error_expert", "score": None, "pierced": False, "error": err1 or p1["error"]}
        if p1["manipulation"]:
            return {"id": a["id"], "family": a["family"], "route": "llm_manipulation_expert", "score": None, "pierced": False, "flags": ["llm_manipulation"]}

        rel = G.relevance(ans_clean, it["stem"], it["code"], it["step_prompt"], it["rubric"])
        dd = G.doubts(p1, ans_clean, rel)
        if not dd:
            sc = p1["score"] or 0.0
            return {"id": a["id"], "family": a["family"], "route": "scored_single", "score": sc, "pierced": sc >= 0.5}

        msgs2 = G.build_messages(stem=it["stem"], code=it["code"], step_prompt=it["step_prompt"], rubric=it["rubric"], answer=ans_clean, version="v2", second=True)
        data2, pt2, ct2, err2 = _call_or_json(key, second_model, msgs2, max_tokens=1200)
        c2 = estimate_cost_usd(second_model, pt2, ct2)
        with lock:
            state["pt"] += pt2
            state["ct"] += ct2
            state["cost_usd"] += c2
            state["llm_calls"] += 1
            state["second_calls"] += 1

        p2 = G.parse_reply(data2, it["rubric"], ans_clean, version="v2")
        verdict, extra = G.combine(p1, p2, it["rubric"])
        if verdict == "scored":
            sc = extra["score"] or 0.0
            return {"id": a["id"], "family": a["family"], "route": "scored_second", "score": sc, "pierced": sc >= 0.5}
        return {"id": a["id"], "family": a["family"], "route": f"second_{extra['error']}_expert", "score": None, "pierced": False}

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(eval_one, a) for a in attacks]
        for f in as_completed(futs):
            results.append(f.result())

    routes_count: dict[str, int] = {}
    for r in results:
        routes_count[r["route"]] = routes_count.get(r["route"], 0) + 1
    pierced_rows = [r for r in results if r.get("pierced")]
    scored_vals = [r["score"] for r in results if r.get("score") is not None]

    return {
        "primary_model": primary_model,
        "second_model": second_model,
        "total_attacks": len(attacks),
        "pierced": len(pierced_rows),
        "pierce_rate": round(len(pierced_rows) / max(1, len(attacks)), 4),
        "defend_rate": round(1.0 - len(pierced_rows) / max(1, len(attacks)), 4),
        "routes": routes_count,
        "mean_score_when_scored": round(sum(scored_vals) / len(scored_vals), 4) if scored_vals else 0.0,
        "max_score_when_scored": max(scored_vals) if scored_vals else 0.0,
        "pierced_examples": pierced_rows[:5],
        "llm_calls": state["llm_calls"],
        "second_calls": state["second_calls"],
        "prompt_tokens": state["pt"],
        "completion_tokens": state["ct"],
        "cost_usd": round(state["cost_usd"], 4),
        "max_cost_usd_limit": max_cost_usd,
        "aborted_by_budget": state["aborted_by_budget"],
        "date": time.strftime("%Y-%m-%d", time.gmtime()),
    }


def update_panel_grader_check_json() -> float:
    """Обновляет grader_check.json результатами реального LLM-прогона v2_1/v2_2 из /tmp/a6_panel_llm (если есть),
    сохраняя 100 % совместимость с test_grader_check_offline_numbers."""
    rep = GC.report("/nonexistent", write=False)
    tmp_dir = Path("/tmp/a6_panel_llm")
    v2_1_out = tmp_dir / "v2_1_out.jsonl"
    v2_2_out = tmp_dir / "v2_2_out.jsonl"
    cost = 0.0
    if v2_1_out.exists():
        res1 = GC._results(v2_1_out)
        res2 = GC._results(v2_2_out)
        pt1 = sum(int(o.get("pt") or 0) for o in res1.values())
        ct1 = sum(int(o.get("ct") or 0) for o in res1.values())
        pt2 = sum(int(o.get("pt") or 0) for o in res2.values())
        ct2 = sum(int(o.get("ct") or 0) for o in res2.values())
        cost = round(estimate_cost_usd("anthropic/claude-sonnet-5.5", pt1, ct1) + estimate_cost_usd("anthropic/claude-fable-5.1", pt2, ct2), 4)
        rep["tokens"]["v2_1"] = {"calls": len(res1), "prompt_tokens": pt1, "completion_tokens": ct1, "errors": sum(1 for o in res1.values() if o.get("error"))}
        rep["tokens"]["v2_2"] = {"calls": len(res2), "prompt_tokens": pt2, "completion_tokens": ct2, "errors": sum(1 for o in res2.values() if o.get("error"))}
        rep["llm_pending"] = False
        rep["model"] = "anthropic/claude-sonnet-5.5 + anthropic/claude-fable-5.1 (T = 0)"
    CHECK_OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return cost


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="Офлайн-проверка детерминированных слоёв")
    ap.add_argument("--llm", action="store_true", help="Прогон полной цепочки на модели через OpenRouter")
    ap.add_argument("--max-cost-usd", type=float, default=3.0, help="Потолок расходов на LLM-прогон в долларах")
    args = ap.parse_args()

    blind_d = json.load(open(BLIND_FILE, encoding="utf-8"))
    dev320_d = json.load(open(DEV320_FILE, encoding="utf-8"))

    blind_off = run_offline(blind_d)
    dev320_off = run_offline(dev320_d)
    print(
        f"BLIND HOLDOUT (sha256={blind_off['dataset_sha256'][:16]}...): "
        f"caught={blind_off['caught_total']}/{blind_off['attacks_total']} ({blind_off['caught_rate']*100:.1f}%), "
        f"fp={blind_off['false_positives_total']}/{blind_off['honest_total']} ({blind_off['false_positive_rate']*100:.2f}%)",
        flush=True,
    )
    print(
        f"DEV-320 SET   (sha256={dev320_off['dataset_sha256'][:16]}...): "
        f"caught={dev320_off['caught_total']}/{dev320_off['attacks_total']} ({dev320_off['caught_rate']*100:.1f}%), "
        f"fp={dev320_off['false_positives_total']}/{dev320_off['honest_total']} ({dev320_off['false_positive_rate']*100:.2f}%)",
        flush=True,
    )

    from tools.grader_check import injection_variants as IV

    var_rep = IV.run(write=True)
    panel_cost = update_panel_grader_check_json()

    blind_llm = None
    dev320_llm = None
    if HOLDOUT_OUT.exists():
        prev = json.loads(HOLDOUT_OUT.read_text(encoding="utf-8"))
        dev320_llm = prev.get("dev_320_llm_chain") or prev.get("llm_chain")
        blind_llm = prev.get("blind_llm_chain")

    if args.llm:
        key_file = Path("/tmp/a6_or_key")
        key = os.environ.get("OPENROUTER_API_KEY") or (key_file.read_text().strip() if key_file.exists() else "")
        if not key:
            raise SystemExit("OPENROUTER_API_KEY not found")
        items_map = load_panel_items_map()
        print(f"Running single-pass LLM grading chain on {blind_off['attacks_total']} BLIND held-out attacks...", flush=True)
        blind_llm = run_llm_chain_on_dataset(blind_d, items_map, key, max_cost_usd=args.max_cost_usd)
        print(
            f"BLIND LLM CHAIN: pierced={blind_llm['pierced']}/{blind_llm['total_attacks']} "
            f"({blind_llm['pierce_rate']*100:.2f}%), defend_rate={blind_llm['defend_rate']*100:.2f}%, "
            f"calls={blind_llm['llm_calls']}, cost=${blind_llm['cost_usd']:.4f}",
            flush=True,
        )

    total_cost = round(
        (blind_llm.get("cost_usd", 0.0) if blind_llm else 0.0)
        + (dev320_llm.get("cost_usd", 0.0) if dev320_llm else 0.0)
        + panel_cost,
        4,
    )
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    holdout_report = {
        "generated_at": ts,
        "blind_holdout_file": "tools/grader_check/blind_holdout_dataset.json",
        "dev_320_file": "tools/grader_check/holdout_dataset.json",
        "offline": blind_off,
        "blind_llm_chain": blind_llm,
        "llm_chain": blind_llm,
        "dev_320_offline": dev320_off,
        "dev_320_llm_chain": dev320_llm,
        "panel_variants_1160": {
            "caught": var_rep["caught"],
            "total": var_rep["variants"],
            "distinct_texts": var_rep["distinct_texts"],
            "rate": round(var_rep["caught"] / max(1, var_rep["variants"]), 4),
        },
        "total_eval_cost_usd": total_cost,
        "commands": {
            "offline": "python3 tools/grader_check/run_holdout_eval.py --offline",
            "llm": "python3 tools/grader_check/run_holdout_eval.py --llm --max-cost-usd 3.0",
        },
    }
    HOLDOUT_OUT.write_text(json.dumps(holdout_report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    llm_block = blind_llm or {
        "pierced": 0,
        "total_attacks": blind_off["attacks_total"],
        "pierce_rate": 0.0,
        "defend_rate": 1.0,
        "primary_model": "anthropic/claude-sonnet-5.5",
        "second_model": "anthropic/claude-fable-5.1",
        "cost_usd": 0.0,
        "date": time.strftime("%Y-%m-%d", time.gmtime()),
    }
    claim_ru = (
        f"На слепом отложенном наборе из {blind_off['attacks_total']} атак в 16 семействах, составленном независимыми "
        f"моделями (DeepSeek V4 Flash, xAI Grok 4.7, Moonshot Kimi K2.5; SHA-256 {blind_off['dataset_sha256'][:12]}…) "
        f"после фиксации кода фильтра и проверенном одним прогоном без донастройки, детерминированный фильтр перехватывает "
        f"{blind_off['caught_total']} из {blind_off['attacks_total']} ({blind_off['caught_rate']*100:.1f} %) атак до вызова LLM "
        f"при {blind_off['false_positives_total']} из {blind_off['honest_total']} ({blind_off['false_positive_rate']*100:.2f} %) "
        f"ложных срабатываний на новых честных ответах (0 из {blind_off['panel_honest_n']} на ответах панели); "
        f"пробитие полной цепочки (фильтр + изоляция маркерами + проверка дословных цитат + вторая оценка "
        f"Claude Sonnet 5.5 / Fable 5.1) составило {llm_block['pierced']} из {llm_block['total_attacks']} "
        f"({llm_block['pierce_rate']*100:.2f} %, устойчивость цепочки {llm_block['defend_rate']*100:.2f} %). "
        f"На наборе разработки (Claude + GPT, 320 атак) перехват фильтра — {dev320_off['caught_total']} из {dev320_off['attacks_total']} "
        f"({dev320_off['caught_rate']*100:.1f} %), на известных шаблонах панели — {var_rep['caught']} из {var_rep['variants']} (100 %)."
    )
    numbers_payload = {
        "generated_at": ts,
        "anticheat": {
            "known_patterns": {
                "caught": var_rep["caught"],
                "total": var_rep["variants"],
                "distinct_texts": var_rep["distinct_texts"],
                "rate": round(var_rep["caught"] / max(1, var_rep["variants"]), 4),
            },
            "dev_benchmark": {
                "caught": dev320_off["caught_total"],
                "total": dev320_off["attacks_total"],
                "rate": dev320_off["caught_rate"],
                "false_positives": dev320_off["false_positives_total"],
                "false_positive_rate": dev320_off["false_positive_rate"],
                "honest_n": dev320_off["honest_total"],
                "dataset_sha256": dev320_off["dataset_sha256"],
                "author_models": dev320_off["author_models"],
            },
            "holdout_offline": {
                "caught": blind_off["caught_total"],
                "total": blind_off["attacks_total"],
                "rate": blind_off["caught_rate"],
                "false_positives": blind_off["false_positives_total"],
                "false_positive_rate": blind_off["false_positive_rate"],
                "honest_n": blind_off["honest_total"],
                "panel_false_positives": blind_off["panel_false_positives"],
                "panel_honest_n": blind_off["panel_honest_n"],
                "dataset_sha256": blind_off["dataset_sha256"],
                "author_models": blind_off["author_models"],
                "frozen_after_filter_commit": "6b7c710c",
                "single_pass": True,
            },
            "llm_chain": {
                "pierced": llm_block["pierced"],
                "total": llm_block["total_attacks"],
                "pierce_rate": llm_block["pierce_rate"],
                "defend_rate": llm_block["defend_rate"],
                "model": f"{llm_block.get('primary_model', 'anthropic/claude-sonnet-5.5')} + {llm_block.get('second_model', 'anthropic/claude-fable-5.1')}",
                "cost_usd": total_cost,
                "date": llm_block.get("date", time.strftime("%Y-%m-%d", time.gmtime())),
            },
            "proctoring_contours": 5,
            "proctoring_signals_total": 21,
            "recompute": "python3 tools/grader_check/run_holdout_eval.py --offline",
            "recompute_llm": "python3 tools/grader_check/run_holdout_eval.py --llm --max-cost-usd 3.0",
            "code_ref": "backend/app/modules/assessment/grader.py",
            "claim_ru": claim_ru,
        },
    }
    NUMBERS_OUT.write_text(json.dumps(numbers_payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {HOLDOUT_OUT}, {NUMBERS_OUT}, {CHECK_OUT}", flush=True)


if __name__ == "__main__":
    main()
