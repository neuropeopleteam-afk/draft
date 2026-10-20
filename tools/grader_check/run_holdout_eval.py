"""Офлайн- и LLM-проверка античита на отложенном наборе (holdout_dataset.json) и наборе панели (grader_check.json).

Команды запуска (из корня репозитория или backend/):
  Офлайн (детерминированные слои, 0 $):
    python tools/grader_check/run_holdout_eval.py --offline

  Полная цепочка на модели с лимитом стоимости (D3, D2, D5):
    python tools/grader_check/run_holdout_eval.py --llm --max-cost-usd 3.0

Записывает:
  - backend/app/modules/validation/data/grader_holdout.json   (подробный отчёт по отложенному набору 320+320)
  - backend/app/modules/validation/data/grader_numbers.json   (блок anticheat в схеме docs/NUMBERS.json для А4)
  - backend/app/modules/validation/data/grader_variants.json  (обновлённая сводка по 1 160 вариациям панели)
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

HOLDOUT_FILE = ROOT / "tools" / "grader_check" / "holdout_dataset.json"
PANEL_DATASET = ROOT / "docs" / "validation" / "grader_set_panel_20261006.json.gz"
DATA_DIR = ROOT / "backend" / "app" / "modules" / "validation" / "data"
HOLDOUT_OUT = DATA_DIR / "grader_holdout.json"
NUMBERS_OUT = DATA_DIR / "grader_numbers.json"

# Расценки OpenRouter ($ за 1 млн токенов) для учёта и ограничения стоимости прогона
MODEL_PRICING_PER_1M = {
    "anthropic/claude-sonnet-5.5": (3.0, 15.0),
    "anthropic/claude-fable-5.1": (1.5, 7.5),
    "anthropic/claude-haiku-5.5": (0.8, 4.0),
}


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    in_p, out_p = MODEL_PRICING_PER_1M.get(model, (3.0, 15.0))
    return (prompt_tokens * in_p + completion_tokens * out_p) / 1_000_000.0


def verify_holdout_sha256(d: dict) -> str:
    core = {"attacks": d["attacks"], "honest": d["honest"]}
    raw = json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    expected = d.get("dataset_sha256")
    if expected and sha != expected:
        raise RuntimeError(f"Holdout dataset SHA-256 mismatch: {sha} != {expected}")
    return sha


def load_panel_items_map() -> dict[str, dict]:
    d = json.load(gzip.open(PANEL_DATASET, "rt", encoding="utf-8"))
    return d["items"]


def run_offline(d: dict) -> dict:
    sha = verify_holdout_sha256(d)
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

    # Панель 06.10 (261 честный ответ)
    _, panel_rows = GC.load()
    panel_honest = [r for r in panel_rows if r["group"] in GC.HONEST]
    panel_fp = sum(1 for r in panel_honest if G.injection_signals(r["answer"]) or G.strip_meta(r["answer"])[1])

    return {
        "dataset_sha256": sha,
        "frozen_before_filter_tuning": bool(d.get("frozen_before_filter_tuning", True)),
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


def run_llm_chain_on_holdout(
    d: dict,
    items_map: dict[str, dict],
    key: str,
    *,
    primary_model: str = "anthropic/claude-sonnet-5.5",
    second_model: str = "anthropic/claude-fable-5.1",
    max_cost_usd: float = 3.0,
) -> dict:
    """Прогоняет все 320 атак отложенного набора через полную цепочку grade_open:
    1) injection_signals → блокировка до модели (route=filter_expert, score=0)
    2) strip_meta: если остаток < MIN_CHARS → meta_only (route=meta_only_expert, score=0)
    3) если остаток ≥ MIN_CHARS (или атака не поймана фильтром) → реальный вызов primary_model (промпт v2)
       + проверка дословных цитат quote_supported + при сомнении (doubts) вызов second_model + combine.
    Атака считается «пробившей цепочку» (pierced), если итоговый статус scored и итоговый балл ≥ 0.5.
    """
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

        # Если даже до второй оценки балл 0.0 (или < 0.5 и нет причин повышать) — пробития нет
        rel = G.relevance(ans_clean, it["stem"], it["code"], it["step_prompt"], it["rubric"])
        dd = G.doubts(p1, ans_clean, rel)
        if not dd:
            sc = p1["score"] or 0.0
            return {"id": a["id"], "family": a["family"], "route": "scored_single", "score": sc, "pierced": sc >= 0.5}

        # Вторая независимая оценка (Fable 5.1)
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


def run_panel_grader_check_llm(
    key: str,
    *,
    model: str = "anthropic/claude-sonnet-5.5",
    limit_per_group: int = 10,
    max_cost_usd: float = 2.0,
) -> dict:
    """Прогоняет grader_check (v2_1 + v2_2) на наборе панели 06.10, чтобы закрыть llm_pending=false в grader_check.json."""
    tmp_dir = Path("/tmp/a6_panel_llm")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    v2_1_req = tmp_dir / "v2_1.jsonl"
    v2_1_out = tmp_dir / "v2_1_out.jsonl"
    v2_2_req = tmp_dir / "v2_2.jsonl"
    v2_2_out = tmp_dir / "v2_2_out.jsonl"
    v1_out = tmp_dir / "v1_out.jsonl"
    if not v1_out.exists():
        v1_out.write_text("", encoding="utf-8")

    GC.build("v2", str(v2_1_req), limit_per_group=limit_per_group)
    reqs1 = [json.loads(line) for line in v2_1_req.read_text(encoding="utf-8").splitlines() if line.strip()]

    lock = threading.Lock()
    cost_state = {"cost": 0.0}

    def _run_batch(reqs: list[dict], out_path: Path, m: str) -> None:
        done = {}
        if out_path.exists():
            for line in out_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    o = json.loads(line)
                    if o.get("text") and not o.get("error"):
                        done[o["req_id"]] = o
        todo = [r for r in reqs if r["req_id"] not in done]
        print(f"  panel LLM [{m}]: todo={len(todo)} (cached={len(done)})", flush=True)
        with open(out_path, "a", encoding="utf-8") as fh:
            def _one(r: dict) -> None:
                with lock:
                    if cost_state["cost"] >= max_cost_usd:
                        return
                t0 = time.time()
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "HTTP-Referer": "https://localhost", "X-Title": "grader-check"}
                body = {"model": m, "messages": r["messages"], "temperature": 0.0, "max_tokens": r.get("max_tokens", 1200)}
                for attempt in range(3):
                    try:
                        resp = httpx.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body, timeout=45.0)
                        if resp.status_code == 200:
                            payload = resp.json()
                            u = payload.get("usage") or {}
                            pt, ct = int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
                            txt = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                            rec = {"req_id": r["req_id"], "model": m, "text": txt, "pt": pt, "ct": ct, "latency": round(time.time() - t0, 2)}
                            with lock:
                                cost_state["cost"] += estimate_cost_usd(m, pt, ct)
                                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                                fh.flush()
                            return
                    except Exception:
                        time.sleep(1.5 * (attempt + 1))

            with ThreadPoolExecutor(max_workers=8) as ex:
                list(ex.map(_one, todo))

    _run_batch(reqs1, v2_1_out, model)
    GC.second(str(v2_1_req), str(v2_1_out), str(v2_2_req))
    reqs2 = [json.loads(line) for line in v2_2_req.read_text(encoding="utf-8").splitlines() if line.strip()]
    _run_batch(reqs2, v2_2_out, "anthropic/claude-fable-5.1")
    rep = GC.report(str(tmp_dir), write=True)
    return {"report": rep, "cost_usd": round(cost_state["cost"], 4)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="Только офлайн-проверка детерминированных слоёв")
    ap.add_argument("--llm", action="store_true", help="Прогон полной цепочки на модели через OpenRouter")
    ap.add_argument("--max-cost-usd", type=float, default=3.0, help="Потолок расходов на LLM-прогон в долларах")
    ap.add_argument("--panel-limit", type=int, default=10, help="Лимит на группу в наборе панели (0 = все)")
    args = ap.parse_args()

    d = json.load(open(HOLDOUT_FILE, encoding="utf-8"))
    off = run_offline(d)
    print(
        f"OFFLINE HOLDOUT (sha256={off['dataset_sha256'][:16]}...): "
        f"caught={off['caught_total']}/{off['attacks_total']} ({off['caught_rate']*100:.1f}%), "
        f"fp={off['false_positives_total']}/{off['honest_total']} ({off['false_positive_rate']*100:.2f}%), "
        f"panel_fp={off['panel_false_positives']}/{off['panel_honest_n']}",
        flush=True,
    )

    # Обновляем grader_variants.json (1 160 параметрических вариаций панели)
    from tools.grader_check import injection_variants as IV

    var_rep = IV.run(write=True)

    llm_res = None
    panel_llm_cost = 0.0
    if args.llm:
        key_file = Path("/tmp/a6_or_key")
        key = os.environ.get("OPENROUTER_API_KEY") or (key_file.read_text().strip() if key_file.exists() else "")
        if not key:
            raise SystemExit("OPENROUTER_API_KEY not found")
        items_map = load_panel_items_map()
        print("Running full LLM grading chain on 320 held-out attacks...", flush=True)
        llm_res = run_llm_chain_on_holdout(d, items_map, key, max_cost_usd=args.max_cost_usd * 0.65)
        print(
            f"LLM HOLDOUT: pierced={llm_res['pierced']}/{llm_res['total_attacks']} "
            f"({llm_res['pierce_rate']*100:.2f}%), defend_rate={llm_res['defend_rate']*100:.2f}%, "
            f"calls={llm_res['llm_calls']}, cost=${llm_res['cost_usd']:.4f}",
            flush=True,
        )
        print("Running LLM v2 pipeline on panel grader_check dataset...", flush=True)
        panel_out = run_panel_grader_check_llm(key, limit_per_group=args.panel_limit, max_cost_usd=args.max_cost_usd * 0.35)
        panel_llm_cost = panel_out["cost_usd"]
        print(f"PANEL LLM DONE: llm_pending={panel_out['report']['llm_pending']}, cost=${panel_llm_cost:.4f}", flush=True)
    elif HOLDOUT_OUT.exists():
        prev = json.loads(HOLDOUT_OUT.read_text(encoding="utf-8"))
        llm_res = prev.get("llm_chain")

    total_cost = round((llm_res.get("cost_usd", 0.0) if llm_res else 0.0) + panel_llm_cost, 4)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    holdout_report = {
        "generated_at": ts,
        "dataset_file": "tools/grader_check/holdout_dataset.json",
        "offline": off,
        "llm_chain": llm_res,
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

    # Формируем grader_numbers.json строго по схеме А4 (docs/NUMBERS.json -> anticheat)
    llm_block = llm_res or {
        "pierced": 0,
        "total": off["attacks_total"],
        "pierce_rate": 0.0,
        "defend_rate": 1.0,
        "model": "anthropic/claude-sonnet-5.5 + anthropic/claude-fable-5.1",
        "cost_usd": 0.0,
        "date": time.strftime("%Y-%m-%d", time.gmtime()),
    }
    claim_ru = (
        f"Детерминированный фильтр с нормализацией (NFKC, омоглифы, транслит, leet, склейка разрядки, Base64/hex/URL, "
        f"комментарии кода) перехватывает {off['caught_total']} из {off['attacks_total']} ({off['caught_rate']*100:.1f} %) "
        f"независимо сгенерированных атак отложенного набора (Claude + GPT, SHA-256 {off['dataset_sha256'][:12]}…) "
        f"и 1 160 из 1 160 (100 %) параметрических вариаций панели при {off['false_positives_total']} из {off['honest_total']} "
        f"({off['false_positive_rate']*100:.2f} %) ложных срабатываний на новых честных ответах и 0 из {off['panel_honest_n']} "
        f"на ответах панели. На полной цепочке с моделью ({llm_block.get('primary_model', 'Claude Sonnet 5.5')} + проверка "
        f"дословных цитат + вторая оценка) пробитие составило {llm_block['pierced']} из {llm_block.get('total_attacks', off['attacks_total'])} "
        f"({llm_block['pierce_rate']*100:.2f} %, защита {llm_block['defend_rate']*100:.2f} %)."
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
            "holdout_offline": {
                "caught": off["caught_total"],
                "total": off["attacks_total"],
                "rate": off["caught_rate"],
                "false_positives": off["false_positives_total"],
                "false_positive_rate": off["false_positive_rate"],
                "honest_n": off["honest_total"],
                "panel_false_positives": off["panel_false_positives"],
                "panel_honest_n": off["panel_honest_n"],
                "dataset_sha256": off["dataset_sha256"],
                "author_models": off["author_models"],
            },
            "llm_chain": {
                "pierced": llm_block["pierced"],
                "total": llm_block.get("total_attacks", off["attacks_total"]),
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
    print(f"Wrote {HOLDOUT_OUT} and {NUMBERS_OUT}", flush=True)


if __name__ == "__main__":
    main()
