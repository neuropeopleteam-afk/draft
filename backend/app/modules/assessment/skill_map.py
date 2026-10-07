"""Навыки семейств банка (skills в YAML) → стек-теги справочника платформы.

Факты T1 «навык подтверждён тестом» пишутся по стек-тегам справочника — по ним работодатель ищет и
ранжирует кандидатов. Авторы банка используют свои, более мелкие названия навыков; здесь — сведение.
Сначала ищется пара (направление семейства, навык), затем навык без направления. Навык без сопоставления
в факты не попадает (остаётся в результате сессии).
"""
from __future__ import annotations

_GLOBAL: dict[str, str] = {
    # общий блок
    "algorithms": "algorithms", "binary_search": "algorithms", "heap": "algorithms", "data_structures": "algorithms",
    "complexity": "algorithms", "sorting": "algorithms", "stack": "algorithms", "queue": "algorithms",
    "intervals": "algorithms", "ordered_dict": "algorithms", "boundary_conditions": "algorithms",
    "branching": "git", "caching": "algorithms",  # branching — только в семействах про ветки git
    "sql": "sql", "joins": "sql", "window_functions": "sql", "having": "sql", "subqueries": "sql",
    "aggregation": "sql", "null_semantics": "sql", "three_valued_logic": "sql", "indexes": "sql",
    "query_planning": "sql", "databases": "sql", "reporting": "sql", "date_ranges": "sql", "sqlite": "sql",
    "http": "http", "rest_api": "http", "api_design": "http", "idempotency": "http",
    "git": "git", "history_rewriting": "git",
    "linux": "linux", "shell": "linux", "bash": "linux", "awk": "linux", "permissions": "linux",
    "text_processing": "linux", "exit_codes": "linux", "logs": "linux",
    "python": "python", "asyncio": "asyncio", "concurrency": "asyncio", "race_conditions": "asyncio",
    "javascript": "javascript", "typescript": "typescript", "react": "react",
    "pytest": "pytest", "statistics": "statistics", "mlops": "mlops", "cryptography": "cryptography",
    # технологические семейства банка (06.10): Docker — общий блок, остальные — backend
    "docker": "docker", "dockerfile": "docker", "docker_compose": "docker", "docker_build_cache": "docker",
    "docker_networking": "docker", "docker_volumes": "docker",
}

_BY_DIRECTION: dict[str, dict[str, str]] = {
    "backend": {
        "fastapi": "fastapi", "postgresql": "postgresql", "databases": "postgresql", "asyncio": "asyncio",
        "threads": "asyncio", "messaging": "rabbitmq", "webhooks": "rest-api", "idempotency": "rest-api",
        "payments": "rest-api", "rate_limiting": "rest-api", "distributed_systems": "rest-api",
        "reliability": "rest-api", "caching": "redis", "decimal": "python", "money": "python",
        "numeric_precision": "python", "dict": "python", "functions": "python", "state": "python",
        "sorting": "python", "algorithms": "python", "testing": "pytest",
        # технологические семейства банка (06.10); «concurrency»/«race_conditions» в них не используются
        "go": "go", "go_slices": "go", "go_defer": "go", "panic_recover": "go", "goroutines": "go",
        "go_channels": "go", "data_races": "go", "sync_mutex": "go", "go_context": "go",
        "java": "java", "java_collections": "java", "equals_hashcode": "java", "java_streams": "java",
        "java_concurrency": "java", "completable_future": "java", "java_exceptions": "java",
        "django": "django", "django_orm": "django", "django_forms": "django", "django_transactions": "django",
        "kafka": "kafka", "kafka_consumer_groups": "kafka", "kafka_partitions": "kafka",
        "kafka_delivery": "kafka", "kafka_offsets": "kafka", "kafka_outbox": "kafka",
    },
    "frontend": {
        "arrays": "javascript", "async_await": "javascript", "closures": "javascript", "operators": "javascript",
        "promises": "javascript", "scope": "javascript", "timers": "javascript", "race_conditions": "javascript",
        "core_web_vitals": "vite-webpack", "web_performance": "vite-webpack", "ux": "a11y",
        "testing": "frontend-testing", "accessibility": "a11y", "aria": "a11y", "screen_readers": "a11y",
        "focus_management": "a11y", "keyboard": "a11y", "html": "html-css",
        "state_management": "state-management", "bundlers": "vite-webpack", "build": "vite-webpack",
    },
    "data_ml": {
        "ab_testing": "statistics", "hypothesis_testing": "statistics", "p_value": "statistics",
        "descriptive_statistics": "statistics", "quartiles": "statistics", "outliers": "statistics",
        "analytics": "pandas", "aggregation": "pandas", "csv": "pandas", "data_cleaning": "pandas",
        "missing_values": "pandas", "data_processing": "pandas", "deduplication": "pandas", "etl": "airflow",
        "iterators": "python", "generators": "python",
        "categorical_encoding": "scikit-learn", "classification_metrics": "scikit-learn",
        "confusion_matrix": "scikit-learn", "cross_validation": "scikit-learn", "data_leakage": "scikit-learn",
        "f1": "scikit-learn", "feature_engineering": "scikit-learn", "group_kfold": "scikit-learn",
        "model_evaluation": "scikit-learn", "precision_recall": "scikit-learn", "preprocessing": "scikit-learn",
        "threshold": "scikit-learn", "time_split": "scikit-learn", "validation": "scikit-learn",
        "reproducibility": "mlops", "training_serving_skew": "mlops", "ml_monitoring": "mlops",
        "data_drift": "mlops", "psi": "mlops", "ml_systems": "mlops",
        "llm": "nlp", "rag": "nlp", "chunking": "nlp", "ranking": "nlp",
        "time_series": "pandas", "slowly_changing_data": "sql", "window_functions": "sql",
    },
    "qa": {
        "test_review": "test-design", "false_positive": "test-design", "defect_localization": "test-design",
        "test_architecture": "test-design", "smoke_testing": "test-design", "incident_analysis": "test-design",
        "data_testing": "test-design", "data_quality": "test-design",
        "fixtures": "pytest", "parametrize": "pytest", "unittest_mock": "pytest", "async_testing": "pytest",
        "jest": "frontend-testing", "ci": "ci-cd", "bash": "ci-cd", "exit_codes": "ci-cd",
        "test_design": "test-design", "boundary_value_analysis": "test-design",
        "equivalence_partitioning": "test-design", "pairwise_testing": "test-design",
        "combinatorial_testing": "test-design", "risk_based_testing": "test-design",
        "regression_strategy": "test-design", "defect_management": "test-design", "triage": "test-design",
        "api_testing": "api-testing", "contract_testing": "api-testing",
        "performance_testing": "load-testing", "load_testing": "load-testing",
    },
    "security": {
        "secure_code_review": "owasp", "input_validation": "owasp", "output_encoding": "owasp", "csrf": "owasp",
        "cors": "owasp", "cookies": "owasp", "authorization": "owasp", "access_control": "owasp",
        "ownership": "owasp", "parameterized_queries": "owasp", "sql": "owasp", "templates": "owasp",
        "serialization": "owasp", "path_normalization": "owasp", "containment": "owasp",
        "token_validation": "owasp", "session_lifecycle": "owasp", "secure_defaults": "owasp",
        "secure_configuration": "owasp", "configuration": "owasp", "secrets_management": "owasp",
        "trust_boundaries": "owasp", "threat_modeling": "owasp", "secure_design": "owasp",
        "dependencies": "owasp", "patch_management": "owasp", "versioning": "owasp", "release_policy": "owasp",
        "http": "network-security",
        "aead": "cryptography", "hmac": "cryptography", "nonce_uniqueness": "cryptography",
        "password_hashing": "cryptography", "scrypt": "cryptography", "salts": "cryptography",
        "secure_randomness": "cryptography", "key_lifecycle": "cryptography",
        "constant_time_comparison": "cryptography",
        "incident_response": "siem-soc", "monitoring": "siem-soc", "logging": "siem-soc",
        "security_logging": "siem-soc", "vulnerability_triage": "siem-soc", "cvss": "siem-soc",
        "risk_prioritization": "siem-soc", "prioritization": "siem-soc", "evidence_preservation": "forensics",
        "recovery": "siem-soc", "communication": "siem-soc", "data_minimization": "owasp",
    },
}


def to_stack_tags(direction: str, skills: list[str]) -> list[str]:
    """Стек-теги справочника для навыков семейства (без повторов, в порядке появления)."""
    out: list[str] = []
    local = _BY_DIRECTION.get(direction, {})
    for s in skills:
        tag = local.get(s) or _GLOBAL.get(s)
        if tag and tag not in out:
            out.append(tag)
    return out


# Технологические теги (07.10, решение Р2): семейства с такими навыками выдаются только кандидату, у которого тег
# есть в заявленном стеке опроса (T0). Иначе Python-бэкендер получал бы задания по Go и Java, и это занижало бы θ.
# Заявленный стек выбирает вопросы, но в ранжировании не участвует (решение 06.10: T0 не учитывается).
STACK_GATED: frozenset[str] = frozenset({"go", "java", "django", "kafka", "docker"})


def stack_gate(direction: str, skills: list[str]) -> frozenset[str]:
    """Стек-теги, без которых семейство кандидату не выдаётся (подмножество STACK_GATED; пусто — семейство для всех)."""
    return frozenset(t for t in to_stack_tags(direction, skills) if t in STACK_GATED)


def allowed_for_stack(direction: str, skills: list[str], stack: list[str] | set[str] | None) -> bool:
    """Можно ли выдать семейство кандидату с заявленным стеком ``stack`` (нет стека — только общие семейства)."""
    return stack_gate(direction, skills) <= set(stack or ())
