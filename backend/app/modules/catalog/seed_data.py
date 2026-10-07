"""Справочник в коде (копия данных миграции 0002): нужен парсерам и сидированию без обращения к БД."""

DIRECTIONS: dict[str, str] = {
    "backend": "Backend",
    "frontend": "Frontend",
    "data_ml": "Data/ML",
    "qa": "QA",
    "security": "Информационная безопасность",
}
GRADES: dict[str, str] = {
    "junior": "Junior",
    "middle": "Middle",
    "senior": "Senior",
}
GRADE_LEVEL = {"junior": 1, "middle": 2, "senior": 3}

# id → (название, вид, направление | None — общий блок)
STACK: dict[str, tuple[str, str, str | None]] = {
    "algorithms": ("Алгоритмы и структуры данных", "practice", None),
    "sql": ("SQL", "language", None),
    "http": ("HTTP и веб", "practice", None),
    "git": ("Git", "tool", None),
    "linux": ("Linux", "tool", None),
    "docker": ("Docker", "tool", None),
    "python": ("Python", "language", 'backend'),
    "fastapi": ("FastAPI", "framework", 'backend'),
    "django": ("Django", "framework", 'backend'),
    "flask": ("Flask", "framework", 'backend'),
    "asyncio": ("asyncio", "framework", 'backend'),
    "postgresql": ("PostgreSQL", "db", 'backend'),
    "redis": ("Redis", "db", 'backend'),
    "kafka": ("Kafka", "tool", 'backend'),
    "rabbitmq": ("RabbitMQ", "tool", 'backend'),
    "rest-api": ("REST API", "practice", 'backend'),
    "grpc": ("gRPC", "framework", 'backend'),
    "go": ("Go", "language", 'backend'),
    "java": ("Java", "language", 'backend'),
    "kotlin": ("Kotlin", "language", 'backend'),
    "csharp": ("C#", "language", 'backend'),
    "php": ("PHP", "language", 'backend'),
    "kubernetes": ("Kubernetes", "tool", None),
    "javascript": ("JavaScript", "language", 'frontend'),
    "typescript": ("TypeScript", "language", 'frontend'),
    "react": ("React", "framework", 'frontend'),
    "vue": ("Vue", "framework", 'frontend'),
    "angular": ("Angular", "framework", 'frontend'),
    "nextjs": ("Next.js", "framework", 'frontend'),
    "html-css": ("HTML и CSS", "language", 'frontend'),
    "tailwind": ("Tailwind CSS", "framework", 'frontend'),
    "state-management": ("Управление состоянием (Redux, Zustand)", "framework", 'frontend'),
    "vite-webpack": ("Сборка (Vite, Webpack)", "tool", 'frontend'),
    "frontend-testing": ("Тесты фронтенда (Vitest, Jest)", "tool", 'frontend'),
    "a11y": ("Доступность (a11y)", "practice", 'frontend'),
    "pandas": ("pandas", "framework", 'data_ml'),
    "numpy": ("NumPy", "framework", 'data_ml'),
    "scikit-learn": ("scikit-learn", "framework", 'data_ml'),
    "pytorch": ("PyTorch", "framework", 'data_ml'),
    "statistics": ("Статистика и A/B-тесты", "practice", 'data_ml'),
    "spark": ("Spark", "tool", 'data_ml'),
    "airflow": ("Airflow", "tool", 'data_ml'),
    "clickhouse": ("ClickHouse", "db", 'data_ml'),
    "nlp": ("NLP", "practice", 'data_ml'),
    "cv": ("Компьютерное зрение", "practice", 'data_ml'),
    "mlops": ("MLOps", "practice", 'data_ml'),
    "test-design": ("Тест-дизайн", "practice", 'qa'),
    "manual-testing": ("Ручное тестирование", "practice", 'qa'),
    "pytest": ("pytest", "framework", 'qa'),
    "selenium": ("Selenium", "tool", 'qa'),
    "playwright": ("Playwright", "tool", 'qa'),
    "api-testing": ("Тестирование API", "practice", 'qa'),
    "load-testing": ("Нагрузочное тестирование", "practice", 'qa'),
    "ci-cd": ("CI/CD", "tool", 'qa'),
    "allure": ("Allure", "tool", 'qa'),
    "owasp": ("OWASP Top 10", "practice", 'security'),
    "pentest": ("Пентест веб-приложений", "practice", 'security'),
    "network-security": ("Сетевая безопасность", "practice", 'security'),
    "cryptography": ("Криптография", "practice", 'security'),
    "siem-soc": ("SIEM и SOC", "tool", 'security'),
    "reverse-engineering": ("Реверс-инжиниринг", "practice", 'security'),
    "forensics": ("Форензика", "practice", 'security'),
    "burp-suite": ("Burp Suite", "tool", 'security'),
    "ctf": ("CTF", "practice", 'security'),
}


def category_title(category_id: str | None) -> str:
    """«backend.middle» → «Backend · Middle»."""
    if not category_id or "." not in category_id:
        return category_id or "—"
    d, g = category_id.split(".", 1)
    return f"{DIRECTIONS.get(d, d)} · {GRADES.get(g, g)}"


def tag_direction(tag: str) -> str | None:
    return STACK[tag][2] if tag in STACK else None


def tag_title(tag: str) -> str:
    return STACK[tag][0] if tag in STACK else tag
