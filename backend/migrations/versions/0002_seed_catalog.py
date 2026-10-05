"""Справочник MVP: 5 направлений × 3 грейда = 15 категорий, стек-теги для опроса

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05

Рыночные диапазоны категорий (₽/мес) — предварительный ориентир команды, уточняется по открытым
данным. Работодатель видит только этот диапазон, а не скрытый минимум кандидата.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIRECTIONS = [
    ("backend", "Backend", "Серверная разработка: API, базы данных, очереди, производительность", "python", 1),
    ("frontend", "Frontend", "Клиентская веб-разработка: интерфейсы, состояние, сборка, доступность", "typescript", 2),
    ("data_ml", "Data/ML", "Анализ данных и машинное обучение: подготовка данных, модели, метрики", "python", 3),
    ("qa", "QA", "Тестирование: тест-дизайн, автоматизация, API и нагрузочное тестирование", "python", 4),
    ("security", "Информационная безопасность", "Анализ защищённости, уязвимости, мониторинг и реагирование", "python", 5),
]

GRADES = [
    ("junior", "Junior", 1, "Решает типовые задачи под присмотром; опыт до 1–2 лет"),
    ("middle", "Middle", 2, "Самостоятельно ведёт задачи и модули; понимает компромиссы"),
    ("senior", "Senior", 3, "Проектирует решения, отвечает за качество и развитие команды"),
]

# (направление, грейд): (от, до) ₽/мес
MARKET = {
    ("backend", "junior"): (80_000, 150_000),
    ("backend", "middle"): (180_000, 300_000),
    ("backend", "senior"): (300_000, 450_000),
    ("frontend", "junior"): (70_000, 130_000),
    ("frontend", "middle"): (160_000, 280_000),
    ("frontend", "senior"): (280_000, 420_000),
    ("data_ml", "junior"): (90_000, 160_000),
    ("data_ml", "middle"): (200_000, 330_000),
    ("data_ml", "senior"): (330_000, 500_000),
    ("qa", "junior"): (60_000, 110_000),
    ("qa", "middle"): (130_000, 220_000),
    ("qa", "senior"): (220_000, 330_000),
    ("security", "junior"): (80_000, 140_000),
    ("security", "middle"): (180_000, 300_000),
    ("security", "senior"): (300_000, 450_000),
}

# (id, название, вид, направление|None=общий блок)
STACK = [
    ("algorithms", "Алгоритмы и структуры данных", "practice", None),
    ("sql", "SQL", "language", None),
    ("http", "HTTP и веб", "practice", None),
    ("git", "Git", "tool", None),
    ("linux", "Linux", "tool", None),
    ("docker", "Docker", "tool", None),
    ("python", "Python", "language", "backend"),
    ("fastapi", "FastAPI", "framework", "backend"),
    ("django", "Django", "framework", "backend"),
    ("flask", "Flask", "framework", "backend"),
    ("asyncio", "asyncio", "framework", "backend"),
    ("postgresql", "PostgreSQL", "db", "backend"),
    ("redis", "Redis", "db", "backend"),
    ("kafka", "Kafka", "tool", "backend"),
    ("rabbitmq", "RabbitMQ", "tool", "backend"),
    ("rest-api", "REST API", "practice", "backend"),
    ("grpc", "gRPC", "framework", "backend"),
    ("go", "Go", "language", "backend"),
    ("java", "Java", "language", "backend"),
    ("javascript", "JavaScript", "language", "frontend"),
    ("typescript", "TypeScript", "language", "frontend"),
    ("react", "React", "framework", "frontend"),
    ("vue", "Vue", "framework", "frontend"),
    ("angular", "Angular", "framework", "frontend"),
    ("nextjs", "Next.js", "framework", "frontend"),
    ("html-css", "HTML и CSS", "language", "frontend"),
    ("tailwind", "Tailwind CSS", "framework", "frontend"),
    ("state-management", "Управление состоянием (Redux, Zustand)", "framework", "frontend"),
    ("vite-webpack", "Сборка (Vite, Webpack)", "tool", "frontend"),
    ("frontend-testing", "Тесты фронтенда (Vitest, Jest)", "tool", "frontend"),
    ("a11y", "Доступность (a11y)", "practice", "frontend"),
    ("pandas", "pandas", "framework", "data_ml"),
    ("numpy", "NumPy", "framework", "data_ml"),
    ("scikit-learn", "scikit-learn", "framework", "data_ml"),
    ("pytorch", "PyTorch", "framework", "data_ml"),
    ("statistics", "Статистика и A/B-тесты", "practice", "data_ml"),
    ("spark", "Spark", "tool", "data_ml"),
    ("airflow", "Airflow", "tool", "data_ml"),
    ("clickhouse", "ClickHouse", "db", "data_ml"),
    ("nlp", "NLP", "practice", "data_ml"),
    ("cv", "Компьютерное зрение", "practice", "data_ml"),
    ("mlops", "MLOps", "practice", "data_ml"),
    ("test-design", "Тест-дизайн", "practice", "qa"),
    ("manual-testing", "Ручное тестирование", "practice", "qa"),
    ("pytest", "pytest", "framework", "qa"),
    ("selenium", "Selenium", "tool", "qa"),
    ("playwright", "Playwright", "tool", "qa"),
    ("api-testing", "Тестирование API", "practice", "qa"),
    ("load-testing", "Нагрузочное тестирование", "practice", "qa"),
    ("ci-cd", "CI/CD", "tool", "qa"),
    ("allure", "Allure", "tool", "qa"),
    ("owasp", "OWASP Top 10", "practice", "security"),
    ("pentest", "Пентест веб-приложений", "practice", "security"),
    ("network-security", "Сетевая безопасность", "practice", "security"),
    ("cryptography", "Криптография", "practice", "security"),
    ("siem-soc", "SIEM и SOC", "tool", "security"),
    ("reverse-engineering", "Реверс-инжиниринг", "practice", "security"),
    ("forensics", "Форензика", "practice", "security"),
    ("burp-suite", "Burp Suite", "tool", "security"),
    ("ctf", "CTF", "practice", "security"),
]

directions = sa.table(
    "directions",
    sa.column("id", sa.String),
    sa.column("title", sa.String),
    sa.column("description", sa.Text),
    sa.column("code_language", sa.String),
    sa.column("sort_order", sa.Integer),
)
grades = sa.table(
    "grades", sa.column("id", sa.String), sa.column("title", sa.String), sa.column("level", sa.Integer),
    sa.column("description", sa.Text),
)
categories = sa.table(
    "categories",
    sa.column("id", sa.String),
    sa.column("direction_id", sa.String),
    sa.column("grade_id", sa.String),
    sa.column("title", sa.String),
    sa.column("market_salary_from", sa.Integer),
    sa.column("market_salary_to", sa.Integer),
)
stack_tags = sa.table(
    "stack_tags",
    sa.column("id", sa.String),
    sa.column("title", sa.String),
    sa.column("kind", sa.String),
    sa.column("direction_id", sa.String),
    sa.column("sort_order", sa.Integer),
)


def upgrade() -> None:
    op.bulk_insert(
        directions,
        [dict(id=i, title=t, description=d, code_language=c, sort_order=o) for i, t, d, c, o in DIRECTIONS],
    )
    op.bulk_insert(grades, [dict(id=i, title=t, level=lv, description=d) for i, t, lv, d in GRADES])
    titles = {d[0]: d[1] for d in DIRECTIONS}
    gtitles = {g[0]: g[1] for g in GRADES}
    op.bulk_insert(
        categories,
        [
            dict(
                id=f"{d}.{g}",
                direction_id=d,
                grade_id=g,
                title=f"{titles[d]} · {gtitles[g]}",
                market_salary_from=lo,
                market_salary_to=hi,
            )
            for (d, g), (lo, hi) in MARKET.items()
        ],
    )
    op.bulk_insert(
        stack_tags,
        [dict(id=i, title=t, kind=k, direction_id=d, sort_order=n) for n, (i, t, k, d) in enumerate(STACK)],
    )


def downgrade() -> None:
    op.execute(stack_tags.delete())
    op.execute(categories.delete())
    op.execute(grades.delete())
    op.execute(directions.delete())
