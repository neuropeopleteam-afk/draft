"""Каталог шире: 4 новых направления × 4 грейда = 16 категорий, стек-теги направлений

Revision ID: ce01
Revises: iv01 (голова integ/wave5 9494b88 на 11.10; при слиянии М5 перевешивает на последнюю голову по порядку слияния)
Create Date: 2026-10-10

Направления: devops «DevOps / SRE», data_eng «Инженер данных», mobile «Мобильная разработка», analyst «Системный /
бизнес-аналитик» (решение владельца 10.10, вариант «А»). Строки справочника есть в БД всегда, но API, опрос, разбор
потребности и подбор показывают их только при CATALOG_EXT_ENABLED и проверенном банке направления
(app/modules/catalog/ext.py; FTT.4 — уровень только по тесту).

Рыночные диапазоны — калькулятор зарплат Хабр Карьеры, тот же метод, что у остальных категорий (docs/SALARY_SOURCES.md):
«от» = p25, «до» = p75, медиана отдельно, округление до 5 000 ₽, на руки; несколько специализаций — среднее с весами по
числу анкет. Выгрузка 10.10.2026 (docs/data_habr_salary_raw_20261010_ext.json): DevOps / SRE = devops + sre,
инженер данных = data_engineer, мобильная разработка = mobileapp_developer, аналитик = systems_analyst +
business_analyst. Малые выборки (меньше 30 анкет) — подпись «ориентир, мало анкет» в docs.

Миграция идемпотентна (повтор не дублирует строки). Работает на SQLite и PostgreSQL 16.
"""
from collections.abc import Sequence
from datetime import date

from alembic import op
import sqlalchemy as sa

revision: str = "ce01"
down_revision: str | None = "iv01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (id, название, описание, язык фрагментов кода, порядок)
DIRECTIONS = [
    ("devops", "DevOps / SRE",
     "Эксплуатация и надёжность: Linux, контейнеры, Kubernetes, CI/CD, инфраструктура как код, мониторинг, инциденты",
     "bash", 6),
    ("data_eng", "Инженер данных",
     "Инженерия данных: SQL-аналитика, ETL/ELT, модели хранилищ, оркестрация, потоковая обработка, качество данных",
     "sql", 7),
    ("mobile", "Мобильная разработка",
     "Мобильные приложения: жизненный цикл, асинхронность, хранение, сеть, UI-потоки (Kotlin, Swift, JS/TS)",
     "kotlin", 8),
    ("analyst", "Системный / бизнес-аналитик",
     "Системный и бизнес-анализ: требования, SQL, BPMN/UML как текстовые модели, API-контракты, критерии приёмки",
     "sql", 9),
]
GRADE_TITLES = {"intern": "Стажёр", "junior": "Junior", "middle": "Middle", "senior": "Senior"}
MARKET_SOURCE = "Хабр Карьера, калькулятор зарплат (p25–p75)"
MARKET_SOURCE_INTERN = "Хабр Карьера, калькулятор зарплат, квалификация Intern (p25–p75)"  # как в ir01
MARKET_AS_OF = date(2026, 10, 10)
# (направление, грейд): (от = p25, до = p75, медиана, число анкет), ₽/мес на руки
MARKET = {
    ("devops", "intern"): (45000, 85000, 65000, 52),
    ("devops", "junior"): (85000, 170000, 115000, 227),
    ("devops", "middle"): (165000, 290000, 225000, 631),
    ("devops", "senior"): (290000, 465000, 365000, 300),
    ("data_eng", "intern"): (65000, 100000, 90000, 14),
    ("data_eng", "junior"): (95000, 175000, 135000, 58),
    ("data_eng", "middle"): (190000, 290000, 235000, 184),
    ("data_eng", "senior"): (320000, 435000, 360000, 79),
    ("mobile", "intern"): (40000, 120000, 85000, 14),
    ("mobile", "junior"): (65000, 115000, 90000, 46),
    ("mobile", "middle"): (165000, 310000, 225000, 292),
    ("mobile", "senior"): (275000, 455000, 370000, 283),
    ("analyst", "intern"): (50000, 100000, 65000, 166),
    ("analyst", "junior"): (75000, 140000, 100000, 561),
    ("analyst", "middle"): (140000, 250000, 190000, 1695),
    ("analyst", "senior"): (230000, 360000, 290000, 750),
}
# (id, название, вид, направление) — копия EXT_STACK из app/modules/catalog/ext.py (миграция не импортирует приложение)
STACK = [
    ("terraform", "Terraform и инфраструктура как код", "tool", "devops"),
    ("ansible", "Ansible", "tool", "devops"),
    ("helm", "Helm", "tool", "devops"),
    ("monitoring", "Мониторинг и алерты (Prometheus, Grafana)", "tool", "devops"),
    ("nginx", "Nginx и балансировка", "tool", "devops"),
    ("sre", "SRE: SLO, инциденты, дежурства", "practice", "devops"),
    ("networking", "Сети: DNS, маршрутизация, межсетевые фильтры", "practice", "devops"),
    ("cloud", "Облачные платформы", "tool", "devops"),
    ("etl", "ETL/ELT-конвейеры", "practice", "data_eng"),
    ("dwh", "Хранилища и модели данных (DWH, Data Vault, «звезда»)", "practice", "data_eng"),
    ("dbt", "dbt", "tool", "data_eng"),
    ("greenplum", "Greenplum", "db", "data_eng"),
    ("streaming", "Потоковая обработка (Flink, Kafka Streams)", "practice", "data_eng"),
    ("data-quality", "Качество данных", "practice", "data_eng"),
    ("android", "Android SDK", "framework", "mobile"),
    ("ios", "iOS SDK (UIKit)", "framework", "mobile"),
    ("swift", "Swift", "language", "mobile"),
    ("jetpack-compose", "Jetpack Compose", "framework", "mobile"),
    ("swiftui", "SwiftUI", "framework", "mobile"),
    ("flutter", "Flutter и Dart", "framework", "mobile"),
    ("react-native", "React Native", "framework", "mobile"),
    ("mobile-architecture", "Архитектура мобильных приложений (MVVM, MVI)", "practice", "mobile"),
    ("requirements", "Сбор и анализ требований", "practice", "analyst"),
    ("bpmn", "BPMN", "practice", "analyst"),
    ("uml", "UML (последовательности, активности, варианты использования)", "practice", "analyst"),
    ("user-stories", "User story и критерии приёмки", "practice", "analyst"),
    ("integrations", "Интеграции и контракты API", "practice", "analyst"),
    ("er-modeling", "Модели данных и ER-диаграммы", "practice", "analyst"),
]
STACK_SORT_FROM = 1000  # после базовых тегов (0002, rd01)

directions = sa.table(
    "directions", sa.column("id", sa.String), sa.column("title", sa.String), sa.column("description", sa.Text),
    sa.column("code_language", sa.String), sa.column("sort_order", sa.Integer),
)
categories = sa.table(
    "categories",
    sa.column("id", sa.String), sa.column("direction_id", sa.String), sa.column("grade_id", sa.String),
    sa.column("title", sa.String), sa.column("market_salary_from", sa.Integer), sa.column("market_salary_to", sa.Integer),
    sa.column("market_salary_median", sa.Integer), sa.column("market_sample_size", sa.Integer),
    sa.column("market_source", sa.String), sa.column("market_as_of", sa.Date),
)
stack_tags = sa.table(
    "stack_tags", sa.column("id", sa.String), sa.column("title", sa.String), sa.column("kind", sa.String),
    sa.column("direction_id", sa.String), sa.column("sort_order", sa.Integer),
)
IDS = [d[0] for d in DIRECTIONS]


def upgrade() -> None:
    conn = op.get_bind()
    have_d = {r[0] for r in conn.execute(sa.select(directions.c.id)).all()}
    rows = [dict(id=i, title=t, description=ds, code_language=c, sort_order=o)
            for i, t, ds, c, o in DIRECTIONS if i not in have_d]
    if rows:
        op.bulk_insert(directions, rows)
    titles = {d[0]: d[1] for d in DIRECTIONS}
    have_c = {r[0] for r in conn.execute(sa.select(categories.c.id)).all()}
    rows = [dict(id=f"{d}.{g}", direction_id=d, grade_id=g, title=f"{titles[d]} · {GRADE_TITLES[g]}",
                 market_salary_from=lo, market_salary_to=hi, market_salary_median=med, market_sample_size=n,
                 market_source=MARKET_SOURCE_INTERN if g == "intern" else MARKET_SOURCE, market_as_of=MARKET_AS_OF)
            for (d, g), (lo, hi, med, n) in MARKET.items() if f"{d}.{g}" not in have_c]
    if rows:
        op.bulk_insert(categories, rows)
    have_t = {r[0] for r in conn.execute(sa.select(stack_tags.c.id)).all()}
    rows = [dict(id=i, title=t, kind=k, direction_id=d, sort_order=STACK_SORT_FROM + n)
            for n, (i, t, k, d) in enumerate(STACK) if i not in have_t]
    if rows:
        op.bulk_insert(stack_tags, rows)


def downgrade() -> None:
    """Снимает строки справочника. Если в БД уже есть данные новых направлений (сессии теста, специализации,
    потребности, вакансии…), откат останавливается с перечнем таблиц: такие данные не удаляются молча."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cats = [f"{d}.{g}" for d in IDS for g in GRADE_TITLES]
    used = []
    for tbl in insp.get_table_names():
        if tbl in ("directions", "categories", "stack_tags"):
            continue
        for fk in insp.get_foreign_keys(tbl):
            ref = fk.get("referred_table")
            if ref not in ("directions", "categories") or len(fk.get("constrained_columns") or []) != 1:
                continue
            col = fk["constrained_columns"][0]
            values = IDS if ref == "directions" else cats
            n = conn.execute(sa.text(f'SELECT COUNT(*) FROM "{tbl}" WHERE "{col}" IN :v')
                             .bindparams(sa.bindparam("v", expanding=True)), {"v": values}).scalar()
            if n:
                used.append(f"{tbl}.{col}: {n}")
    if used:
        raise RuntimeError("Откат ce01 остановлен: есть данные новых направлений — " + "; ".join(used))
    op.execute(stack_tags.delete().where(stack_tags.c.id.in_([s[0] for s in STACK])))
    op.execute(categories.delete().where(categories.c.direction_id.in_(IDS)))
    op.execute(directions.delete().where(directions.c.id.in_(IDS)))
