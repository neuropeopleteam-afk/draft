"""Ф6 (В9): автоимя потребности — не только категория; нормальный и DevOps-тексты различимы."""
from app.modules.matching.need_parser import parse_need
from app.modules.matching.router import _need_title

NORMAL = ("Ищем Middle Python-разработчика в команду платежей: Python, FastAPI, PostgreSQL обязательно, "
          "Redis желательно. Удалённо, вилка 230–290 тыс. ₽.")
DEVOPS = ("Ищем DevOps-инженера уровня middle: Kubernetes, Terraform, Linux, CI/CD, мониторинг. "
          "Удалённо, вилка 250–300 тыс. ₽.")


def test_title_has_skills_and_differs_for_devops():
    a = _need_title(parse_need(NORMAL, use_llm=False))
    b = _need_title(parse_need(DEVOPS, use_llm=False))
    assert a.startswith("Backend · Middle — ") and "Python" in a
    assert b.startswith("DevOps / SRE") and "ближайшая категория — Backend" in b
    assert a != b and a != "Backend · Middle" and b != "Backend · Middle"


def test_title_fallbacks():
    assert _need_title({}) == "Потребность"
    assert _need_title({"direction": "qa", "grade": "junior"}) == "QA · Junior"
    req = {"direction": "backend", "grade": "senior", "stack_required": [
        {"tag": "sql", "weight": 0.5}, {"tag": "python", "weight": 1.0}, {"tag": "git", "weight": 0.8},
        {"tag": "http", "weight": 0.3}]}
    assert _need_title(req) == "Backend · Senior — Python, Git, SQL"
    assert _need_title({"direction": "frontend", "stack_desired": [{"tag": "git", "weight": 0.3}]}) == "Frontend — Git"
