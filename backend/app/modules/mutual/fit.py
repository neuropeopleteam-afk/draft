"""«Насколько предложение подходит кандидату» — вторая сторона подбора (Н9), без БД: чистые функции.

Факторы (все — самоописание кандидата T0 или условия предложения; в скор match-v1 не входят):
  format    0,25 — формат работы предложения против желаемого кандидатом
  location  0,15 — город присутствия или удалёнка (переезд — частично)
  salary    0,30 — верх вилки против скрытого минимума: только «в ожиданиях / ниже ожиданий», сам минимум не
                   раскрывается; минимум округляется вверх до 10 000 ₽, число сравнений ограничено (service.py)
  stack     0,15 — пересечение стека потребности с интересами кандидата (явные интересы, иначе стек из опроса)
  tasks     0,05 — тип задач из текста потребности (словарь ниже) против отмеченных кандидатом
  readiness 0,10 — готовность к предложениям: ищу активно / открыт / сейчас не ищу

Веса заданы до проверки и ни на чём не подбирались (разметки откликов кандидатов нет). Неизвестный фактор
не штрафует: вес перераспределяется по известным; известных меньше 0,25 веса — уровень «мало данных».
Уровень: ≥ 0,75 — подходит, ≥ 0,45 — частично, иначе — вероятно, откажет. Вилка ниже ожиданий, несовпадение
формата или города без переезда — «вероятно, откажет» независимо от остального; совместимый, но другой формат,
переезд или «сейчас не ищет» — не выше «частично».
"""
from __future__ import annotations

import math
import re

from app.modules.catalog.seed_data import STACK

ALGORITHM = "mutual-v1"
WEIGHTS = {"format": 0.25, "location": 0.15, "salary": 0.30, "stack": 0.15, "tasks": 0.05, "readiness": 0.10}
FACTOR_TITLES = {"format": "Формат", "location": "Город или удалёнка", "salary": "Вилка", "stack": "Интерес к стеку",
                 "tasks": "Интерес к задачам", "readiness": "Готовность к предложениям"}
VALUE = {"ok": 1.0, "partial": 0.5, "bad": 0.0}
MIN_KNOWN_WEIGHT = 0.25
SALARY_STEP = 10_000
LEVELS = {"high": "Предложение подходит кандидату", "medium": "Подходит частично", "low": "Вероятно, откажет",
          "unknown": "Мало данных о кандидате"}
LEVELS_ME = {"high": "Предложение вам подходит", "medium": "Подходит частично", "low": "Не совпадает с вашими ожиданиями",
             "unknown": "Мало данных"}
LEVEL_ORDER = {"high": 0, "medium": 1, "unknown": 1, "low": 2}
OFFERS = {"active": "Ищу работу активно", "open": "Открыт к предложениям", "not_looking": "Сейчас не ищу"}
WF = {"office": "офис", "hybrid": "гибрид", "remote": "удалённо", "any": "любой формат"}

# Типы задач: (название, ключевые основы для поиска в тексте потребности). Короткие латинские — по границе слова.
TASKS: dict[str, tuple[str, tuple[str, ...]]] = {
    "payments": ("Платежи и финтех", ("платеж", "платёж", "финтех", "fintech", "банк", "эквайринг", "биллинг")),
    "highload": ("Высокие нагрузки", ("высоконагруж", "highload", "нагрузк", "rps", "масштабир")),
    "integrations": ("Интеграции и API", ("интеграц", "api", "микросервис", "grpc", "вебхук")),
    "data": ("Данные и аналитика", ("аналитик", "etl", "dwh", "хранилищ", "витрин", "отчётност", "отчетност")),
    "ml": ("ML и нейросети", ("машинн", "ml", "нейросет", "llm", "рекомендац")),
    "product_ui": ("Интерфейсы и продукт", ("интерфейс", "личн кабинет", "личного кабинета", "личный кабинет", "ui", "ux",
                                            "вёрстк", "верстк", "дизайн-систем")),
    "infra": ("Инфраструктура и DevOps", ("инфраструкт", "devops", "kubernetes", "ci/cd", "облак", "sre")),
    "security": ("Безопасность", ("безопасн", "пентест", "уязвим", "soc", "защит")),
    "testing": ("Автоматизация тестирования", ("автотест", "автоматизац тестир", "тестирован", "qa")),
    "new_product": ("Новый продукт с нуля", ("с нуля", "mvp", "стартап")),
}


def _pattern(kw: str) -> re.Pattern:
    if re.fullmatch(r"[a-z/]{2,5}", kw):
        return re.compile(rf"(?<![a-zа-яё]){re.escape(kw)}(?![a-zа-яё])")
    return re.compile(r"\s+".join(re.escape(w) for w in kw.split()))


_PATTERNS = {k: [_pattern(w) for w in kws] for k, (_, kws) in TASKS.items()}


def detect_tasks(text: str | None) -> list[dict]:
    """Типы задач в тексте потребности: [{id, title, quote}] — с цитатой (фрагмент текста), без LLM."""
    low = (text or "").lower()
    out = []
    for k, pats in _PATTERNS.items():
        for p in pats:
            m = p.search(low)
            if m:
                s, e = m.start(), m.end()
                while e < len(low) and low[e].isalnum():  # до конца слова: «платеж» → «платежей»
                    e += 1
                out.append({"id": k, "title": TASKS[k][0], "quote": (text or "")[s:e]})
                break
    return out


def _formats(req: dict) -> list[str]:
    f = [x for x in (req.get("work_formats") or []) if x in ("office", "hybrid", "remote")]
    if not f and req.get("work_format") in ("office", "hybrid", "remote"):
        f = [req["work_format"]]
    return f


# Совместимость формата: желаемый кандидатом → предложенный
_FORMAT_FIT = {
    "remote": {"remote": "ok", "hybrid": "bad", "office": "bad"},
    "hybrid": {"hybrid": "ok", "office": "partial", "remote": "partial"},
    "office": {"office": "ok", "hybrid": "partial", "remote": "partial"},
}
_RANK = {"ok": 0, "partial": 1, "bad": 2}


def _f(key: str, status: str, text: str) -> dict:
    return {"key": key, "title": FACTOR_TITLES[key], "status": status, "text": text, "weight": WEIGHTS[key]}


def rub(v: int | None) -> str:
    return f"{v:,}".replace(",", "\u00a0") + "\u00a0₽" if v else "—"


def rounded_minimum(minimum: int | None) -> int | None:
    """Минимум для сравнения у работодателя: вверх до 10 000 ₽ — ответ зависит только от «корзины» вилки."""
    return int(math.ceil(minimum / SALARY_STEP) * SALARY_STEP) if minimum else None


def salary_bucket(salary_to: int) -> int:
    return int(salary_to // SALARY_STEP)


def offer_fit(*, work_format: str, city: str | None, relocation: bool, salary_min: int | None,
              privacy: dict, declared_stack: set[str], prefs: dict | None, req: dict, need_text: str | None,
              salary_to: int | None, audience: str = "employer", salary_limited: bool = False,
              salary_basis: str | None = None) -> dict:
    """Факторы, уровень и одна строка объяснения. audience=candidate — тексты для самого кандидата (свои данные).
    salary_basis — основание верха вилки («gross» до вычета НДФЛ / «net» на руки): минимум кандидата хранится «на руки»,
    поэтому вилка до вычета сравнивается после пересчёта (как below_minimum в приглашениях); None — сравнить как есть."""
    from app.modules.contact.salary import to_net

    me = audience == "candidate"
    salary_cmp = to_net(salary_to, salary_basis) if (salary_to and salary_basis) else salary_to  # с чем сравниваем минимум
    basis_note = f" (≈{rub(salary_cmp)} на руки)" if (salary_to and salary_basis == "gross" and salary_cmp != salary_to) else ""
    prefs = prefs or {}
    factors: list[dict] = []

    # ---- формат
    offered = _formats(req)
    if not offered:
        factors.append(_f("format", "unknown", "Формат в предложении не указан"))
    elif not me and not privacy.get("show_work_format", True):
        factors.append(_f("format", "hidden", "Формат скрыт кандидатом"))
    elif work_format == "any":
        factors.append(_f("format", "ok", "Подходит любой формат" if me else "Кандидату подходит любой формат"))
    else:
        st = min((_FORMAT_FIT.get(work_format, {}).get(o, "partial") for o in offered), key=_RANK.get)
        offer_t = " или ".join(WF[o] for o in offered)
        want_t = WF.get(work_format, work_format)
        text = {"ok": f"{offer_t.capitalize()} — {'как вы хотите' if me else 'как хочет кандидат'}",
                "partial": f"Предложение: {offer_t}; {'вы хотите' if me else 'кандидат хочет'} {want_t}",
                "bad": f"{'Вы хотите' if me else 'Кандидат хочет'} {want_t}, в предложении — {offer_t}"}[st]
        factors.append(_f("format", st, text))

    # ---- город или удалёнка
    on_site = [o for o in offered if o in ("office", "hybrid")]
    if offered and not on_site:
        factors.append({**_f("location", "ok", "Удалённо — город не важен"), "in_line": False})
    elif not req.get("city"):
        factors.append(_f("location", "unknown", "Город в предложении не указан"))
    elif not me and not privacy.get("show_city", True):
        factors.append(_f("location", "hidden", "Город скрыт кандидатом"))
    elif (city or "").strip().casefold() == req["city"].strip().casefold():
        factors.append(_f("location", "ok", f"Город совпадает: {req['city']}"))
    elif relocation:
        factors.append(_f("location", "partial", f"Работа в городе {req['city']}: "
                                                 f"{'вы готовы' if me else 'кандидат готов'} к переезду"))
    else:
        factors.append(_f("location", "bad", f"Работа в городе {req['city']}: {'вы в другом городе' if me else 'кандидат в другом городе'} "
                                             "и без переезда"))

    # ---- вилка против скрытого минимума (работодателю — только «в ожиданиях / ниже ожиданий»)
    if not salary_to:
        factors.append(_f("salary", "unknown", "В предложении нет вилки"))
    elif me:
        if not salary_min:
            factors.append(_f("salary", "unknown", "Вы не указали минимум зарплаты"))
        elif salary_cmp >= salary_min:
            factors.append(_f("salary", "ok", f"Верх вилки {rub(salary_to)}{basis_note} — не ниже вашего минимума"))
        else:
            factors.append(_f("salary", "bad", f"Верх вилки {rub(salary_to)}{basis_note} ниже вашего минимума {rub(salary_min)}"))
    elif prefs.get("salary_signal") is False:
        factors.append(_f("salary", "hidden", "Кандидат не сообщает, в ожиданиях ли вилка"))
    elif not salary_min:
        factors.append(_f("salary", "unknown", "Кандидат не указал ожидания по зарплате"))
    elif salary_limited:
        factors.append(_f("salary", "limited", "Лимит сравнений вилки на сегодня исчерпан — кандидат увидит оценку сам"))
    elif salary_bucket(salary_cmp) * SALARY_STEP >= rounded_minimum(salary_min):
        factors.append(_f("salary", "ok", "Вилка в ожиданиях кандидата"))
    else:
        factors.append(_f("salary", "bad", "Верх вилки ниже ожиданий кандидата"))

    # ---- интерес к стеку
    need_tags = list(dict.fromkeys(i["tag"] for i in (req.get("stack_required") or []) + (req.get("stack_desired") or [])))
    explicit = [t for t in prefs.get("interest_tags") or [] if t in STACK]
    if explicit:
        interest, source = set(explicit), "ваших интересах" if me else "интересах кандидата"
    else:
        interest, source = set(declared_stack), "вашем стеке из опроса" if me else "стеке из опроса"
    if not need_tags:
        factors.append(_f("stack", "unknown", "Стек в предложении не указан"))
    elif not me and not privacy.get("show_stack", True):
        factors.append(_f("stack", "hidden", "Стек скрыт кандидатом"))
    elif not interest:
        factors.append(_f("stack", "unknown", "Интересы по стеку не указаны"))
    else:
        hit = [t for t in need_tags if t in interest]
        names = ", ".join(STACK.get(t, (t,))[0] for t in hit[:4]) + (" и др." if len(hit) > 4 else "")
        share = len(hit) / len(need_tags)
        st = "ok" if share >= 0.6 else "partial" if hit else "bad"
        text = (f"В {source} {len(hit)} из {len(need_tags)} технологий: {names}" if hit
                else f"Ни одной технологии предложения нет в {source}")
        factors.append(_f("stack", st, text))

    # ---- интерес к задачам
    tasks = detect_tasks(need_text)
    mine = [t for t in prefs.get("interest_tasks") or [] if t in TASKS]
    if not mine:
        factors.append(_f("tasks", "unknown", "Интерес к задачам не указан"))
    elif not tasks:
        factors.append(_f("tasks", "unknown", "Тип задач в тексте не распознан"))
    else:
        hit = [t for t in tasks if t["id"] in mine]
        if hit:
            factors.append(_f("tasks", "ok", f"Задачи {'из ваших интересов' if me else 'в интересах кандидата'}: "
                                             + ", ".join(f"{t['title'].lower()} («{t['quote']}»)" for t in hit[:2])))
        else:
            factors.append(_f("tasks", "partial", "Задачи предложения ("
                                                  + ", ".join(t["title"].lower() for t in tasks[:2])
                                                  + f") не из {'отмеченных вами' if me else 'отмеченных кандидатом'}"))

    # ---- готовность к предложениям
    status = prefs.get("offers_status")
    if status == "active":
        factors.append(_f("readiness", "ok", "Ищете работу активно" if me else "Ищет работу активно"))
    elif status == "open":
        factors.append(_f("readiness", "ok", "Открыты к предложениям" if me else "Открыт к предложениям"))
    elif status == "not_looking":
        factors.append(_f("readiness", "bad", "Вы отметили «сейчас не ищу»" if me else
                          "Сейчас не ищет — ответ менее вероятен"))
    else:
        factors.append(_f("readiness", "unknown", "Готовность к предложениям не указана"))

    return summarize(factors, audience)


def summarize(factors: list[dict], audience: str = "employer") -> dict:
    known = [f for f in factors if f["status"] in VALUE]
    wsum = sum(f["weight"] for f in known)
    by = {f["key"]: f["status"] for f in factors}
    veto = by.get("salary") == "bad" or by.get("format") == "bad" or by.get("location") == "bad"
    if wsum < MIN_KNOWN_WEIGHT and not veto:
        score, level = None, "unknown"
    else:
        score = round(sum(f["weight"] * VALUE[f["status"]] for f in known) / wsum, 3) if wsum else 0.0
        level = "high" if score >= 0.75 else "medium" if score >= 0.45 else "low"
        if veto:
            level = "low"
        elif level == "high" and (by.get("readiness") == "bad" or "partial" in (by.get("format"), by.get("location"))):
            level = "medium"  # не тот формат (но совместимый), переезд или «сейчас не ищу» — не выше «частично»
    order = sorted(factors, key=lambda f: ({"bad": 0, "partial": 2, "ok": 1}.get(f["status"], 3), -f["weight"]))
    shown = [f for f in order if f["status"] in VALUE and f.get("in_line", True)][:3] or [f for f in order if f["status"] != "unknown"][:1]
    parts = [f["text"] if i == 0 else f["text"][:1].lower() + f["text"][1:] for i, f in enumerate(shown)]
    line = "; ".join(parts) if parts else "Условия предложения и интересы кандидата не указаны"
    return {"algorithm": ALGORITHM, "level": level, "title": (LEVELS_ME if audience == "candidate" else LEVELS)[level],
            "score": score,
            "decline_risk": veto, "line": line, "factors": factors,
            "known_weight": round(wsum, 2)}


def mutual_order(results: list[dict], fits: dict[str, dict]) -> list[str]:
    """Порядок «с учётом интереса кандидата»: ярус статуса грейда → уровень (подходит / частично и мало данных /
    вероятно, откажет) → прежнее место match-v1. Скор подбора не меняется."""
    from app.modules.profiles.facts import GRADE_STATUS_ORDER

    def key(r: dict):
        lvl = (fits.get(r["ref"]) or {}).get("level", "unknown")
        return (GRADE_STATUS_ORDER.get(r.get("grade_status") or "confirmed", 0), LEVEL_ORDER[lvl], r.get("rank") or 0)

    return [r["ref"] for r in sorted(results, key=key)]
