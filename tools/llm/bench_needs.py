"""Разбор 50 реальных вакансий (docs/realdata/vacancies_50.json) моделями цепочки — «качество / время».

Путь продукта целиком: parse_need → вырезание ПДн и ст. 64 → модель → проверка цитат → слияние с правилами.
Для каждой модели — одна попытка без перехода по цепочке (LLM_CHAIN = её провайдер, LLM_MODEL_PARSE_NEED =
модель), автомат-выключатель выключен. Метрики — measure() из tools/realdata/benchmark.py (silver-разметка И8):
«llm+rules» — итог продукта, «llm_only» — то, что модель извлекла сама (после нормализации и проверки цитат).

Ключи — только в окружении процесса (OPENROUTER_API_KEY, LLM_API_KEY, LLM_FOLDER_ID, LLM_BASE_URL); в вывод и
файлы не попадают. Запуск (по одному разу на модель, без повторов без причины):

    python tools/llm/bench_needs.py --models openrouter=anthropic/claude-sonnet-5.5,yandex=yandexgpt/latest \
        --out docs/llm/needs_bench.json [--conc 3]
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import statistics as st
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "realdata"))
os.environ.setdefault("LLM_DISABLED", "false")
os.environ["LLM_BREAKER_FAILURES"] = "0"

from app.core.config import get_settings  # noqa: E402
from app.modules.llm import client as llm  # noqa: E402
from app.modules.matching import need_parser as NP  # noqa: E402
from benchmark import measure  # noqa: E402


_tl = threading.local()
_orig_chat_json = NP.chat_json


def _recording_chat_json(*a, **kw):
    """Как need_parser.chat_json, но запоминает ответ модели в потоке (для «llm_only» и задержки)."""
    res = _orig_chat_json(*a, **kw)
    _tl.res = res
    return res


NP.chat_json = _recording_chat_json


def _pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else None


def run_model(spec: str, rows: list[dict], conc: int) -> dict:
    prov, model = spec.split("=", 1)
    os.environ["LLM_CHAIN"] = prov
    os.environ["LLM_MODEL_PARSE_NEED"] = f"{prov}={model}"
    get_settings.cache_clear()
    llm.reset_state()

    def one(row):
        t0 = time.monotonic()
        _tl.res = None
        req = NP.parse_need(row["text"])
        res = _tl.res
        llm_only = None
        if res is not None and res.ok and isinstance(res.data, dict):
            masked = NP.bias_filter.mask(row["text"], NP.bias_filter.find_bias(row["text"]))
            r, _ = NP._llm_requirements(res.data, masked)
            llm_only = NP._with_quotes_from_original(NP.normalize(r, method="llm"), row["text"])
        return {"id": row["id"], "requirements": req, "llm_only": llm_only, "wall_s": round(time.monotonic() - t0, 3),
                "ok": bool(res and res.ok), "error": res.error if res else "no_call",
                "latency_ms": res.latency_ms if res else None, "usage": res.usage if res else None}

    with ThreadPoolExecutor(conc) as ex:
        out = list(ex.map(one, rows))
    ok = [o for o in out if o["ok"]]
    lat = [o["latency_ms"] / 1000 for o in ok if o["latency_ms"] is not None]
    usage = [o["usage"] or {} for o in out]
    errors: dict[str, int] = {}
    for o in out:
        if not o["ok"]:
            errors[o["error"]] = errors.get(o["error"], 0) + 1
    cost = sum(u.get("cost") or 0 for u in usage)
    return {"provider": prov, "model": model, "label": llm.model_label(model), "calls": len(out), "ok": len(ok),
            "errors": errors, "latency_s": {"median": round(st.median(lat), 2) if lat else None,
                                             "p90": round(_pct(lat, 0.9), 2) if lat else None,
                                             "max": round(max(lat), 2) if lat else None},
            "tokens": {"prompt": sum(u.get("prompt_tokens") or 0 for u in usage),
                       "completion": sum(u.get("completion_tokens") or 0 for u in usage)},
            "cost_usd": round(cost, 4) if cost else None,
            "llm_rules": measure(rows, [o["requirements"] for o in out]),
            "llm_only": {**measure(rows, [o["llm_only"] for o in out]), "n_with_reply": len(ok)},
            "per_text": [{k: o[k] for k in ("id", "ok", "error", "latency_ms")} for o in out]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--conc", type=int, default=3)
    ap.add_argument("--tag", default="", help="подпись прогона в ключе результата (например, «reasoning low»)")
    a = ap.parse_args()
    rows = json.loads((ROOT / "docs/realdata/vacancies_50.json").read_text())["vacancies"]
    path = Path(a.out)
    result = json.loads(path.read_text()) if path.exists() else {
        "corpus": "docs/realdata/vacancies_50.json", "annotation": "silver (И8): не экспертная разметка", "models": {}}
    result["rules_only"] = measure(rows, [NP.parse_need(r["text"], use_llm=False) for r in rows])
    for spec in a.models.split(","):
        t0 = time.time()
        r = run_model(spec, rows, a.conc)
        r["wall_total_s"] = round(time.time() - t0, 1)
        r["date"] = time.strftime("%Y-%m-%d")
        r["reasoning"] = llm.reasoning_for("parse_need") if r["provider"] == "openrouter" else None
        result["models"][r["model"] + (f" ({a.tag})" if a.tag else "")] = r
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        f, m, o = r["llm_rules"]["fields"], r["llm_rules"], r["llm_only"]
        print(f"{r['model']}: ok {r['ok']}/{r['calls']} {r['errors']} медиана {r['latency_s']['median']} с, "
              f"p90 {r['latency_s']['p90']} с; направление {f['direction']['correct']}, опыт "
              f"{f['experience_years_min']['correct']}, формат {f['work_format']['correct']}; стек P "
              f"{m['stack_micro_precision']} R {m['stack_micro_recall']}; только модель: P {o['stack_micro_precision']} "
              f"R {o['stack_micro_recall']}", flush=True)


if __name__ == "__main__":
    main()
