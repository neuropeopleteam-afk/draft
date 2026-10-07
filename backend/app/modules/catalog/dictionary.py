"""Словари для разбора текста без LLM: синонимы стек-тегов, роли, софт-скиллы, признаки грейда и направления.

Используются в двух местах: структурирование потребности работодателя и разбор резюме кандидата.
Ключи стек-тегов совпадают с идентификаторами справочника (миграция 0002).
"""
import re

# id стек-тега → синонимы (нижний регистр; границы слова проверяются регулярным выражением)
STACK_ALIASES: dict[str, list[str]] = {
    "algorithms": ["алгоритм", "структуры данных", "algorithms", "data structures", "leetcode", "олимпиадн"],
    "sql": ["sql", "postgres sql", "запрос", "mysql", "t-sql", "pl/sql"],
    "http": ["http", "rest", "веб-протокол", "tcp/ip"],
    "git": ["git", "github", "gitlab", "bitbucket"],
    "linux": ["linux", "bash", "unix", "ubuntu", "debian", "centos", "shell"],
    "docker": ["docker", "контейнер", "docker-compose", "kubernetes", "k8s"],
    "python": ["python", "питон", "python3"],
    "fastapi": ["fastapi", "fast api"],
    "django": ["django", "drf", "django rest"],
    "flask": ["flask"],
    "asyncio": ["asyncio", "async/await", "асинхрон", "aiohttp"],
    "postgresql": ["postgresql", "postgres", "постгрес", "psql"],
    "redis": ["redis"],
    "kafka": ["kafka", "кафка"],
    "rabbitmq": ["rabbitmq", "rabbit", "amqp"],
    "rest-api": ["rest api", "restful", "openapi", "swagger", "api"],
    "grpc": ["grpc", "protobuf"],
    "go": ["golang", "go-разработ", "на go", "go "],
    "java": ["java", "spring", "kotlin"],
    "javascript": ["javascript", "js", "es6", "ecmascript", "node.js", "nodejs"],
    "typescript": ["typescript", "ts"],
    "react": ["react", "react.js", "reactjs", "реакт"],
    "vue": ["vue", "vue.js", "vuejs", "nuxt"],
    "angular": ["angular"],
    "nextjs": ["next.js", "nextjs"],
    "html-css": ["html", "css", "scss", "sass", "вёрстк", "верстк"],
    "tailwind": ["tailwind"],
    "state-management": ["redux", "zustand", "mobx", "effector", "управление состоянием"],
    "vite-webpack": ["webpack", "vite", "rollup", "esbuild"],
    "frontend-testing": ["jest", "vitest", "testing library", "cypress"],
    "a11y": ["a11y", "доступност", "accessibility", "wcag"],
    "pandas": ["pandas"],
    "numpy": ["numpy"],
    "scikit-learn": ["scikit-learn", "sklearn", "scikit"],
    "pytorch": ["pytorch", "torch", "tensorflow", "keras"],
    "statistics": ["статистик", "a/b", "ab-тест", "а/б", "statistics", "гипотез"],
    "spark": ["spark", "pyspark", "hadoop"],
    "airflow": ["airflow"],
    "clickhouse": ["clickhouse", "кликхаус"],
    "nlp": ["nlp", "обработка естественного языка", "llm", "трансформер", "bert", "rag"],
    "cv": ["computer vision", "компьютерное зрение", "opencv", "yolo", "cv-"],
    "mlops": ["mlops", "mlflow", "kubeflow", "dvc"],
    "test-design": ["тест-дизайн", "тест дизайн", "test design", "тест-кейс", "тест кейс", "чек-лист", "граничных значений"],
    "manual-testing": ["ручное тестирование", "ручного тестирования", "manual testing", "мануальн"],
    "pytest": ["pytest"],
    "selenium": ["selenium", "selenide"],
    "playwright": ["playwright"],
    "api-testing": ["тестирование api", "тестирования api", "postman", "api testing", "api-тест"],
    "load-testing": ["нагрузочн", "jmeter", "locust", "k6", "load testing"],
    "ci-cd": ["ci/cd", "ci cd", "jenkins", "gitlab ci", "github actions", "teamcity"],
    "allure": ["allure"],
    "owasp": ["owasp", "xss", "sql-инъекц", "csrf", "ssrf"],
    "pentest": ["пентест", "pentest", "тестирование на проникновение", "penetration"],
    "network-security": ["сетевая безопасность", "сетевой безопасност", "firewall", "межсетев", "ids", "ips", "vpn"],
    "cryptography": ["криптограф", "cryptography", "pki", "tls", "шифрован"],
    "siem-soc": ["siem", "soc", "splunk", "maxpatrol", "kuma", "elk"],
    "reverse-engineering": ["реверс", "reverse engineering", "ida pro", "ghidra"],
    "forensics": ["форензик", "forensics", "расследован инцидент", "dfir"],
    "burp-suite": ["burp"],
    "ctf": ["ctf", "capture the flag"],
}

# Короткие синонимы ищем только как отдельное слово в типичном написании (иначе много ложных срабатываний)
CASE_SENSITIVE_SHORT = {"go ": r"Go|golang", "ts": r"TS", "js": r"JS", "soc": r"SOC", "ids": r"IDS", "ips": r"IPS",
                        "api": r"API", "elk": r"ELK", "k6": r"k6"}
SHORT_TAG = {"go ": "go", "ts": "typescript", "js": "javascript", "soc": "siem-soc", "ids": "network-security",
             "ips": "network-security", "api": "rest-api", "elk": "siem-soc", "k6": "load-testing"}

DIRECTION_KEYWORDS: dict[str, list[str]] = {
    "backend": ["backend", "бэкенд", "бекенд", "back-end", "серверн", "api-сервис", "микросервис"],
    "frontend": ["frontend", "фронтенд", "front-end", "фронт", "клиентская часть", "интерфейс", "spa"],
    "data_ml": ["data scien", "machine learning", "машинн", "ml-", "ml ", "data/ml", "аналитик данных", "дата-сайент",
                "модел", "нейросет", "data engineer"],
    "qa": ["qa", "тестировщик", "тестирован", "автотест", "quality assurance", "sdet"],
    "security": ["информационн безопасност", "информационной безопасности", "кибербез", "иб ", "безопасност",
                 "pentest", "пентест", "soc-аналитик", "appsec", "security"],
}

GRADE_KEYWORDS: dict[str, list[str]] = {
    "intern": ["стажёр", "стажер", "стажир", "intern", "trainee", "без опыта", "студент", "школьник"],
    "junior": ["junior", "джуниор", "джун", "младш", "начинающ"],
    "middle": ["middle", "мидл", "миддл", "опытный разработчик"],
    "senior": ["senior", "сеньор", "синьор", "старш", "ведущ", "lead", "тимлид", "архитектор", "principal"],
}

ROLES: dict[str, list[str]] = {
    "developer": ["разработчик", "developer", "программист", "engineer", "инженер-программист"],
    "team_lead": ["тимлид", "team lead", "teamlead", "руководитель группы", "руководил командой", "лид команды"],
    "tech_lead": ["техлид", "tech lead", "технический лидер"],
    "architect": ["архитектор", "architect"],
    "mentor": ["ментор", "наставни", "mentor", "менторство", "обучал"],
    "analyst": ["аналитик", "analyst"],
    "tester": ["тестировщик", "qa-инженер", "qa engineer", "sdet"],
    "researcher": ["исследовател", "researcher", "научн"],
    "devops": ["devops", "sre"],
}
ROLE_TITLES = {
    "developer": "Разработчик", "team_lead": "Тимлид", "tech_lead": "Техлид", "architect": "Архитектор",
    "mentor": "Ментор", "analyst": "Аналитик", "tester": "Тестировщик", "researcher": "Исследователь",
    "devops": "DevOps/SRE",
}

SOFT_SKILLS: dict[str, list[str]] = {
    "communication": ["коммуникаб", "коммуникац", "communication", "общени"],
    "teamwork": ["команд", "teamwork", "team player", "работа в команде"],
    "responsibility": ["ответствен", "responsib"],
    "learning": ["обучаем", "быстро учусь", "самообучен", "fast learner", "саморазвит"],
    "leadership": ["лидерск", "leadership", "руководил"],
    "problem_solving": ["решение проблем", "аналитическ", "problem solving", "критическое мышление"],
    "mentoring": ["наставни", "менторств", "mentoring"],
    "time_management": ["тайм-менеджмент", "time management", "самоорганизац", "планирован"],
    "presentation": ["выступал", "доклад", "презентац", "публичн"],
}
SOFT_SKILL_TITLES = {
    "communication": "Коммуникация", "teamwork": "Работа в команде", "responsibility": "Ответственность",
    "learning": "Обучаемость", "leadership": "Лидерство", "problem_solving": "Решение проблем",
    "mentoring": "Наставничество", "time_management": "Самоорганизация", "presentation": "Публичные выступления",
}

WORK_FORMAT_KEYWORDS = {
    "remote": ["удалённ", "удаленн", "удалёнк", "удаленк", "remote", "дистанцион", "из дома"],
    "hybrid": ["гибрид", "hybrid"],
    "office": ["в офисе", "офис", "office", "on-site"],
}

REQUIRED_CUES = ["требован", "обязательн", "необходим", "must", "нужно", "нужен", "нужна", "нужны", "ожидаем", "опыт работы с",
                 "уверенн", "знание", "умение", "владение"]
DESIRED_CUES = ["будет плюсом", "плюсом", "желательн", "nice to have", "приветству", "преимуществ", "хорошо, если",
                "было бы здорово", "дополнительно"]


def _alias_regex(alias: str) -> re.Pattern:
    a = re.escape(alias.strip())
    # Слева — граница слова. Справа: для латинских синонимов — не латинская буква/цифра (java ≠ javascript),
    # для русских основ допускаем окончания («статистик|а»).
    right = r"(?![a-zA-Z0-9+#])" if re.search(r"[A-Za-z0-9+#.]$", alias.strip()) else ""
    return re.compile(rf"(?<![\w\-]){a}{right}", re.IGNORECASE)


_COMPILED: dict[str, list[re.Pattern]] = {
    tag: [_alias_regex(a) for a in aliases if a not in CASE_SENSITIVE_SHORT] for tag, aliases in STACK_ALIASES.items()
}
_SHORT = {k: re.compile(rf"(?<![\w\-])(?:{rx})(?![\w\-])") for k, rx in CASE_SENSITIVE_SHORT.items()}


def find_stack_spans(text: str) -> dict[str, tuple[int, int]]:
    """Стек-теги в тексте → (начало, конец) первого упоминания: цитата, на основании которой тег извлечён."""
    found: dict[str, tuple[int, int]] = {}
    for tag, pats in _COMPILED.items():
        for p in pats:
            m = p.search(text)
            if m and (tag not in found or m.start() < found[tag][0]):
                found[tag] = (m.start(), m.end())
    for short, pat in _SHORT.items():
        if short == "api":
            continue  # «API» само по себе слишком общее; REST API ловится полным синонимом
        m = pat.search(text)
        tag = SHORT_TAG[short]
        if m and (tag not in found or m.start() < found[tag][0]):
            found[tag] = (m.start(), m.end())
    return found


def find_stack(text: str) -> dict[str, int]:
    """Стек-теги в тексте → позиция первого упоминания (для порядка и весов)."""
    return {t: s for t, (s, _e) in find_stack_spans(text).items()}


def find_key_span(text: str, words: list[str]) -> tuple[int, int] | None:
    """Первое вхождение любого из ключевых слов (нижний регистр) → (начало, конец) в исходном тексте."""
    low = text.lower()
    best = None
    for w in words:
        i = low.find(w)
        if i >= 0 and (best is None or i < best[0]):
            best = (i, i + len(w.rstrip()))
    if best:  # основа слова («удалённ») → слово целиком («удалённо»)
        e = best[1]
        while e < len(text) and (text[e].isalpha()) and best[1] - best[0] >= 3:
            e += 1
        best = (best[0], e)
    return best


def find_keys(text: str, table: dict[str, list[str]]) -> dict[str, int]:
    low = text.lower()
    out: dict[str, int] = {}
    for key, words in table.items():
        hits = sum(low.count(w) for w in words)
        if hits:
            out[key] = hits
    return out
