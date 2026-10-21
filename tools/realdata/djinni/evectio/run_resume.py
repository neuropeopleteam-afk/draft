"""Наш разбор резюме «один в один» на их ручном наборе резюме (Эвектио, MIT): resumes_labeled.json (24, РАЗРАБОТКА —
по нему они дорабатывали свой разбор, мы — только таблицу соответствия навыков) и resumes_labeled_test.json
(16, ОТЛОЖЕННАЯ — один прогон после FREEZE).

Наш продукт вызывается так же, как экран «Загрузить резюме» (POST /api/candidate/resume, candidate_router):
red = pii.redact(text); fields = extract(red.text) — с выключенной языковой моделью (LLM_DISABLED=true: прогон без
ключей и воспроизводим). Поля ответа продукта: pii_found.full_name/email/phone/telegram, extracted.stack,
extracted.experience_years, extracted.direction_hint. GitHub и город продукт в ответе не выдаёт — эти поля
считаются «нет в продукте» и показываются отдельно (в точности их ответ = None, т.е. верно только там, где в эталоне пусто).

Сравнение и метрики — дословно их resume_eval.evaluate (нормализация телефона/телеграма, стаж ±0,5 года,
micro-P/R/F1 по навыкам). Навыки: наши теги переводятся в названия их онтологии таблицей OUR_TO_THEIR
(по названиям навыков, без разметки); тег без пары в их онтологии отбрасывается (их онтологию он не может назвать).
Запуск: python run_resume.py --part dev|holdout --src <клон> [--out file.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "../../../.."))
sys.path.insert(0, os.path.join(REPO, "backend"))
os.environ["LLM_DISABLED"] = "true"
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/a17_evectio.db")

FILES = {"dev": "backend/app/validation/data/resumes_labeled.json", "holdout": "backend/app/validation/data/resumes_labeled_test.json"}
FIELDS = ["name", "email", "phone", "telegram", "github", "city", "specialization", "experience_years"]
NOT_IN_PRODUCT = {"github", "city"}

# Наш тег → названия навыков их онтологии (по совпадению названий; пусто — пары нет)
OUR_TO_THEIR: dict[str, list[str]] = {
    "a11y": [], "airflow": ["Airflow"], "algorithms": ["Алгоритмы"], "allure": ["Allure"], "angular": ["Angular"],
    "api-testing": [], "asyncio": [], "burp-suite": ["Burp Suite"], "ci-cd": ["CI/CD"], "clickhouse": ["ClickHouse"],
    "cryptography": ["Криптография"], "csharp": ["C#"], "ctf": ["CTF"], "cv": ["Computer Vision"], "django": ["Django"],
    "docker": ["Docker"], "fastapi": ["FastAPI"], "flask": ["Flask"], "forensics": ["Анализ инцидентов"],
    "frontend-testing": ["Jest"], "git": ["Git"], "go": ["Go"], "grpc": ["gRPC"], "html-css": ["HTML", "CSS"],
    "http": [],  # наш «HTTP и веб» — зонтичная практика, их «HTTP» — отдельный навык (решение на РАЗРАБОТКЕ: 12 лишних из 12) "java": ["Java"], "javascript": ["JavaScript"], "kafka": ["Kafka"], "kotlin": ["Kotlin"],
    "kubernetes": ["Kubernetes"], "linux": ["Linux"], "load-testing": ["Нагрузочное тестирование"],
    "manual-testing": ["Ручное тестирование"], "mlops": ["MLOps"], "network-security": [], "nextjs": ["Next.js"],
    "nlp": ["NLP"], "numpy": ["NumPy"], "owasp": ["OWASP"], "pandas": ["Pandas"], "pentest": ["Пентест"], "php": ["PHP"],
    "playwright": [], "postgresql": ["PostgreSQL"], "pytest": ["Pytest"], "python": ["Python"], "pytorch": ["PyTorch"],
    "rabbitmq": ["RabbitMQ"], "react": ["React"], "redis": ["Redis"], "rest-api": ["REST API"],
    "reverse-engineering": ["Reverse Engineering"], "scikit-learn": ["scikit-learn"], "selenium": ["Selenium"],
    "siem-soc": ["SIEM"], "spark": ["Spark"], "sql": ["SQL"], "state-management": ["Redux"], "statistics": ["Статистика"],
    "tailwind": [], "test-design": ["Тест-дизайн"], "typescript": ["TypeScript"], "vite-webpack": ["Webpack", "Vite"], "vue": ["Vue"],
}
OUR_DIR_TO_THEIR = {"backend": "backend", "frontend": "frontend", "qa": "qa", "data_ml": "ml", "security": "infosec"}


def _norm(v):  # их _norm
    return None if v in (None, "") else str(v).strip().lower().replace("ё", "е")


def product_parse(text: str) -> dict:
    from app.modules.resume.extract import extract
    from app.modules.resume.pii import redact

    red = redact(text)
    fields = extract(red.text)
    f = red.found
    return {"pii_found": {"full_name": (f.get("person") or [None])[0], "email": (f.get("email") or [None])[0],
                          "phone": (f.get("phone") or [None])[0], "telegram": (f.get("telegram") or [None])[0]},
            "extracted": {k: fields.get(k) for k in ("stack", "experience_years", "direction_hint", "grade_hint", "method")}}


def to_their_pred(p: dict) -> dict:
    """Ответ продукта → поля их сравнения (как их _pred: телефон — последние 10 цифр, телеграм без @)."""
    pf, ex = p["pii_found"], p["extracted"]
    phone = pf["phone"]
    skills: list[str] = []
    for s in ex.get("stack") or []:
        for n in OUR_TO_THEIR.get(s["tag"], []):
            if n not in skills:
                skills.append(n)
    return {"name": pf["full_name"], "email": pf["email"],
            "phone": re.sub(r"\D", "", phone)[-10:] if phone else None,
            "telegram": (pf["telegram"] or "").lstrip("@") or None,
            "github": None, "city": None,
            "specialization": OUR_DIR_TO_THEIR.get(ex.get("direction_hint") or ""),
            "experience_years": ex.get("experience_years"), "skills": skills}


def evaluate(path: str) -> dict:
    data = json.load(open(path, encoding="utf-8"))
    correct = {f: 0 for f in FIELDS}
    tp = fp = fn = 0
    exp_err, rows = [], []
    for it in data["items"]:
        g, p = it["gold"], to_their_pred(product_parse(it["text"]))
        ok = {}
        for f in FIELDS:
            if f == "experience_years":
                gv, pv = g[f], p[f]
                ok[f] = (gv is None and not pv) or (gv is not None and pv is not None and abs(gv - pv) <= 0.5)
                if gv is not None and pv is not None:
                    exp_err.append(abs(gv - pv))
            else:
                ok[f] = _norm(g[f]) == _norm(p[f])
            correct[f] += ok[f]
        gs, ps = set(g["skills"]), set(p["skills"])
        tp += len(gs & ps)
        fp += len(ps - gs)
        fn += len(gs - ps)
        rows.append({"id": it["id"], "errors": [f for f in FIELDS if not ok[f]], "missed_skills": sorted(gs - ps),
                     "extra_skills": sorted(ps - gs), "pred_spec": p["specialization"], "gold_spec": g["specialization"]})
    n = len(data["items"])
    prec, rec = tp / max(1, tp + fp), tp / max(1, tp + fn)
    # Навыки на общей части онтологий: эталонные навыки, у которых есть пара среди наших тегов
    shared = {x for v in OUR_TO_THEIR.values() for x in v}
    tp2 = fn2 = 0
    for it, r in zip(data["items"], rows):
        gs = {s for s in it["gold"]["skills"] if s in shared}
        miss = {s for s in r["missed_skills"] if s in shared}
        fn2 += len(miss)
        tp2 += len(gs) - len(miss)
    rec2 = tp2 / max(1, tp2 + fn2)
    gold_dirs = sum(1 for it in data["items"] if it["gold"]["specialization"] in OUR_DIR_TO_THEIR.values())
    spec_ok_shared = sum(1 for it, r in zip(data["items"], rows) if it["gold"]["specialization"] in OUR_DIR_TO_THEIR.values() and "specialization" not in r["errors"])
    return {
        "resumes": n, "skills_labeled": tp + fn,
        "field_accuracy": {f: round(correct[f] / n, 3) for f in FIELDS},
        "fields_not_in_product": sorted(NOT_IN_PRODUCT),
        "skills": {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(2 * prec * rec / max(1e-9, prec + rec), 3)},
        "skills_shared_ontology": {"gold_skills": tp2 + fn2, "recall": round(rec2, 3), "precision": round(prec, 3),
                                   "f1": round(2 * prec * rec2 / max(1e-9, prec + rec2), 3)},
        "specialization_on_shared_directions": {"n": gold_dirs, "accuracy": round(spec_ok_shared / max(1, gold_dirs), 3)},
        "experience_mae": round(statistics.mean(exp_err), 2) if exp_err else None,
        "per_resume": rows,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["dev", "holdout"], required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    path = os.path.join(a.src, FILES[a.part])
    r = evaluate(path)
    r["source"] = {"repo": "github.com/archebaldo777/sporthackathon", "commit": "85bbc78", "file": FILES[a.part],
                   "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(), "license": "MIT", "part": a.part}
    if a.out:
        json.dump(r, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in r.items() if k != "per_resume"}, ensure_ascii=False))
    return r


if __name__ == "__main__":
    main()
