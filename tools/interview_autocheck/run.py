#!/usr/bin/env python3
"""Автопроверка движка ИИ-интервьюера на модельных кандидатах (модель, не люди). Написано 10.10.2026.

Три роли — честный / списавший / «плавающий» — проходят устную защиту одних и тех же письменных ответов; движок ведёт
разговор и оценивает. Итог: «честных подтверждено X из Y, списавших поймано Z из W, плавающих не подтверждено V из U»,
дата, SHA ветки, модели. Результаты — tools/interview_autocheck/results/<дата>_<sha>.{md,json} (без ключей).

Запуск из корня репозитория (ключи в окружении, не печатать):
  set -a; . ~/.secrets/openrouter.env; set +a
  LLM_CHAIN=openrouter INTERVIEW_STUB=0 python3 tools/interview_autocheck/run.py --n 2
  python3 tools/interview_autocheck/run.py --stub      # без сети: сценарные реплики и оценка по правилам (CI)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import SPEC
from personas import COMMON, PERSONAS, SCRIPTED

CANDIDATE_MODEL = os.environ.get("AUTOCHECK_CANDIDATE_MODEL", "anthropic/claude-sonnet-4.6")


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def candidate_reply(persona: str, question: str, history: list[dict], stub: bool, k: int) -> tuple[str, float]:
    if stub:
        lines = SCRIPTED[persona]
        return lines[min(k, len(lines)) - 1], 0.0
    from app.modules.llm import client as llm

    answers = "\n\n".join(f"Задание «{t['title']}»: {t['answer']}" for t in SPEC["context"]["tasks"])
    system = f"{COMMON}\n\n{PERSONAS[persona]['role']}\n\nТВОИ ПИСЬМЕННЫЕ ОТВЕТЫ\n{answers}"
    msgs = [{"role": "system", "content": system}] + history + [{"role": "user", "content": question}]
    res = llm.chat(msgs, temperature=0.8, max_tokens=350, model=CANDIDATE_MODEL, timeout_s=40)
    if not res.ok or not res.text.strip():
        return SCRIPTED[persona][min(k, len(SCRIPTED[persona])) - 1], 0.0
    cost = 0.0
    if isinstance(res.usage, dict):
        try:
            cost = float(res.usage.get("cost") or 0)
        except (TypeError, ValueError):
            cost = 0.0
    return " ".join(res.text.split()), cost


def run_session(persona: str, stub: bool) -> dict:
    from app.modules.interview import engine as e

    spec = e.normalize_spec(e.SessionSpec(**SPEC))
    now = datetime.now(UTC)
    out = e.next_turn(e.TurnInput(spec=spec, transcript=e.Transcript(), now=now))
    history: list[dict] = []
    cost = out.cost_usd
    k = 1
    while not out.finished:
        reply, c = candidate_reply(persona, out.text, history, stub, k)
        history += [{"role": "user", "content": out.text}, {"role": "assistant", "content": reply}]
        cost += c
        out = e.next_turn(e.TurnInput(spec=spec, transcript=out.transcript, candidate_text=reply, now=now + timedelta(seconds=45 * k)))
        spec = spec.model_copy(update={"started_at": out.started_at})
        cost += out.cost_usd
        k += 1
        if k > 12:
            break
    t0 = time.time()
    v = e.evaluate(spec, out.transcript)
    return {"persona": persona, "label": PERSONAS[persona]["label"], "expect": PERSONAS[persona]["expect"],
            "verdict": v.verdict, "verdict_label": v.verdict_label, "score": v.score, "coverage": v.coverage,
            "levels": [q.level for q in v.questions], "lowered": sum(1 for q in v.questions if q.lowered),
            "removed_quotes": v.removed_quotes, "flags": v.flags, "summary": v.summary, "source": v.source,
            "turn_source": out.source, "judge_seconds": round(time.time() - t0, 1), "cost_usd": round(cost + v.cost_usd, 4),
            "transcript": [{"who": u.who, "n": u.n, "kind": u.kind, "text": u.text} for u in out.transcript.items]}


def ok(r: dict) -> bool:
    exp = r["expect"]
    if exp == "confirmed":
        return r["verdict"] == "confirmed"
    if exp == "discrepancies":
        return r["verdict"] == "discrepancies"
    return r["verdict"] != "confirmed"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=2, help="сессий на роль (по умолчанию 2)")
    ap.add_argument("--stub", action="store_true", help="без сети: сценарные реплики, оценка по правилам")
    ap.add_argument("--personas", default="honest,copied,floating")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "results"))
    args = ap.parse_args()
    if args.stub:
        os.environ["INTERVIEW_STUB"] = "1"
    from app.modules.interview import engine as e
    e.reset_interview_settings()
    stub = e.is_stub()
    s = e.get_interview_settings()
    sha, started = git_sha(), datetime.now(UTC)
    results = []
    for persona in [p.strip() for p in args.personas.split(",") if p.strip()]:
        for i in range(args.n):
            r = run_session(persona, stub)
            results.append(r)
            print(f"{r['label']:>10} #{i + 1}: {r['verdict']} ({r['verdict_label']}) балл={r['score']} уровни={r['levels']} "
                  f"цитат убрано={r['removed_quotes']} {'OK' if ok(r) else 'MISS'} {r['cost_usd']} USD", flush=True)

    def count(p):
        rs = [r for r in results if r["persona"] == p]
        return sum(1 for r in rs if ok(r)), len(rs)

    h, hn = count("honest")
    c, cn = count("copied")
    f, fn = count("floating")
    insufficient = sum(1 for r in results if r["verdict"] == "insufficient")
    total_cost = round(sum(r["cost_usd"] for r in results), 4)
    headline = (f"честных подтверждено {h} из {hn}, списавших поймано {c} из {cn}, «плавающих» не подтверждено {f} из {fn}"
                f" (модель, не люди; «мало данных» — {insufficient})")
    mode = "заглушка (правила, сценарные реплики)" if stub else f"модели: реплики {s.interview_model_turn}, оценка {s.interview_model_judge}, кандидат {CANDIDATE_MODEL}"
    date = started.astimezone(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M МСК")
    print(f"\nИТОГ: {headline}; {date}; SHA {sha}; {mode}; стоимость {total_cost} USD")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{started.strftime('%Y%m%d_%H%M')}_{sha}{'_stub' if stub else ''}"
    (out_dir / f"{stem}.json").write_text(json.dumps({"date": date, "sha": sha, "mode": mode, "headline": headline,
                                                       "cost_usd": total_cost, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# Автопроверка ИИ-интервьюера — {date}, SHA {sha}", "", f"**{headline}.** Режим: {mode}. Стоимость: {total_cost} USD.", "",
             "Кандидаты — модельные роли (модель, не люди): честный объясняет своими словами; списавший повторяет текст, путает термины, "
             "не помнит «почему»; плавающий говорит общими словами без конкретики.", "",
             "| Роль | № | Вердикт | Балл | Уровни по вопросам | Цитат убрано | Ожидание | Итог |", "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        lines.append(f"| {r['label']} | {i} | {r['verdict_label']} | {r['score'] if r['score'] is not None else '—'} | {', '.join(r['levels'])} | "
                     f"{r['removed_quotes']} | {r['expect']} | {'OK' if ok(r) else 'MISS'} |")
    lines += ["", "## Резюме оценщика по сессиям", ""]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r['label']}** — {r['summary']}" + (f" Флаги: {'; '.join(r['flags'])}" if r["flags"] else ""))
    (out_dir / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Сохранено: {out_dir / (stem + '.md')}")
    return 0 if (h == hn and c == cn) else 1


if __name__ == "__main__":
    raise SystemExit(main())
