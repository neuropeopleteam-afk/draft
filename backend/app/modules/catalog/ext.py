"""Расширение каталога: 4 новых направления (DevOps / SRE, инженер данных, мобильная разработка, системный и
бизнес-аналитик) за флагом CATALOG_EXT_ENABLED (по умолчанию выключен).

Правило организаторов FTT.4: уровень присваивается только по тесту, поэтому направление без проверенного банка
заданий не показывается. Направление расширения видно, только если одновременно:
1. включён флаг ``CATALOG_EXT_ENABLED``;
2. банк прошёл проверку по направлению — «список из банка»: ``directions_verified`` в манифесте синхронизации
   ``backend/assessment_bank/BANK_SYNC.json`` (пишет tools/sync_bank.py) И то же правило на загруженном реестре
   семейств (``bank_ready``): не меньше ``catalog_ext_min_families`` семейств направления (без канареек) и каждый
   грейд Стажёр…Senior покрыт не меньше чем ``catalog_ext_min_per_grade`` семействами;
3. направление не исключено списком ``CATALOG_EXT_DIRECTIONS`` (пусто — все готовые).

Без флага всё как до расширения: строки справочника (миграция ce01) лежат в БД, но API, опрос, разбор потребности
и подбор их не видят. Данные направлений (стек-теги, синонимы, ключевые слова) — здесь, отдельно от базового
справочника seed_data.py, чтобы выключенный флаг не менял поведение ни в одном месте.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

from app.core.config import get_settings

BASE_DIRECTIONS: tuple[str, ...] = ("backend", "frontend", "data_ml", "qa", "security")

# id → название (как в миграции ce01)
EXT_DIRECTIONS: dict[str, str] = {
    "devops": "DevOps / SRE",
    "data_eng": "Инженер данных",
    "mobile": "Мобильная разработка",
    "analyst": "Системный / бизнес-аналитик",
}
# Короткие подписи для автоимени потребности («DevOps · Middle — Terraform, Kubernetes»)
EXT_SHORT_TITLES: dict[str, str] = {"devops": "DevOps", "data_eng": "Инженер данных", "mobile": "Mobile",
                                    "analyst": "Аналитик"}
EXT_DESCRIPTIONS: dict[str, str] = {
    "devops": "Эксплуатация и надёжность: Linux, контейнеры, Kubernetes, CI/CD, инфраструктура как код, мониторинг, инциденты",
    "data_eng": "Инженерия данных: SQL-аналитика, ETL/ELT, модели хранилищ, оркестрация, потоковая обработка, качество данных",
    "mobile": "Мобильные приложения: жизненный цикл, асинхронность, хранение, сеть, UI-потоки (Kotlin, Swift, JS/TS)",
    "analyst": "Системный и бизнес-анализ: требования, SQL, BPMN/UML как текстовые модели, API-контракты, критерии приёмки",
}
# Язык фрагментов кода в заданиях направления (directions.code_language)
EXT_CODE_LANGUAGE: dict[str, str] = {"devops": "bash", "data_eng": "sql", "mobile": "kotlin", "analyst": "sql"}
EXT_SORT_ORDER: dict[str, int] = {"devops": 6, "data_eng": 7, "mobile": 8, "analyst": 9}

# Стек-теги направлений расширения: id → (название, вид, направление). Общий блок (Linux, Docker, SQL, Git, HTTP,
# Kubernetes) и теги других направлений не дублируются — они показываются в опросе через EXT_RELATED_TAGS.
EXT_STACK: dict[str, tuple[str, str, str]] = {
    # DevOps / SRE
    "terraform": ("Terraform и инфраструктура как код", "tool", "devops"),
    "ansible": ("Ansible", "tool", "devops"),
    "helm": ("Helm", "tool", "devops"),
    "monitoring": ("Мониторинг и алерты (Prometheus, Grafana)", "tool", "devops"),
    "nginx": ("Nginx и балансировка", "tool", "devops"),
    "sre": ("SRE: SLO, инциденты, дежурства", "practice", "devops"),
    "networking": ("Сети: DNS, маршрутизация, межсетевые фильтры", "practice", "devops"),
    "cloud": ("Облачные платформы", "tool", "devops"),
    # Инженер данных
    "etl": ("ETL/ELT-конвейеры", "practice", "data_eng"),
    "dwh": ("Хранилища и модели данных (DWH, Data Vault, «звезда»)", "practice", "data_eng"),
    "dbt": ("dbt", "tool", "data_eng"),
    "greenplum": ("Greenplum", "db", "data_eng"),
    "streaming": ("Потоковая обработка (Flink, Kafka Streams)", "practice", "data_eng"),
    "data-quality": ("Качество данных", "practice", "data_eng"),
    # Мобильная разработка
    "android": ("Android SDK", "framework", "mobile"),
    "ios": ("iOS SDK (UIKit)", "framework", "mobile"),
    "swift": ("Swift", "language", "mobile"),
    "jetpack-compose": ("Jetpack Compose", "framework", "mobile"),
    "swiftui": ("SwiftUI", "framework", "mobile"),
    "flutter": ("Flutter и Dart", "framework", "mobile"),
    "react-native": ("React Native", "framework", "mobile"),
    "mobile-architecture": ("Архитектура мобильных приложений (MVVM, MVI)", "practice", "mobile"),
    # Системный / бизнес-аналитик
    "requirements": ("Сбор и анализ требований", "practice", "analyst"),
    "bpmn": ("BPMN", "practice", "analyst"),
    "uml": ("UML (последовательности, активности, варианты использования)", "practice", "analyst"),
    "user-stories": ("User story и критерии приёмки", "practice", "analyst"),
    "integrations": ("Интеграции и контракты API", "practice", "analyst"),
    "er-modeling": ("Модели данных и ER-диаграммы", "practice", "analyst"),
}

# Теги базового справочника, которые показываются в опросе направления расширения (вместе с общим блоком):
# инженеру данных — Spark и Airflow (они в Data/ML), мобильному разработчику — Kotlin (Backend) и т. п.
EXT_RELATED_TAGS: dict[str, tuple[str, ...]] = {
    "devops": ("ci-cd", "python", "go", "postgresql", "redis", "kafka"),
    "data_eng": ("python", "spark", "airflow", "kafka", "clickhouse", "postgresql", "pandas"),
    "mobile": ("kotlin", "javascript", "typescript", "rest-api", "frontend-testing"),
    "analyst": ("rest-api", "postgresql", "statistics", "test-design"),
}

# Синонимы для разбора текста (как STACK_ALIASES словаря): нижний регистр, границы слова проверяются регулярным
# выражением. Действуют только для видимых направлений расширения.
EXT_ALIASES: dict[str, list[str]] = {
    "terraform": ["terraform", "terragrunt", "pulumi", "infrastructure as code", "инфраструктура как код", "iac"],
    "ansible": ["ansible", "playbook"],
    "helm": ["helm"],
    "monitoring": ["prometheus", "grafana", "zabbix", "alertmanager", "victoriametrics", "observability",
                   "наблюдаемост"],
    "nginx": ["nginx", "haproxy", "envoy", "балансировщик", "load balancer", "балансировк нагрузки"],
    "sre": ["slo", "sli", "error budget", "on-call", "дежурств", "постмортем", "postmortem", "site reliability"],
    "networking": ["dns", "iptables", "nftables", "маршрутизация трафика", "сетевая маршрутизац", "vlan", "bgp", "ospf",
                   "модель osi"],
    "cloud": ["aws", "gcp", "azure", "yandex cloud", "яндекс облак", "openstack", "vk cloud", "облачные платформ",
              "облачных платформ", "облачной инфраструктур", "облачная инфраструктур"],
    "etl": ["etl", "elt", "пайплайн данных", "пайплайны данных", "data pipeline", "конвейер данных", "конвейеры данных"],
    "dwh": ["dwh", "data warehouse", "хранилище данных", "хранилищ данных", "data vault", "star schema", "схема звезда",
            "kimball", "data lake", "lakehouse", "витрин данных", "витрины данных"],
    "dbt": ["dbt"],
    "greenplum": ["greenplum"],
    "streaming": ["flink", "kafka streams", "spark streaming", "потоковая обработка", "потоковой обработк",
                  "stream processing"],
    "data-quality": ["data quality", "качество данных", "качества данных", "great expectations", "data contract"],
    "android": ["android", "андроид"],
    "ios": ["ios", "uikit"],
    "swift": ["swift"],
    "jetpack-compose": ["jetpack compose", "compose ui"],
    "swiftui": ["swiftui"],
    "flutter": ["flutter", "dart"],
    "react-native": ["react native", "react-native"],
    "mobile-architecture": ["mvvm", "mvi", "viper", "clean architecture"],
    "requirements": ["сбор требований", "сбора требований", "анализ требований", "анализа требований",
                     "управление требованиями", "функциональные требования", "нефункциональные требования",
                     "написание технических заданий", "составление технических заданий", "написание тз",
                     "подготовка тз", "srs"],
    "bpmn": ["bpmn", "моделирование бизнес-процессов", "моделирования бизнес-процессов", "нотаци бизнес-процесс"],
    "uml": ["uml", "sequence diagram", "диаграмм последовательност", "use case диаграмм", "диаграмм вариантов использования",
            "диаграмм прецедентов", "plantuml"],
    "user-stories": ["user story", "user stories", "пользовательские истории", "критерии приёмки", "критерии приемки",
                     "acceptance criteria"],
    "integrations": ["проектирование интеграц", "интеграционн взаимодейств", "json schema", "asyncapi", "wsdl", "soap",
                     "контракт api", "контракты api", "проектирование api"],
    "er-modeling": ["er-диаграмм", "er диаграмм", "erd", "нормальные формы", "логическая модель данных",
                    "логической модели данных", "концептуальная модель данных"],
}
# Синонимы, которые в базовом словаре вели к тегу другого направления, а у расширения — свой тег (React Native не React)
EXT_SHADOWS: dict[str, str] = {"react-native": "react"}

# Ключевые слова направления в тексте вакансии/резюме (как DIRECTION_KEYWORDS словаря, подстроки нижнего регистра)
EXT_DIRECTION_KEYWORDS: dict[str, list[str]] = {
    "devops": ["devops", "девопс", "sre", "site reliability", "platform engineer", "инженер инфраструктур",
               "инженер эксплуатац", "администратор linux"],
    "data_eng": ["data engineer", "дата-инженер", "дата инженер", "инженер данных", "инженер по данным",
                 "dwh-разработ", "etl-разработ", "разработчик dwh", "разработчик etl"],
    "mobile": ["мобильный разработчик", "мобильного разработчика", "мобильной разработк", "мобильная разработк",
               "мобильных приложений", "мобильного приложения", "мобильные приложения", "мобильное приложение",
               "mobile developer", "mobile engineer", "mobile-разработ", "android", "андроид", "ios-разработ",
               "ios developer", "ios engineer", "swift", "flutter", "react native"],
    "analyst": ["системный аналитик", "системного аналитика", "бизнес-аналитик", "бизнес аналитик", "business analyst",
                "system analyst", "systems analyst", "аналитик требований", "аналитик-проектировщик"],
}
# Ключевые слова базовых направлений, которые с видимым направлением расширения ведут на него (а не в ближайшую
# категорию): направление расширения → {базовое направление: слова}
EXT_TAKES_KEYWORDS: dict[str, dict[str, tuple[str, ...]]] = {"data_eng": {"data_ml": ("data engineer",)}}

# Профессии, которые до расширения вели в ближайшую категорию (matching/coverage.py), → направление расширения
COVERAGE_ROLE_DIRECTION: dict[str, str] = {"devops": "devops", "mobile": "mobile", "analytics": "analyst"}

# Подписи модельных данных (демо-кандидаты новых направлений)
MODEL_LABEL = "модель, не люди"

GRADE_IDS: tuple[str, ...] = ("intern", "junior", "middle", "senior")
# Уровни выше Senior (банк feat/bank-ext, schema.Grade): присваиваются только с флагом GRADES_EXT_ENABLED
TOP_GRADE_IDS: tuple[str, ...] = ("lead", "principal")


def grades_ext_on() -> bool:
    """Включены ли уровни Lead/Principal (флаг GRADES_EXT_ENABLED; без поля в настройках — выключены)."""
    return bool(getattr(get_settings(), "grades_ext_enabled", False))


def in_active_pool(spec) -> bool:
    """Участвует ли семейство банка в тесте при текущих флагах.

    Семейства только уровней Lead/Principal (в ``target_grades`` нет ни одного из Стажёр…Senior) без флага
    GRADES_EXT_ENABLED не выдаются и не считаются «проверяемыми навыками» — тест для 4 уровней остаётся прежним.
    """
    tg = set(getattr(spec, "target_grades", None) or ())
    if not tg or tg & set(GRADE_IDS):
        return True
    return grades_ext_on()


def active_specs(specs):
    """Фильтр ``in_active_pool`` для коллекции семейств (load_specs().values())."""
    return [s for s in specs if in_active_pool(s)]
BANK_SYNC = Path(__file__).resolve().parents[3] / "assessment_bank" / "BANK_SYNC.json"


def _manifest_verified() -> tuple[str, ...] | None:
    """«Список из банка»: directions_verified манифеста синхронизации (None — ключа нет, старый манифест)."""
    try:
        data = json.loads(BANK_SYNC.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    v = data.get("directions_verified")
    return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else None


def readiness_rule(specs, min_families: int, min_per_grade: int) -> dict[str, dict]:
    """Готовность банка по направлениям расширения: число семейств и покрытие грейдов (то же правило — в sync_bank)."""
    out: dict[str, dict] = {}
    for d in EXT_DIRECTIONS:
        # семейства направления без канареек, нацеленные хотя бы на один из уровней Стажёр…Senior
        fams = [s for s in specs if s.direction == d and not getattr(s, "canary", False)
                and set(s.target_grades or ()) & set(GRADE_IDS)]
        per_grade = {g: sum(1 for s in fams if g in (s.target_grades or ())) for g in GRADE_IDS}
        ok = len(fams) >= min_families and all(n >= min_per_grade for n in per_grade.values())
        out[d] = {"families": len(fams), "per_grade": per_grade, "ready": ok}
    return out


@lru_cache(maxsize=4)
def _bank_readiness(min_families: int, min_per_grade: int) -> dict[str, dict]:
    try:
        from assessment_bank import load_specs
        specs = list(load_specs().values())
    except Exception:  # noqa: BLE001 — нет банка (заглушка теста) — направления расширения не готовы
        specs = []
    rule = readiness_rule(specs, min_families, min_per_grade)
    listed = _manifest_verified()
    for d, r in rule.items():
        r["in_manifest"] = listed is None or d in listed
        r["ready"] = r["ready"] and r["in_manifest"]
    return rule


def bank_readiness() -> dict[str, dict]:
    s = get_settings()
    return _bank_readiness(s.catalog_ext_min_families, s.catalog_ext_min_per_grade)


def bank_ready() -> tuple[str, ...]:
    """Направления расширения, чей банк прошёл проверку (без учёта флага)."""
    s = get_settings()
    forced = [x.strip() for x in (s.catalog_ext_force_ready or "").split(",") if x.strip()]
    if forced:  # только тесты и локальная проверка интерфейса до готовности банка; на стенде не задавать
        return tuple(d for d in EXT_DIRECTIONS if d in forced)
    return tuple(d for d, r in bank_readiness().items() if r["ready"])


def enabled() -> bool:
    return bool(get_settings().catalog_ext_enabled)


def visible_ext() -> tuple[str, ...]:
    """Видимые направления расширения: флаг включён, банк готов, направление не исключено списком."""
    s = get_settings()
    if not s.catalog_ext_enabled:
        return ()
    allow = {x.strip() for x in (s.catalog_ext_directions or "").split(",") if x.strip()}
    return tuple(d for d in bank_ready() if not allow or d in allow)


def visible_directions() -> tuple[str, ...]:
    """Все видимые направления: 5 базовых + видимые направления расширения (в порядке каталога)."""
    return BASE_DIRECTIONS + visible_ext()


def is_visible(direction: str | None) -> bool:
    return direction in BASE_DIRECTIONS or direction in visible_ext()


def hidden_ext() -> tuple[str, ...]:
    """Направления расширения, скрытые сейчас (флаг выключен или банк не готов)."""
    vis = set(visible_ext())
    return tuple(d for d in EXT_DIRECTIONS if d not in vis)


def visible_stack() -> dict[str, tuple[str, str, str]]:
    """Стек-теги видимых направлений расширения."""
    vis = set(visible_ext())
    return {t: v for t, v in EXT_STACK.items() if v[2] in vis}


def direction_title(direction: str | None) -> str:
    from app.modules.catalog.seed_data import DIRECTIONS

    if not direction:
        return "—"
    return DIRECTIONS.get(direction) or EXT_DIRECTIONS.get(direction) or direction


def meta() -> dict:
    """Блок «catalog» для /api/meta: видимые направления — интерфейс строит по ним выбор направления."""
    return {"ext_enabled": enabled(), "directions": list(visible_directions()), "ext": list(visible_ext()),
            "ext_titles": {d: EXT_DIRECTIONS[d] for d in visible_ext()}, "model_label": MODEL_LABEL}


def reset_cache() -> None:
    """Сброс кэша готовности (после синхронизации банка и в тестах)."""
    _bank_readiness.cache_clear()


# ------------------------------------------------------------------ тип параметра API «направление»
# Все 9 направлений в схеме OpenAPI; скрытое сейчас направление расширения (флаг выключен или банк не проверен)
# отклоняется валидацией — 422, как прежде для любого неизвестного направления.
from typing import Annotated, Literal  # noqa: E402

from pydantic import AfterValidator  # noqa: E402

DirectionLiteral = Literal["backend", "frontend", "data_ml", "qa", "security", "devops", "data_eng", "mobile", "analyst"]


def _check_visible(v: str | None) -> str | None:
    if v is not None and not is_visible(v):
        raise ValueError("Направление пока недоступно: банк заданий направления не прошёл проверку или расширение "
                         "каталога выключено")
    return v


DirectionId = Annotated[DirectionLiteral, AfterValidator(_check_visible)]
