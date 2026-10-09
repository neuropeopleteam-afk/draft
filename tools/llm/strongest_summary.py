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
        if mid:
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
         "conditions": CONDITIONS, "pending": PENDING, "probes": probes, "not_measured": NOT_MEASURED}
    d["recommendation"] = recommend(d)
    return d


CONDITIONS = [
    "Одна и та же малая выборка для всех моделей; путь продукта целиком (вырезание ПДн, проверка цитат, слияние с "
    "правилами); одна попытка на вход, без перехода по цепочке; настройки рассуждений — как в продукте (разбор и "
    "резюме — low, оценка — по умолчанию модели); 4 запроса параллельно; песочница → OpenRouter напрямую.",
    "Разметки — модели, не люди: вакансии — исправленная разметка (silver И8 + лишние теги, подтверждённые GPT 6.1 Sol; "
    "лишние теги новых моделей не проверялись — их точность занижена), резюме — автор набора (модель Claude), "
    "оценщик — согласие сильнейших моделей (медиана, без самой оцениваемой).",
    "Интервал — бутстреп 90 % по входам: на 15–50 входах разница в несколько сотых — в пределах шума.",
    "Цена — фактическая (usage.cost OpenRouter) на 1000 вызовов функции; рубли — по курсу ЦБ РФ на 09.10.2026.",
]
NOT_MEASURED = [
    {"model": "YandexGPT 5.1", "why": "не цель после смены задачи 09.10 (решение штаба); ключ Yandex AI Studio в песочницу "
                                     "не передан. Прежний замер 08.10 — docs/LLM.md, разделы 6 и 11"},
    {"model": "Объяснения подборки, «почему», ранжирование, категория", "why": "модель не вызывается — правила"},
]
PENDING = ("Дорогие модели (Claude Fable 5.1, GPT-6 Astra Pro, Claude Opus 5.5) — после пополнения баланса; до этого "
           "эталон оценщика — медиана остальных моделей замера.")


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


def write(wdir: Path) -> dict:
    d = build(wdir)
    text = json.dumps(d, ensure_ascii=False, indent=1)
    OUT.write_text(text, encoding="utf-8")
    DATA_COPY.write_text(text, encoding="utf-8")
    print("→", OUT, DATA_COPY)
    return d


if __name__ == "__main__":
    write(Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/strong"))
