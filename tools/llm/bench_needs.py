"""Разбор 50 реальных вакансий (docs/realdata/vacancies_50.json) моделями цепочки — «качество / время».

Путь продукта целиком: parse_need → вырезание ПДн и ст. 64 → модель → проверка цитат → слияние с правилами.
Для каждой модели — одна попытка без перехода по цепочке (LLM_CHAIN = её провайдер, LLM_MODEL_PARSE_NEED =
модель), автомат-выключатель выключен. Метрики — measure() из tools/realdata/benchmark.py (silver-разметка И8):
«llm+rules» — итог продукта, «llm_only» — то, что модель извлекла сама (после нормализации и проверки цитат).

Ключи — только в окружении процесса (OPENROUTER_API_KEY, LLM_API_KEY, LLM_FOLDER_ID, LLM_BASE_URL); в вывод и
файлы не попадают. Запуск (по одному разу на модель, без повторов без причины):

    python tools/llm/bench_needs.py --models openrouter=anthropic/claude-sonnet-5.5,yandex=yandexgpt/latest \
        --out docs/llm/needs_bench.json [--conc 3]

Для независимой проверки одного нового прогона: --predictions-out docs/llm/needs_sonnet_tags.json.
Полные requirements и отдельные списки тегов сохраняются без ключей и тела запроса.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
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
    _tl.call_kwargs = {k: kw.get(k) for k in ("func", "max_tokens")}
    return res


NP.chat_json = _recording_chat_json


def _pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else None


def run_model(spec: str, rows: list[dict], conc: int, predictions_out: Path | None = None) -> dict:
    prov, model = spec.split("=", 1)
    os.environ["LLM_CHAIN"] = prov
    os.environ["LLM_MODEL_PARSE_NEED"] = f"{prov}={model}"
    get_settings.cache_clear()
    llm.reset_state()

    def one(row):
        t0 = time.monotonic()
        _tl.res = None
        _tl.call_kwargs = None
        req = NP.parse_need(row["text"])
        res = _tl.res
        llm_only = None
        if res is not None and res.ok and isinstance(res.data, dict):
            masked = NP.bias_filter.mask(row["text"], NP.bias_filter.find_bias(row["text"]))
            r, _ = NP._llm_requirements(res.data, masked)
            llm_only = NP._with_quotes_from_original(NP.normalize(r, method="llm"), row["text"])
        return {"id": row["id"], "requirements": req, "llm_only": llm_only, "wall_s": round(time.monotonic() - t0, 3),
                "ok": bool(res and res.ok), "error": res.error if res else "no_call",
                "latency_ms": res.latency_ms if res else None, "usage": res.usage if res else None,
                "call_settings": _tl.call_kwargs}

    with ThreadPoolExecutor(conc) as ex:
        out = list(ex.map(one, rows))
    if predictions_out is not None:
        save_predictions(predictions_out, prov, model, rows, out)
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


def save_predictions(path: Path, provider: str, model: str, rows: list[dict], out: list[dict]) -> None:
    """Persist auditable per-text stack without secrets or submitted request bodies."""
    corpus = ROOT / "docs/realdata/vacancies_50.json"
    result = {
        "schema_version": 1,
        "purpose": "Per-vacancy predictions for independent auditing; this is a separately recorded run.",
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provider": provider,
        "model": model,
        "reasoning": llm.reasoning_for("parse_need") if provider == "openrouter" else None,
        "corpus": "docs/realdata/vacancies_50.json",
        "corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "per_text": [
            {
                "id": o["id"],
                "source_url": row["source_url"],
                "text_sha256": row["text_sha256"],
                "ok": o["ok"],
                "error": o["error"],
                "latency_ms": o["latency_ms"],
                "call_settings": o["call_settings"],
                "stack_required": [i["tag"] for i in o["requirements"]["stack_required"]],
                "stack_desired": [i["tag"] for i in o["requirements"]["stack_desired"]],
                "requirements": o["requirements"],
                "llm_only": o["llm_only"],
            }
            for row, o in zip(rows, out)
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--conc", type=int, default=3)
    ap.add_argument("--tag", default="", help="подпись прогона в ключе результата (например, «reasoning low»)")
    ap.add_argument("--predictions-out", type=Path, help="полная выдача одного нового прогона для аудита")
    a = ap.parse_args()
    specs = a.models.split(",")
    if a.predictions_out is not None and len(specs) != 1:
        ap.error("--predictions-out разрешён только для одной модели, чтобы не перезаписать её выдачу")
    rows = json.loads((ROOT / "docs/realdata/vacancies_50.json").read_text())["vacancies"]
    path = Path(a.out)
    result = json.loads(path.read_text()) if path.exists() else {
        "corpus": "docs/realdata/vacancies_50.json", "annotation": "silver (И8): не экспертная разметка", "models": {}}
    result["rules_only"] = measure(rows, [NP.parse_need(r["text"], use_llm=False) for r in rows])
    for spec in specs:
        t0 = time.time()
        r = run_model(spec, rows, a.conc, a.predictions_out)
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
