"""И10 (08.10, п. 5): чистая машина без ключей LLM — функции с моделью работают по запасному пути, /api/meta честен.

Тесты идут с LLM_DISABLED=true (tests/conftest.py); отдельная проверка — настройки без LLM_DISABLED и без ключей
(так стартует свежий клон по README). Подписи интерфейса (frontend/src/components/LlmOff.tsx) смотрят на
`llm.configured` из /api/meta.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from tests.test_day2_rules import H, _pdf_bytes
from tests.test_infra_0610 import _login


def test_meta_says_llm_is_off(client):
    llm = client.get("/api/meta").json()["llm"]
    assert llm == {"configured": False, "provider": None, "model": None}


def test_fresh_clone_settings_have_no_llm_without_keys():
    """Свежий клон: ни LLM_DISABLED, ни ключей, ни backend/.env — `llm_configured` ложно, провайдер и модель не выдумываются."""
    root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("LLM_")}
    code = ("from app.core.config import Settings; from app.modules.llm.client import status; "
            "s = Settings(_env_file=None); print(s.llm_configured, s.llm_disabled)")
    r = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=60, env=env)
    assert r.returncode == 0, r.stderr[-1500:]
    assert r.stdout.split() == ["False", "False"]  # не «выключен флагом», а просто без ключей


def test_need_parse_works_by_rules_and_says_so(client):
    e = _login(client, "employer", "new")["access_token"]
    text = "Нужен Python-разработчик уровня middle: FastAPI, PostgreSQL, Docker, опыт от 3 лет, удалённо"
    r = client.post("/api/employer/needs/parse", json={"text": text}, headers=H(e))
    assert r.status_code == 200, r.text
    req = r.json()
    assert req["method"] == "rules" and req["llm"] == {"used": False, "reason": "not_configured"}
    assert req["direction"] == "backend" and req["grade"] == "middle"
    tags = {i["tag"] for i in req["stack_required"]}
    assert {"python", "fastapi", "postgresql"} <= tags
    # цитата из текста есть у каждого требования, источник — словарь
    assert all(i["evidence"]["source"] == "rules" and i["evidence"]["quote"] in text for i in req["stack_required"])


def test_resume_is_parsed_by_rules_without_llm(client):
    c = _login(client, "candidate", "new")["access_token"]
    pdf = _pdf_bytes(["Смирнова Анна Викторовна", "Backend-разработчик", "anna.smirnova@yandex.ru, +7 999 123-45-67",
                      "Python, FastAPI, PostgreSQL, Docker, Redis. Опыт 4 года."])
    r = client.post("/api/me/resume", files={"file": ("cv.pdf", pdf, "application/pdf")}, headers=H(c))
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["method"] == "rules" and d["extracted"]["llm"] == {"used": False, "reason": "not_configured"}
    assert {"python", "fastapi", "postgresql"} <= {s["tag"] for s in d["extracted"]["stack"]}
    assert "anna.smirnova" not in str(d["text_preview"])  # ПДн вырезаны локально, модели они и не нужны


def test_open_answer_is_pending_for_expert_not_graded_by_model():
    from app.modules.assessment.grader import grade_open

    rubric = {"criteria": [{"id": "correctness", "title": "Корректность", "weight": 0.6},
                           {"id": "clarity", "title": "Ясность", "weight": 0.4}]}
    g = grade_open(stem="Опишите идемпотентную обработку платёжных вебхуков", code=None, step_prompt=None,
                   rubric=rubric, answer="Храним идентификатор события с уникальным ключом и обрабатываем в транзакции. " * 3)
    assert g.status == "pending" and g.method == "none" and g.error == "llm_not_configured"
    assert g.score is None  # балл не выдумывается


def test_expert_pack_llm_grade_reports_not_configured():
    from app.core.db import SessionLocal
    from app.modules.experts.llm_grade import grade_pack

    with SessionLocal() as db:
        out = grade_pack(db)
    assert out["ok"] is False and out["error"] == "llm_not_configured"
