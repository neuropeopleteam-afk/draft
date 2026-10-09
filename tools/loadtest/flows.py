"""Чистые помощники сценариев нагрузки жюри (без Locust): их же проверяет backend/tests/test_loadtest_jury.py."""
from __future__ import annotations

import random

CAND_PERSONAS = ["candidate_new", "candidate_nofsp", "candidate_junior", "candidate"]
GRADE_FOR = {"candidate_new": "junior", "candidate_nofsp": "middle", "candidate_junior": "junior", "candidate": "middle"}

# Тексты потребностей — фиксированный набор: модель (фоновое уточнение И27) вызывается не больше одного раза на текст,
# повторный разбор того же текста — из кэша. Контактов и персональных данных в текстах нет.
NEED_TEXTS = [
    "Ищем Middle Python-разработчика в команду платёжного сервиса: FastAPI, PostgreSQL, Docker, опыт от 2 лет, "
    "удалённо или гибрид, вилка 220–280 тыс. рублей.",
    "Нужен Junior frontend-разработчик: TypeScript, React, вёрстка по макетам Figma, тесты Jest, офис в Москве.",
    "Senior Data Scientist: Python, pandas, scikit-learn, SQL, A/B-тесты, опыт продакшен-моделей от 4 лет, удалёнка.",
    "QA-инженер Middle: автотесты на pytest и Playwright, API-тестирование, CI в GitLab, опыт от 2 лет.",
]
REQ_KEYS = ("direction", "grade", "experience_years_min", "work_format", "city", "salary_from", "salary_to")


def is_llm_item(item: dict) -> bool:
    """Задание, ответ на которое оценивает LLM по рубрике: open_answer и шаг 3 open_book_3step.
    predict_output тоже отвечается строкой, но сверяется с ключом после нормализации — без модели."""
    fmt, kind = item.get("format"), item.get("answer_kind", "option")
    return fmt == "open_answer" or (fmt == "open_book_3step" and kind == "text")


def answer_for(item: dict, rnd: random.Random | None = None) -> dict:
    """Тело POST …/answers для автопроверяемого задания (случайный ответ — «средний» кандидат не нужен)."""
    rnd = rnd or random
    kind = item.get("answer_kind", "option")
    if kind == "text":
        ans = rnd.choice(["0", "1", "2", "None", "True", "[1, 2, 3]", "3"])
    elif kind == "line":
        ans = rnd.randint(1, max(1, len((item.get("code") or "x").splitlines())))
    else:
        ans = rnd.choice([o["id"] for o in item.get("options") or [{"id": "A"}]])
    body = {"item_id": item["item_id"], "answer": ans, "time_spent_ms": rnd.randint(4_000, 40_000)}
    if item.get("step"):
        body["step"] = item["step"]
    return body


def need_requirements(parsed: dict) -> dict:
    """Требования из ответа POST /needs/parse → тело requirements для POST /needs (как «Подтвердить всё» в интерфейсе):
    сохранение с готовыми требованиями не вызывает разбор и модель повторно."""
    req = {k: parsed.get(k) for k in REQ_KEYS if parsed.get(k) is not None}
    for k in ("stack_required", "stack_desired"):
        req[k] = [{"tag": x["tag"], "weight": x.get("weight", 1.0), "status": "confirmed"} for x in parsed.get(k) or []]
    return req


def invitation_body(ref: str, need_id: str) -> dict:
    return {"candidate_ref": ref, "need_id": need_id, "position_title": "Разработчик (нагрузочный тест)",
            "offer_description": "Нагрузочный тест песочницы жюри: приглашение без реального оффера.",
            "salary_from": 150000, "salary_to": 220000, "contact_method": "Чат платформы"}
