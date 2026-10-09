"""Ядро роли (Я1, 09.10): основной язык или определяющий фреймворк/навык потребности — обязательный признак подбора.

Зачем. Все три разметчика пакета v2 (модель, не люди) независимо отметили один класс ошибок match-v1: сильный кандидат
(высокий θ, всё прочее подтверждено) с ДРУГИМ основным языком или ядром роли — Java/PHP/C# на Senior Go, не-Python на
Python/FastAPI, DS/NLP без CV на CV — стоит высоко, хотя для нанимающего это «смежное направление».

Ядро — правилами и словарём, без LLM:
1. Берутся обязательные навыки потребности (stack_required) в порядке упоминания.
2. Словарь направлений (CORE_KINDS) говорит, что в этом направлении определяет роль:
   * Backend, QA, ИБ — основной язык (Python, Go, Java, Kotlin, C#, PHP, JavaScript, TypeScript);
   * Frontend — фреймворк (React, Vue, Angular; Next.js — семейство React): JavaScript, TypeScript, HTML/CSS —
     общая основа направления, роль не различают;
   * Data/ML — специализация (компьютерное зрение, NLP), если её нет — фреймворк глубокого обучения (PyTorch):
     Python и SQL — общая основа направления.
3. Ядро — все обязательные навыки первого подходящего вида: «Java или Kotlin» → любой из двух. SQL и HTML/CSS ядром
   не бывают. Если в обязательном ничего такого нет — ядра нет, признак не действует.

Состояние ядра у кандидата:
* confirmed — подтверждено тестом (T1, доля ≥ 0,5) само или через фреймворк этого языка (FastAPI → Python,
  Next.js → React; словарь IMPLIES);
* declared — заявлено кандидатом (T0), тестом не подтверждено (не проверялось или ниже порога);
* absent — не заявлено и не подтверждено (если тест проверял — ниже порога): «смежное направление».

«Нет данных» ≠ «не умеет»: если ядро в пуле подборки ни у кого не заявлено и не подтверждено, признак не действует.

Влияние на порядок — за флагом RANK_CORE_SKILL (RANK_CORE_SKILL=0 — прежний порядок match-v1.1). По умолчанию включён
с 09.10 после замера: make bench, v1-разметка и контроль на v2 (только на сервере) не хуже, см. docs/core_skill/README.md.
Политика (POLICY, выбрана замером, docs/core_skill/README.md):
* group — кандидаты без ядра (absent) идут отдельной группой ниже остальных внутри яруса статуса грейда: старше
  яруса обязательного (Ф2), из выдачи не выпадают, в шапке — причина;
* within — то же, но внутри яруса обязательного (младше его);
* cap — без ядра не выше места CAP_PLACE (потолок места), ниже — прежний порядок;
* penalty — минус PENALTY к баллу (сравнение — внутри яруса обязательного).
confirmed и declared различаются и без нового признака: подтверждённое ядро входит в балл (стек T1) и в ярус
обязательного, заявленное — нет.
"""
from __future__ import annotations

import os
import re

from app.modules.catalog.seed_data import STACK
from app.modules.profiles.facts import Bundle, skill_confirmed

FLAG = "RANK_CORE_SKILL"
POLICIES = ("group", "within", "cap", "penalty")
POLICY = "group"  # выбрано замером (bench + v1), см. docs/core_skill/README.md
CAP_PLACE = 10
PENALTY = 0.20

LANGUAGES = ("python", "go", "java", "kotlin", "csharp", "php", "javascript", "typescript")
FRONTEND_FRAMEWORKS = ("react", "vue", "angular", "nextjs")
ML_SPECIALIZATIONS = ("cv", "nlp")
ML_FRAMEWORKS = ("pytorch",)
# Направление → виды ядра по старшинству: (вид, теги, которые могут быть ядром, теги-основа направления — не ядро)
CORE_KINDS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "backend": (("language", LANGUAGES),),
    "qa": (("language", LANGUAGES),),
    "security": (("language", LANGUAGES),),
    "frontend": (("framework", FRONTEND_FRAMEWORKS),),
    "data_ml": (("specialization", ML_SPECIALIZATIONS), ("framework", ML_FRAMEWORKS)),
}
KIND_TITLE = {"language": "Основной язык роли", "framework": "Определяющий фреймворк роли",
              "specialization": "Определяющий навык роли"}
# Фреймворк подразумевает язык (или семейство): подтверждённый FastAPI — это подтверждённый Python
IMPLIES: dict[str, tuple[str, ...]] = {
    "python": ("fastapi", "django", "flask", "asyncio", "pytest", "pandas", "numpy", "scikit-learn", "pytorch"),
    "javascript": ("typescript", "react", "vue", "angular", "nextjs"),
    "react": ("nextjs",),
    "nextjs": ("react",),
}
STATE_ORDER = {"confirmed": 0, "declared": 1, "absent": 2}
FAMILY = {"nextjs": "react"}  # «React, Next.js» — одно ядро «React» (Next.js засчитывается через IMPLIES)
# «обучим React», «научим Go» — то, чему работодатель обещает научить, ядром роли не считается
_TEACH = re.compile(r"(обуч|научим|научит|будем учить|подучим|освоите|освоить|без опыта (?:в|с|на))", re.IGNORECASE)


def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "off", "")


def enabled() -> bool:
    return _flag(FLAG, "1")  # включён по умолчанию после замера (п. 7 карточки Я1); RANK_CORE_SKILL=0 — выключить


def _title(tag: str) -> str:
    return STACK.get(tag, (tag,))[0]


def _direction(req: dict) -> str | None:
    d = req.get("direction")
    if d:
        return d
    dirs = [STACK[i["tag"]][2] for i in req.get("stack_required") or [] if isinstance(i, dict) and i.get("tag") in STACK
            and STACK[i["tag"]][2]]
    return max(set(dirs), key=dirs.count) if dirs else None


def _taught(item: dict) -> bool:
    """Требование стоит в обороте «обучим …»: по контексту цитаты до самой цитаты (в пределах фрагмента)."""
    ev = item.get("evidence") or {}
    ctx, quote = ev.get("context") or "", ev.get("quote") or ""
    pos = ctx.find(quote) if quote else -1
    before = ctx[:pos] if pos >= 0 else ""
    before = re.split(r"[.;:!?]", before)[-1]  # только своё предложение/перечень
    return bool(_TEACH.search(before))


def role_core(req: dict) -> dict | None:
    """Ядро роли из потребности: {"kind", "tags", "title", "label"} или None — ядра нет (признак не действует)."""
    d = _direction(req)
    items = [i for i in req.get("stack_required") or [] if isinstance(i, dict) and i.get("tag")]
    must = [FAMILY.get(i["tag"], i["tag"]) for i in items if not _taught(i)]
    if not d or not must:
        return None
    for kind, allowed in CORE_KINDS.get(d, ()):
        tags = list(dict.fromkeys(t for t in must if t in allowed))
        if tags:
            return {"kind": kind, "tags": tags, "title": " или ".join(_title(t) for t in tags),
                    "label": KIND_TITLE[kind], "direction": d}
    return None


def state(b: Bundle, core: dict) -> dict:
    """Состояние ядра у кандидата: {"state", "via", "tested_low"}; via — тег, которым подтверждено/заявлено."""
    tags = core["tags"]
    implied = [x for t in tags for x in IMPLIES.get(t, ()) if x not in tags]
    for group in (tags, implied):
        for t in group:
            if skill_confirmed(b.skills_t1.get(t)):
                return {"state": "confirmed", "via": t, "implied": group is implied}
    declared = b.stack_t0
    tested_low = next((t for t in tags if b.skills_t1.get(t) is not None), None)
    for group in (tags, implied):
        for t in group:
            if t in declared:
                return {"state": "declared", "via": t, "implied": group is implied, "tested_low": tested_low}
    return {"state": "absent", "via": None, "implied": False, "tested_low": tested_low}


def text(core: dict, st: dict, active: bool, on: bool) -> str:
    """Строка объяснения: «подтверждён тестом», «заявлен — тестом не подтверждён», «не заявлен и не подтверждён»."""
    s, via = st["state"], st.get("via")
    if s == "confirmed":
        return "Подтверждён тестом" + (f" (через {_title(via)})" if st.get("implied") else "")
    if s == "declared":
        base = "Заявлен кандидатом" + (f" (через {_title(via)})" if st.get("implied") else "")
        tail = ("; тест проверял — ниже порога подтверждения" if st.get("tested_low") else
                ", тестом не подтверждён")
        return base + tail + " — можно проверить зондом"
    out = "Не заявлен и не подтверждён" + ("; тест проверял — ниже порога" if st.get("tested_low") else "") \
        + " — смежное направление"
    if not active:
        return out + ". В этой подборке ядро не заявлено ни у кого — на порядок не влияет"
    if on:
        return out + ". Кандидат в выдаче, но ниже тех, у кого ядро роли заявлено или подтверждено"
    return out


def available(bundles: list[Bundle], core: dict | None) -> bool:
    """Признак действует, только если ядро хоть у кого-то в пуле заявлено или подтверждено."""
    if not core:
        return False
    return any(state(b, core)["state"] != "absent" for b in bundles)


def assess_pool(bundles: list[Bundle], req: dict, on: bool | None = None) -> dict:
    """{user_id: {...}} для всех кандидатов пула: состояние ядра, строка объяснения, ключ порядка (0/1).
    При выключенном флаге key = 0 у всех (тексты остаются)."""
    on = enabled() if on is None else on
    core = role_core(req)
    if not core:
        return {}
    states = {b.profile.user_id: state(b, core) for b in bundles}
    active = any(s["state"] != "absent" for s in states.values())
    out = {}
    for b in bundles:
        st = states[b.profile.user_id]
        absent = st["state"] == "absent"
        out[b.profile.user_id] = {
            "kind": core["kind"], "label": core["label"], "title": core["title"], "tags": core["tags"],
            "state": st["state"], "via": _title(st["via"]) if st.get("via") else None,
            "implied": bool(st.get("implied")), "tested_low": bool(st.get("tested_low")), "active": active,
            "text": text(core, st, active, on), "key": int(on and active and absent),
            "headline": headline(core, st),
        }
    return out


def describe(b: Bundle, req: dict, active: bool = True, on: bool | None = None) -> dict | None:
    """Одна карточка без пула (карточка кандидата из подборки, сравнение): состояние и тексты; active — действует ли
    признак в подборке (по умолчанию да: пул неизвестен). None — у потребности нет ядра."""
    on = enabled() if on is None else on
    core = role_core(req)
    if not core:
        return None
    st = state(b, core)
    return {"kind": core["kind"], "label": core["label"], "title": core["title"], "tags": core["tags"],
            "state": st["state"], "via": _title(st["via"]) if st.get("via") else None, "implied": bool(st.get("implied")),
            "tested_low": bool(st.get("tested_low")), "active": active, "text": text(core, st, active, on),
            "key": int(on and active and st["state"] == "absent"), "headline": headline(core, st)}


def headline(core: dict, st: dict) -> str:
    """Короткая строка для шапки карточки и сравнения: «Основной язык роли — Go: не заявлен»."""
    word = {"confirmed": "подтверждён тестом", "declared": "заявлен, тестом не подтверждён",
            "absent": "не заявлен"}[st["state"]]
    return f"{core['label']} — {core['title']}: {word}"


def reason(info: dict) -> dict:
    """Строка в объяснении подборки (reasons) — как у требований: уровень и статус."""
    level = {"confirmed": "T1", "declared": "T0", "absent": "none"}[info["state"]]
    status = {"confirmed": "confirmed", "declared": "declared", "absent": "mismatch"}[info["state"]]
    return {"requirement": f"{info['label']}: {info['title']}", "level": level, "status": status, "core": True,
            "text": info["text"]}


def sort_key(grade_tier: int, must_tier: int, score: float, core_key: int, policy: str = POLICY) -> tuple:
    """Ключ сортировки до «рейтинг → ref»: (ярус статуса грейда, …, −балл). core_key = 1 — ядро отсутствует
    (и признак действует). cap — порядок без признака, потолок места — cap_positions (внутри яруса статуса грейда)."""
    if policy == "group":
        return (grade_tier, core_key, must_tier, -score)
    if policy == "within":
        return (grade_tier, must_tier, core_key, -score)
    if policy == "penalty":
        return (grade_tier, must_tier, -(score - PENALTY * core_key))
    return (grade_tier, must_tier, -score)


def cap_positions(absent: list[bool], cap: int = CAP_PLACE) -> list[int]:
    """Потолок места (policy = cap): индексы прежнего порядка в новом. Первые cap мест — первые cap кандидатов
    с ядром (заявлено или подтверждено), остальные — в прежнем порядке: кандидат без ядра не выше места cap + 1,
    пока кандидатов с ядром хватает."""
    head = [i for i, a in enumerate(absent) if not a][:cap]
    hs = set(head)
    return head + [i for i in range(len(absent)) if i not in hs]
