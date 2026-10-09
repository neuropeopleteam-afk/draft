"""Я2 (смена цели 09.10 17:40): сильнейшая модель для каждой LLM-функции — замер кандидатов OpenRouter на одних входах.

Функции и наборы — те же, что в ru_llm_bench.py (без ПДн: опубликованные вакансии, синтетические резюме, набор
оценщика); малая выборка этапа 2:
  needs_delta  первые 15 вакансий И8 (путь продукта: словарь + дельта модели), разметка — silver и исправленная
               (silver + подтверждённые GPT 6.1 Sol лишние теги, docs/llm/extra_tags_judgement.json) — модели, не люди;
  needs_jury   15 демо- и «жюрийных» текстов (без разметки — согласие с другими моделями, доля ответов);
  resume       20 синтетических резюме (docs/llm/resume_synth.json);
  grade        по 5 ответов из каждой из 10 групп набора оценщика = 50 (эталоны сильный/средний/слабый, ответы
               моделей, 5 видов атак), тайм-аут 50 с (бюджет оценки продукта).
Объяснения подборки, «почему», ранжирование, категория — без LLM (правила), здесь не меряются.

Деньги: потолок на модель (--cap-usd) и пол баланса ключа (--floor-usd, по умолчанию 8 $): до запуска — проверка
баланса (/api/v1/credits; печатается только число), в ходе — учёт usage.cost, превысили потолок — оставшиеся входы
пропускаются. Ключ — только в окружении (OPENROUTER_API_KEY), в вывод и файлы не попадает.

    python tools/llm/strongest_bench.py estimate                       # цена прогона на модель ДО запуска
    python tools/llm/strongest_bench.py run --model openrouter=z-ai/glm-5.3 --cap-usd 0.6
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "llm"))
sys.path.insert(0, str(ROOT / "tools" / "fastparse"))

PRICES = ROOT / "docs" / "llm" / "strongest_prices.json"
WDIR = Path(os.environ.get("STRONG_DIR", "/tmp/strong"))

# кандидаты (id проверены штабом 09.10 17:35); open — веса опубликованы (hugging_face_id в каталоге OpenRouter)
CANDIDATES = [
    ("anthropic/claude-fable-5.1", "closed", "дорогая"),
    ("openai/gpt-6-astra-pro", "closed", "дорогая"),
    ("anthropic/claude-opus-5.5", "closed", "дорогая"),
    ("openai/gpt-6.1-sol-pro", "closed", ""),
    ("anthropic/claude-sonnet-5.5", "closed", "модель стенда"),
    ("x-ai/grok-4.7", "closed", ""),
    ("google/gemini-3.1-pro-preview", "closed", ""),
    ("moonshotai/kimi-k3", "open", ""),
    ("qwen/qwen3.8-2.4t-a95b", "open", ""),
    ("deepseek/deepseek-v4-pro-0813", "open", ""),
    ("z-ai/glm-5.3", "open", ""),
    ("qwen/qwen3.8-27b", "open", "встаёт на 1 GPU"),
]
# малая выборка этапа 2: вызовов на функцию
SAMPLE = {"needs_delta": 15, "needs_jury": 15, "resume": 20, "grade": 50}
FULL = {"needs_delta": 50, "needs_jury": 15, "resume": 20, "grade": 406}
# средние токены на вызов — замер Sonnet 5.5 09.10 (/tmp/rullm, ru_llm_bench): вход, выход
TOKENS = {"needs_delta": (5065, 323), "needs_jury": (4324, 135), "resume": (638, 88), "grade": (2348, 305)}
# во сколько раз выход больше, чем у Sonnet: модели с рассуждениями пишут скрытый ход мысли (оплачивается как выход);
# оценка до пробы — диапазон «как у Sonnet» … «×6»
REASONING_X = (1.0, 6.0)


def fetch_prices() -> dict:
    with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=60) as r:
        data = json.load(r)["data"]
    by = {m["id"]: m for m in data}
    out = {"date": time.strftime("%Y-%m-%d %H:%M"), "source": "https://openrouter.ai/api/v1/models", "models": {}}
    for mid, kind, note in CANDIDATES:
        m = by.get(mid)
        if not m:
            out["models"][mid] = {"missing": True}
            continue
        p = m.get("pricing") or {}
        out["models"][mid] = {
            "name": m.get("name"), "kind": kind, "note": note,
            "in_usd_per_m": round(float(p.get("prompt") or 0) * 1e6, 4),
            "out_usd_per_m": round(float(p.get("completion") or 0) * 1e6, 4),
            "context": m.get("context_length"), "hugging_face_id": m.get("hugging_face_id") or None,
            "reasoning": "reasoning" in (m.get("supported_parameters") or []),
            "structured_outputs": "structured_outputs" in (m.get("supported_parameters") or []),
        }
    PRICES.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def estimate(sizes: dict, prices: dict) -> list[dict]:
    rows = []
    for mid, kind, note in CANDIDATES:
        p = prices["models"].get(mid) or {}
        if p.get("missing"):
            rows.append({"model": mid, "missing": True})
            continue
        claude = mid.startswith("anthropic/")
        lo = hi = 0.0
        for f, n in sizes.items():
            pt, ct = TOKENS[f]
            base_in = n * pt * p["in_usd_per_m"] / 1e6
            x_lo, x_hi = (1.0, 1.5) if claude else REASONING_X
            lo += base_in + n * ct * x_lo * p["out_usd_per_m"] / 1e6
            hi += base_in + n * ct * x_hi * p["out_usd_per_m"] / 1e6
        rows.append({"model": mid, "kind": kind, "note": note, "open_weights": p.get("hugging_face_id"),
                     "in": p["in_usd_per_m"], "out": p["out_usd_per_m"], "usd_lo": round(lo, 2), "usd_hi": round(hi, 2)})
    return rows


def balance_usd() -> float | None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    req = urllib.request.Request("https://openrouter.ai/api/v1/credits", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r).get("data") or {}
    return round(float(d.get("total_credits") or 0) - float(d.get("total_usage") or 0), 3)


def cmd_estimate(a) -> None:
    prices = fetch_prices()
    small, full = estimate(SAMPLE, prices), estimate(FULL, prices)
    out = {"date": prices["date"], "sample": SAMPLE, "full": FULL, "tokens_per_call_sonnet": TOKENS,
           "reasoning_x": REASONING_X, "rows": [{**s, "full_usd_lo": f.get("usd_lo"), "full_usd_hi": f.get("usd_hi")}
                                                for s, f in zip(small, full)]}
    (ROOT / "docs" / "llm" / "strongest_estimate.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                                    encoding="utf-8")
    print("| Модель | веса | вход / выход, $ за 1 млн | малая выборка, $ | полный набор, $ |")
    print("|---|---|---|---|---|")
    for r in out["rows"]:
        if r.get("missing"):
            print(f"| {r['model']} | нет в каталоге | | | |")
            continue
        print(f"| {r['model']} | {'открытые' if r['open_weights'] else 'закрытые'} | {r['in']} / {r['out']} | "
              f"{r['usd_lo']}–{r['usd_hi']} | {r['full_usd_lo']}–{r['full_usd_hi']} |")


def cmd_run(a) -> None:
    import ru_llm_bench as B

    bal = balance_usd()
    if bal is not None:
        print(f"баланс ключа: {bal} $, пол {a.floor_usd} $, потолок прогона {a.cap_usd} $")
        if bal - a.cap_usd < a.floor_usd:
            sys.exit("отказ: прогон может опустить баланс ниже пола")
    B.SPEND["cap"] = a.cap_usd
    wdir = WDIR / B.slug(a.model)
    wdir.mkdir(parents=True, exist_ok=True)
    for f in a.funcs.split(","):
        path = wdir / f"{f}.json"
        if path.exists() and not a.force:
            print("есть:", path)
            continue
        t0 = time.time()
        if f == "needs_delta":
            r = B.run_needs(a.model, a.conc, full=False, limit=SAMPLE["needs_delta"])
        elif f == "needs_jury":
            r = B.run_needs(a.model, a.conc, full=False, jury=True)
        elif f == "resume":
            r = B.run_resume(a.model, a.conc, limit=SAMPLE["resume"])
        elif f == "grade":
            try:
                r = B.run_grade(a.model, a.conc, wdir, limit_per_group=5, timeout=50, with_second=False)
            except KeyError:  # отчёт grader_check рассчитан на полный набор — метрики выборки считает strongest_summary
                r = {"spec": a.model, "func": "grade", "date": time.strftime("%Y-%m-%d"), "raw": "g/v2_1_out.jsonl"}
        else:
            sys.exit(f"неизвестная функция {f}")
        r["wall_s"] = round(time.time() - t0, 1)
        r["spent_usd_process"] = round(B.SPEND["usd"], 4)
        path.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{a.model} {f}: {r['wall_s']} с, потрачено процессом {B.SPEND['usd']:.3f} $ → {path}", flush=True)
        if B._over_cap():
            print("потолок расходов достигнут — остальные функции не запускаются")
            break


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("estimate")
    r = sub.add_parser("run")
    r.add_argument("--model", required=True)
    r.add_argument("--funcs", default="resume,needs_jury,needs_delta,grade")
    r.add_argument("--conc", type=int, default=4)
    r.add_argument("--cap-usd", type=float, required=True)
    r.add_argument("--floor-usd", type=float, default=8.0)
    r.add_argument("--force", action="store_true")
    a = ap.parse_args()
    cmd_estimate(a) if a.cmd == "estimate" else cmd_run(a)


if __name__ == "__main__":
    main()
