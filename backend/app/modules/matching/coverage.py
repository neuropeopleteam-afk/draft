"""Explain nearest MVP category without pretending to test an unsupported profession."""
import re

from app.modules.catalog.seed_data import DIRECTIONS

ROLES = (
    ("devops", "DevOps / SRE", r"\bdevops\b|\bsre\b", "backend",
     "Linux, HTTP, SQL и общие принципы серверной разработки",
     "эксплуатация Kubernetes, IaC, облака, отказоустойчивость и on-call"),
    ("mobile", "Мобильная разработка", r"\bandroid\b|\bios\b|\bswift\b|мобильн\w*\s+разработ", "frontend",
     "алгоритмы, HTTP, клиентская логика и общие принципы интерфейсов",
     "Android SDK, iOS SDK, Swift, Compose, жизненный цикл и публикация приложений"),
    ("1c", "Разработка 1С", r"(?<!\w)1[сc](?!\w)", "backend",
     "алгоритмы, SQL и общие принципы серверной разработки",
     "платформа 1С, конфигурации, управляемые формы и бухгалтерский учёт"),
    ("gamedev", "Разработка игр", r"\bunity\b|\bunreal\b|\bgamedev\b|геймдев|разработ\w*\s+игр", "frontend",
     "алгоритмы и общие принципы клиентской разработки",
     "Unity, Unreal, игровой цикл, графика и физика"),
    ("analytics", "Аналитика", r"аналитик\w*\s+(?:данных|продукт|бизнес|систем)|\bdata analyst\b|\bdata\s*[-–]?\s*аналитик\b|\bbusiness analyst\b"
     r"|бизнес[- ]?аналитик|системн\w*\s+аналитик", "data_ml",
     "SQL, статистика и работа с данными",
     "предметная область, бизнес-анализ, BPMN и специализированные BI-инструменты"),
)


_OWN_ANALYST = re.compile(r"бизнес|систем|business|system", re.I)


def _first_role(text: str):
    """Первая профессия вне базового каталога в заголовке/первых строках → (совпадение, строка ROLES) или None."""
    # Profession is decided from the title/first lines, not from incidental SDK mentions.
    head = text[:400]
    if re.search(r"\bqa\b|\bsdet\b|тестировщик|тестирован", head.split("\n")[0], re.I):
        return None
    # Несколько ролей в заголовке («Бизнес-аналитик / аналитик 1С») — берём названную первой (И18)
    hits = [(m, r) for r in ROLES if (m := re.search(r[2], head, re.I))]
    return min(hits, key=lambda h: h[0].start()) if hits else None


def _own_direction(role: str, quote: str) -> str | None:
    """Направление расширения каталога для профессии, если оно видно (CATALOG_EXT_ENABLED и проверенный банк)."""
    from app.modules.catalog.ext import COVERAGE_ROLE_DIRECTION, is_visible

    d = COVERAGE_ROLE_DIRECTION.get(role)
    if not d or not is_visible(d):
        return None
    if role == "analytics" and not _OWN_ANALYST.search(quote):
        return None  # аналитик данных / продуктовый аналитик — по-прежнему ближайшая Data/ML
    return d


def coverage(text: str) -> dict | None:
    hit = _first_role(text)
    if not hit:
        return None
    m, (role, title, pattern, nearest, tested, untested) = hit
    if _own_direction(role, m.group(0)):
        return None  # своё направление каталога: частичного соответствия нет (own_direction)
    return {"role": role, "title": title, "nearest_direction": nearest,
            "nearest_title": DIRECTIONS[nearest], "supported": False,
            "tested": tested, "not_tested": untested,
            "message": f"Отдельной категории «{title}» пока нет. Ближайшая — {DIRECTIONS[nearest]}. "
                       "Это частичное соответствие, а не подтверждение профессионального грейда.",
            "evidence": {"start": m.start(), "end": m.end(), "quote": text[m.start():m.end()],
                         "source": "rules"}}


def own_direction(text: str) -> dict | None:
    """Профессия, у которой с расширением каталога есть своё направление (DevOps / SRE, мобильная разработка,
    системный / бизнес-аналитик): {"direction", "evidence"}; без флага или без проверенного банка — None."""
    hit = _first_role(text)
    if not hit:
        return None
    m, row = hit
    d = _own_direction(row[0], m.group(0))
    if not d:
        return None
    return {"direction": d, "evidence": {"start": m.start(), "end": m.end(), "quote": text[m.start():m.end()],
                                         "source": "rules", "basis": "title"}}
