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
    ("analytics", "Аналитика", r"аналитик\w*\s+(?:данных|продукт|бизнес|систем)|\bdata analyst\b|\bdata\s*[-–]?\s*аналитик\b|\bbusiness analyst\b", "data_ml",
     "SQL, статистика и работа с данными",
     "предметная область, бизнес-анализ, BPMN и специализированные BI-инструменты"),
)


def coverage(text: str) -> dict | None:
    # Profession is decided from the title/first lines, not from incidental SDK mentions.
    head = text[:400]
    if re.search(r"\bqa\b|\bsdet\b|тестировщик|тестирован", head.split("\n")[0], re.I):
        return None
    for role, title, pattern, nearest, tested, untested in ROLES:
        m = re.search(pattern, head, re.I)
        if m:
            return {"role": role, "title": title, "nearest_direction": nearest,
                    "nearest_title": DIRECTIONS[nearest], "supported": False,
                    "tested": tested, "not_tested": untested,
                    "message": f"Отдельной категории «{title}» пока нет. Ближайшая — {DIRECTIONS[nearest]}. "
                               "Это частичное соответствие, а не подтверждение профессионального грейда.",
                    "evidence": {"start": m.start(), "end": m.end(), "quote": text[m.start():m.end()],
                                 "source": "rules"}}
    return None
