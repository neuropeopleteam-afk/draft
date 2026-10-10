"""«Только российская модель» — все LLM-функции продукта на одних и тех же входах: Claude Sonnet 5.5
(OpenRouter) против YandexGPT 5.1 (Yandex AI Studio) против правил. Результат — backend/app/modules/validation/data/ru_llm.json.

Функции и наборы (без ПДн: синтетика или опубликованные тексты вакансий, ПДн вырезаются продуктом до модели):
  needs_delta  разбор потребности, путь продукта (быстрый разбор: словарь + запрос-дельта) — 50 реальных
               вакансий (docs/realdata/vacancies_50.json), silver-разметка;
  needs_full   прежний полный разбор (mode=full) — те же 50 вакансий;
  needs_jury   15 демо- и «жюрийных» потребностей (сленг, английский стек) — без разметки: доля ответов, задержка,
               согласие итоговых тегов с Sonnet;
  resume       разбор резюме — 20 синтетических резюме (docs/llm/resume_synth.json, разметка автора набора — модель);
  grade        оценка развёрнутого ответа + вторая оценка спорных (grade_second) — набор оценщика (406 ответов
               панели 06.10, промпт v2, эталон — gpt-oss-120b, не эксперты).
Объяснения подборки, ранжирование, категория — без LLM (правила), здесь не меряются.

Каждая модель — одна попытка на вход без перехода по цепочке (LLM_CHAIN = её провайдер), автомат выключен.
Ключи — только в окружении процесса (OPENROUTER_API_KEY …; LLM_PROVIDER, LLM_BASE_URL, LLM_API_KEY, LLM_FOLDER_ID,
LLM_MODEL для yandex); в вывод и файлы не попадают. Ответы моделей хранятся только в рабочем каталоге (--dir), в
docs — сводка.

    python tools/llm/ru_llm_bench.py run --model openrouter=anthropic/claude-sonnet-5.5 --dir /tmp/rullm
    python tools/llm/ru_llm_bench.py run --model yandex=yandexgpt-5.1/latest --dir /tmp/rullm
    python tools/llm/ru_llm_bench.py summary --dir /tmp/rullm   # → backend/app/modules/validation/data/ru_llm.json
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import statistics as st
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "realdata"))
sys.path.insert(0, str(ROOT / "tools" / "fastparse"))
os.environ.setdefault("LLM_DISABLED", "false")
os.environ["LLM_BREAKER_FAILURES"] = "0"

FUNCS = ("needs_delta", "needs_full", "needs_jury", "resume", "grade")  # + needs_delta_schema (только для yandex)
# Цена за 1000 токенов (вход, выход). Yandex AI Studio, синхронный режим, с НДС (aistudio.yandex.ru/ru/docs/ai-studio/pricing,
# 09.10.2026); OpenRouter — поле usage.cost ответа (фактическая цена запроса, $).
PRICE_RUB_PER_1K = {"yandexgpt-5.1": (0.8, 0.8), "yandexgpt": (1.2, 1.2), "yandexgpt-lite": (0.2, 0.2)}
FORMAT_ERRORS = ("invalid_json", "invalid_reply", "empty", "schema_rejected")

_tl = threading.local()


# учёт расходов процесса (usage.cost OpenRouter) и потолок: превысили — оставшиеся входы пропускаются (budget_skip)
SPEND = {"usd": 0.0, "cap": None}
_spend_lock = threading.Lock()


def _over_cap() -> bool:
    return SPEND["cap"] is not None and SPEND["usd"] >= SPEND["cap"]


def _add_cost(res) -> None:
    c = (getattr(res, "usage", None) or {}).get("cost") or 0
    with _spend_lock:
        SPEND["usd"] += float(c)


def slug(spec: str) -> str:
    return re.sub(r"[^a-zA-Z0-9.]+", "_", spec).strip("_")


def pct(xs: list[float], q: float) -> float | None:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else None


def _set_model(spec: str, funcs: tuple[str, ...]) -> None:
    from app.core.config import get_settings
    from app.modules.llm import client as llm

    prov, model = spec.split("=", 1)
    os.environ["LLM_CHAIN"] = prov
    for f in funcs:
        os.environ[f"LLM_MODEL_{f.upper()}"] = f"{prov}={model}"
    get_settings.cache_clear()
    llm.reset_state()


def _recorder(module):
    """Подмена chat_json модуля: запоминает результат вызова модели в потоке (задержка, токены, ошибка)."""
    orig = module.chat_json

    def rec(*a, **kw):
        res = orig(*a, **kw)
        _tl.res = res
        _add_cost(res)
        return res

    module.chat_json = rec
    return orig


def _call_info(res) -> dict:
    if res is None:
        return {"called": False}
    u = res.usage or {}
    return {"called": True, "ok": bool(res.ok), "error": res.error, "latency_ms": res.latency_ms,
            "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
            "cost_usd": u.get("cost"), "model_reported": res.model_reported,
            "attempt_errors": [a.get("error") for a in res.attempts if a.get("error")]}


def _pool(fn, rows, conc):
    with ThreadPoolExecutor(conc) as ex:
        return list(ex.map(fn, rows))


# ------------------------------------------------------------------ разбор потребности
def _vacancies() -> list[dict]:
    return json.loads((ROOT / "docs/realdata/vacancies_50.json").read_text())["vacancies"]


def _jury_texts() -> list[tuple[str, str, str]]:
    import bench as FB  # tools/fastparse/bench.py

    return FB.texts()


def _tags(req: dict) -> dict:
    return {"required": sorted(i["tag"] for i in req.get("stack_required") or []),
            "desired": sorted(i["tag"] for i in req.get("stack_desired") or [])}


def run_needs(spec: str, conc: int, full: bool, jury: bool = False, limit: int = 0, rows: list[dict] | None = None,
              func: str | None = None) -> dict:
    """rows — свой набор ({id, text}); func — подпись функции в результате (напр. needs_hard)."""
    from app.modules.matching import need_parser as NP

    _set_model(spec, ("parse_need",))
    orig = _recorder(NP)
    try:
        if rows is None:
            rows = [{"id": i, "kind": k, "text": t} for i, k, t in _jury_texts()] if jury else _vacancies()
        rows = rows[:limit] if limit else rows

        def one(row):
            if _over_cap():
                return {"id": row["id"], "called": False, "skipped": "budget"}
            _tl.res = None
            t0 = time.monotonic()
            req = NP.parse_need(row["text"], full=full)
            info = _call_info(_tl.res)
            llm_info = req.get("llm") or {}
            return {"id": row["id"], **info, "wall_ms": int((time.monotonic() - t0) * 1000),
                    "used": bool(llm_info.get("used")), "dropped_without_quote": llm_info.get("dropped_without_quote"),
                    "tags": _tags(req), "requirements": req}

        out = _pool(one, rows, conc)
    finally:
        NP.chat_json = orig
    return {"spec": spec, "func": func or ("needs_jury" if jury else ("needs_full" if full else "needs_delta")),
            "date": time.strftime("%Y-%m-%d"), "per_text": out}


def rules_needs(jury: bool = False) -> dict:
    from app.modules.matching import need_parser as NP

    rows = [{"id": i, "text": t} for i, _, t in _jury_texts()] if jury else _vacancies()
    return {"per_text": [{"id": r["id"], "tags": _tags(req), "requirements": req}
                         for r in rows for req in [NP.parse_need(r["text"], use_llm=False)]]}


# ------------------------------------------------------------------ резюме
def _resumes() -> list[dict]:
    return json.loads((ROOT / "docs/llm/resume_synth.json").read_text())["rows"]


def _resume_pred(o: dict) -> dict:
    return {"stack": sorted(s["tag"] for s in o["stack"]), "roles": sorted(r["id"] for r in o["roles"]),
            "soft": sorted(s["id"] for s in o["soft_skills"]), "experience_years": o["experience_years"],
            "llm_stack": sorted(s["tag"] for s in o["stack"] if s.get("by") == "llm")}


def run_resume(spec: str, conc: int, limit: int = 0, rows: list[dict] | None = None, func: str = "resume") -> dict:
    """rows — свой набор; для набора с вымышленными ПДн (поле pii) сохраняются: какие pii остались в тексте,
    ушедшем модели (промах вырезания продукта), и сырой ответ модели (проверка «восстановления» ПДн)."""
    from app.modules.resume import extract as RX
    from app.modules.resume.pii import redact

    _set_model(spec, ("resume",))
    orig = _recorder(RX)
    try:
        def one(row):
            if _over_cap():
                return {"id": row["id"], "called": False, "skipped": "budget"}
            _tl.res = None
            red = redact(row["text"], use_ner=True).text
            o = RX.extract(red, use_llm=True)
            rec = {"id": row["id"], **_call_info(_tl.res), "used": bool((o.get("llm") or {}).get("used")),
                   **_resume_pred(o)}
            if row.get("pii"):
                low = red.lower()
                rec["pii_sent"] = [x for x in row["pii"] if x.lower() in low]
                rec["reply_text"] = getattr(_tl.res, "text", None) if _tl.res is not None else None
                rec["sent_text"] = red
            return rec

        src = rows if rows is not None else _resumes()
        out = _pool(one, src[:limit] if limit else src, conc)
    finally:
        RX.chat_json = orig
    return {"spec": spec, "func": func, "date": time.strftime("%Y-%m-%d"), "per_text": out}


def rules_resume() -> dict:
    from app.modules.resume import extract as RX
    from app.modules.resume.pii import redact

    return {"per_text": [{"id": r["id"], **_resume_pred(RX.extract(redact(r["text"], use_ner=True).text, use_llm=False))}
                         for r in _resumes()]}


# ------------------------------------------------------------------ оценщик
def _chat_batch(spec: str, req_path: Path, out_path: Path, func: str, conc: int, timeout: float) -> None:
    """Как tools/llm/chain_runner.py (формат выхода для grader_check report), в процессе; лимит 3000 — как в продукте."""
    from app.modules.llm import client as llm

    done = set()
    if out_path.exists():
        done = {json.loads(x)["req_id"] for x in open(out_path, encoding="utf-8") if not json.loads(x).get("error")}
    recs = [json.loads(x) for x in open(req_path, encoding="utf-8")]
    recs = [r for r in recs if r["req_id"] not in done]
    lock = threading.Lock()
    fout = open(out_path, "a", encoding="utf-8")

    def one(r):
        if _over_cap():
            return  # потолок расходов: вход не запрашивается (докачка — повторным запуском)
        t0 = time.time()
        res = llm.chat(r["messages"], temperature=r.get("temperature", 0.0), max_tokens=3000, model=spec, func=func,
                       timeout_s=timeout, want_json=True)
        _add_cost(res)
        u = res.usage or {}
        o = {"req_id": r["req_id"], "model": res.model or spec.split("=", 1)[1], "provider": res.provider,
             "text": res.text, "pt": u.get("prompt_tokens"), "ct": u.get("completion_tokens"), "cost": u.get("cost"),
             "latency": round(time.time() - t0, 2), "latency_call": round(res.latency_ms / 1000, 2)}
        if not res.ok:
            o["error"] = res.error
        with lock:
            fout.write(json.dumps(o, ensure_ascii=False) + "\n")
            fout.flush()

    _pool(one, recs, conc)
    fout.close()


def run_grade(spec: str, conc: int, wdir: Path, limit_per_group: int = 0, second: str | None = None,
              timeout: float = 40, with_second: bool = True) -> dict:
    """second — модель второй оценки (по умолчанию та же; путь продукта для openrouter — Claude Fable 5.1)."""
    from app.modules.validation import grader_check as GC

    _set_model(spec, ("grade", "grade_second"))
    g = wdir / "g"
    g.mkdir(parents=True, exist_ok=True)
    if not (g / "v2_1.jsonl").exists():
        GC.build("v2", str(g / "v2_1.jsonl"), limit_per_group)
    _chat_batch(spec, g / "v2_1.jsonl", g / "v2_1_out.jsonl", "grade", conc, timeout)
    GC.second(str(g / "v2_1.jsonl"), str(g / "v2_1_out.jsonl"), str(g / "v2_2.jsonl"))
    if with_second:
        _chat_batch(second or spec, g / "v2_2.jsonl", g / "v2_2_out.jsonl", "grade_second", conc, timeout)
    return grade_summary(spec, wdir, second)


def grade_summary(spec: str, wdir: Path, second: str | None = None) -> dict:
    sys.path.insert(0, str(ROOT / "tools" / "llm"))
    import grader_summary as GS
    from app.modules.assessment import grader as G
    from app.modules.llm.client import _extract_json
    from app.modules.validation import grader_check as GC

    g = wdir / "g"
    label = spec.split("=", 1)[1]
    second_label = (second.split("=", 1)[1] + " (независимый вызов, обратный порядок критериев)" if second and second != spec
                    else f"{label} (та же модель: независимый вызов, обратный порядок критериев)")
    summ = GS.summarize(str(g), label, second_label,
                        "ru_llm_bench grade", "Эталон сравнения — gpt-oss-120b (модель, не эксперты).")
    # формат ответа: доля ответов, которые продукт принял бы (parse_reply ok), отдельно от ошибок сети
    items, rows = GC.load()
    by_id = {r["id"]: r for r in rows}
    fmt = {}
    for stage in ("v2_1", "v2_2"):
        # доля отказов — по ПЕРВОЙ попытке на вход (докачка повторяет только сбойные, качество оценщика — по последней);
        # токены и цена — по всем вызовам
        res, retried = {}, 0
        pt, ct, cost = 0, 0, 0.0
        p_out = g / f"{stage}_out.jsonl"
        for line in (open(p_out, encoding="utf-8") if p_out.exists() else []):
            o = json.loads(line)
            pt += o.get("pt") or 0
            ct += o.get("ct") or 0
            cost += o.get("cost") or 0
            if o["req_id"] in res:
                retried += 1
                continue
            res[o["req_id"]] = o
        calls, transport, bad = len(res), 0, 0
        lat = []
        for rid, o in res.items():
            if o.get("error") and o["error"] not in FORMAT_ERRORS:
                transport += 1
                continue
            r = by_id[rid]
            it = items[r["item"]]
            ans = GC._redacted(G.strip_meta(r["answer"].strip())[0])
            p = G.parse_reply(_extract_json(o.get("text") or "") if not o.get("error") else None, it["rubric"], ans)
            if not p["ok"]:
                bad += 1
            else:
                lat.append(float(o.get("latency_call") or o.get("latency") or 0))
        fmt[stage] = {"calls": calls, "ok": calls - transport - bad, "format_fail": bad, "transport_fail": transport,
                      "latency_s": {"p50": round(pct(lat, 0.5), 2) if lat else None,
                                    "p95": round(pct(lat, 0.95), 2) if lat else None},
                      "tokens": {"prompt": pt, "completion": ct}, "cost_usd": round(cost, 4) if cost else None,
                      "retried": retried}
    summ["format"] = fmt
    return {"spec": spec, "second": second or spec, "func": "grade", "date": time.strftime("%Y-%m-%d"), "summary": summ}


# ------------------------------------------------------------------ запуск
def cmd_run(a) -> None:
    if a.cap_usd:  # потолок расходов процесса и пол баланса ключа (как strongest_bench.py)
        import strongest_bench as SB

        bal = SB.balance_usd()
        if bal is not None:
            print(f"баланс ключа: {bal} $, пол {a.floor_usd} $, потолок прогона {a.cap_usd} $", flush=True)
            if bal - a.cap_usd < a.floor_usd:
                sys.exit("отказ: прогон может опустить баланс ниже пола")
        SPEND["cap"] = a.cap_usd
    wdir = Path(a.dir) / slug(a.model)
    wdir.mkdir(parents=True, exist_ok=True)
    funcs = a.funcs.split(",") if a.funcs else FUNCS
    for f in funcs:
        path = wdir / f"{f}.json"
        if path.exists() and not a.force and f != "grade":
            print(f"{f}: уже есть {path}, пропуск (--force — заново)", flush=True)
            continue
        t0 = time.time()
        if f == "needs_delta":
            r = run_needs(a.model, a.conc, full=False)
        elif f == "needs_delta_schema":  # та же дельта с JSON-схемой и у Yandex (LLM_YANDEX_JSON_SCHEMA)
            os.environ["LLM_YANDEX_JSON_SCHEMA"] = "true"
            try:
                r = run_needs(a.model, a.conc, full=False)
            finally:
                os.environ.pop("LLM_YANDEX_JSON_SCHEMA", None)
            r["func"] = f
        elif f == "needs_full":
            r = run_needs(a.model, a.conc, full=True)
        elif f == "needs_jury":
            r = run_needs(a.model, a.conc, full=False, jury=True)
        elif f == "resume":
            r = run_resume(a.model, a.conc)
        elif f == "grade":
            r = run_grade(a.model, a.conc, wdir, a.limit_per_group, a.second_model or None)
        else:
            raise SystemExit(f"неизвестная функция {f}")
        r["wall_s"] = round(time.time() - t0, 1)
        path.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        recs = r.get("per_text") or []
        ok = sum(1 for x in recs if x.get("ok"))
        print(f"{a.model} {f}: {ok}/{len(recs) or '—'} ответов, {r['wall_s']} с → {path}", flush=True)
    rules = Path(a.dir) / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    if not (rules / "needs.json").exists():
        (rules / "needs.json").write_text(json.dumps(rules_needs(), ensure_ascii=False), encoding="utf-8")
        (rules / "needs_jury.json").write_text(json.dumps(rules_needs(jury=True), ensure_ascii=False), encoding="utf-8")
        (rules / "resume.json").write_text(json.dumps(rules_resume(), ensure_ascii=False), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--model", required=True, help="openrouter=anthropic/claude-sonnet-5.5 | yandex=yandexgpt-5.1/latest")
    r.add_argument("--dir", required=True)
    r.add_argument("--funcs", default="", help="через запятую: " + ",".join(FUNCS))
    r.add_argument("--conc", type=int, default=4)
    r.add_argument("--force", action="store_true")
    r.add_argument("--second-model", default="", help="модель второй оценки (путь продукта openrouter: "
                   "openrouter=anthropic/claude-fable-5.1); пусто — та же, что первая (режим LLM_CHAIN=yandex)")
    r.add_argument("--cap-usd", type=float, default=0.0, help="потолок расходов процесса, $ (0 — без потолка)")
    r.add_argument("--floor-usd", type=float, default=3.0, help="пол баланса ключа OpenRouter, $ (с --cap-usd)")
    r.add_argument("--limit-per-group", type=int, default=0, help="оценщик: не больше N ответов на группу (проба)")
    s = sub.add_parser("summary")
    s.add_argument("--dir", required=True)
    s.add_argument("--out", default=None, help="по умолчанию — backend/app/modules/validation/data/ru_llm.json")
    s.add_argument("--regrade", action="store_true", help="пересчитать grade.json по сохранённым ответам (без вызовов)")
    a = ap.parse_args()
    if a.cmd == "run":
        cmd_run(a)
    else:
        from ru_llm_summary import DATA, write_summary  # tools/llm/ru_llm_summary.py

        if a.regrade:
            for gj in sorted(Path(a.dir).glob("*/grade.json")):
                old = json.loads(gj.read_text(encoding="utf-8"))
                second = old.get("second") if old.get("second") != old["spec"] else None
                new = grade_summary(old["spec"], gj.parent, second)
                new["date"] = old.get("date", new["date"])
                gj.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
                print("пересчитано:", gj)
        write_summary(Path(a.dir), Path(a.out) if a.out else DATA)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "tools" / "llm"))
    main()
