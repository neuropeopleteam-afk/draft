"""Демо-вакансии для 10 демо-компаний: `python -m app.integrations.vacancies.demo [--reset]`.

Все записи помечены is_demo и удаляются вместе с демо-компаниями (ON DELETE CASCADE). Вилки — внутри рыночного
диапазона категории, кроме одной намеренно завышенной («вакансия-приманка»): на ней видно, как индекс доверия
предупреждает кандидата.
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import delete, select

from app.core.db import SessionLocal, get_engine, utcnow
from app.integrations.vacancies.models import Vacancy
from app.modules.profiles.models import Company

# (индекс демо-компании, должность, категория, стек, от, до, формат, описание)
VACANCIES = [
    (0, "Python-разработчик (платёжные сервисы)", "backend.middle", ["python", "fastapi", "postgresql", "kafka"], 200_000, 280_000, "remote",
     "Развиваем сервисы платежей: API на FastAPI, PostgreSQL, очереди Kafka. Код-ревью, тесты, дежурства по графику."),
    (0, "Java-разработчик senior (ядро платежей)", "backend.senior", ["java", "postgresql", "kafka"], 320_000, 420_000, "hybrid",
     "Проектирование и развитие платёжного ядра, наставничество двух разработчиков, участие в архитектурных решениях."),
    (1, "Аналитик данных junior", "data_ml.junior", ["python", "pandas", "sql"], 95_000, 140_000, "hybrid",
     "Отчёты и исследования по городским сервисам: выгрузки SQL, анализ в pandas, визуализация. Наставник в команде."),
    (2, "Специалист по анализу защищённости", "security.middle", ["owasp", "linux"], 190_000, 280_000, "office",
     "Пентест веб-приложений клиентов, отчёты об уязвимостях, участие в CTF-командах компании приветствуется."),
    (3, "Frontend-разработчик (React, TypeScript)", "frontend.middle", ["react", "typescript"], 170_000, 250_000, "remote",
     "Витрина и личный кабинет маркетплейса: React, TypeScript, дизайн-система, доступность интерфейсов."),
    (4, "QA-инженер (API и автотесты)", "qa.middle", ["pytest", "playwright"], 140_000, 210_000, "hybrid",
     "Тест-дизайн и автотесты для медицинской информационной системы: API, pytest, Playwright, Allure."),
    (5, "Go-разработчик senior (маршрутизация)", "backend.senior", ["go", "postgresql", "kafka", "docker"], 310_000, 440_000, "remote",
     "Сервисы построения маршрутов и расчёта тарифов: Go, PostgreSQL, Kafka. Высокая нагрузка, on-call раз в месяц."),
    (6, "Junior frontend-разработчик", "frontend.junior", ["react", "typescript"], 80_000, 120_000, "office",
     "Интерфейсы образовательной платформы. Обучение внутри команды, наставник, ревью каждого изменения."),
    (7, "ML-инженер (компьютерное зрение)", "data_ml.senior", ["python", "pandas"], 340_000, 480_000, "hybrid",
     "Модели контроля качества на производстве: CV, обучение и вывод моделей в эксплуатацию, MLOps."),
    (8, "Senior frontend: «до 900 тыс. ₽, без опыта»", "frontend.senior", ["react", "typescript"], 600_000, 900_000, "remote",
     "Срочно! Высокий доход с первого дня, опыт не важен, оформление после оплаты обучения. "
     "(Демо: намеренно неправдоподобная вилка — индекс доверия предупреждает кандидата.)"),
    (9, "Junior QA (ручное тестирование)", "qa.junior", ["sql"], 70_000, 100_000, "office",
     "Ручное тестирование веб- и мобильных приложений заказчиков, тест-кейсы, баг-репорты, основы API-тестирования."),
]


def seed(reset: bool = False) -> dict:
    get_engine()
    with SessionLocal() as db:
        companies = db.scalars(select(Company).where(Company.is_demo.is_(True)).order_by(Company.name)).all()
        by_name = {c.name: c for c in companies}
        from app.modules.demo.seed import COMPANIES

        ordered = [by_name.get(name) for name, _, _ in COMPANIES]
        if reset:
            db.execute(delete(Vacancy).where(Vacancy.is_demo.is_(True)))
        elif db.scalar(select(Vacancy.id).where(Vacancy.is_demo.is_(True)).limit(1)):
            return {"created": 0, "note": "демо-вакансии уже есть (--reset, чтобы пересоздать)"}
        made = 0
        for ci, title, cat, stack, s_from, s_to, fmt, desc in VACANCIES:
            c = ordered[ci] if ci < len(ordered) else None
            if c is None:
                continue
            db.add(Vacancy(company_id=c.id, created_by=c.created_by, title=title, category_id=cat, description=desc,
                           stack=stack, salary_from=s_from, salary_to=s_to, work_format=fmt, city=c.city,
                           status="published", published_at=utcnow(), is_demo=True))
            made += 1
        db.commit()
        return {"created": made, "demo_companies": len(companies)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reset", action="store_true", help="удалить демо-вакансии и создать заново")
    print(json.dumps(seed(reset=ap.parse_args().reset), ensure_ascii=False))


if __name__ == "__main__":
    main()
