"""И27: замер быстрого разбора потребности до/после на 10 демо-потребностях и 5 «жюрийных» (сленг, английский стек).

До — прежний синхронный разбор (POST /needs/parse mode=full: полный промпт, ответ ждёт модель).
После — mode=fast: ответ словарём (первая карточка), модель с запросом-дельтой в фоне (опрос GET /needs/parse/{id}),
повтор того же текста — из кэша. Запросы идут через приложение (TestClient, SQLite во временном каталоге), модель —
настоящая (цепочка из окружения: OPENROUTER_API_KEY …; ключ в вывод не попадает). Персональных данных в текстах нет.

Запуск (из backend/): DATABASE_URL=sqlite:////tmp/fastparse/bench.db DEV_MODE=true LLM_CHAIN=openrouter \
    python ../tools/fastparse/bench.py --out ../tools/fastparse/bench_0910.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

J40 = {n["id"]: n["text"] for n in json.loads((ROOT / "tools/jury_match/needs_40.json").read_text())["needs"]}


def texts() -> list[tuple[str, str, str]]:
    from app.modules.jury.seed import NEEDS

    example = ("Ищем бэкенд-разработчика уровня middle: обязательно Python, FastAPI и PostgreSQL, опыт с Redis. "
               "Будет плюсом Kafka. Удалённо, 220–300 тыс. ₽")  # пример на экране «Потребности»
    demo = [(f"D{i + 1}", "демо: песочница жюри", t) for i, t in enumerate(NEEDS)]
    demo.append(("D5", "демо: пример на экране", example))
    demo += [(k, "демо: аудит подбора (needs_40)", J40[k]) for k in ("J03", "J10", "J16", "J26", "J31")]
    jury = [(k, "жюри: сленг / английский", J40[k]) for k in ("J01", "J27", "J19", "J39")]
    jury.append(("E1", "жюри: английский стек", "Looking for a middle frontend engineer: React + TS, Next.js, "
                                                 "Tailwind; Playwright e2e tests nice to have. Hybrid, St. Petersburg."))
    return demo + jury


def tags(r: dict) -> dict:
    return {"req": sorted(i["tag"] for i in r.get("stack_required") or []),
            "des": sorted(i["tag"] for i in r.get("stack_desired") or [])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="bench_fastparse.json")
    a = ap.parse_args()
    os.environ.setdefault("DEV_MODE", "true")
    os.environ.setdefault("JWT_SECRET", "bench-secret-not-for-prod-0123456789abcdef")
    os.environ.setdefault("MAIL_BACKEND", "dev")
    os.environ["ATS_STAGE_POLL_S"] = "0"
    os.environ["JURY_SPARE_SANDBOXES"] = "0"
    os.environ["ASSIGNMENTS_FEED_INTERVAL_S"] = "0"
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    url = os.environ["DATABASE_URL"]
    cfg = Config(str(ROOT / "backend/alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend/migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["skip_logging"] = True
    command.upgrade(cfg, "head")
    get_settings.cache_clear()
    from app.main import app
    from app.modules.resume.pii import redact

    redact("Прогрев Ивана Петрова", use_ner=True)  # загрузка NER — один раз при старте процесса, не в замере
    rows = []
    with TestClient(app) as c:
        email = f"bench{int(time.time())}@example.com"
        r = c.post("/api/auth/register", json={"email": email, "password": "Passw0rd!", "role": "employer",
                                               "consent_processing": True, "company_name": "Замер"})
        code = r.json()["dev_verification_code"]
        tok = c.post("/api/auth/verify-email", json={"email": email, "code": code}).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        for nid, kind, text in texts():
            t0 = time.perf_counter()
            full = c.post("/api/employer/needs/parse", json={"text": text, "mode": "full"}, headers=h).json()
            t_full = time.perf_counter() - t0
            t0 = time.perf_counter()
            fast = c.post("/api/employer/needs/parse", json={"text": text}, headers=h).json()
            t_first = time.perf_counter() - t0
            job, t_bg = fast.get("parse_job"), None
            res = fast
            if job and job["status"] == "pending":
                while True:
                    time.sleep(0.1)
                    j = c.get(f"/api/employer/needs/parse/{job['id']}", headers=h).json()
                    if j["status"] != "pending":
                        t_bg, res = time.perf_counter() - t0, j
                        break
            t0 = time.perf_counter()
            again = c.post("/api/employer/needs/parse", json={"text": text}, headers=h).json()
            t_cache = time.perf_counter() - t0
            result = res.get("result") or res
            delta = res.get("delta") or []
            rows.append({
                "id": nid, "kind": kind, "text": text,
                "before_full_s": round(t_full, 2), "before_llm_ms": (full.get("llm") or {}).get("latency_ms"),
                "before_used": (full.get("llm") or {}).get("used"),
                "first_card_ms": round(t_first * 1000), "background_s": round(t_bg, 2) if t_bg else None,
                "delta_llm_ms": (res.get("llm") or {}).get("latency_ms"), "status": res.get("status"),
                "cache_ms": round(t_cache * 1000), "cached": bool((again.get("llm") or {}).get("cached")),
                "rules": tags(fast), "full": tags(full), "fast": tags(result),
                "added": [d["tag"] for d in delta if d["kind"] == "add_tag"],
                "confirmed": [d["tag"] for d in delta if d["kind"] == "confirm_tag"],
                "offers": [d["id"] for d in delta if not d["auto"]],
                # что модель добавила к словарю: прежний полный промпт (full) и запрос-дельта (added)
                "full_added": sorted({*tags(full)["req"], *tags(full)["des"]} - {*tags(fast)["req"], *tags(fast)["des"]}),
                "model": (res.get("llm") or {}).get("model_label"),
            })
            print(json.dumps({k: rows[-1][k] for k in ("id", "before_full_s", "first_card_ms", "background_s",
                                                         "cache_ms", "added", "offers")}, ensure_ascii=False),
                  flush=True)

    def med(k):
        v = [r[k] for r in rows if r[k] is not None]
        return round(statistics.median(v), 2) if v else None

    summary = {k: med(k) for k in ("before_full_s", "first_card_ms", "background_s", "cache_ms", "before_llm_ms",
                                   "delta_llm_ms")}
    summary.update(n=len(rows), max_before_full_s=max(r["before_full_s"] for r in rows),
                   max_background_s=max((r["background_s"] or 0) for r in rows),
                   max_first_card_ms=max(r["first_card_ms"] for r in rows),
                   done=sum(r["status"] == "done" for r in rows), cached=sum(r["cached"] for r in rows))
    Path(a.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
