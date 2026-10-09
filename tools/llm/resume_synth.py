"""Синтетический набор резюме для замера функции `resume` (Я2, «только российская модель»).

20 резюме ИТ-специалистов, написанных автором набора (модель, не люди) — без персональных данных: ФИО и контакты
уже заменены плейсхолдерами, как после resume/pii.redact. Сленг, транслит и английские названия — нарочно
(«постгря», «кубер», «торч», «k8s»): словарь их частью не знает, это и проверяет модель.

Разметка (gold) — тем же автором: стек-теги справочника, явно упомянутые в тексте как опыт кандидата; роли; стаж
в годах на 10.2026 (по периодам работы или явной фразе). Это не экспертная разметка.

    python tools/llm/resume_synth.py            # → docs/llm/resume_synth.json
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "llm" / "resume_synth.json"

HEAD = "[ФИО]\n[почта] · [телефон] · [ссылка]\n"

R = [
    ("r01", "Москва\nBackend-разработчик\n\nОпыт работы\n03.2021 — по настоящее время, финтех-компания, разработчик\n"
            "Пишу сервисы на питоне: FastAPI, асинхронщина на asyncio, БД — постгря, кэш в редисе. Деплой — докер, "
            "пайплайны в GitLab CI. Покрываю код тестами на pytest.\n"
            "09.2019 — 02.2021, веб-студия, младший разработчик: Django, шаблоны, немного JS.\n\n"
            "Навыки: Python, SQL, Git, Linux, REST API",
     ["python", "fastapi", "asyncio", "postgresql", "redis", "docker", "ci-cd", "pytest", "django", "javascript",
      "sql", "git", "linux", "rest-api"], ["developer"], 7.1),
    ("r02", "Казань\nFrontend developer\n\nОпыт: 4 года коммерческой разработки.\n"
            "Стек: React + TS, стейт — Redux Toolkit и Zustand, сборка Vite, стили на Tailwind. Писал SSR на Next. "
            "Тесты компонентов — Jest и Testing Library, e2e — плейрайт. Слежу за доступностью (ARIA, клавиатура).\n"
            "Наставник двух джунов, провожу код-ревью.",
     ["react", "typescript", "state-management", "vite-webpack", "tailwind", "nextjs", "frontend-testing",
      "playwright", "a11y"], ["developer", "mentor"], 4.0),
    ("r03", "Санкт-Петербург\nData Scientist\n\n2022 — н. в. — ритейл, DS: прогноз спроса (пандас, нампай, "
            "склерн, бустинги), A/B-тесты и статистика, витрины в кликхаусе, оркестрация на Airflow.\n"
            "2020 — 2022 — банк, аналитик данных: SQL, Python, отчёты.\n"
            "Pet-проект: классификация отзывов на торче (BERT), NLP.",
     ["pandas", "numpy", "scikit-learn", "statistics", "clickhouse", "airflow", "sql", "python", "pytorch", "nlp"],
     ["researcher", "analyst"], 6.8),
    ("r04", "Новосибирск\nQA Automation Engineer\n\nОпыт работы 5 лет.\n"
            "Автотесты UI на Selenium и Playwright (Python), API — requests + pytest, отчёты в Allure. "
            "Нагрузочное — JMeter и Locust. Тест-дизайн: классы эквивалентности, граничные значения, pairwise. "
            "Ручное тестирование мобильных приложений. Интеграция тестов в Jenkins.",
     ["selenium", "playwright", "python", "api-testing", "pytest", "allure", "load-testing", "test-design",
      "manual-testing", "ci-cd"], ["tester"], 5.0),
    ("r05", "Москва\nСпециалист по информационной безопасности\n\n"
            "01.2020 — настоящее время — SOC-аналитик, затем пентестер. Мониторинг в SIEM (MaxPatrol, Splunk), "
            "разбор инцидентов, форензика рабочих станций. Пентест веб-приложений: Burp Suite, OWASP Top 10. "
            "Сетевая безопасность: VLAN, межсетевые экраны, Wireshark. Участвую в CTF (реверс, крипта).",
     ["siem-soc", "forensics", "pentest", "burp-suite", "owasp", "network-security", "ctf", "reverse-engineering",
      "cryptography"], ["analyst"], 6.8),
    ("r06", "Екатеринбург\nJava-разработчик\n\nОпыт: 2018 — 2026, интегратор, разработчик → техлид.\n"
            "Spring Boot, микросервисы, Kafka и RabbitMQ, PostgreSQL, gRPC между сервисами. Kotlin — новые сервисы. "
            "Контейнеры — Docker, кубер (Helm), CI/CD в GitLab. Проектирую архитектуру модулей.",
     ["java", "kafka", "rabbitmq", "postgresql", "grpc", "kotlin", "docker", "kubernetes", "ci-cd"],
     ["developer", "tech_lead", "architect"], 8.0),
    ("r07", "Удалённо\nGo-разработчик (Golang)\n\n06.2022 — н. в. — маркетплейс: сервисы на Go, gRPC и REST, "
            "Postgres, Redis, Кафка. Метрики и алерты, k8s.\n"
            "07.2021 — 05.2022 — стажёр-разработчик PHP.",
     ["go", "grpc", "rest-api", "postgresql", "redis", "kafka", "kubernetes", "php"], ["developer"], 5.2),
    ("r08", "Нижний Новгород\nСтажёр / Junior Python\n\nВыпускник 2026 года. Учебные проекты: телеграм-бот на "
            "aiogram (asyncio), парсер на requests, REST API на Flask с SQLite. Знаю Git, базовый Linux, SQL. "
            "Решаю задачи на алгоритмы (LeetCode, 300+ задач).\nОпыта работы нет.",
     ["python", "asyncio", "flask", "rest-api", "git", "linux", "sql", "algorithms"], ["developer"], 0.0),
    ("r09", "Москва\nMLOps-инженер\n\n2021 — н. в. — MLOps в телекоме: выкатка моделей, MLflow, мониторинг дрейфа, "
            "Kubernetes и Kubeflow, Docker. Spark для подготовки фич, Airflow. Python, Bash, Linux.\n"
            "2019 — 2021 — DevOps-инженер: Ansible, Terraform, CI/CD.",
     ["mlops", "kubernetes", "docker", "spark", "airflow", "python", "linux", "ci-cd"], ["devops"], 7.8),
    ("r10", "Самара\nFullstack-разработчик\n\nОпыт работы — 3 года.\n"
            "Бэк — Node.js (Express) на TypeScript, фронт — Vue 3 + Pinia, иногда Angular. HTML/CSS, адаптивная "
            "вёрстка. Базы — MySQL и Postgres. Docker Compose, nginx, Linux-сервера.",
     ["javascript", "typescript", "vue", "state-management", "angular", "html-css", "sql", "postgresql", "docker",
      "linux"], ["developer"], 3.0),
    ("r11", "Москва\nC# / .NET разработчик\n\n10.2019 — по настоящее время, производственная компания.\n"
            "ASP.NET Core, Entity Framework, MS SQL, очереди на RabbitMQ, юнит-тесты xUnit. Фронт — немного React. "
            "Работаю в команде из 8 человек, выступал на внутренних митапах.",
     ["csharp", "sql", "rabbitmq", "react"], ["developer"], 7.0),
    ("r12", "Томск\nComputer Vision Engineer\n\n2023 — н. в. — детекция дефектов на конвейере: PyTorch, YOLO, "
            "OpenCV, ONNX; разметка и аугментации. Numpy, статистика метрик качества.\n"
            "2021 — 2023 — инженер-исследователь в университете (CV, сегментация).",
     ["pytorch", "cv", "numpy", "statistics"], ["researcher"], 5.8),
    ("r13", "Краснодар\nТестировщик (manual QA)\n\nОпыт: 1 год 6 месяцев.\nФункциональное и регрессионное "
            "тестирование веба, тест-кейсы и чек-листы в TestIT, баг-репорты в Jira. Проверяю API в Postman, "
            "простые SQL-запросы, логи в Kibana. Начал изучать автотесты на питоне.",
     ["manual-testing", "test-design", "api-testing", "sql", "python"], ["tester"], 1.5),
    ("r14", "Москва\nTeam Lead backend\n\n2015 — н. в. — от разработчика до тимлида команды из 7 человек.\n"
            "Python (Django, DRF, Celery), PostgreSQL, ClickHouse, Redis, RabbitMQ. Найм, онбординг, менторство, "
            "планирование спринтов. Архитектурные ревью, высоконагруженные сервисы.",
     ["python", "django", "rest-api", "postgresql", "clickhouse", "redis", "rabbitmq"],
     ["developer", "team_lead", "mentor", "architect"], 11.8),
    ("r15", "Уфа\nAndroid-разработчик\n\n03.2022 — н. в. — Kotlin, Jetpack Compose, корутины, Retrofit (REST), "
            "Room. CI — GitHub Actions. Java — поддержка старого кода.",
     ["kotlin", "rest-api", "ci-cd", "java"], ["developer"], 4.6),
    ("r16", "Москва\nАналитик данных / BI\n\nОпыт 2 года: SQL (оконные функции), Python (pandas), дашборды в "
            "Power BI и DataLens, проверка гипотез, статистические тесты. ClickHouse и Greenplum.",
     ["sql", "python", "pandas", "statistics", "clickhouse"], ["analyst"], 2.0),
    ("r17", "Пермь\nDevSecOps\n\n2020 — н. в. — безопасная разработка: SAST/DAST в CI/CD, проверка зависимостей, "
            "харденинг Linux и Docker-образов, секреты в Vault, Kubernetes RBAC. OWASP ASVS, моделирование угроз.",
     ["ci-cd", "linux", "docker", "kubernetes", "owasp"], ["devops"], 6.8),
    ("r18", "Воронеж\nJunior frontend\n\nСтажировка 07.2025 — 12.2025 (6 месяцев), затем junior до сих пор.\n"
            "JavaScript, React, HTML и CSS, вебпак, немного TypeScript. Учусь писать тесты на Jest.",
     ["javascript", "react", "html-css", "vite-webpack", "typescript", "frontend-testing"], ["developer"], 1.3),
    ("r19", "Москва\nData Engineer\n\n2021 — 2026 — дата-инженер: Spark (PySpark), Airflow, Kafka, ClickHouse и "
            "Postgres, хранилище на Hadoop. Python, SQL, Docker, CI/CD.",
     ["spark", "airflow", "kafka", "clickhouse", "postgresql", "python", "sql", "docker", "ci-cd"],
     ["developer"], 5.0),
    ("r20", "Ростов-на-Дону\nPHP-разработчик\n\nОпыт работы 6 лет. Laravel и Symfony, MySQL, Redis, очереди, "
            "REST API для мобильных клиентов. Docker, Git, Linux. Немного Vue на фронте.",
     ["php", "sql", "redis", "rest-api", "docker", "git", "linux", "vue"], ["developer"], 6.0),
]


def build() -> dict:
    rows = [{"id": i, "text": HEAD + t, "gold": {"stack": sorted(set(s)), "roles": sorted(set(r)),
                                                  "experience_years": e}} for i, t, s, r, e in R]
    return {"name": "resume_synth", "date": "2026-10-09", "n": len(rows),
            "note": "синтетика, автор набора и разметки — модель (не люди, не эксперты); ПДн нет (плейсхолдеры)",
            "rows": rows}


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    d = build()
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"→ {OUT}: {d['n']} резюме")
