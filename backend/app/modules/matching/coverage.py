"""Explain nearest MVP category without pretending to test an unsupported profession."""
import re
from functools import lru_cache

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


# --- Я10: «что проверено тестом / что НЕ проверено» для подборки и вопрос-зонд на непроверенный навык -------------
# Заготовки вопроса для роли вне каталога: короткая практическая задача на 15–30 минут, ответ оценивает работодатель —
# оценённый зонд становится фактом T1 (как любой зонд). Тексты — без оценочных слов и без персональных данных.
PROBES = {
    "devops": ("Эксплуатация: выкладка без простоя",
               "Сервис из трёх подов в Kubernetes отдаёт 502 при каждой выкладке. Опишите по шагам, как найдёте причину "
               "и что поменяете (пробы готовности, стратегия выкладки, ресурсы), и как проверите, что простоя больше нет."),
    "mobile": ("Мобильная разработка: жизненный цикл экрана",
               "Экран со списком теряет введённые данные при повороте и сворачивании приложения. Опишите, где хранить "
               "состояние, как его восстановить и как это проверить тестом (Android или iOS — на выбор)."),
    "1c": ("1С: проведение документа",
           "При проведении документа «Реализация» остатки уходят в минус без ошибки. Опишите, где в конфигурации "
           "искать причину, как добавить контроль остатков и как проверить исправление."),
    "gamedev": ("Игры: игровой цикл",
                "Персонаж «проваливается» сквозь пол на слабых устройствах. Опишите, как связаны частота кадров и "
                "физика, что поменяете в игровом цикле (Unity или Unreal — на выбор) и как проверите."),
    "analytics": ("Аналитика: просевшая метрика",
                  "Конверсия в оплату за неделю упала с 4 % до 3 %. Опишите план разбора: какие данные возьмёте, какие "
                  "гипотезы проверите первыми и как отличите реальное падение от ошибки в данных."),
}


def probe_for_skill(title: str) -> dict:
    """Заготовка зонда на один навык, который тест платформы не подтверждает: работодатель правит её перед отправкой."""
    return {"title": f"Вопрос по навыку: {title}"[:200],
            "task": f"Опишите задачу из своей практики, где вы применяли {title}: что нужно было сделать, что вы "
                    "сделали сами, какая была главная трудность и как вы её решили. Если опыта нет — опишите, как "
                    "подошли бы к типовой задаче с этим навыком. 10–15 строк."}


def bank_tags(direction: str | None) -> frozenset[str]:
    """Стек-теги, которые проверяет тест платформы направления: семейства банка направления и общего блока (без канареек)."""
    return _bank_tags(direction or "")


@lru_cache(maxsize=16)
def _bank_tags(direction: str) -> frozenset[str]:
    from assessment_bank import load_specs

    from app.modules.assessment.skill_map import to_stack_tags

    from app.modules.catalog.ext import in_active_pool

    out: set[str] = set()
    for s in load_specs().values():
        if s.canary or s.direction not in (direction, "common") or not in_active_pool(s):
            continue
        out.update(to_stack_tags(s.direction, s.skills))
    return frozenset(out)


def scope(req: dict | None) -> dict | None:
    """Что из требований потребности тест платформы проверяет, а что — нет (только по требованиям, без кандидатов).

    Для профессии вне каталога (coverage) — ближайшая категория и общий текст «проверяется / не проверяется»; для любой
    потребности — навыки вне справочника (unknown_terms) и навыки справочника, которых нет в заданиях теста направления.
    None — если всё обязательное и желательное тест проверяет и роль в каталоге (показывать нечего).
    """
    if not req:
        return None
    from app.modules.catalog.ext import EXT_STACK
    from app.modules.catalog.seed_data import DIRECTION_TITLES, STACK

    cov = req.get("coverage") or None
    have = bank_tags(req.get("direction"))
    items = [(i, True) for i in req.get("stack_required") or []] + [(i, False) for i in req.get("stack_desired") or []]
    tested, not_tested = [], []
    for it, must in items:
        tag = it.get("tag")
        if not tag:
            continue
        title = STACK.get(tag, EXT_STACK.get(tag, (tag,)))[0]  # теги расширения каталога — со своим названием
        if tag in have:
            tested.append({"tag": tag, "title": title, "must": must})
        else:
            not_tested.append({"tag": tag, "title": title, "must": must, "why": "нет заданий в тесте направления",
                               "probe": probe_for_skill(title)})
    for u in req.get("unknown_terms") or []:
        term = (u.get("term") if isinstance(u, dict) else str(u)) or ""
        if term and all(x["title"].casefold() != term.casefold() for x in not_tested):
            not_tested.append({"tag": None, "title": term, "must": None, "why": "вне справочника",
                               "probe": probe_for_skill(term)})
    if not cov and not not_tested:
        return None
    role = (cov or {}).get("role")
    p = PROBES.get(role or "")
    return {
        "out_of_catalog": bool(cov), "role": role, "role_title": (cov or {}).get("title"),
        "nearest_title": (cov or {}).get("nearest_title") or DIRECTION_TITLES.get(req.get("direction") or ""),
        "tested": tested, "tested_note": (cov or {}).get("tested"),
        "not_tested": not_tested, "not_tested_note": (cov or {}).get("not_tested"),
        "probe": {"title": p[0], "task": p[1]} if p else (not_tested[0]["probe"] if not_tested else None),
    }
