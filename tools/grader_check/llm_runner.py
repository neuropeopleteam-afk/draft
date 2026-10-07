"""Прогон готовых запросов через Yandex AI Studio (OpenAI-совместимый API) — запускается там, где есть ключ (сервер «Москва»).

Только stdlib (на сервере нет httpx). Ключ и каталог — из окружения (llm.env), в вывод не пишутся:

    set -a; . /opt/spectrek_fsp/secrets/llm.env; set +a
    python3 yandex_runner.py --requests up.jsonl --out up_out.jsonl --model gpt-oss-120b/latest \
        --conc 8 [--reasoning-effort medium] [--max-tokens 6000] [--temperature 0.3]

Вход: jsonl с полями req_id, messages и (необязательно) max_tokens, temperature, extra.
Выход: req_id, model, text (content), reasoning_len, usage, finish, latency, error.
Докачка: req_id, уже полученные без ошибки, пропускаются. Ключей ответов во входе нет
(для оценщика по рубрике во входе есть рубрика — как и в рабочем оценщике приложения).
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def call(base, headers, body, timeout):
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", required=True, help="gpt-oss-120b/latest | yandexgpt/latest")
    ap.add_argument("--conc", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=None)
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--reasoning-effort", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()
    key, folder = os.environ["LLM_API_KEY"], os.environ["LLM_FOLDER_ID"]
    base = os.environ.get("LLM_BASE_URL", "https://llm.api.cloud.yandex.net/v1")
    headers = {"Content-Type": "application/json", "Authorization": f"Api-Key {key}", "OpenAI-Project": folder}
    model = a.model if a.model.startswith("gpt://") else f"gpt://{folder}/{a.model}"
    done = set()
    if os.path.exists(a.out):
        for line in open(a.out, encoding="utf-8"):
            try:
                o = json.loads(line)
                if not o.get("error"):
                    done.add(o["req_id"])
            except Exception:  # noqa: BLE001
                pass
    recs = [json.loads(l) for l in open(a.requests, encoding="utf-8")]
    recs = [r for r in recs if r["req_id"] not in done and r.get("rule_score") is None]
    if a.limit:
        recs = recs[: a.limit]
    lock = threading.Lock()
    fout = open(a.out, "a", encoding="utf-8")
    st = {"n": 0, "err": 0, "pt": 0, "ct": 0, "rt": 0, "t0": time.time()}
    print(f"[{a.model}] к отправке {len(recs)} (уже есть {len(done)})", flush=True)

    def one(r):
        body = {"model": model, "messages": r["messages"]}
        mt = r.get("max_tokens") or a.max_tokens
        if mt:
            body["max_tokens"] = mt
        t = r.get("temperature", a.temperature)
        if t is not None:
            body["temperature"] = t
        if a.reasoning_effort:
            body["reasoning_effort"] = a.reasoning_effort
        body.update(r.get("extra") or {})
        out = {"req_id": r["req_id"], "model": a.model, "reasoning_effort": a.reasoning_effort}
        t0 = time.time()
        res, err = None, None
        for attempt in range(5):
            try:
                res = call(base, headers, body, a.timeout)
                err = None
                break
            except urllib.error.HTTPError as e:
                err = f"http_{e.code}: {e.read()[:300].decode(errors='replace')}"
                if e.code in (400, 401, 403, 404):
                    break
                time.sleep(3 * (attempt + 1) + (10 if e.code == 429 else 0))
            except Exception as e:  # noqa: BLE001
                err = repr(e)[:300]
                time.sleep(3 * (attempt + 1))
        out["latency"] = round(time.time() - t0, 2)
        if res is not None and err is None:
            try:
                ch = res["choices"][0]
                msg = ch.get("message") or {}
                u = res.get("usage") or {}
                det = u.get("completion_tokens_details") or {}
                out.update(text=msg.get("content") or "", reasoning_len=len(msg.get("reasoning_content") or ""),
                           finish=ch.get("finish_reason"), pt=u.get("prompt_tokens"),
                           ct=u.get("completion_tokens"), rt=det.get("reasoning_tokens"))
                if not out["text"] and msg.get("reasoning_content"):
                    out["reasoning_tail"] = msg["reasoning_content"][-1500:]
            except Exception as e:  # noqa: BLE001
                err = f"bad_payload {e!r} {str(res)[:300]}"
        if err:
            out["error"] = err
        with lock:
            fout.write(json.dumps(out, ensure_ascii=False) + "\n")
            fout.flush()
            st["n"] += 1
            st["err"] += bool(err)
            st["pt"] += out.get("pt") or 0
            st["ct"] += out.get("ct") or 0
            st["rt"] += out.get("rt") or 0
            if st["n"] % 50 == 0:
                el = time.time() - st["t0"]
                print(f"[{a.model}] {st['n']}/{len(recs)} {el:.0f}s err={st['err']} pt={st['pt']} "
                      f"ct={st['ct']} rt={st['rt']}", flush=True)

    with ThreadPoolExecutor(a.conc) as ex:
        list(ex.map(one, recs))
    el = time.time() - st["t0"]
    print(f"[{a.model}] ГОТОВО {st['n']} за {el:.0f}s err={st['err']} prompt_tok={st['pt']} "
          f"compl_tok={st['ct']} reasoning_tok={st['rt']}", flush=True)


if __name__ == "__main__":
    main()
