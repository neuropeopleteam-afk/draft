"""Прогон готовых запросов (jsonl: req_id, messages, temperature, max_tokens) через клиент продукта
app.modules.llm.client — тот же путь, что в приложении (OpenRouter напрямую или через ретранслятор, Yandex AI Studio).

Формат выхода совместим с tools/grader_check/llm_runner.py (ветка feat/integrity): req_id, model, text, pt, ct,
latency, error — его разбирает `python -m app.modules.validation.grader_check report`.

    python tools/llm/chain_runner.py --requests v2_1.jsonl --out v2_1_out.jsonl \
        --model openrouter=anthropic/claude-sonnet-5.5 --conc 4

Ключи — только из окружения процесса; в вывод не пишутся. Докачка: req_id, уже полученные без ошибки, пропускаются.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("LLM_DISABLED", "false")
os.environ["LLM_BREAKER_FAILURES"] = "0"  # пакетный прогон: автомат не нужен, повторы — ниже

from app.modules.llm import client as llm  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", required=True, help="openrouter=anthropic/claude-sonnet-5.5 | yandex=yandexgpt/latest")
    ap.add_argument("--conc", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--retries", type=int, default=2)
    a = ap.parse_args()
    prov = a.model.split("=", 1)[0]
    os.environ["LLM_CHAIN"] = prov
    done = set()
    if os.path.exists(a.out):
        for line in open(a.out, encoding="utf-8"):
            o = json.loads(line)
            if not o.get("error"):
                done.add(o["req_id"])
    recs = [json.loads(x) for x in open(a.requests, encoding="utf-8")]
    recs = [r for r in recs if r["req_id"] not in done and r.get("rule_score") is None]
    lock = threading.Lock()
    fout = open(a.out, "a", encoding="utf-8")
    st = {"n": 0, "err": 0, "pt": 0, "ct": 0, "cost": 0.0, "t0": time.time()}
    print(f"[{a.model}] к отправке {len(recs)} (уже есть {len(done)})", flush=True)

    def one(r):
        t0 = time.time()
        res = None
        for attempt in range(a.retries + 1):
            res = llm.chat(r["messages"], temperature=r.get("temperature", 0.0), max_tokens=r.get("max_tokens") or 1500,
                           model=a.model, timeout_s=a.timeout)
            if res.ok or (res.error or "").startswith(("http_400", "http_401", "http_403", "http_404")):
                break
            time.sleep(3 * (attempt + 1))
        u = res.usage or {}
        out = {"req_id": r["req_id"], "model": res.model or a.model.split("=", 1)[1], "provider": res.provider,
               "text": res.text, "pt": u.get("prompt_tokens"), "ct": u.get("completion_tokens"), "cost": u.get("cost"),
               "latency": round(time.time() - t0, 2), "latency_call": round(res.latency_ms / 1000, 2)}
        if not res.ok:
            out["error"] = res.error
        with lock:
            fout.write(json.dumps(out, ensure_ascii=False) + "\n")
            fout.flush()
            st["n"] += 1
            st["err"] += not res.ok
            st["pt"] += out["pt"] or 0
            st["ct"] += out["ct"] or 0
            st["cost"] += out["cost"] or 0
            if st["n"] % 50 == 0:
                print(f"[{a.model}] {st['n']}/{len(recs)} {time.time() - st['t0']:.0f}s err={st['err']} "
                      f"pt={st['pt']} ct={st['ct']} ${st['cost']:.2f}", flush=True)

    with ThreadPoolExecutor(a.conc) as ex:
        list(ex.map(one, recs))
    print(f"[{a.model}] ГОТОВО {st['n']} за {time.time() - st['t0']:.0f}s err={st['err']} prompt_tok={st['pt']} "
          f"compl_tok={st['ct']} cost=${st['cost']:.2f}", flush=True)


if __name__ == "__main__":
    main()
