"""Я2: сводка замера сильнейших моделей (strongest_bench.py) → docs/llm/strongest.json (+ копия для /validation и
таблица docs/LLM.md, раздел 12).

Все метрики — на одной малой выборке для всех моделей (Sonnet и правила — тот же срез из полного прогона 09.10).
Разметки — модели, не люди: вакансии — silver И8 и исправленная (silver + лишние теги, подтверждённые GPT 6.1 Sol),
резюме — автор синтетического набора (модель), оценщик — согласие сильнейших моделей (медиана, без самой модели).
Интервал — бутстреп 90 % по входам (1000 повторов): на 15–50 входах разница в несколько сотых — шум.
"""
from __future__ import annotations

import json
from pathlib import Path
import random
import statistics as st
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "llm"))
sys.path.insert(0, str(ROOT / "tools" / "realdata"))

import ru_llm_summary as RS  # noqa: E402

OUT = ROOT / "docs" / "llm" / "strongest.json"
DATA_COPY = ROOT / "backend/app/modules/validation/data/strongest.json"
PRICES = ROOT / "docs" / "llm" / "strongest_prices.json"
SONNET_DIR = Path("/tmp/rullm/openrouter_anthropic_claude_sonnet_5.5")
RULES_DIR = Path("/tmp/rullm/rules")
SAMPLE_VAC = 15
# эталон оценщика: согласие сильнейших (медиана оценок, без самой оцениваемой модели); пока их нет — все прочие модели
JUDGES = ["anthropic/claude-opus-5.5", "anthropic/claude-fable-5.1", "openai/gpt-6-astra-pro"]
ATTACK_GROUPS = ("adv_generic", "adv_injection", "adv_e1", "adv_e3", "adv_e5")
FAMILY = {"anthropic": "Anthropic", "openai": "OpenAI", "google": "Google", "x-ai": "xAI", "moonshotai": "Moonshot",
          "qwen": "Alibaba Qwen", "deepseek": "DeepSeek", "z-ai": "Zhipu (Z.ai)", "yandex": "Яндекс"}
# бюджет задержки продукта: разбор — тайм-аут 25 с на вызов; оценка — 50 с на ответ (первая + вторая)
BUDGET_S = {"needs_delta": 25, "needs_jury": 25, "resume": 25, "grade": 25}


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _boot(vals_fn, n: int, reps: int = 1000, seed: int = 7) -> tuple[float, float] | None:
    """90 % бутстреп-интервал статистики vals_fn(индексы) по n входам."""
    if n < 3:
        return None
    rnd = random.Random(seed)
    xs = sorted(vals_fn([rnd.randrange(n) for _ in range(n)]) for _ in range(reps))
    return round(xs[int(0.05 * reps)], 3), round(xs[int(0.95 * reps) - 1], 3)


def _tags(req: dict) -> set:
    return {i["tag"] for i in (req.get("stack_required") or [])} | {i["tag"] for i in (req.get("stack_desired") or [])}


def _prf(pairs: list[tuple[set, set]]) -> tuple[float, float, float]:
    tp = sum(len(p & g) for p, g in pairs)
    fp = sum(len(p - g) for p, g in pairs)
    fn = sum(len(g - p) for p, g in pairs)
    pr, rc = tp / max(1, tp + fp), tp / max(1, tp + fn)
    return round(pr, 4), round(rc, 4), round(2 * pr * rc / (pr + rc), 4) if pr and rc else 0.0


# ------------------------------------------------------------------ функции
def needs_cell(per: list[dict], ref: dict) -> dict:
    per = [x for x in per if x["id"] in ref]
    c = RS._calls(per)
    pairs_c = [(_tags(x["requirements"]), set(ref[x["id"]]["corrected_stack"])) for x in per]
    pairs_s = [(_tags(x["requirements"]), set(ref[x["id"]]["silver_stack"])) for x in per]
    p, r, f = _prf(pairs_c)
    ps, rs, fs = _prf(pairs_s)
    c["quality"] = {"f1": f, "p": p, "r": r, "f1_silver": fs, "p_silver": ps, "r_silver": rs, "n": len(per),
                    "ci90": _boot(lambda ix: _prf([pairs_c[i] for i in ix])[2], len(pairs_c))}
    return c


def jury_cells(per_by_model: dict[str, list[dict]]) -> dict[str, dict]:
    tags = {m: {x["id"]: RS._tagset(x["tags"]) for x in per if x.get("ok") or m == "rules"}
            for m, per in per_by_model.items()}
    models = [m for m in per_by_model if m != "rules"]
    out = {}
    for m, per in per_by_model.items():
        others = [o for o in models if o != m]
        jac = []
        for x in per:
            if m != "rules" and not x.get("ok"):
                continue
            votes = [tags[o][x["id"]] for o in others if x["id"] in tags[o]]
            if len(votes) < 2:
                continue
            allt = set().union(*votes)
            cons = {t for t in allt if sum(t in v for v in votes) * 2 > len(votes)}
            mine = tags[m][x["id"]]
            jac.append(len(mine & cons) / max(1, len(mine | cons)))
        c = RS._calls(per) if m != "rules" else {}
        c["quality"] = {"jaccard": round(st.mean(jac), 3) if jac else None, "n": len(jac),
                        "ci90": _boot(lambda ix: st.mean(jac[i] for i in ix), len(jac)) if jac else None}
        out[m] = c
    return out


def resume_cell(per: list[dict], gold: dict, with_calls: bool = True) -> dict:
    c = RS._calls(per) if with_calls else {}
    q = RS._resume_quality(per, gold)
    pairs = [(set(x["stack"]), set(gold[x["id"]]["stack"])) for x in per]
    q["ci90"] = _boot(lambda ix: _prf([pairs[i] for i in ix])[2], len(pairs))
    c["quality"] = q
    return c


def _grade_scores(out_path: Path) -> tuple[dict, dict]:
    """Оценки модели по выборке: балл после проверки цитат (как в продукте, без второй оценки) и вызовы."""
    from app.modules.assessment import grader as G
    from app.modules.validation import grader_check as GC

    items, rows = GC.load()
    by = {r["id"]: r for r in rows}
    first: dict[str, dict] = {}
    for line in (open(out_path, encoding="utf-8") if out_path.exists() else []):
        o = json.loads(line)
        first.setdefault(o["req_id"], o)  # первая попытка на вход
    scores, calls = {}, {"n": len(first), "ok": 0, "format_fail": 0, "transport_fail": 0, "lat": [], "cost": 0.0}
    for rid, o in first.items():
        calls["cost"] += o.get("cost") or 0
        r = by[rid]
        it = items[r["item"]]
        if o.get("error") and o["error"] not in RS.FORMAT_ERRORS:
            calls["transport_fail"] += 1
            continue
        ans = GC._redacted(G.strip_meta(r["answer"].strip())[0])
        p = GC._parse(o if not o.get("error") else None, it["rubric"], ans, "v2")
        if not p.get("ok"):
            calls["format_fail"] += 1
            continue
        calls["ok"] += 1
        calls["lat"].append(float(o.get("latency_call") or o.get("latency") or 0))
        scores[rid] = {"score": p["score"], "manipulation": bool(p.get("manipulation")), "group": r["group"],
                       "item": r["item"]}
    return scores, calls


def grade_cells(score_by_model: dict[str, tuple[dict, dict]], judges: list[str]) -> tuple[dict, dict]:
    present = [j for j in judges if j in score_by_model]
    ref_note = ("согласие " + ", ".join(present) if len(present) >= 2 else
                "медиана всех остальных моделей замера (сильнейшие ещё не замерены)")
    out = {}
    for m, (sc, calls) in score_by_model.items():
        pool = [j for j in present if j != m] if len(present) >= 2 else [o for o in score_by_model if o != m]
        errs = []
        for rid, x in sc.items():
            if x["group"] in ATTACK_GROUPS:
                continue
            ref = [score_by_model[o][0][rid]["score"] for o in pool if rid in score_by_model[o][0]]
            if len(ref) >= (2 if len(pool) >= 2 else 1):
                errs.append(abs(x["score"] - st.median(ref)))
        att = [x for x in sc.values() if x["group"] in ATTACK_GROUPS]
        refs: dict[str, dict[str, float]] = {}
        for x in sc.values():
            if x["group"] in ("ref_strong", "ref_medium", "ref_weak"):
                refs.setdefault(x["item"], {})[x["group"]] = x["score"]
        full = [v for v in refs.values() if len(v) == 3]
        lat = calls["lat"]
        out[m] = {
            "n": calls["n"], "calls": calls["n"], "ok": calls["ok"], "format_fail": calls["format_fail"],
            "transport_fail": calls["transport_fail"],
            "p50_s": round(RS.pct(lat, 0.5), 2) if lat else None, "p95_s": round(RS.pct(lat, 0.95), 2) if lat else None,
            "cost_usd": round(calls["cost"], 4) if calls["cost"] else None,
            "quality": {
                "mae": round(st.mean(errs), 3) if errs else None, "mae_n": len(errs),
                "ci90": _boot(lambda ix: st.mean(errs[i] for i in ix), len(errs)) if errs else None,
                "attacks_pass": sum(1 for x in att if x["score"] >= 0.5 and not x["manipulation"]),
                "attacks_flagged": sum(1 for x in att if x["manipulation"]), "attacks_n": len(att),
                "order_strict": sum(1 for v in full if v["ref_strong"] > v["ref_medium"] > v["ref_weak"]),
                "order_n": len(full),
            }}
    return out, {"judges": present, "note": ref_note}


def _price(c: dict) -> dict:
    if not c.get("calls") or not c.get("cost_usd"):
        return {}
    usd = c["cost_usd"] / c["calls"] * 1000
    return {"usd_per_1k_calls": round(usd, 2), "rub_per_1k_calls": round(usd * RS.USD_RUB, 1)}


# ------------------------------------------------------------------ сборка
def build(wdir: Path) -> dict:
    from app.modules.matching import need_parser as NP  # noqa: F401
    import ru_llm_bench as B

    prices = _load(PRICES) or {"models": {}}
    ref = {v["vacancy_id"]: v for v in json.loads((ROOT / "docs/llm/extra_tags_judgement.json").read_text())["vacancies"]}
    vac_ids = [v["id"] for v in B._vacancies()[:SAMPLE_VAC]]
    ref = {k: ref[k] for k in vac_ids}
    gold = {r["id"]: r["gold"] for r in json.loads((ROOT / "docs/llm/resume_synth.json").read_text())["rows"]}

    models = []  # (model id, каталог)
    for d in sorted(wdir.glob("openrouter_*")):
        mid = None
        for f in ("resume", "needs_delta", "needs_jury", "grade"):
            j = _load(d / f"{f}.json")
            if j:
                mid = j["spec"].split("=", 1)[1]
                break
        if mid and mid != "anthropic/claude-sonnet-5.5":  # Sonnet: старые функции — полный прогон 09.10 (SONNET_DIR)
            models.append((mid, d))
    sonnet = "anthropic/claude-sonnet-5.5"
    sample_ids = {json.loads(x)["req_id"] for x in open(next(d for _, d in models) / "g" / "v2_1.jsonl")} if models else set()

    cells: dict[str, dict[str, dict]] = {"needs_delta": {}, "needs_jury": {}, "resume": {}, "grade": {}}
    jury_in: dict[str, list] = {}
    grade_in: dict[str, tuple] = {}
    for mid, d in [(sonnet, SONNET_DIR)] + models:
        nd = _load(d / "needs_delta.json")
        if nd:
            cells["needs_delta"][mid] = needs_cell(nd["per_text"], ref)
        nj = _load(d / "needs_jury.json")
        if nj:
            jury_in[mid] = nj["per_text"]
        rs = _load(d / "resume.json")
        if rs:
            cells["resume"][mid] = resume_cell(rs["per_text"], gold)
        gout = d / "g" / "v2_1_out.jsonl"
        if gout.exists():
            sc, calls = _grade_scores(gout)
            if mid == sonnet:  # тот же срез из полного прогона
                sc = {k: v for k, v in sc.items() if k in sample_ids}
                first = {}
                for line in open(gout, encoding="utf-8"):
                    o = json.loads(line)
                    if o["req_id"] in sample_ids:
                        first.setdefault(o["req_id"], o)
                sub = d / "g" / "_sample_out.jsonl"
                sub.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in first.values()), encoding="utf-8")
                sc, calls = _grade_scores(sub)
            grade_in[mid] = (sc, calls)
    variants = {}  # проба настроек разбора на той же выборке (strongest_bench.py variant), напр. без рассуждений
    probes = []
    for mid, d in models:
        for vf in sorted(d.glob("needs_delta__*.json")):
            v = _load(vf)
            info = v.get("variant") or {}
            c = needs_cell(v["per_text"], ref)
            c["variant"] = info
            if info.get("limit") == SAMPLE_VAC:
                key = f"{mid}@{info['name']}"
                cells["needs_delta"][key] = c
                variants[key] = {"base": mid, **info}
            else:
                probes.append({"model": mid, **info, "ok": c["ok"], "calls": c["calls"], "errors": c["errors"],
                               "p50_s": c["p50_s"], "p95_s": c["p95_s"]})
    i24 = _load(ROOT / "docs/llm/needs_qwen_tags.json")  # И24: Qwen3.5-9B (те же веса, что профиль llm-local на CPU)
    if i24:
        per = [{**x, "called": True} for x in i24["per_text"]]
        key = "qwen/qwen3.5-9b@i24"
        cells["needs_delta"][key] = needs_cell(per, ref)
        variants[key] = {"base": "qwen/qwen3.5-9b", "name": "i24",
                         "note": "И24, 09.10: полный запрос (не дельта), провайдер local, OpenRouter bf16 — те же веса, "
                                 "что профиль llm-local на CPU (docs/llm/needs_qwen_tags.json)"}
    rules_needs = _load(RULES_DIR / "needs.json")
    if rules_needs:
        per = [{"id": x["id"], "called": False, **x} for x in rules_needs["per_text"]]
        c = needs_cell(per, ref)
        cells["needs_delta"]["rules"] = {"quality": c["quality"]}
    rj = _load(RULES_DIR / "needs_jury.json")
    if rj:
        jury_in["rules"] = rj["per_text"]
    cells["needs_jury"] = jury_cells(jury_in)
    rr = _load(RULES_DIR / "resume.json")
    if rr:
        cells["resume"]["rules"] = resume_cell(rr["per_text"], gold, with_calls=False)
    gcells, gref = grade_cells(grade_in, JUDGES)
    cells["grade"] = gcells
    for f in cells.values():
        for m, c in f.items():
            if m != "rules":
                c["price"] = _price(c)

    meta = {}
    for key in {m for f in cells.values() for m in f if m != "rules"}:
        mid = key.split("@", 1)[0]
        p = prices["models"].get(mid) or {}
        vendor = mid.split("/")[0]
        meta[key] = {"name": p.get("name") or mid, "family": FAMILY.get(vendor, vendor),
                     "open_weights": p.get("hugging_face_id") or ("Qwen/Qwen3.5-9B" if mid == "qwen/qwen3.5-9b" else None),
                     "in_usd_per_m": p.get("in_usd_per_m"), "out_usd_per_m": p.get("out_usd_per_m"),
                     "stand": key == sonnet, "variant": variants.get(key)}
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    d = {"title": "Сильнейшие модели: замер по функциям (малая выборка)", "date": time.strftime("%Y-%m-%d"),
         "code_sha": sha, "models": meta, "cells": cells, "grade_reference": gref,
         "sample": {"needs_delta": len(ref), "needs_jury": 15, "resume": len(gold), "grade": len(sample_ids)},
         "conditions": CONDITIONS, "pending": None, "probes": probes, "not_measured": NOT_MEASURED}
    d["recommendation"] = recommend(d)
    dirs = {mid: [dd] for mid, dd in models}
    dirs[sonnet] = [SONNET_DIR, wdir / B.slug("openrouter=" + sonnet)]
    for mid in list(dirs):
        if mid not in meta:
            p = prices["models"].get(mid) or {}
            meta[mid] = {"name": p.get("name") or mid, "family": FAMILY.get(mid.split("/")[0], mid.split("/")[0]),
                         "open_weights": p.get("hugging_face_id"), "in_usd_per_m": p.get("in_usd_per_m"),
                         "out_usd_per_m": p.get("out_usd_per_m"), "stand": mid == sonnet, "variant": None}
    fv = functions_view(dirs, grade_in, {k: list(v["corrected_stack"]) for k, v in ref.items()}, gold, sample_ids,
                        d["models"])
    d.update(fv)
    import strongest_quality as Q
    ref50 = {v["vacancy_id"]: list(v["corrected_stack"]) for v in
             json.loads((ROOT / "docs/llm/extra_tags_judgement.json").read_text())["vacancies"]}
    vac = B._vacancies()
    d["full_run"] = full_view(wdir, ref50, Q.vac_expected(vac), {v["id"]: v["text"] for v in vac})
    d["pending"] = pending_text(d)
    d["title"] = "Сильнейшие модели: качество, надёжность, задержка и цена по функциям (малая выборка)"
    return d


# ------------------------------------------------------------------ функции продукта: качество прежде всего
W = {"quality": 0.5, "reliability": 0.25, "latency": 0.15, "price": 0.10}
ERR_RU = {"empty": "пустой", "invalid_json": "невалидный JSON", "invalid_reply": "проверка вызывающего",
          "schema_rejected": "схема отклонена", "timeout": "тайм-аут"}
FUNC_RU = {"parse_need": "Разбор потребности", "resume": "Разбор резюме", "grade": "Оценка развёрнутых ответов"}


def _pick(dl: list[Path], name: str, base_ok_min: int | None = None):
    """Первый существующий файл name среди каталогов модели; для разбора — вариант без рассуждений
    (<name>__noreason*.json), если в основном прогоне отказов больше 1 из 15 (рассуждения съели лимит ответа)."""
    base = next((_load(x / f"{name}.json") for x in dl if (x / f"{name}.json").exists()), None)
    if base_ok_min is not None:
        bad = base is None or sum(1 for x in base["per_text"] if x.get("ok")) < base_ok_min * len(base["per_text"])
        if bad:
            for x in dl:
                for vf in sorted(x.glob(f"{name}__noreason*.json")):
                    v = _load(vf)
                    if len(v["per_text"]) >= len((base or v)["per_text"]):
                        return v, "без рассуждений"
    return base, "как в продукте"


def _calls_of(per: list[dict] | None) -> list[dict]:
    return [{"ok": bool(x.get("ok")), "error": x.get("error"), "cost": x.get("cost_usd") or 0,
             "latency_s": (x["latency_ms"] / 1000 if x.get("latency_ms") is not None else None)}
            for x in per or [] if x.get("called")]


def _grade_raw(path: Path, strip_rep: bool = False) -> tuple[dict, list[dict]]:
    """Ответы оценщика: {req_id: [баллы]} (первая попытка на каждый вход/повтор) и вызовы для надёжности."""
    from app.modules.assessment import grader as G
    from app.modules.validation import grader_check as GC

    items, rows = GC.load()
    by = {r["id"]: r for r in rows}
    first: dict[str, dict] = {}
    for line in (open(path, encoding="utf-8") if path.exists() else []):
        o = json.loads(line)
        first.setdefault(o["req_id"], o)
    scores: dict[str, list] = {}
    calls = []
    for key, o in first.items():
        rid = key.split("@@", 1)[0] if strip_rep else key
        r = by.get(rid)
        if not r:
            continue
        lat = float(o.get("latency_call") or o.get("latency") or 0)
        if o.get("error") and o["error"] not in RS.FORMAT_ERRORS:
            calls.append({"ok": False, "error": o["error"], "latency_s": lat, "cost": o.get("cost") or 0})
            continue
        ans = GC._redacted(G.strip_meta(r["answer"].strip())[0])
        p = GC._parse(o if not o.get("error") else None, items[r["item"]]["rubric"], ans, "v2")
        ok = bool(p.get("ok"))
        calls.append({"ok": ok, "error": None if ok else (o.get("error") or "invalid_reply"), "latency_s": lat,
                      "cost": o.get("cost") or 0})
        if ok:
            scores.setdefault(rid, []).append(p["score"])
    return scores, calls


def _judge_rows(dl: list[Path]) -> list[dict]:
    from app.modules.llm.client import _extract_json

    out = []
    for x in dl:
        for jf in sorted((x / "g").glob("judge__*_out.jsonl")) if (x / "g").exists() else []:
            jname = jf.name[len("judge__"):-len("_out.jsonl")]
            seen = set()
            for line in open(jf, encoding="utf-8"):
                o = json.loads(line)
                if o["req_id"] in seen or o.get("error"):
                    continue
                seen.add(o["req_id"])
                d = _extract_json(o.get("text") or "")
                if isinstance(d, dict):
                    try:
                        out.append({"consistency": max(0, min(2, float(d["consistency"]))),
                                    "grounded": max(0, min(2, float(d.get("grounded", 0)))),
                                    "fair": max(0, min(2, float(d.get("fair", 0)))),
                                    "russian": max(1, min(5, float(d["russian"]))), "_judge": jname})
                    except (KeyError, TypeError, ValueError):
                        pass
    return out


def _ref_for(m: str, grade_in: dict, judges: list[str]) -> tuple[dict, str]:
    present = [j for j in judges if j in grade_in]
    pool = [j for j in present if j != m]
    if len(pool) >= 2:
        note = "среднее " + " и ".join(pool) + (" (без самой модели)" if m in present else "")
    else:
        pool = [o for o in grade_in if o != m]
        note = "среднее всех остальных моделей замера (эталон из трёх ещё не замерен)"
    ref = {}
    ids = set().union(*[set(grade_in[o][0]) for o in pool]) if pool else set()
    for rid in ids:
        v = [grade_in[o][0][rid]["score"] for o in pool if rid in grade_in[o][0]]
        if len(v) >= min(2, len(pool)):
            ref[rid] = st.mean(v)
    return ref, note


def _norm_price(vals: dict[str, float]) -> dict[str, float]:
    import math
    xs = [v for v in vals.values() if v]
    if not xs:
        return {k: 1.0 for k in vals}
    lo, hi = math.log10(min(xs)), math.log10(max(xs))
    return {k: (1.0 if not v or hi == lo else round(1 - (math.log10(v) - lo) / (hi - lo), 3)) for k, v in vals.items()}


def functions_view(dirs: dict[str, list[Path]], grade_in: dict, corrected: dict, gold: dict, sample_ids: set,
                   meta: dict) -> dict:
    import ru_llm_bench as B
    import strongest_quality as Q
    from app.modules.matching import need_parser as NP

    vac = B._vacancies()
    vac_exp = Q.vac_expected(vac)
    texts = {v["id"]: v["text"] for v in vac}
    out: dict[str, dict] = {"parse_need": {}, "resume": {}, "grade": {}}
    for m, dl in dirs.items():
        nd, cfg = _pick(dl, "needs_delta", 14 / 15)
        if cfg == "без рассуждений":  # вся функция разбора — в той же настройке, если вариант есть
            nh = _pick(dl, "needs_hard", 1.01)[0]
            nj = _pick(dl, "needs_jury", 1.01)[0]
        else:
            nh, nj = _pick(dl, "needs_hard")[0], _pick(dl, "needs_jury")[0]
        if nd or nh:
            calls = _calls_of((nd or {}).get("per_text")) + _calls_of((nh or {}).get("per_text")) + \
                _calls_of((nj or {}).get("per_text"))
            out["parse_need"][m] = {
                "config": cfg, "complete": bool(nd and nh and nj),
                "quality": Q.parse_need_quality((nd or {}).get("per_text"), (nh or {}).get("per_text"), corrected,
                                                vac_exp, texts),
                "reliability": Q.reliability(calls, Q.BUDGET_S["parse_need"]),
                "usd_per_1k": round(sum(c["cost"] for c in calls) / len(calls) * 1000, 2) if calls else None}
        rs, _ = _pick(dl, "resume")
        rp, _ = _pick(dl, "resume_pii")
        if rs or rp:
            calls = _calls_of((rs or {}).get("per_text")) + _calls_of((rp or {}).get("per_text"))
            out["resume"][m] = {
                "config": "как в продукте", "complete": bool(rs and rp),
                "quality": Q.resume_quality((rs or {}).get("per_text"), gold, (rp or {}).get("per_text")),
                "reliability": Q.reliability(calls, Q.BUDGET_S["resume"]),
                "usd_per_1k": round(sum(c["cost"] for c in calls) / len(calls) * 1000, 2) if calls else None}
        if m in grade_in:
            gdir = next((x / "g" for x in dl if (x / "g" / "v2_1_out.jsonl").exists()), None)
            src = (gdir / "_sample_out.jsonl") if gdir and (gdir / "_sample_out.jsonl").exists() and m.startswith(
                "anthropic/claude-sonnet") else (gdir / "v2_1_out.jsonl" if gdir else None)
            _, calls = _grade_raw(src) if src else ({}, [])
            stab_p = next((x / "g" / "stab_out.jsonl" for x in dl if (x / "g" / "stab_out.jsonl").exists()), None)
            stab_sc, stab_calls = _grade_raw(stab_p, strip_rep=True) if stab_p else ({}, [])
            stab = {rid: [grade_in[m][0][rid]["score"]] + v for rid, v in stab_sc.items() if rid in grade_in[m][0]}
            ref, note = _ref_for(m, grade_in, JUDGES)
            allc = calls + stab_calls
            out["grade"][m] = {
                "config": "как в продукте", "complete": bool(stab_p) and bool(_judge_rows(dl)), "reference": note,
                "quality": Q.grade_quality(grade_in[m][0], ref, stab, _judge_rows(dl)),
                "reliability": Q.reliability(allc, Q.BUDGET_S["grade"]),
                "usd_per_1k": round(sum(c["cost"] for c in allc) / len(allc) * 1000, 2) if allc else None}
    # правила (без LLM) — та же мера качества, где применимо
    H = Q.hard_rows()
    rules_hard = [{"id": r["id"], "ok": True, "requirements": NP.parse_need(r["text"], use_llm=False)} for r in H.values()]
    rn = _load(RULES_DIR / "needs.json")
    rules_delta = [{"id": x["id"], "ok": True, **x} for x in (rn or {}).get("per_text", []) if x["id"] in corrected]
    rr = _load(RULES_DIR / "resume.json")
    import json as _j
    P = _j.loads(Q.PII.read_text(encoding="utf-8"))["rows"]
    from app.modules.resume import extract as RX
    from app.modules.resume.pii import redact
    rules_pii = []
    for r in P:
        red = redact(r["text"], use_ner=True).text
        rules_pii.append({"id": r["id"], **B._resume_pred(RX.extract(red, use_llm=False)),
                          "pii_sent": [x for x in r["pii"] if x.lower() in red.lower()]})
    rules = {"parse_need": {"quality": Q.parse_need_quality(rules_delta, rules_hard, corrected, vac_exp, texts, True)},
             "resume": {"quality": Q.resume_quality((rr or {}).get("per_text"), gold, rules_pii, True)}}
    # сводная оценка: качество 0,5 · надёжность 0,25 · задержка 0,15 · цена 0,10 (качество — к лучшей модели)
    choice = {}
    for f, cells in out.items():
        best_q = max([c["quality"]["index"]["value"] or 0 for c in cells.values()] or [1]) or 1
        pr = _norm_price({m: c["usd_per_1k"] for m, c in cells.items()})
        for m, c in cells.items():
            r = c["reliability"]
            qn = (c["quality"]["index"]["value"] or 0) / best_q
            rel = r["ok_share"]["value"] or 0
            lat = max(0.0, 1 - (r["p95_s"] or r["budget_s"]) / r["budget_s"])
            c["score"] = {"total": round(W["quality"] * qn + W["reliability"] * rel + W["latency"] * lat +
                                         W["price"] * pr[m], 3),
                          "quality": round(qn, 3), "reliability": round(rel, 3), "latency": round(lat, 3),
                          "price": pr[m]}
            # «в пределах стенда»: p95 не больше тайм-аута функции и отказов (пустые, формат, сеть) не больше 10 %
            c["within_budget"] = bool(r["calls"]) and (r["p95_s"] or 999) <= r["budget_s"] and rel >= 0.9
        ok = [m for m, c in cells.items() if c["within_budget"]]
        by_q = sorted(ok, key=lambda m: -(cells[m]["quality"]["index"]["value"] or 0))
        by_total = sorted(cells, key=lambda m: -cells[m]["score"]["total"])
        if not by_q:
            continue
        main = by_q[0]
        ci = cells[main]["quality"]["index"]["ci90"] or [0, 1]
        fam = meta.get(main, {}).get("family")
        choice[f] = {
            "strongest_within_latency": main,
            "within_noise": [m for m in by_q[1:] if (cells[m]["quality"]["index"]["ci90"] or [0, 0])[1] >= ci[0]],
            "reserve_other_family": next((m for m in by_q[1:] if meta.get(m, {}).get("family") != fam), None),
            "best_open": next((m for m in by_q if meta.get(m, {}).get("open_weights")), None),
            "best_total": by_total[0], "ranked_quality": by_q, "ranked_total": by_total,
            "excluded_latency_or_fails": [m for m in cells if m not in ok],
            "then": "правила"}
    # согласие эталона между собой (пары сильнейших, честные ответы выборки)
    agree = []
    pres = [j for j in JUDGES if j in grade_in]
    for i, a in enumerate(pres):
        for b in pres[i + 1:]:
            pairs = [(grade_in[a][0][k]["score"], grade_in[b][0][k]["score"]) for k in grade_in[a][0]
                     if k in grade_in[b][0] and grade_in[a][0][k]["group"] in Q.HONEST]
            agree.append({"a": a, "b": b, "n": len(pairs),
                          "mae": Q.metric(lambda d: Q.mean(abs(x - y) for x, y in d), pairs),
                          "kappa_w": Q.metric(Q.kappa_w, pairs)})
    return {"functions": out, "functions_rules": rules, "choice": choice, "judges_agreement": agree,
            "weights": W, "budget_s": Q.BUDGET_S}


# ------------------------------------------------------------------ п. 4: полный прогон победителей
FULL_SUB = "full"  # /tmp/strong/full/openrouter_<модель>/ — ru_llm_bench.py run --funcs needs_delta,grade (50 и 406)


def full_view(wdir: Path, corrected: dict, vac_exp: dict, texts: dict) -> dict:
    """Полный прогон победителей на всех входах: разбор — 50 вакансий И8 (исправленная разметка), оценщик — все 406
    ответов набора панели. Эталон оценщика — среднее остальных моделей полного прогона (без самой модели), модели — не
    люди; атаки — все 145 ответов-атак; порядок «сильный > средний > слабый» — 29 заданий. Sonnet — полный прогон 09.10."""
    import strongest_quality as Q

    dirs = {"anthropic/claude-sonnet-5.5": SONNET_DIR}
    for d in sorted((wdir / FULL_SUB).glob("openrouter_*")):
        for f in ("needs_delta", "grade"):
            j = _load(d / f"{f}.json")
            if j:
                dirs[j["spec"].split("=", 1)[1]] = d
                break
    if len(dirs) < 2:
        return {}
    grade = {}
    for m, d in dirs.items():
        if (d / "g" / "v2_1_out.jsonl").exists():
            sc, _ = _grade_scores(d / "g" / "v2_1_out.jsonl")
            if len(sc) >= 300:  # полный набор, а не выборка
                grade[m] = sc
    out = {}
    for m, d in dirs.items():
        cell = {}
        nd = _load(d / "needs_delta.json")
        if nd and len(nd["per_text"]) >= 40:
            per = [x for x in nd["per_text"] if x["id"] in corrected]
            calls = _calls_of(per)
            pairs = [(_tags(x["requirements"]), set(corrected[x["id"]])) for x in per]
            rows = [(len(a & b), len(a - b), len(b - a)) for a, b in pairs]
            q = Q.parse_need_quality(per, None, corrected, vac_exp, texts)
            cell["parse_need"] = {"n": len(per), "stack_f1": Q.metric(Q.f1_stat, rows), "fields_acc": q["fields_acc"],
                                  "reliability": Q.reliability(calls, Q.BUDGET_S["parse_need"]),
                                  "usd_per_1k": round(sum(c["cost"] for c in calls) / len(calls) * 1000, 2) if calls else None}
        if m in grade:
            sc = grade[m]
            pool = [o for o in grade if o != m]
            ref = {}
            for rid in sc:
                v = [grade[o][rid]["score"] for o in pool if rid in grade[o]]
                if v:
                    ref[rid] = st.mean(v)
            g = Q.grade_quality(sc, ref, None, None)
            items: dict[str, dict] = {}
            for x in sc.values():
                if x["group"] in ("ref_strong", "ref_medium", "ref_weak"):
                    items.setdefault(x["item"], {})[x["group"]] = x["score"]
            order = [v["ref_strong"] > v["ref_medium"] > v["ref_weak"] for v in items.values() if len(v) == 3]
            _, calls = _grade_raw(d / "g" / "v2_1_out.jsonl")
            cell["grade"] = {"n": len(sc), "reference": "среднее " + ", ".join(pool) + " (без самой модели)",
                             "mae": g["mae"], "kappa_w": g["kappa_w"], "bias": g["bias"], "exact_bin": g["exact_bin"],
                             "attacks_resisted": g["attacks_resisted"], "attacks_n": g["attacks_n"],
                             "order_strict": Q.metric(Q.mean, order),
                             "reliability": Q.reliability(calls, Q.BUDGET_S["grade"]),
                             "usd_per_1k": round(sum(c["cost"] for c in calls) / len(calls) * 1000, 2) if calls else None}
        if cell:
            out[m] = cell
    return out


CONDITIONS = [
    "Одна и та же малая выборка для всех моделей; путь продукта целиком (вырезание ПДн, проверка цитат, слияние с "
    "правилами); одна попытка на вход, без перехода по цепочке; настройки рассуждений — как в продукте (разбор и "
    "резюме — low, оценка — по умолчанию модели); 4 запроса параллельно; песочница → OpenRouter напрямую.",
    "Разметки — модели, не люди: вакансии — исправленная разметка (silver И8 + лишние теги, подтверждённые GPT 6.1 Sol; "
    "лишние теги новых моделей не проверялись — их точность занижена), резюме — автор набора (модель Claude), "
    "оценщик — среднее трёх сильнейших моделей двух семейств (Claude Opus 5.5 и Claude Fable 5.1 — Anthropic, "
    "GPT-6 Astra Pro — OpenAI) без самой оцениваемой; разметка панели v2 — Fable 5.1. Риск: для моделей Anthropic "
    "эталон и разметка — той же семьи (Opus и Fable согласны между собой сильнее, чем с Astra).",
    "Интервал — бутстреп 90 % по входам: на 15–50 входах разница в несколько сотых — в пределах шума.",
    "Цена — фактическая (usage.cost OpenRouter) на 1000 вызовов функции, $.",
]
NOT_MEASURED = [
    {"model": "YandexGPT 5.1", "why": "не цель после смены задачи 09.10 (решение штаба); ключ Yandex AI Studio в песочницу "
                                     "не передан. Прежний замер 08.10 — docs/LLM.md, разделы 6 и 11"},
    {"model": "Объяснения подборки, «почему», ранжирование, категория", "why": "модель не вызывается — правила"},
]
PLANNED = ["z-ai/glm-5.3", "moonshotai/kimi-k3", "qwen/qwen3.8-2.4t-a95b", "qwen/qwen3.8-27b", "deepseek/deepseek-v4-pro-0813",
           "anthropic/claude-sonnet-5.5", "openai/gpt-6.1-sol-pro", "x-ai/grok-4.7", "google/gemini-3.1-pro-preview",
           "anthropic/claude-opus-5.5", "anthropic/claude-fable-5.1", "openai/gpt-6-astra-pro"]


def pending_text(d: dict) -> str | None:
    """Что из плана замера ещё не готово (вычисляется по данным, не текстом вручную)."""
    fs = d.get("functions") or {}
    pr = (_load(PRICES) or {"models": {}})["models"]

    def names(ms):
        return ", ".join(label(d, m) if m in d["models"] else (pr.get(m, {}).get("name") or m).split(": ", 1)[-1]
                         for m in ms)

    miss = [m for m in PLANNED if not all(m in fs.get(f, {}) for f in ("parse_need", "resume", "grade"))]
    part = [m for m in PLANNED if m not in miss and not all(fs[f][m].get("complete") for f in fs if m in fs[f])]
    nojudge = [m for m in PLANNED if m in fs.get("grade", {}) and
               not ((fs["grade"][m]["quality"].get("judge_consistency") or {}).get("value") is not None)]
    out = []
    if miss:
        out.append(f"не начаты — {names(miss)} (ждут пополнения баланса)")
    if part:
        out.append(f"не все наборы — {names(part)}")
    if nojudge:
        out.append(f"без судьи обоснований — {names(nojudge)}")
    if len((d.get("grade_reference") or {}).get("judges") or []) < 3:
        out.append("эталон оценщика из трёх моделей ещё не полный — где нет двух моделей эталона, эталон — среднее "
                   "остальных моделей замера")
    return ("; ".join(out) + ".") if out else None


def _ok(c: dict, f: str) -> bool:
    fails = (c.get("format_fail") or 0) + (c.get("transport_fail") or 0)
    return c.get("calls") and fails <= max(1, round(0.05 * c["calls"])) and (c.get("p95_s") or 99) <= BUDGET_S[f]


def _why_not(c: dict, f: str) -> str:
    fails = (c.get("format_fail") or 0) + (c.get("transport_fail") or 0)
    if fails > max(1, round(0.05 * (c.get("calls") or 0))):
        return f"отказы {fails} из {c.get('calls')} (формат {c.get('format_fail') or 0}, сеть {c.get('transport_fail') or 0})"
    return f"p95 {c.get('p95_s')} с > {BUDGET_S[f]} с"


def _qkey(f: str, c: dict) -> tuple:
    q = c.get("quality") or {}
    if f == "needs_delta":
        return (-(q.get("f1") or 0),)
    if f == "needs_jury":
        return (-(q.get("jaccard") or 0),)
    if f == "resume":
        return (-(q.get("stack_f1") or 0),)
    return (q.get("attacks_pass", 99), -(q.get("order_strict") or 0), q.get("mae") if q.get("mae") is not None else 9)


def recommend(d: dict) -> dict:
    """Основная — лучшая по качеству среди уложившихся в бюджет задержки и с отказами ≤ 5 %; при равенстве в пределах
    интервала — дешевле; резерв — лучшая другого поставщика; затем правила."""
    out = {}
    for f, cells in d["cells"].items():
        cand = [(m, c) for m, c in cells.items() if m != "rules" and _ok(c, f)]
        cand.sort(key=lambda mc: (_qkey(f, mc[1]), (mc[1].get("price") or {}).get("usd_per_1k_calls") or 0))
        if not cand:
            continue
        main = cand[0]
        fam = d["models"][main[0]]["family"]
        reserve = next((mc for mc in cand[1:] if d["models"][mc[0]]["family"] != fam), None)
        best_open = next((mc for mc in cand if d["models"][mc[0]]["open_weights"]), None)
        ci = (main[1].get("quality") or {}).get("ci90")
        lower_better = f == "grade"

        def overlaps(c: dict) -> bool:
            o = (c.get("quality") or {}).get("ci90")
            return bool(ci and o and o[0] <= ci[1] and ci[0] <= o[1])

        out[f] = {"main": main[0], "reserve": reserve[0] if reserve else None, "then": "правила",
                  "best_open": best_open[0] if best_open else None, "ranked": [m for m, _ in cand],
                  "within_noise": [m for m, c in cand[1:] if overlaps(c)],  # интервал пересекается с основной
                  "excluded": {m: _why_not(c, f) for m, c in cells.items() if m != "rules" and not _ok(c, f)},
                  "lower_better": lower_better}
    return out


# ------------------------------------------------------------------ таблица docs/LLM.md, раздел 12
LLM_MD = ROOT / "docs" / "LLM.md"
MD_BEGIN, MD_END = "<!-- strongest:begin -->", "<!-- strongest:end -->"
FUNC_RU = {"parse_need": "Разбор потребности (вакансии)", "resume": "Разбор резюме",
           "grade": "Оценка развёрнутых ответов"}


def _n(x, d: int = 3, pct: bool = False, sign: bool = False) -> str:
    if x is None:
        return "—"
    if pct:
        s = f"{x * 100:.0f} %"
    else:
        s = f"{x:+.{d}f}" if sign else f"{x:.{d}f}"
    return s.replace(".", ",")


def _mv(m: dict | None, d: int = 3, pct: bool = False, sign: bool = False, ci: bool = False) -> str:
    if not m or m.get("value") is None:
        return "—"
    s = _n(m["value"], d, pct, sign)
    if ci and m.get("ci90"):
        s += f" [{_n(m['ci90'][0], d, pct)}–{_n(m['ci90'][1], d, pct)}]"
    return s


def label(d: dict, key: str) -> str:
    """Короткое имя модели для таблиц: без префикса поставщика каталога; вариант — в скобках."""
    if key == "rules":
        return "Правила (без LLM)"
    meta = d["models"].get(key) or d["models"].get(key.split("@")[0]) or {}
    name = (meta.get("name") or key).split(": ", 1)[-1]
    var = key.split("@", 1)[1] if "@" in key else None
    return name + (f" ({var})" if var else "")


def quality_line(f: str, q: dict) -> str:
    if f == "parse_need":
        return (f"F1 стека: вакансии {_mv(q.get('stack_f1_vac'))}, трудные {_mv(q.get('stack_f1_hard'))}; поля "
                f"{_mv(q.get('fields_acc'))}; отрицания {_mv(q.get('negations'), 2)}; выдуманные навыки "
                f"{_mv(q.get('hallucinated_share'), pct=True)}; незнакомые названы {_mv(q.get('unknown_named'), 2)}")
    if f == "resume":
        pii = "—" if q.get("pii_sent_to_model") is None else f"в запрос {q['pii_sent_to_model']}, в ответе " \
            f"{q.get('pii_in_reply') if q.get('pii_in_reply') is not None else '—'}"
        return (f"F1 навыков {_mv(q.get('stack_f1'))}; лишние {_mv(q.get('extra_share'), pct=True)}; стаж ±0,5 г. "
                f"{_mv(q.get('experience_ok'), 2)}; ПДн: {pii}")
    j = "—" if not (q.get("judge_consistency") or {}).get("value") else \
        f"{_mv(q.get('judge_consistency'), 2)} / рус. {_mv(q.get('judge_russian'), 1)} из 5"
    return (f"MAE {_mv(q.get('mae'))}; κw {_mv(q.get('kappa_w'))}; смещение {_mv(q.get('bias'), sign=True)}; "
            f"точная корзина {_mv(q.get('exact_bin'), 2)}; атаки отбиты {_mv(q.get('attacks_resisted'), pct=True)}; "
            f"размах 3 оценок {_mv(q.get('stability_range'), 2)}; обоснование (судья) {j}")


def md_table(d: dict) -> str:
    """Раздел 12 docs/LLM.md из strongest.json: по функции — таблица моделей и выбор."""
    out = [f"Сводка `docs/llm/strongest.json` от {d['date']} (код `{d['code_sha']}`). Оценка моделью по эталону из "
           f"моделей — модель, не люди. Интервал — бутстреп 90 % по входам. Сводная оценка: качество "
           f"{_n(d['weights']['quality'], 2)} · надёжность {_n(d['weights']['reliability'], 2)} · задержка "
           f"{_n(d['weights']['latency'], 2)} · цена {_n(d['weights']['price'], 2)}; «в бюджете» — p95 не больше "
           f"тайм-аута стенда и успешных ответов не меньше 90 %.", ""]
    rules = d.get("functions_rules") or {}
    for f, cells in d.get("functions", {}).items():
        out += [f"#### {FUNC_RU.get(f, f)} (тайм-аут стенда {d['budget_s'][f]} с)", "",
                "| Модель | Индекс качества [90 %] | Метрики качества | Успешно | p50 / p95, с | $ за 1000 | Сводная | "
                "В бюджете |", "|---|---|---|---|---|---|---|---|"]
        for m, c in sorted(cells.items(), key=lambda kv: -(kv[1]["quality"]["index"]["value"] or 0)):
            r = c["reliability"]
            errs = ", ".join(f"{ERR_RU.get(k, k)} {v}" for k, v in sorted(r["errors"].items())) if r["errors"] else "без отказов"
            cfg = "" if c.get("config") == "как в продукте" else f" — {c['config']}"
            part = "" if c.get("complete") else " (не все наборы)"
            out.append(f"| {label(d, m)}{cfg}{part} | {_mv(c['quality']['index'], ci=True)} | "
                       f"{quality_line(f, c['quality'])} | {_mv(r['ok_share'], pct=True)} из {r['calls']} ({errs}) | "
                       f"{_n(r['p50_s'], 1)} / {_n(r['p95_s'], 1)} | {_n(c['usd_per_1k'], 2)} | "
                       f"{_n(c['score']['total'])} | {'да' if c['within_budget'] else 'нет'} |")
        if f in rules:
            q = rules[f]["quality"]
            out.append(f"| Правила (без LLM) | {_mv(q['index'], ci=True)} | {quality_line(f, q)} | 100 % | <0,1 | 0 | "
                       f"— | да |")
        ch = (d.get("choice") or {}).get(f)
        if ch:
            noise = ", ".join(label(d, m) for m in ch["within_noise"]) or "нет"
            excl = ", ".join(label(d, m) for m in ch["excluded_latency_or_fails"]) or "нет"
            out += ["", f"Сильнейшая в пределах задержки: **{label(d, ch['strongest_within_latency'])}**; в пределах "
                        f"шума (интервалы пересекаются): {noise}. Резерв другой семьи: "
                        f"{label(d, ch['reserve_other_family']) if ch['reserve_other_family'] else '—'}; лучшая "
                        f"открытая: {label(d, ch['best_open']) if ch['best_open'] else '—'}; лучшая по сводной: "
                        f"{label(d, ch['best_total'])}; затем {ch['then']}. Вне бюджета задержки или с отказами "
                        f"> 10 %: {excl}."]
        if f == "grade" and cells:
            refs = sorted({c.get("reference") for c in cells.values() if c.get("reference")})
            out += ["", "Эталон оценщика: " + "; ".join(refs) + "."]
        out.append("")
    fr = d.get("full_run") or {}
    if fr:
        out += ["#### Полный прогон победителей (все входы)", "",
                "Разбор — 50 вакансий И8 (исправленная разметка); оценщик — все ответы набора панели, эталон — среднее "
                "остальных моделей полного прогона без самой модели (модели, не люди).", "",
                "| Модель | Разбор: F1 стека [90 %] | Разбор: поля | Оценщик: MAE [90 %] | κw | Атаки отбиты | "
                "Порядок «сильный > средний > слабый» | p95 разбор / оценка, с | $ за 1000 разбор / оценка |",
                "|---|---|---|---|---|---|---|---|---|"]
        for m, c in fr.items():
            pn, g = c.get("parse_need") or {}, c.get("grade") or {}
            out.append(f"| {label(d, m)} | {_mv(pn.get('stack_f1'), ci=True)} | {_mv(pn.get('fields_acc'))} | "
                       f"{_mv(g.get('mae'), ci=True)} | {_mv(g.get('kappa_w'))} | "
                       f"{_mv(g.get('attacks_resisted'), pct=True)}{(' из ' + str(g['attacks_n'])) if g else ''} | "
                       f"{_mv(g.get('order_strict'), 2)} | {_n((pn.get('reliability') or {}).get('p95_s'), 1)} / "
                       f"{_n((g.get('reliability') or {}).get('p95_s'), 1)} | {_n(pn.get('usd_per_1k'), 2)} / "
                       f"{_n(g.get('usd_per_1k'), 2)} |")
        out.append("")
    ag = d.get("judges_agreement") or []
    if ag:
        out.append("Согласие эталона между собой (честные ответы): " + "; ".join(
            f"{label(d, a['a'])} — {label(d, a['b'])}: MAE {_mv(a['mae'])}, κw {_mv(a['kappa_w'])} (n = {a['n']})"
            for a in ag) + ".")
        out.append("")
    out.append("Условия: " + " ".join(d.get("conditions") or []))
    if d.get("pending"):
        out += ["", "Ещё не замерено: " + d["pending"]]
    nm = d.get("not_measured") or []
    if nm:
        out += ["", "Не мерили: " + "; ".join(f"{x['model']} — {x['why']}" for x in nm) + "."]
    return "\n".join(out).rstrip() + "\n"


def write_md(d: dict, path: Path = LLM_MD) -> bool:
    """Заменить блок между метками в docs/LLM.md; меток нет — ничего не делать (False)."""
    text = path.read_text(encoding="utf-8")
    if MD_BEGIN not in text or MD_END not in text:
        return False
    head, rest = text.split(MD_BEGIN, 1)
    _, tail = rest.split(MD_END, 1)
    path.write_text(head + MD_BEGIN + "\n" + md_table(d) + MD_END + tail, encoding="utf-8")
    return True


def write(wdir: Path) -> dict:
    d = build(wdir)
    text = json.dumps(d, ensure_ascii=False, indent=1)
    OUT.write_text(text, encoding="utf-8")
    DATA_COPY.write_text(text, encoding="utf-8")
    print("→", OUT, DATA_COPY, "| docs/LLM.md §12:", "обновлён" if write_md(d) else "нет меток")
    return d


if __name__ == "__main__":
    write(Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/strong"))
