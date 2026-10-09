"""Блок «Какая модель где» на /validation#experts: сводка прогонов из docs/llm/*.json →
backend/app/modules/validation/data/llm_models.json (читает GET /api/validation/llm-models).

Числа не пересчитываются заново — берутся из сохранённых прогонов (методика и оговорки — docs/LLM.md, разделы 6 и 9):
  python tools/llm/llm_models_table.py            # записать
  python tools/llm/llm_models_table.py --check    # сверить, что файл актуален (тест)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "docs" / "llm"
OUT = ROOT / "backend" / "app" / "modules" / "validation" / "data" / "llm_models.json"
SONNET = "anthropic/claude-sonnet-5.5 (reasoning low, max_tokens 2500)"
YANDEX = "yandexgpt-5.1/latest (max_tokens 1200)"
QWEN = "qwen/qwen3.5-9b (openrouter bf16)"


def _j(name: str) -> dict:
    return json.loads((D / name).read_text(encoding="utf-8"))


def _f1(p: float, r: float) -> float:
    return round(2 * p * r / (p + r), 3)


def _needs(m: dict | None, date: str, n: int = 50, p=None, r=None) -> dict:
    lr = (m or {}).get("llm_rules") or {}
    p = p if p is not None else lr["stack_micro_precision"]
    r = r if r is not None else lr["stack_micro_recall"]
    return {"ok": m.get("ok") if m else None, "n": n, "p": round(p, 3), "r": round(r, 3), "f1": _f1(p, r),
            "median_s": (m or {}).get("latency_s", {}).get("median"), "date": date}


def _grader(c: dict, date: str, note: str | None = None) -> dict:
    a = c.get("attacks") or {}
    out = {"mae_a": c["vs_gptoss_A"]["mae"], "mae_b": c["vs_gptoss_B"]["mae"], "attacks_pass": a.get("pass"),
           "attacks_n": a.get("n"), "expert_honest": c.get("expert_share_honest"), "date": date}
    if note:
        out["note"] = note
    return out


def build() -> dict:
    nb, loc, cpu = _j("needs_bench.json"), _j("needs_bench_local.json"), _j("needs_cpu_qwen.json")
    gs, gq = _j("grader_check_sonnet.json"), _j("grader_check_qwen.json")
    panel = json.loads((OUT.parent / "grader_check.json").read_text(encoding="utf-8"))["conditions"]["panel_score"]
    ro = nb["rules_only"]
    cm = next(iter(cpu["needs_bench"]["models"].values()))
    om = next(iter(cpu["openrouter_same_20"]["models"].values()))
    rows = [
        {"model": "Правила и словари", "where": "всегда; последний рубеж, если модель не ответила",
         "needs": _needs(None, "08.10", p=ro["stack_micro_precision"], r=ro["stack_micro_recall"]),
         "grader": None, "grader_none": "без модели открытые ответы проверяет эксперт"},
        {"model": "Claude Sonnet 5.5", "where": "сервер: первая модель цепочки, вторая оценка — Claude Fable 5.1",
         "needs": _needs(nb["models"][SONNET], "08.10"), "grader": _grader(gs["condition_v2_near005"], "08.10")},
        {"model": "YandexGPT 5.1", "where": "сервер: запасная модель (Yandex AI Studio)",
         "needs": _needs(nb["models"][YANDEX], "08.10"),
         "grader": _grader(panel, "06.10", "yandexgpt/latest, старый промпт, атаки — только 29 инъекций")},
        {"model": "Qwen3.5-9B (открытые веса)", "where": "профиль llm-local на CPU: оценка открытых ответов; разбор — правила",
         "needs": {**_needs(loc["models"][QWEN], "09.10"), "note": "облако, те же веса без квантования"},
         "grader": _grader(gq["conditions"]["v2"], "09.10", "облако, те же веса без квантования")},
    ]
    return {
        "date": "2026-10-09",
        "rows": rows,
        "cpu": {"model": "Qwen3.5-9B Q4_K_M", "machine": "8 vCPU без GPU", "n": cm["limit"],
                "median_s": cm["latency_s"]["median"], "p90_s": cm["latency_s"]["p90"],
                "ram_gib": cpu["memory_gb"]["shipped_load_mode_none_cache_ram_512"]["VmRSS"],
                "tok_s": cpu["speed_tokens_per_s"]["generation_median"],
                "same_n_p": cm["llm_rules"]["stack_micro_precision"], "same_n_r": cm["llm_rules"]["stack_micro_recall"],
                "cloud_n_p": om["llm_rules"]["stack_micro_precision"], "cloud_n_r": om["llm_rules"]["stack_micro_recall"],
                "cloud2_n_p": cpu["openrouter_same_20"]["run2_first_20"]["stack_micro_precision"],
                "cloud2_n_r": cpu["openrouter_same_20"]["run2_first_20"]["stack_micro_recall"]},
        "caveat": ("Прогоны моделей: разбор — на silver-разметке 50 вакансий (не экспертной), оценщик — 406 ответов, "
                   "эталон — модель gpt-oss-120b, не эксперты; A — ответы gpt-oss-120b, B — ответы открытых моделей. "
                   "Ключа Yandex для нового прогона не было: YandexGPT — цифры 08.10 и панели 06.10."),
        "how": "make llm-local",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    data = build()
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    if a.check:
        ok = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("актуален" if ok else f"устарел: python {Path(__file__).relative_to(ROOT)}")
        sys.exit(0 if ok else 1)
    OUT.write_text(text, encoding="utf-8")
    print(f"→ {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
