"""Подтверждённый фреймворк или профильный инструмент подтверждает базовый/смежный навык (W1, флаг MATCH_IMPLIED).

Задание теста по FastAPI или Django решается только кодом на Python, по React или Vue — кодом на JavaScript, по
Spring — на Java, по PostgreSQL или ClickHouse — запросами SQL, по Docker и Kubernetes — командами Linux. Поэтому навык
фреймворка или экосистемы, подтверждённый заданиями теста (T1, доля ≥ 0,5), засчитывается как подтверждение связанного
навыка при расчёте покрытия обязательных навыков потребности (ranking.stack_part, must_have.coverage).

Балл производного подтверждения — балл исходного навыка × ``IMPLIED_FACTOR`` (0,9): прямое подтверждение навыка всегда
не хуже производного. В объяснении подборки такой навык подписан «Подтверждён через <навык>» (T1, производное).
"""
from __future__ import annotations

import os

from app.modules.profiles.facts import skill_confirmed

IMPLIED_FACTOR = 0.9

# подтверждённый навык (T1) → (базовые и тесно связанные навыки той же экосистемы, которые он подтверждает)
IMPLIES: dict[str, tuple[str, ...]] = {
    # Python и веб-бэкенд
    "fastapi": ("python", "flask", "rest-api", "http"),
    "django": ("python", "flask", "rest-api", "sql", "php", "javascript", "typescript", "react", "html-css"),
    "flask": ("python", "rest-api", "http"),
    "asyncio": ("python",),
    "pandas": ("python", "statistics"),
    "numpy": ("python",),
    "scikit-learn": ("python", "numpy", "pandas", "statistics"),
    "pytorch": ("python", "numpy", "cv", "scikit-learn"),
    "nlp": ("python", "pytorch", "cv"),
    "mlops": ("python", "fastapi", "kafka", "cloud", "monitoring", "redis", "clickhouse", "dwh", "etl", "data-quality"),
    "pytest": ("python", "allure", "test-design"),
    "airflow": ("python", "etl", "dwh"),
    # JavaScript / TypeScript / Frontend
    "react": ("javascript", "nextjs", "html-css", "tailwind", "state-management"),
    "vue": ("javascript", "html-css"),
    "nextjs": ("javascript", "react", "html-css"),
    "angular": ("typescript", "javascript", "html-css"),
    "typescript": ("javascript", "vue", "angular"),
    "html-css": ("tailwind",),
    "state-management": ("javascript", "react", "vue"),
    "vite-webpack": ("javascript", "html-css", "php", "java"),
    "frontend-testing": ("playwright", "selenium", "javascript"),
    "react-native": ("javascript", "mobile-architecture", "flutter"),
    # Java / Kotlin / C# / Go / Mobile
    "spring": ("java", "rest-api"),
    "java": ("spring", "csharp", "grpc", "kotlin", "monitoring", "integrations"),
    "kotlin": ("java", "android", "jetpack-compose"),
    "android": ("kotlin", "java", "jetpack-compose", "mobile-architecture"),
    "jetpack-compose": ("kotlin", "android"),
    "swift": ("ios", "swiftui"),
    "ios": ("swift", "swiftui", "mobile-architecture"),
    "swiftui": ("swift", "ios"),
    "mobile-architecture": ("flutter", "react-native", "state-management", "jetpack-compose", "swiftui", "html-css", "api-testing", "monitoring"),
    "flutter": ("mobile-architecture",),
    "go": ("grpc", "rest-api", "monitoring", "clickhouse", "integrations"),
    # SQL / Data Engineering / DWH
    "postgresql": ("sql", "greenplum"),
    "clickhouse": ("sql", "greenplum", "dwh"),
    "greenplum": ("sql", "postgresql", "dwh"),
    "dbt": ("sql", "dwh", "etl"),
    "dwh": ("sql", "etl", "dbt", "greenplum", "clickhouse", "monitoring", "cloud"),
    "etl": ("sql", "dwh", "dbt", "airflow", "pandas", "flask"),
    "spark": ("python", "sql", "etl", "dwh", "kafka", "greenplum", "clickhouse", "java"),
    "streaming": ("kafka", "etl", "rabbitmq"),
    "data-quality": ("sql", "etl", "dwh", "pytest"),
    # Linux / DevOps / SRE
    "docker": ("linux",),
    "kubernetes": ("linux", "docker", "helm"),
    "helm": ("kubernetes", "docker", "linux"),
    "ansible": ("linux", "ci-cd"),
    "terraform": ("cloud", "linux", "ci-cd"),
    "ci-cd": ("git", "docker", "ansible", "terraform"),
    "sre": ("monitoring", "linux", "ansible", "helm", "terraform", "cloud", "redis", "clickhouse", "siem-soc", "owasp", "cryptography", "rabbitmq", "javascript", "html-css"),
    "monitoring": ("sre", "linux"),
    "networking": ("linux", "nginx", "network-security"),
    "cloud": ("linux", "docker", "terraform"),
    # QA
    "test-design": ("manual-testing", "allure", "requirements"),
    "api-testing": ("http", "rest-api", "integrations", "kafka", "go", "monitoring"),
    "load-testing": ("monitoring", "http", "rest-api", "go"),
    "playwright": ("typescript", "javascript", "allure", "frontend-testing", "selenium"),
    "selenium": ("java", "python", "csharp", "android", "allure", "frontend-testing"),
    # ИБ (Security)
    "owasp": ("pentest", "burp-suite", "network-security", "http", "java", "php", "csharp", "javascript", "requirements"),
    "network-security": ("networking", "linux", "siem-soc", "ansible"),
    "forensics": ("reverse-engineering", "ctf", "siem-soc", "linux"),
    "siem-soc": ("linux", "networking", "monitoring", "ansible", "redis", "rabbitmq", "clickhouse"),
    # Системный и бизнес-анализ
    "requirements": ("user-stories", "bpmn", "uml"),
    "integrations": ("rest-api", "http", "api-testing", "rabbitmq", "java", "csharp"),
    "er-modeling": ("sql", "dwh", "etl", "greenplum", "clickhouse", "pandas"),
}


def enabled() -> bool:
    return os.environ.get("MATCH_IMPLIED", "1").strip().lower() not in ("0", "false", "no", "off", "")


def implied_by(skills_t1: dict, tag: str):
    """Подтверждённый фреймворк/инструмент, который подтверждает tag (лучший по баллу), или None."""
    if not enabled():
        return None
    best = None
    for src, targets in IMPLIES.items():
        if tag not in targets:
            continue
        f = skills_t1.get(src)
        if skill_confirmed(f) and (best is None or f.value.get("score", 0) > best[1].value.get("score", 0)):
            best = (src, f)
    return best


def implied_score(skills_t1: dict, tag: str) -> float:
    hit = implied_by(skills_t1, tag)
    return round(IMPLIED_FACTOR * float(hit[1].value.get("score", 0)), 3) if hit else 0.0
