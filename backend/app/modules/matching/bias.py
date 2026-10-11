"""Фильтр дискриминационных требований в тексте потребности (ст. 64 ТК РФ).

Ст. 64 ТК РФ запрещает ограничения и преимущества при приёме на работу в зависимости от пола, расы, цвета кожи,
национальности, языка, происхождения, имущественного, семейного, социального и должностного положения, возраста,
места жительства (в том числе регистрации), отношения к религии, убеждений и других обстоятельств, не связанных
с деловыми качествами; отказывать женщинам по мотивам беременности или наличия детей тоже нельзя.

Что делает фильтр (детерминированно, без LLM — работает всегда):
* находит такие фрагменты и возвращает их с позицией в тексте, категорией и предложением переписать через навыки;
* маскирует их пробелами перед разбором требований: из них не извлекается ничего — ни грейд («не старше 35» не
  превращается в «senior»), ни стек, ни опыт; LLM их тоже не получает;
* предлагает исправленный текст: фрагменты убраны, добавлена фраза о навыках и уровне.

Ранжирование читает только направление, грейд, стек, опыт и формат (ranking.score_candidate), а о кандидате —
только подтверждённые факты T1/T2: пола, возраста и имени в нём нет. Это проверяет атака «Сменить пол, возраст и
имя» на странице /validation.
"""
from __future__ import annotations

import re

LAW = "ст. 64 ТК РФ"
CATEGORIES: dict[str, dict[str, str]] = {
    "age": {
        "title": "Возраст",
        "law": "Возраст не связан с деловыми качествами (ст. 64 ТК РФ)",
        "suggestion": "Вместо возраста опишите уровень и опыт: {level}{exp}.",
    },
    "gender": {
        "title": "Пол",
        "law": "Пол не связан с деловыми качествами (ст. 64 ТК РФ)",
        "suggestion": "Укажите задачи и навыки, а не пол: {skills}.",
    },
    "family": {
        "title": "Семейное положение и дети",
        "law": "Семейное положение и наличие детей не связаны с деловыми качествами (ст. 64 ТК РФ)",
        "suggestion": "Если важны график или командировки, напишите это прямо: «командировки раз в месяц», "
                      "«дежурства по графику».",
    },
    "appearance": {
        "title": "Внешность, раса, национальность, язык",
        "law": "Раса, национальность, происхождение и внешность не связаны с деловыми качествами (ст. 64 ТК РФ)",
        "suggestion": "Если нужен язык для работы, укажите задачу и уровень: «деловая переписка на английском, B2».",
    },
    "religion": {
        "title": "Религия и убеждения",
        "law": "Отношение к религии и убеждения не связаны с деловыми качествами (ст. 64 ТК РФ)",
        "suggestion": "Уберите это требование: оценивайте навыки — {skills}.",
    },
    "residence": {
        "title": "Место жительства и регистрация",
        "law": "Место жительства и регистрация не связаны с деловыми качествами (ст. 64 ТК РФ)",
        "suggestion": "Укажите формат и место работы: «офис в Москве, гибрид 2 дня в неделю» — регистрация не нужна.",
    },
    "other": {
        "title": "Обстоятельства, не связанные с деловыми качествами",
        "law": "Не связано с деловыми качествами (ст. 64 ТК РФ)",
        "suggestion": "Опишите, что важно для работы: {skills}.",
    },
}

_Y = r"(?:\s*(?:лет|года?|г\.))"
_AGE2 = r"(?:1[6-9]|[2-7]\d)"
_RAW: list[tuple[str, str]] = [
    # возраст
    ("age", rf"\bвозраст\w*\s*(?:[:—–-]\s*)?(?:от\s+{_AGE2}\s*)?(?:(?:до|не\s+старше|не\s+более)\s+)?{_AGE2}"
            rf"(?:\s*[-–—]\s*{_AGE2})?{_Y}?"),
    ("age", rf"\b(?:не\s+старше|не\s+моложе|моложе|младше)\s+{_AGE2}{_Y}?"),
    ("age", rf"\b(?:в\s+возрасте|возрастом)\s+(?:от\s+)?{_AGE2}(?:\s*(?:[-–—]|до)\s*{_AGE2})?{_Y}?"),
    ("age", rf"(?<![\w.,])(?:от\s+)?{_AGE2}\s*(?:[-–—]|до)\s*{_AGE2}\s*(?:лет|года)\b"),
    ("age", rf"\bдо\s+{_AGE2}\s*(?:лет|года)\b"),
    ("age", r"\bмолод(?:ой|ая|ую|ые|ых|ого|ому|ым|ыми|ом|ее|ёж\w*|еж\w*)\s+(?:(?:и|,)\s*\w+\s+)?"
            r"(?:коллектив\w*|команд\w*|специалист\w*|сотрудник\w*|люд\w*|кандидат\w*|разработчик\w*|человек\w*|"
            r"парн\w*|девушк\w*)"),
    ("age", r"\bмолод[её]жн\w*\s+(?:коллектив\w*|команд\w*)"),
    ("age", r"\b(?:пред)?пенсионн?\w*\s+возраст\w*|\bвозрастн\w*\s+(?:ограничени|ценз)\w*"),
    # пол
    ("gender", r"(?:\bтолько\s+|\bисключительно\s+)?\b(?:мужчин\w*|женщин\w*|девушк\w*|юнош\w*|парн(?:я|ей|и|ям|ями)\b|"
               r"парень\b)"),
    ("gender", r"\b(?:мужского|женского)\s+пола\b|\bпол\s*[:—–-]?\s*(?:мужской|женский)\b|"
               r"\b(?:мужск|женск)\w*\s+коллектив\w*"),
    # семья и дети
    ("family", r"\bбез\s+(?:маленьких\s+|малолетних\s+)?детей\b|\bбездетн\w*|"
               r"\b(?:нет|отсутстви\w*|наличи\w*)\s+(?:маленьких\s+|малолетних\s+)?детей\b"),
    ("family", r"\bне\s+(?:планиру\w*|собира\w*)\s+(?:\w+\s+){0,2}?(?:детей|декрет\w*|беременн\w*)|\bдекрет\w*|"
               r"\bбеременн\w*"),
    ("family", r"\bне\s+замужем\b|\bнезамужн\w*|\bхолост\w*|\bне\s+женат\w*|\bсемейн\w*\s+положени\w*"),
    # внешность, раса, национальность, язык
    ("appearance", r"\b(?:славянск|европейск|азиатск|кавказск|восточн)\w*\s+(?:внешност|национальност|"
                   r"происхожден)\w*|\bславянск\w*"),
    ("appearance", r"\b(?:(?:приятн|привлекательн|презентабельн)\w*\s+)?внешност\w*|\bнациональност\w*|"
                   r"\bцвет\w*\s+кожи|\bрас(?:а|ы|е|у|ой|ов\w*)\b|\bбез\s+акцента\b|\bрусск\w*\s+по\s+национальности"),
    # религия и убеждения
    ("religion", r"\bвероисповедан\w*|\b(?:православн|мусульман|иудей|католи[кч]|буддист|атеист)\w*|\bрелиги\w*"),
    # место жительства и регистрация
    ("residence", r"\b(?:с\s+)?(?:московск\w*\s+|постоянн\w*\s+|местн\w*\s+)?прописк\w*|"
                  r"\b(?:постоянн\w*\s+)?регистрац\w*\s+по\s+месту\s+(?:жительства|пребывания)|"
                  r"\b(?:постоянн\w*\s+)?регистрац\w*\s+в\s+(?:москв|московск|санкт|петербург|спб|област|"
                  r"город|регион)\w*|\bместн\w*\s+жител\w*|\bиногородн\w*|\bтолько\s+(?:жител\w*|москвич\w*)"),
    # прочее, не связанное с деловыми качествами
    ("other", r"\bбез\s+вредных\s+привычек|\bне\s*курящ\w*|\b(?:член\w*|состоящ\w*)\s+(?:в\s+)?(?:партии|профсоюз\w*)"),
]
_PATTERNS = [(cat, re.compile(rx, re.IGNORECASE)) for cat, rx in _RAW]
# Числа «до 20 лет», «25–35 лет» рядом с опытом/стажем — это опыт, а не возраст
_EXP_NEAR = re.compile(r"(?:опыт\w*|стаж\w*)[^.;\n]{0,40}$", re.IGNORECASE)
_EXP_AFTER = re.compile(r"^\s*(?:опыт\w*|стаж\w*|на\s+рынке|работы)", re.IGNORECASE)
_NUMERIC_AGE = {3, 4}  # индексы шаблонов возраста, которые совпадают и с опытом


def _is_experience(text: str, s: int, e: int) -> bool:
    return bool(_EXP_NEAR.search(text[max(0, s - 60):s]) or _EXP_AFTER.search(text[e:e + 20]))


def find_bias(text: str) -> list[dict]:
    """Фрагменты текста, нарушающие ст. 64 ТК РФ: [{category, title, start, end, quote, law}] по порядку."""
    spans: list[tuple[int, int, str]] = []
    for i, (cat, rx) in enumerate(_PATTERNS):
        for m in rx.finditer(text):
            s, e = m.start(), m.end()
            while e > s and text[e - 1] in " \t,.;:":
                e -= 1
            if e <= s:
                continue
            if i in _NUMERIC_AGE and _is_experience(text, s, e):
                continue
            spans.append((s, e, cat))
    spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    merged: list[list] = []
    for s, e, cat in spans:  # пересекающиеся фрагменты объединяем, категория — у первого (самого длинного)
        if merged and s < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
            continue
        merged.append([s, e, cat])
    return [{"category": cat, "title": CATEGORIES[cat]["title"], "start": s, "end": e, "quote": text[s:e],
             "law": CATEGORIES[cat]["law"]} for s, e, cat in merged]


def mask(text: str, findings: list[dict]) -> str:
    """Те же позиции, но фрагменты заменены пробелами: из них не извлекается ни одно требование."""
    out = list(text)
    for f in findings:
        for i in range(f["start"], f["end"]):
            if out[i] not in "\n.;!?":
                out[i] = " "
    return "".join(out)


_STOP = {"только", "исключительно", "и", "а", "также", "лет", "года", "год", "возраст", "возраста", "в", "во", "с",
         "со", "для", "на", "до", "от", "не", "без", "из", "к", "по", "кандидат", "кандидаты", "кандидатов", "ищем",
         "нужен", "нужна", "нужны", "требуется", "требуются", "желательно", "обязательно", "предпочтительно",
         "строго", "приглашаем", "берём", "берем", "рассматриваем", "лучше", "или", "либо", "можно"}
_TAIL_PREP = re.compile(r"(?:\s+|^)(?:в|во|с|со|для|из|на|к|и|а|до|от|без|или)\s*$", re.IGNORECASE)
_DROP = "\0DROP"
_HEAD_CONJ = re.compile(r"^\s*(?:и|а|или|также)\s+", re.IGNORECASE)


def _skills_phrase(req: dict) -> str:
    from app.modules.catalog.seed_data import tag_title

    tags = [tag_title(i["tag"]) for i in (req.get("stack_required") or [])[:4]]
    return ", ".join(tags) if tags else "ключевые навыки и задачи"


def _level_phrase(req: dict) -> str:
    from app.modules.catalog.seed_data import GRADES

    g = req.get("grade")
    return f"грейд {GRADES.get(g, g)}" if g else "нужный грейд"


def suggestions(findings: list[dict], req: dict) -> list[dict]:
    """Добавляет к находкам предложение переписать через навыки (с учётом разобранных требований)."""
    exp = req.get("experience_years_min")
    ctx = {"level": _level_phrase(req), "skills": _skills_phrase(req),
           "exp": f", опыт от {exp:g} лет" if exp else ", опыт в годах, если он важен"}
    return [{**f, "suggestion": CATEGORIES[f["category"]]["suggestion"].format(**ctx)} for f in findings]


def rewrite(text: str, findings: list[dict], req: dict) -> str | None:
    """Исправленный текст: дискриминационные фрагменты убраны, добавлена фраза об оценке по навыкам."""
    if not findings:
        return None
    pieces = re.split(r"([,;.!?\n]+)", text)
    out: list[str] = []
    pos = 0
    for i, piece in enumerate(pieces):
        start, end = pos, pos + len(piece)
        pos = end
        if i % 2 == 1:  # разделитель
            out.append(piece)
            continue
        hits = [f for f in findings if f["start"] < end and f["end"] > start]
        if not hits:
            out.append(piece)
            continue
        chars = list(piece)
        for f in hits:
            s, e = max(f["start"], start) - start, min(f["end"], end) - start
            pre = _TAIL_PREP.search("".join(chars[:s]))  # «в молодой коллектив» → убираем и предлог
            if pre and pre.group(0).strip():
                s = pre.start() + (len(pre.group(0)) - len(pre.group(0).lstrip()))
            for k in range(s, e):
                chars[k] = "\0"
        rest = re.sub(r"\s+", " ", "".join(c for c in chars if c != "\0")).strip()
        rest = _HEAD_CONJ.sub("", _TAIL_PREP.sub("", rest)).strip(" —–-:")
        words = [w for w in re.findall(r"[\wёЁ+#/-]+", rest.lower()) if w not in _STOP and not w.isdigit()]
        if not words:
            out.append(_DROP)
            continue
        lead = " " if piece[:1].isspace() else ""
        out.append(lead + rest)
    res: list[str] = []
    for x in out:  # выброшенную часть убираем вместе с запятой перед ней
        if x == _DROP:
            if res and re.fullmatch(r"\s*[,;]+\s*", res[-1]):
                res.pop()
            continue
        res.append(x)
    s = "".join(res)
    s = re.sub(r"\s+([,.;!?])", r"\1", s)
    s = re.sub(r"([,;])\s*([.!?])", r"\2", s)
    s = re.sub(r"([.!?])\s*[,;]+", r"\1", s)
    s = re.sub(r"[,;]{2,}", ",", s)
    s = re.sub(r"\.{2,}", ".", s)
    s = re.sub(r"^[\s,.;:—–-]+", "", s)
    s = re.sub(r"[ \t]{2,}", " ", s).strip()
    s = re.sub(r"(^|[.!?]\s+)([a-zа-яё])", lambda m: m.group(1) + m.group(2).upper(), s)
    if s and s[-1] not in ".!?":
        s += "."
    tail = f"Оцениваем по навыкам и уровню: {_level_phrase(req)}, {_skills_phrase(req)}."
    return f"{s} {tail}".strip()
