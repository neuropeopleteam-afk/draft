"""Направления каталога → запросы поиска hh.ru (профессиональная роль + слова в названии вакансии).

Один источник для «Рынка по hh.ru» (``market.ROLE_QUERY``), снимка рынка для индекса доверия, частот навыков
«Что сейчас просит рынок», таблицы спроса и корпуса проверки подбора (``tools/realdata/hh_plus.py``).

Профессиональные роли hh.ru (справочник ``GET /professional_roles``, раздел «Информационные технологии», 10.10.2026):
96 «Программист, разработчик», 124 «Тестировщик», 116 «Специалист по информационной безопасности», 165
«Дата-сайентист», 156 «BI-аналитик, аналитик данных», 160 «DevOps-инженер», 148 «Системный аналитик», 150
«Бизнес-аналитик», 114 «Системный инженер».

Четыре новых направления (devops, data_eng, mobile, analyst) — в каталоге продукта только при CATALOG_EXT_ENABLED
(ветка каталога); здесь они нужны для данных рынка и замеров и в интерфейс сами по себе не попадают.
"""
from __future__ import annotations

# Слова грейда в названии вакансии (поиск NAME:… и метка корпуса)
GRADE_WORDS = {"intern": ["стажер", "стажёр", "intern", "стажировка", "trainee"],
               "junior": ["junior", "джуниор", "младший"],
               "middle": ["middle", "мидл"],
               "senior": ["senior", "сеньор", "старший", "ведущий", "lead", "тимлид"]}

_MOBILE = ["android", "ios", "flutter", "react native", "мобильн", "mobile", "swift"]
_DATA_ENG = ["data engineer", "инженер данных", "дата-инженер", "dwh", "etl", "big data", "data platform",
             "hadoop", "spark"]

# direction → (роли hh.ru, слова в названии или None — роль узкая сама, слова-исключения в названии)
HH_DIRECTIONS: dict[str, dict] = {
    "backend": {"title": "Backend", "roles": ["96"],
                "words": ["backend", "бэкенд", "бекенд", "back-end", "python", "java", "golang", "go", "php",
                          "node.js", "c#", ".net", "kotlin", "scala", "ruby", "c++"],
                "not": ["frontend", "фронтенд", "fullstack", "full-stack", "android", "ios", "mobile", "мобильн",
                        "data engineer", "инженер данных", "devops"]},
    "frontend": {"title": "Frontend", "roles": ["96"],
                 "words": ["frontend", "фронтенд", "front-end", "react", "vue", "angular", "javascript", "typescript"],
                 "not": ["react native", "fullstack", "full-stack", "backend", "бэкенд"]},
    "qa": {"title": "QA", "roles": ["124"], "words": None, "not": []},
    "data_ml": {"title": "Data/ML", "roles": ["165", "96"],
                "words": ["data scientist", "ml", "machine learning", "дата-сайентист", "машинн", "nlp",
                          "computer vision", "llm", "data science"],
                "not": ["data engineer", "инженер данных", "devops"]},
    "security": {"title": "Информационная безопасность", "roles": ["116"], "words": None, "not": []},
    "devops": {"title": "DevOps / SRE", "roles": ["160"], "words": None, "not": []},
    "data_eng": {"title": "Инженер данных", "roles": ["96", "165", "156", "114"], "words": _DATA_ENG,
                 "not": ["devops"]},
    "mobile": {"title": "Мобильная разработка", "roles": ["96"], "words": _MOBILE, "not": []},
    "analyst": {"title": "Системный / бизнес-аналитик", "roles": ["148", "150"], "words": None, "not": []},
}
NEW_DIRECTIONS = ("devops", "data_eng", "mobile", "analyst")


def q(words: list[str]) -> str:
    """Список слов → выражение языка запросов hh.ru: (a OR "b c" OR …)."""
    return "(" + " OR ".join(f'"{w}"' if " " in w else w for w in words) + ")"


def search_text(direction: str, grade: str | None = None) -> str | None:
    """Текст запроса для направления (и слова грейда в названии, если grade задан)."""
    d = HH_DIRECTIONS[direction]
    parts = []
    if d["words"]:
        parts.append(f"NAME:{q(d['words'])}")
    if grade:
        parts.append(f"NAME:{q(GRADE_WORDS[grade])}")
    text = " AND ".join(parts)
    if d["not"] and text:
        text += f" NOT NAME:{q(d['not'])}"
    return text or None


def search_params(direction: str, grade: str | None, area: str, *, with_salary: bool = False,
                  experience: list[str] | None = None, per_page: int = 100) -> list[tuple[str, str]]:
    """Параметры GET /vacancies: роли, регион, свежие сначала; grade — слово грейда в названии."""
    p: list[tuple[str, str]] = []
    t = search_text(direction, grade)
    if t:
        p.append(("text", t))
    p += [("professional_role", r) for r in HH_DIRECTIONS[direction]["roles"]]
    p += [("area", area), ("per_page", str(per_page)), ("order_by", "publication_time")]
    if with_salary:
        p.append(("only_with_salary", "true"))
    p += [("experience", e) for e in experience or []]
    return p
