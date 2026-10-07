"""Справочник в коде (копия данных миграции 0002): нужен парсерам и сидированию без обращения к БД."""

DIRECTIONS: dict[str, str] = {
    "backend": "Backend",
    "frontend": "Frontend",
    "data_ml": "Data/ML",
    "qa": "QA",
    "security": "Информационная безопасность",
}
# Грейды снизу вверх. «Стажёр» (intern) — ниже Junior, для начинающих участников ФСП (решение владельца 07.10).
# Единственный источник правды о наборе грейдов на стороне платформы: другие модули импортируют отсюда,
# «ровно три грейда» нигде не предполагается.
GRADES: dict[str, str] = {
    "intern": "Стажёр",
    "junior": "Junior",
    "middle": "Middle",
    "senior": "Senior",
}
GRADE_LEVEL = {"intern": 0, "junior": 1, "middle": 2, "senior": 3}
GRADE_ORDER: tuple[str, ...] = tuple(GRADES)  # ("intern", "junior", "middle", "senior")
# Пороги на шкале θ: θ ≥ cut[g] → не ниже грейда g. Между Junior, Middle и Senior — одна единица шкалы; порог Стажёра
# −1,75 выбран симуляцией теста по заранее заданному правилу (app/modules/validation/intern_cut.py, блок на /validation):
# из кандидатов −1,5/−1,75/−2,0/−2,25 только он даёт ложные подтверждения ≤ 10 % и ложные отказы ≤ 20 % на банке
# с лёгкими семействами; на текущем банке у него же минимальная сумма ошибок.
GRADE_CUTS = {"intern": -1.75, "junior": -1.0, "middle": 0.0, "senior": 1.0}
# Стартовая оценка θ адаптивного теста по заявленному грейду (середина полосы грейда, у Стажёра — чуть выше порога)
GRADE_START_THETA = {"intern": -1.25, "junior": -0.5, "middle": 0.5, "senior": 1.3}
# Подсказка грейда по стажу (лет): до полугода — Стажёр, до 1,5 — Junior, до 4,5 — Middle, дальше — Senior
GRADE_BY_EXPERIENCE: tuple[tuple[float, str], ...] = ((0.5, "intern"), (1.5, "junior"), (4.5, "middle"))
GRADE_EXPERIENCE_TEXT = {"intern": "без опыта или до полугода", "junior": "до 1,5 лет опыта", "middle": "1,5–4,5 года",
                         "senior": "от 4,5 лет"}


def grade_by_experience(years: float | None) -> str | None:
    """Грейд-подсказка по стажу в годах (None — стаж неизвестен)."""
    if years is None:
        return None
    for limit, g in GRADE_BY_EXPERIENCE:
        if years < limit:
            return g
    return GRADE_ORDER[-1]


def grade_above(grade: str) -> str | None:
    i = GRADE_ORDER.index(grade)
    return GRADE_ORDER[i + 1] if i + 1 < len(GRADE_ORDER) else None


def grade_below(grade: str) -> str | None:
    i = GRADE_ORDER.index(grade)
    return GRADE_ORDER[i - 1] if i > 0 else None

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
