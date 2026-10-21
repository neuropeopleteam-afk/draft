"""Словари для разбора текста без LLM: синонимы стек-тегов, роли, софт-скиллы, признаки грейда и направления.

Используются в двух местах: структурирование потребности работодателя и разбор резюме кандидата.
Ключи стек-тегов совпадают с идентификаторами справочника (миграция 0002).
"""
from functools import lru_cache
import re

from app.modules.catalog.seed_data import GRADES_EXT

# id стек-тега → синонимы (нижний регистр; границы слова проверяются регулярным выражением)
STACK_ALIASES: dict[str, list[str]] = {
    "algorithms": ["алгоритм", "структуры данных", "algorithms", "data structures", "leetcode", "олимпиадн"],
    "sql": ["sql", "postgres sql", "запрос", "mysql", "t-sql", "pl/sql", "ms sql", "mssql", "transact-sql", "субд"],
    "http": ["http", "rest", "веб-протокол", "tcp/ip", "websocket", "websockets"],
    "git": ["git", "github", "gitlab", "bitbucket", "gitflic"],
    "linux": ["linux", "bash", "unix", "ubuntu", "debian", "centos", "shell", "линукс", "rhel", "astra linux", "астра линукс", "ред ос", "redos", "systemd"],
    "docker": ["docker", "контейнер", "docker-compose", "докер", "docker compose", "dockerfile", "containerd", "podman"],
    "kubernetes": ["kubernetes", "k8s", "кубер", "openshift", "опеншифт", "k3s"],
    "python": ["python", "питон", "python3", "пайтон", "pydantic", "celery", "sqlalchemy", "alembic"],
    "fastapi": ["fastapi", "fast api", "фаст апи", "фастапи"],  # «фаст апи» — сленг (И27, Н1)
    "django": ["django", "drf", "django rest", "джанго"],
    "flask": ["flask", "фласк"],
    "asyncio": ["asyncio", "async/await", "асинхрон", "aiohttp", "async await"],
    "postgresql": ["postgresql", "postgres", "постгр", "psql", "pg", "pl/pgsql"],
    "redis": ["redis", "редис", "in-memory", "memcached"],
    "kafka": ["kafka", "кафк", "apache kafka"],
    "rabbitmq": ["rabbitmq", "rabbit", "amqp", "брокер сообщений", "очереди сообщений", "nats"],
    "rest-api": ["rest api", "restful", "openapi", "swagger", "api", "graphql", "soap", "json api"],
    "grpc": ["grpc", "protobuf", "protocol buffers"],
    "go": ["golang", "go-разработ", "на go", "go ", "голанг"],
    "java": ["java", "spring", "jvm", "jdk", "spring boot", "spring framework", "hibernate", "maven", "junit"],
    "kotlin": ["kotlin", "котлин", "ktor", "coroutines"],
    "csharp": ["c#", "c sharp", ".net", "asp.net", "dotnet", ".net core", "entity framework", "ef core", "wpf", "wcf"],
    "php": ["php", "laravel", "symfony", "yii", "yii2", "bitrix", "битрикс"],
    "javascript": ["javascript", "js", "es6", "ecmascript", "node.js", "nodejs", "node js", "джаваскрипт", "ajax"],
    "typescript": ["typescript", "ts", "тайпскрипт"],
    "react": ["react", "react.js", "reactjs", "react js", "реакт"],
    "vue": ["vue", "vue.js", "vuejs", "nuxt", "vue 2", "vue 3", "vue2", "vue3"],
    "angular": ["angular", "ангуляр", "angularjs"],
    "nextjs": ["next.js", "nextjs", "некст"],
    "html-css": ["html", "css", "scss", "sass", "вёрстк", "верстк", "html5", "css3", "less", "flexbox", "grid"],
    "tailwind": ["tailwind", "tailwindcss"],
    "state-management": ["redux", "zustand", "mobx", "effector", "управление состоянием", "редакс", "ngrx", "pinia", "vuex"],
    "vite-webpack": ["webpack", "vite", "rollup", "esbuild"],
    "frontend-testing": ["jest", "vitest", "testing library", "cypress"],
    # «доступност» — только в контексте интерфейса (CONTEXT_ALIASES ниже): «в пешей доступности», триада ИБ — не a11y
    "a11y": ["a11y", "доступност", "веб-доступност", "цифровая доступност", "цифровой доступност", "accessibility",
             "wcag"],
    "pandas": ["pandas", "пандас", "polars", "dataframe"],
    "numpy": ["numpy", "scipy"],
    "scikit-learn": ["scikit-learn", "sklearn", "scikit", "catboost", "lightgbm", "xgboost", "градиентный бустинг"],
    "pytorch": ["pytorch", "torch", "tensorflow", "keras"],
    "statistics": ["статистик", "a/b", "ab-тест", "а/б", "statistics", "гипотез", "математическая статистика", "матстатистик", "теория вероятност", "эконометрик", "временные ряды"],
    "spark": ["spark", "pyspark", "hadoop", "apache spark", "hdfs", "hive", "mapreduce", "big data", "больших данных"],
    "airflow": ["airflow", "apache airflow", "dag", "prefect", "luigi"],
    "clickhouse": ["clickhouse", "кликхаус"],
    "nlp": ["nlp", "обработка естественного языка", "llm", "трансформер", "bert", "rag", "langchain"],
    "cv": ["computer vision", "компьютерное зрение", "opencv", "yolo", "cv-"],
    "mlops": ["mlops", "mlflow", "kubeflow", "dvc", "triton", "clearml"],
    "test-design": ["тест-дизайн", "тест дизайн", "test design", "тест-кейс", "тест кейс", "test case", "чек-лист", "граничных значений", "функциональное тестирование", "функционального тестирования", "регрессионное тестирование", "регрессионного тестирования", "тестовая документация"],
    "manual-testing": ["ручное тестирование", "ручного тестирования", "manual testing", "мануальн", "ручной тестировщ",
                       "ручного тестировщ", "тестировщик ручн", "manual qa", "баг-репорт", "баг репорт", "исследовательское тестирование", "приемочное тестирование"],
    "pytest": ["pytest", "unittest"],
    "selenium": ["selenium", "selenide", "selenium ide", "webdriver", "appium", "aqa"],
    "playwright": ["playwright", "плейрайт"],
    "api-testing": ["тестирование api", "тестирования api", "postman", "api testing", "api-тест", "charles", "fiddler", "soapui", "insomnia"],
    "load-testing": ["нагрузочн", "jmeter", "locust", "k6", "load testing", "gatling"],
    "ci-cd": ["ci/cd", "ci cd", "cicd", "jenkins", "gitlab ci", "github actions", "teamcity", "argo cd", "argocd"],
    "allure": ["allure", "аллюр", "testops", "tms", "testrail", "qase"],
    "owasp": ["owasp", "xss", "sql-инъекц", "csrf", "ssrf", "анализ защищенности", "анализа защищенности", "sast", "dast", "appsec"],
    "pentest": ["пентест", "pentest", "тестирование на проникновение", "penetration", "pentester", "red team", "redteam"],
    "network-security": ["сетевая безопасность", "сетевой безопасност", "firewall", "межсетев", "ids", "ips", "vpn", "ngfw", "vipnet", "dlp", "waf", "edr", "xdr", "active directory"],
    "cryptography": ["криптограф", "cryptography", "pki", "tls", "шифрован", "ipsec"],
    "siem-soc": ["siem", "soc", "splunk", "maxpatrol", "kuma", "elk", "расследование инцидентов", "реагирование на инцидент", "корреляция событий"],
    "reverse-engineering": ["реверс", "reverse engineering", "ida pro", "ghidra"],
    "forensics": ["форензик", "forensics", "расследован инцидент", "dfir"],
    "burp-suite": ["burp", "burp suite", "nmap", "metasploit", "nessus"],
    "ctf": ["ctf", "capture the flag"],
}

# Известные технологии, которых нет в справочнике платформы: тест их не проверяет. Не молчим — показываем работодателю
# «не учтено в подборе» (И18). Ключ — как показать, значение — синонимы (тот же разбор границ слова, что у стек-тегов).
UNSUPPORTED_TECH: dict[str, list[str]] = {
    "Rust": ["rust"], "C++": ["c++"], "Swift": ["swift"], "Objective-C": ["objective-c"], "Scala": ["scala"],
    "Ruby": ["ruby", "rails"], "Elixir": ["elixir"], "Erlang": ["erlang"], "Haskell": ["haskell"], "Perl": ["perl"],
    "Dart/Flutter": ["dart", "flutter"], "React Native": ["react native"], "Svelte": ["svelte"], "jQuery": ["jquery"],
    "RxJS": ["rxjs"], "GraphQL": ["graphql"], "Celery": ["celery"], "Hibernate": ["hibernate"], "Gradle": ["gradle"],
    "Maven": ["maven"], "Terraform": ["terraform"], "Ansible": ["ansible"], "Helm": ["helm"],
    "Prometheus": ["prometheus"], "Grafana": ["grafana"], "Zabbix": ["zabbix"], "Nginx": ["nginx"],
    "Elasticsearch": ["elasticsearch", "elastic search", "opensearch"], "MongoDB": ["mongodb", "mongo"],
    "Cassandra": ["cassandra"], "Tarantool": ["tarantool"], "Oracle": ["oracle"], "Greenplum": ["greenplum"],
    "Flink": ["flink"], "Hive": ["hive"], "dbt": ["dbt"], "Tableau": ["tableau"], "Power BI": ["power bi", "powerbi"],
    "Excel": ["excel"], "Superset": ["superset"], "Looker": ["looker"], "AWS": ["aws"], "GCP": ["gcp"],
    "Azure": ["azure"], "Appium": ["appium"], "JUnit": ["junit"], "TestNG": ["testng"], "Cucumber": ["cucumber"],
    "Gatling": ["gatling"], "eBPF": ["ebpf"], "DPDK": ["dpdk"], "Active Directory": ["active directory"],
    "Cobalt Strike": ["cobalt strike"], "Metasploit": ["metasploit"], "OSCP": ["oscp"], "Wireshark": ["wireshark"],
    "BPMN": ["bpmn"], "UML": ["uml"], "Figma": ["figma"], "Unity": ["unity"], "Unreal": ["unreal"],
    "Android": ["android"], "iOS": ["ios"], "Kotlin Multiplatform": ["kmp"], "Jetpack Compose": ["jetpack compose"],
    "1С": ["1с", "1c"],  # «1С:Предприятие» — вне справочника, не терять (И27, Н2)
}

# Короткие синонимы ищем только как отдельное слово в типичном написании (иначе много ложных срабатываний)
CASE_SENSITIVE_SHORT = {"go ": r"Go|golang", "ts": r"TS", "js": r"JS", "soc": r"SOC", "ids": r"IDS", "ips": r"IPS",
                        "api": r"API", "elk": r"ELK", "k6": r"k6"}
SHORT_TAG = {"go ": "go", "ts": "typescript", "js": "javascript", "soc": "siem-soc", "ids": "network-security",
             "ips": "network-security", "api": "rest-api", "elk": "siem-soc", "k6": "load-testing"}

DIRECTION_KEYWORDS: dict[str, list[str]] = {
    "backend": ["backend", "бэкенд", "бекенд", "back-end", "серверн", "api-сервис", "микросервис", "бэк ", "бек ",
                "разработчик python", "python-разработчик", "java-разработчик", "разработчик java", "go-разработчик",
                "разработчик c#", "разработчик .net", "разработчик php"],
    "frontend": ["frontend", "фронтенд", "front-end", "фронт", "клиентская часть", "интерфейс", "spa",
                 "react-разработчик", "разработчик react", "vue-разработчик", "разработчик vue", "javascript/react", "node js"],
    "data_ml": ["data scien", "machine learning", "машинн", "ml-", "ml ", "data/ml", "аналитик данных", "дата-сайент",
                "ml-модел", "моделей машинн", "обучение модел", "нейросет", "data engineer", "deep learning", "computer vision"],
    "qa": ["qa", "тестировщик", "тестирован", "автотест", "quality assurance", "sdet", "aqa", "инженер по тестированию", "специалист по тестированию"],
    "security": ["информационн безопасност", "информационной безопасности", "кибербез", "иб ", "отдел иб", "управление иб",
                 "специалист по иб", "инженер иб", "анализ защищенност", "анализа защищенност", "технической безопасности",
                 "обеспечения безопасности", "корпоративной защиты", "фрод-мониторинг", "антифрод-аналитик", "pentest",
                 "пентест", "soc-аналитик", "команду soc", "отдел soc", "специалист soc", "appsec", "devsecops",
                 "security", "защит информац", "защиты информации"],
}

GRADE_KEYWORDS: dict[str, list[str]] = {
    "intern": ["стажёр", "стажер", "стажир", "стажировк", "intern", "trainee", "без опыта", "студент", "школьник"],
    "junior": ["junior", "джуниор", "джун", "младш", "начинающ", "выпускник"],
    "middle": ["middle", "мидл", "миддл", "опытный разработчик"],
    "senior": ["senior", "сеньор", "синьор", "старш", "ведущ", "lead", "тимлид", "архитектор", "principal", "head of"],
}
if GRADES_EXT:  # флаг GRADES_EXT_ENABLED: Lead и Principal — свои уровни, а не Senior (видимость — catalog.levels)
    GRADE_KEYWORDS["senior"] = ["senior", "сеньор", "синьор", "старш", "ведущ"]
    GRADE_KEYWORDS["lead"] = ["team lead", "teamlead", "tech lead", "techlead", "тимлид", "техлид", "лид команды",
                              "lead ", "lead-", "lead/", "архитектор", "architect", "head of"]
    GRADE_KEYWORDS["principal"] = ["principal", "staff engineer", "staff-инженер", "главный архитектор",
                                   "chief architect", "принципал"]

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
    "remote": ["удалённ", "удаленн", "удалёнк", "удаленк", "удалённо", "удаленно", "remote", "дистанцион", "из дома"],
    "hybrid": ["гибрид", "hybrid"],
    "office": ["в офисе", "офис", "office", "on-site", "на месте работодателя", "на\u00a0месте работодателя"],
}

REQUIRED_CUES = ["требован", "обязательн", "необходим", "must", "нужно", "нужен", "нужна", "нужны", "ожидаем", "опыт работы с",
                 "уверенн", "знание", "умение", "владение"]
DESIRED_CUES = ["будет плюсом", "плюсом", "желательн", "nice to have", "приветству", "преимуществ", "хорошо, если",
                "было бы здорово", "дополнительно", "немного", "но плюс"]  # «докер не обязателен, но плюс» (И27)


def _alias_regex(alias: str) -> re.Pattern:
    a = re.escape(alias.strip())
    # Слева — граница слова. Справа: для латинских синонимов — не латинская буква/цифра (java ≠ javascript),
    # для русских основ допускаем окончания («статистик|а»).
    right = r"(?![a-zA-Z0-9+#])" if re.search(r"[A-Za-z0-9+#.]$", alias.strip()) else ""
    return re.compile(rf"(?<![\w\-]){a}{right}", re.IGNORECASE)


# Синонимы, которые значат навык только в своём контексте. «доступност» → a11y: на 414 реальных вакансиях hh.ru
# (корпус 10.10.2026) голое слово дало 31 срабатывание, из них про доступность интерфейсов — 1; остальные —
# «в пешей/шаговой доступности от метро», «конфиденциальность, целостность, доступность» (ИБ), «высокой доступности
# сервисов» (надёжность). Считаем a11y, только если в той же фразе есть слово интерфейса и нет этих оборотов.
_CLAUSE_END = re.compile(r"[;!?\n•]|\.\s")
_A11Y_CONTEXT = re.compile(
    r"интерфейс|(?<![a-zа-яё])ui(?![a-zа-яё])|(?<![a-zа-яё])ux(?![a-zа-яё])|фронт|front|react|vue|angular|"
    r"svelte|html|css|вёрстк|верстк|семантик|seo|aria|wcag|a11y|клавиатур|экранн|скринридер|screen ?reader|слабовидящ|"
    r"незрячи|инклюзив|ограниченными возможност|инвалидност|дизайн-систем|контраст",
    re.IGNORECASE)
_A11Y_BEFORE_NOT = re.compile(r"(?:пеш|шагов|транспортн|высок)\w*\s+$", re.IGNORECASE)   # «в пешей доступности»
_A11Y_AFTER_NOT = re.compile(r"^\w*\s+(?:от|до)\s", re.IGNORECASE)                      # «доступности от м. …»
_A11Y_CLAUSE_NOT = re.compile(r"конфиденциальн|целостн", re.IGNORECASE)                  # триада ИБ


def _clause(text: str, start: int, end: int) -> tuple[str, str]:
    """Часть фразы до совпадения и после него (до ближайшей границы фразы, не дальше 80 знаков)."""
    left = text[max(0, start - 80):start]
    cut = [m.end() for m in _CLAUSE_END.finditer(left)]
    left = left[cut[-1]:] if cut else left
    right = text[end:end + 80]
    m = _CLAUSE_END.search(right)
    return left, right[:m.start()] if m else right


def _a11y_context(text: str, m: re.Match) -> bool:
    left, right = _clause(text, m.start(), m.end())
    if _A11Y_BEFORE_NOT.search(left) or _A11Y_AFTER_NOT.search(right) or _A11Y_CLAUSE_NOT.search(left + " " + right):
        return False
    return bool(_A11Y_CONTEXT.search(left) or _A11Y_CONTEXT.search(right))


CONTEXT_ALIASES = {("a11y", "доступност"): _a11y_context}

def _alias_pattern_str(alias: str) -> str:
    a = re.escape(alias.strip())
    right = r"(?![a-zA-Z0-9+#])" if re.search(r"[A-Za-z0-9+#.]$", alias.strip()) else ""
    return rf"{a}{right}"


def _combine_aliases(aliases: list[str]) -> list[re.Pattern]:
    if not aliases:
        return []
    ordered = sorted(aliases, key=lambda x: -len(x.strip()))
    body = "|".join(_alias_pattern_str(a) for a in ordered)
    return [re.compile(rf"(?<![\w\-])(?:{body})", re.IGNORECASE)]


_COMPILED: dict[str, list[re.Pattern]] = {
    tag: _combine_aliases([a for a in aliases if a not in CASE_SENSITIVE_SHORT and (tag, a) not in CONTEXT_ALIASES])
    for tag, aliases in STACK_ALIASES.items()
}
_CONTEXTUAL = [(tag, _alias_regex(a), check) for (tag, a), check in CONTEXT_ALIASES.items()]
_SHORT = {k: re.compile(rf"(?<![\w\-])(?:{rx})(?![\w\-])") for k, rx in CASE_SENSITIVE_SHORT.items()}


def _visible_ext_tags() -> tuple[str, ...]:
    from app.modules.catalog.ext import visible_stack

    return tuple(visible_stack())


def direction_keywords() -> dict[str, list[str]]:
    """Ключевые слова направлений с учётом расширения каталога (ext.py): без видимых направлений расширения — ровно
    DIRECTION_KEYWORDS; с ними — свои слова у DevOps/SRE, инженера данных, мобильной разработки и аналитика, а
    «data engineer» уходит из Data/ML к инженеру данных (раньше вёл в ближайшую категорию)."""
    from app.modules.catalog.ext import EXT_DIRECTION_KEYWORDS, EXT_TAKES_KEYWORDS, visible_ext

    from app.modules.catalog.ext import enabled

    if not enabled():
        return DIRECTION_KEYWORDS
    vis = visible_ext()
    taken = {w for d in vis for words in EXT_TAKES_KEYWORDS.get(d, {}).values() for w in words}
    # «spa» как подстрока срабатывал внутри «Spark», «space» (Data Engineer со Spark в заголовке уходил во Frontend):
    # с флагом расширения каталога — только отдельным словом «SPA»
    out = {d: [_SPA_WORD if w == "spa" else w for w in words if w not in taken]
           for d, words in DIRECTION_KEYWORDS.items()}
    out.update({d: EXT_DIRECTION_KEYWORDS[d] for d in vis})
    return out


_SPA_WORD = r"re:(?<![a-zа-яё])spa(?![a-zа-яё])"


def _ext_spans(text: str, found: dict[str, tuple[int, int]]) -> None:
    """Стек-теги видимых направлений расширения (на месте в found). React Native — не React: синоним базового тега
    внутри фрагмента тега расширения не считается упоминанием базового тега (EXT_SHADOWS)."""
    tags = _visible_ext_tags()
    if not tags:
        return
    from app.modules.catalog.ext import EXT_SHADOWS

    for tag in tags:
        for p in _ext_compiled().get(tag, ()):
            m = p.search(text)
            if m and (tag not in found or m.start() < found[tag][0]):
                found[tag] = (m.start(), m.end())
    for tag, shadowed in EXT_SHADOWS.items():
        if tag in found and shadowed in found:
            masked = text
            for p in _ext_compiled()[tag]:
                masked = p.sub(lambda m: " " * (m.end() - m.start()), masked)
            first = None
            for p in _COMPILED.get(shadowed, ()):
                m = p.search(masked)
                if m and (first is None or m.start() < first[0]):
                    first = (m.start(), m.end())
            if first is None:
                found.pop(shadowed)
            else:
                found[shadowed] = first


_EXT_COMPILED: dict[str, list[re.Pattern]] | None = None


def _ext_compiled() -> dict[str, list[re.Pattern]]:
    global _EXT_COMPILED
    if _EXT_COMPILED is None:
        from app.modules.catalog.ext import EXT_ALIASES

        _EXT_COMPILED = {tag: _combine_aliases(aliases) for tag, aliases in EXT_ALIASES.items()}
    return _EXT_COMPILED


@lru_cache(maxsize=512)
def _find_stack_spans_cached(text: str, ext_tags: tuple[str, ...]) -> tuple[tuple[str, tuple[int, int]], ...]:
    found: dict[str, tuple[int, int]] = {}
    for tag, pats in _COMPILED.items():
        for p in pats:
            m = p.search(text)
            if m and (tag not in found or m.start() < found[tag][0]):
                found[tag] = (m.start(), m.end())
    for tag, pat, check in _CONTEXTUAL:
        m = next((m for m in pat.finditer(text) if check(text, m)), None)
        if m and (tag not in found or m.start() < found[tag][0]):
            found[tag] = (m.start(), m.end())
    for short, pat in _SHORT.items():
        if short == "api":
            continue  # «API» само по себе слишком общее; REST API ловится полным синонимом
        m = pat.search(text)
        tag = SHORT_TAG[short]
        if m and (tag not in found or m.start() < found[tag][0]):
            found[tag] = (m.start(), m.end())
    _ext_spans(text, found)
    return tuple(found.items())


def find_stack_spans(text: str) -> dict[str, tuple[int, int]]:
    """Стек-теги в тексте → (начало, конец) первого упоминания: цитата, на основании которой тег извлечён."""
    return dict(_find_stack_spans_cached(text, _visible_ext_tags()))


_UNSUPPORTED = {name: _combine_aliases(aliases) for name, aliases in UNSUPPORTED_TECH.items()}


def find_unsupported_spans(text: str) -> dict[str, tuple[int, int]]:
    """Технологии вне справочника → позиция первого упоминания (кроме фрагментов, уже распознанных как стек-тег)."""
    known = list(find_stack_spans(text).values())
    out: dict[str, tuple[int, int]] = {}
    for name, pats in _UNSUPPORTED.items():
        for p in pats:
            for m in p.finditer(text):
                if not any(s < m.end() and m.start() < e for s, e in known):
                    if name not in out or m.start() < out[name][0]:
                        out[name] = m.span()
                    break
    return out


def find_stack(text: str) -> dict[str, int]:
    """Стек-теги в тексте → позиция первого упоминания (для порядка и весов)."""
    return {t: s for t, (s, _e) in find_stack_spans(text).items()}


def find_key_span(text: str, words: list[str]) -> tuple[int, int] | None:
    """Первое вхождение любого из ключевых слов (нижний регистр) → (начало, конец) в исходном тексте."""
    low = text.lower()
    best = None
    for w in words:
        if w.startswith("re:"):  # выражение (граница слова): только у расширения каталога, см. direction_keywords
            m = re.search(w[3:], low)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), m.end())
            continue
        i = low.find(w)
        if i >= 0 and (best is None or i < best[0]):
            best = (i, i + len(w.rstrip()))
    if best:  # основа слова («удалённ») → слово целиком («удалённо»)
        e = best[1]
        while e < len(text) and (text[e].isalpha()) and best[1] - best[0] >= 3:
            e += 1
        best = (best[0], e)
    return best


def kw_pattern(word: str) -> str:
    """Регулярное выражение ключевого слова: «re:…» — уже выражение (граница слова и т. п.), иначе — как подстрока."""
    return word[3:] if word.startswith("re:") else re.escape(word)


def find_keys(text: str, table: dict[str, list[str]]) -> dict[str, int]:
    low = text.lower()
    out: dict[str, int] = {}
    for key, words in table.items():
        hits = sum(len(re.findall(w[3:], low)) if w.startswith("re:") else low.count(w) for w in words)
        if hits:
            out[key] = hits
    return out
