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
    # лёгкие семейства у порога Junior (07.10)
    "sql_aggregates": "sql", "sql_null": "sql", "filesystem": "linux",
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
        # семейства 07.10: Django — миграции и сигналы, Java — память и GC, Python — коллекции
        "django_signals": "django", "django_migrations": "django", "java_memory": "java", "java_gc": "java",
        "python_collections": "python",
    },
    "frontend": {
        "arrays": "javascript", "async_await": "javascript", "closures": "javascript", "operators": "javascript",
        "promises": "javascript", "scope": "javascript", "timers": "javascript", "race_conditions": "javascript",
        "core_web_vitals": "vite-webpack", "web_performance": "vite-webpack", "ux": "a11y",
        "testing": "frontend-testing", "accessibility": "a11y", "aria": "a11y", "screen_readers": "a11y",
        "focus_management": "a11y", "keyboard": "a11y", "html": "html-css",
        "state_management": "state-management", "bundlers": "vite-webpack", "build": "vite-webpack",
        "js_types": "javascript",
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
        "descriptive_stats": "statistics",
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
        "secrets_handling": "owasp",
    },
}

# Направления расширения каталога (волна 7, app/modules/catalog/ext.py). Сведение действует только для семейств своих
# направлений — у базовых направлений ничего не меняется. Навык без сопоставления ищется в _GLOBAL (sql, linux, docker…).
_BY_DIRECTION.update({
    "devops": {
        "kubernetes": "kubernetes", "k8s": "kubernetes", "pods": "kubernetes", "deployments": "kubernetes",
        "probes": "kubernetes", "resources": "kubernetes", "kubernetes_manifests": "kubernetes",
        "rbac": "kubernetes", "scheduling": "kubernetes", "services": "kubernetes", "ingress": "kubernetes",
        "helm": "helm", "helm_charts": "helm", "templating": "helm",
        "terraform": "terraform", "iac": "terraform", "infrastructure_as_code": "terraform", "state": "terraform",
        "ansible": "ansible", "configuration_management": "ansible", "idempotency": "ansible",
        "ci": "ci-cd", "ci_cd": "ci-cd", "cicd": "ci-cd", "pipelines": "ci-cd", "github_actions": "ci-cd",
        "gitlab_ci": "ci-cd", "deployment": "ci-cd", "release": "ci-cd", "artifacts": "ci-cd", "rollback": "ci-cd",
        "monitoring": "monitoring", "prometheus": "monitoring", "promql": "monitoring", "alerting": "monitoring",
        "metrics": "monitoring", "observability": "monitoring", "grafana": "monitoring", "logging": "monitoring",
        "tracing": "monitoring",
        "sre": "sre", "slo": "sre", "sli": "sre", "error_budget": "sre", "incident_response": "sre",
        "incidents": "sre", "postmortem": "sre", "on_call": "sre", "capacity_planning": "sre", "reliability": "sre",
        "networking": "networking", "dns": "networking", "tcp": "networking", "tcp_ip": "networking",
        "routing": "networking", "firewall": "networking", "iptables": "networking", "subnets": "networking",
        "tls": "networking", "network_debugging": "networking",
        "nginx": "nginx", "load_balancing": "nginx", "reverse_proxy": "nginx",
        "cloud": "cloud", "iam": "cloud", "object_storage": "cloud", "autoscaling": "cloud",
        "systemd": "linux", "processes": "linux", "signals": "linux", "cron": "linux", "disk": "linux",
        "containers": "docker", "images": "docker", "secrets": "kubernetes", "configmaps": "kubernetes",
    },
    "data_eng": {
        "etl": "etl", "elt": "etl", "pipelines": "etl", "data_pipelines": "etl", "incremental_load": "etl",
        "idempotency": "etl", "backfill": "etl", "deduplication": "etl", "cdc": "etl", "upsert": "etl",
        "merge": "etl", "late_data": "etl",
        "dwh": "dwh", "data_modeling": "dwh", "dimensional_modeling": "dwh", "star_schema": "dwh",
        "data_vault": "dwh", "scd": "dwh", "slowly_changing_dimensions": "dwh", "slowly_changing_data": "dwh",
        "partitioning": "dwh", "data_marts": "dwh", "normalization": "dwh", "lakehouse": "dwh",
        "dbt": "dbt", "greenplum": "greenplum", "mpp": "greenplum", "distribution_keys": "greenplum",
        "airflow": "airflow", "orchestration": "airflow", "dags": "airflow", "scheduling": "airflow",
        "spark": "spark", "pyspark": "spark", "shuffles": "spark", "joins_distributed": "spark",
        "streaming": "streaming", "stream_processing": "streaming", "windowing": "streaming",
        "watermarks": "streaming", "exactly_once": "streaming", "flink": "streaming",
        "kafka": "kafka", "kafka_partitions": "kafka", "kafka_offsets": "kafka", "kafka_consumer_groups": "kafka",
        "clickhouse": "clickhouse", "columnar_storage": "clickhouse",
        "data_quality": "data-quality", "data_validation": "data-quality", "data_contracts": "data-quality",
        "data_testing": "data-quality", "anomaly_detection": "data-quality", "null_semantics": "sql",
        "python": "python", "pandas": "pandas", "parquet": "dwh", "file_formats": "dwh",
    },
    "mobile": {
        "android": "android", "android_lifecycle": "android", "activity_lifecycle": "android",
        "fragments": "android", "intents": "android", "services": "android", "permissions": "android",
        "workmanager": "android", "room": "android",
        "ios": "ios", "uikit": "ios", "ios_lifecycle": "ios", "view_controllers": "ios", "app_lifecycle": "ios",
        "swift": "swift", "optionals": "swift", "arc": "swift", "memory_management": "swift",
        "retain_cycles": "swift", "swift_concurrency": "swift", "gcd": "swift", "actors": "swift",
        "swiftui": "swiftui", "combine": "swiftui",
        "kotlin": "kotlin", "coroutines": "kotlin", "kotlin_coroutines": "kotlin", "flow": "kotlin",
        "null_safety": "kotlin", "kotlin_collections": "kotlin",
        "jetpack_compose": "jetpack-compose", "compose": "jetpack-compose", "recomposition": "jetpack-compose",
        "state_hoisting": "jetpack-compose",
        "flutter": "flutter", "dart": "flutter", "widgets": "flutter",
        "react_native": "react-native",
        "javascript": "javascript", "typescript": "typescript", "async_await": "javascript", "promises": "javascript",
        "event_loop": "javascript",
        "architecture": "mobile-architecture", "mvvm": "mobile-architecture", "mvi": "mobile-architecture",
        "clean_architecture": "mobile-architecture", "dependency_injection": "mobile-architecture",
        "state_management": "mobile-architecture", "navigation": "mobile-architecture",
        "lifecycle": "mobile-architecture", "ui_threading": "mobile-architecture", "main_thread": "mobile-architecture",
        "offline_first": "mobile-architecture", "caching": "mobile-architecture", "storage": "mobile-architecture",
        "persistence": "mobile-architecture",
        "networking": "rest-api", "rest_api": "rest-api", "retries": "rest-api", "pagination": "rest-api",
        "push_notifications": "android", "testing": "frontend-testing", "ui_testing": "frontend-testing",
    },
    "analyst": {
        "requirements": "requirements", "requirements_analysis": "requirements", "elicitation": "requirements",
        "functional_requirements": "requirements", "non_functional_requirements": "requirements", "nfr": "requirements",
        "traceability": "requirements", "srs": "requirements", "ambiguity": "requirements",
        "stakeholders": "requirements", "prioritization": "requirements", "moscow": "requirements",
        "bpmn": "bpmn", "business_processes": "bpmn", "process_modeling": "bpmn", "gateways": "bpmn",
        "uml": "uml", "sequence_diagrams": "uml", "activity_diagrams": "uml", "state_machines": "uml",
        "use_cases": "uml", "class_diagrams": "uml", "plantuml": "uml",
        "user_stories": "user-stories", "acceptance_criteria": "user-stories", "gherkin": "user-stories",
        "bdd": "user-stories", "invest": "user-stories", "edge_cases": "user-stories",
        "integrations": "integrations", "api_contracts": "integrations", "api_design": "integrations",
        "openapi": "integrations", "json_schema": "integrations", "message_contracts": "integrations",
        "idempotency": "integrations", "error_handling": "integrations", "versioning": "integrations",
        "async_integration": "integrations", "webhooks": "integrations",
        "er_modeling": "er-modeling", "data_modeling": "er-modeling", "erd": "er-modeling",
        "normalization": "er-modeling", "keys": "er-modeling", "cardinality": "er-modeling",
        "rest_api": "rest-api", "http": "http", "postgresql": "postgresql", "statistics": "statistics",
        "test_design": "test-design", "boundary_value_analysis": "test-design",
    },
})


_BY_DIRECTION["devops"].update({"exit_codes": "linux", "quoting": "linux", "rolling_update": "kubernetes"})
_BY_DIRECTION["mobile"].update({"mobile_networking": "rest-api",
    "closures": "swift", "timers": "javascript", "authentication": "rest-api", "background_execution":
    "mobile-architecture", "ui_lists": "mobile-architecture", "deep_links": "mobile-architecture",
    "concurrency": "mobile-architecture", "migrations": "mobile-architecture", "sqlite": "mobile-architecture"})
# Префиксы навыков у направлений расширения каталога: «k8s_qos» → kubernetes, «mobile_threading» → мобильная архитектура
_PREFIX_BY_DIRECTION: dict[str, tuple[tuple[str, str], ...]] = {
    "devops": (("k8s_", "kubernetes"), ("kubernetes_", "kubernetes"), ("helm_", "helm"), ("terraform_", "terraform"),
               ("ansible_", "ansible"), ("ci_", "ci-cd"), ("mon_", "monitoring"), ("prometheus_", "monitoring"),
               ("net_", "networking"), ("sre_", "sre"), ("bash_", "linux"), ("linux_", "linux"),
               ("nginx_", "nginx"), ("cloud_", "cloud"), ("docker_", "docker")),
    "data_eng": (("etl_", "etl"), ("dwh_", "dwh"), ("dbt_", "dbt"), ("spark_", "spark"), ("kafka_", "kafka"),
                 ("airflow_", "airflow"), ("dq_", "data-quality"), ("data_quality_", "data-quality"),
                 ("stream_", "streaming"), ("streaming_", "streaming"), ("greenplum_", "greenplum"),
                 ("clickhouse_", "clickhouse")),
    "mobile": (("mobile_", "mobile-architecture"), ("android_", "android"), ("ios_", "ios"), ("swift_", "swift"),
               ("swiftui_", "swiftui"), ("kotlin_", "kotlin"), ("compose_", "jetpack-compose"),
               ("flutter_", "flutter"), ("dart_", "flutter"), ("rn_", "react-native")),
    "analyst": (("req_", "requirements"), ("requirements_", "requirements"), ("bpmn_", "bpmn"), ("uml_", "uml"),
                ("story_", "user-stories"), ("api_", "integrations"), ("integration_", "integrations"),
                ("er_", "er-modeling")),
}


def _by_prefix(direction: str, skill: str) -> str | None:
    for pre, tag in _PREFIX_BY_DIRECTION.get(direction, ()):
        if skill.startswith(pre):
            return tag
    return None


def to_stack_tags(direction: str, skills: list[str]) -> list[str]:
    """Стек-теги справочника для навыков семейства (без повторов, в порядке появления)."""
    out: list[str] = []
    local = _BY_DIRECTION.get(direction, {})
    for s in skills:
        tag = local.get(s) or _GLOBAL.get(s) or _by_prefix(direction, s)
        if tag and tag not in out:
            out.append(tag)
    return out


# Технологические теги (07.10, решение Р2): семейства с такими навыками выдаются только кандидату, у которого тег
# есть в заявленном стеке опроса (T0). Иначе Python-бэкендер получал бы задания по Go и Java, и это занижало бы θ.
# Заявленный стек выбирает вопросы, но в ранжировании не участвует (решение 06.10: T0 не учитывается).
STACK_GATED: frozenset[str] = frozenset({"go", "java", "django", "kafka", "docker"})


# Для направлений расширения каталога часть «технологических» тегов — ядро профессии, а не выбор стека: Docker у
# DevOps / SRE и Kafka у инженера данных выдаются всем кандидатам направления.
UNGATED_BY_DIRECTION: dict[str, frozenset[str]] = {"devops": frozenset({"docker"}), "data_eng": frozenset({"kafka"})}


def stack_gate(direction: str, skills: list[str]) -> frozenset[str]:
    """Стек-теги, без которых семейство кандидату не выдаётся (подмножество STACK_GATED; пусто — семейство для всех)."""
    free = UNGATED_BY_DIRECTION.get(direction, frozenset())
    return frozenset(t for t in to_stack_tags(direction, skills) if t in STACK_GATED and t not in free)


def allowed_for_stack(direction: str, skills: list[str], stack: list[str] | set[str] | None) -> bool:
    """Можно ли выдать семейство кандидату с заявленным стеком ``stack`` (нет стека — только общие семейства)."""
    return stack_gate(direction, skills) <= set(stack or ())
