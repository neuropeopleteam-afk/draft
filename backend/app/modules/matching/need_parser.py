"""Потребность работодателя текстом → структурированные требования.

Основной путь — детерминированный (словарь стек-тегов и правила), он работает всегда.
Если настроен LLM, его ответ используется как уточнение, но проходит ту же нормализацию: неизвестные
теги отбрасываются, направление и грейд — только из справочника. Перед отправкой в LLM из текста
вырезаются контакты (почты, телефоны, ссылки) — см. resume.pii.
"""
from __future__ import annotations

import re

from app.modules.catalog.dictionary import (
    DESIRED_CUES,
    DIRECTION_KEYWORDS,
    GRADE_KEYWORDS,
    REQUIRED_CUES,
    WORK_FORMAT_KEYWORDS,
    find_keys,
    find_stack,
)
from app.modules.catalog.seed_data import STACK
from app.modules.llm.client import chat_json

DIRECTIONS = ("backend", "frontend", "data_ml", "qa", "security")
GRADES = ("junior", "middle", "senior")
COMMON_TAGS = {"algorithms", "sql", "http", "git", "linux", "docker"}


def tag_directions() -> dict[str, str | None]:
    return {t: v[2] for t, v in STACK.items()}


_SALARY_RE = re.compile(
    r"(?:от\s*)?(\d{2,3}(?:[\s\u00a0]?\d{3})?)\s*(к|k|тыс\.?)?\s*(?:₽|руб\.?|р\.)?\s*(?:—|–|-|до)\s*"
    r"(\d{2,3}(?:[\s\u00a0]?\d{3})?)\s*(?:(к|k|тыс\.?)\s*(?:₽|руб\w*|р\.)?|(?:₽|руб\w*|р\.))",
    re.IGNORECASE,
)
_EXP_RE = re.compile(r"(?:опыт\w*[^.\n]{0,40}?(?:от|не менее|более)?\s*)(\d{1,2})(?:\s*[-–+]\s*(\d{1,2}))?\+?\s*(?:год|лет)",
                     re.IGNORECASE)


def _money(num: str, suffix: str | None) -> int:
    v = int(re.sub(r"\D", "", num))
    if suffix and suffix.lower().startswith(("к", "k", "тыс")):
        v *= 1000
    elif v < 1000:
        v *= 1000
    return v


_NUM = r"(\d{2,3}(?:[\s\u00a0]\d{3})+|\d{2,7})"
_SUF = r"(?:(к|k|тыс\.?|тысяч\w*)(?![а-яёa-z]))"
_CUR = r"(?:₽|руб\w*|р\.|rub)"
_ONE_SIDE_RE = re.compile(rf"(от|до)\s*{_NUM}\s*(?:{_SUF}\s*{_CUR}?|{_CUR})", re.IGNORECASE)
# «Зарплата 260 000 ₽ на руки», «260 тыс. рублей», «180к»: одно значение с валютой или «к/тыс.»
_SINGLE_RE = re.compile(rf"(?<![\d.,–—-]){_NUM}\s*(?:{_SUF}\s*{_CUR}?|{_CUR})", re.IGNORECASE)
# «Зарплата: 250000», «оклад 180 000» — число без валюты, но сразу после слова о деньгах
_KEYWORD_RE = re.compile(rf"(?:зарплат\w*|оклад\w*|зп|з/п|доход\w*|вилк\w*|компенсац\w*)\s*[:—–-]?\s*(?:от\s*)?"
                         rf"(\d{{2,3}}(?:[\s\u00a0]\d{{3}})+|\d{{5,7}})(?!\s*(?:лет|год|%))", re.IGNORECASE)
_KEYWORD_RANGE_RE = re.compile(rf"(?:зарплат\w*|оклад\w*|зп|з/п|доход\w*|вилк\w*|компенсац\w*)\s*[:—–-]?\s*(?:от\s*)?"
                               rf"{_NUM}\s*{_SUF}?\s*(?:—|–|-|до)\s*{_NUM}\s*{_SUF}?", re.IGNORECASE)
_NET_RE = re.compile(r"на\s+руки|после\s+вычета|чистыми|\bnet\b", re.IGNORECASE)


def _ok(v: int) -> bool:
    return 10_000 <= v <= 5_000_000


def parse_salary(text: str) -> tuple[int | None, int | None]:
    """Вилка из текста: «220–300 тыс.», «от 200 до 250 тыс.», «до 300 000 рублей», «от 150к»,
    одно значение «Зарплата 260 000 ₽ на руки» / «260 тыс. рублей» / «180к» → (260000, 260000)."""
    m = _SALARY_RE.search(text)
    if m:
        lo, hi = _money(m.group(1), m.group(2) or m.group(4)), _money(m.group(3), m.group(4))
        if lo > hi:
            lo, hi = hi, lo
        if _ok(lo) and _ok(hi):
            return lo, hi
    kr = _KEYWORD_RANGE_RE.search(text)
    if kr:
        lo, hi = _money(kr.group(1), kr.group(2) or kr.group(4)), _money(kr.group(3), kr.group(4))
        lo, hi = min(lo, hi), max(lo, hi)
        if _ok(lo) and _ok(hi):
            return lo, hi
    one = _ONE_SIDE_RE.search(text)
    if one:
        v = _money(one.group(2), one.group(3))
        if _ok(v):
            return (v, None) if one.group(1).lower() == "от" else (None, v)
    for rx in (_SINGLE_RE, _KEYWORD_RE):
        for s in rx.finditer(text):
            v = _money(s.group(1), s.group(2) if rx is _SINGLE_RE else None)
            if _ok(v):
                return v, v
    return None, None


def salary_is_net(text: str) -> bool:
    return bool(_NET_RE.search(text))


def parse_experience(text: str) -> float | None:
    m = _EXP_RE.search(text)
    return float(m.group(1)) if m else None


def _sentences(text: str) -> list[tuple[int, int, str]]:
    out, pos = [], 0
    for part in re.split(r"(?<=[.!?;\n])", text):
        if part.strip():
            out.append((pos, pos + len(part), part))
        pos += len(part)
    return out


def _section_kind(text: str) -> list[tuple[int, int, str]]:
    """Размечаем текст на зоны «обязательно» / «желательно» по заголовкам и маркерам в предложениях."""
    zones = []
    current = "neutral"
    for start, end, sent in _sentences(text):
        low = sent.lower()
        if any(c in low for c in DESIRED_CUES):
            kind = "desired"
            current = "desired" if low.strip().endswith(":") else current
        elif any(c in low for c in REQUIRED_CUES):
            kind = "required"
            current = "required" if low.strip().endswith(":") else current
        else:
            kind = current
        zones.append((start, end, kind))
    return zones


def parse_rules(text: str, hint_direction: str | None = None, hint_grade: str | None = None) -> dict:
    """Детерминированный разбор. Возвращает требования в каноническом виде (см. normalize)."""
    tags = find_stack(text)
    zones = _section_kind(text)
    dirs = tag_directions()

    def zone_of(pos: int) -> str:
        for s, e, k in zones:
            if s <= pos < e:
                return k
        return "neutral"

    # Направление: ключевые слова (вес 3) + голоса стек-тегов (вес 1)
    votes = {d: 3 * n for d, n in find_keys(text, DIRECTION_KEYWORDS).items()}
    for t in tags:
        d = dirs.get(t)
        if d:
            votes[d] = votes.get(d, 0) + 1
    direction = hint_direction or (max(votes, key=votes.get) if votes else None)

    # Грейд: ключевые слова, иначе по требуемому опыту
    gk = find_keys(text, GRADE_KEYWORDS)
    exp = parse_experience(text)
    if hint_grade:
        grade = hint_grade
    elif gk:
        grade = max(gk, key=lambda g: (gk[g], GRADES.index(g)))
    elif exp is not None:
        grade = "junior" if exp < 1.5 else "middle" if exp < 4 else "senior"
    else:
        grade = None

    required, desired = [], []
    for t, pos in sorted(tags.items(), key=lambda kv: kv[1]):
        z = zone_of(pos)
        item = {"tag": t}
        if z == "desired":
            desired.append(item)
        else:
            required.append(item)
    # Веса: обязательные 1.0 → 0.6 по порядку упоминания (первое — важнее), общий блок ×0.8; желательные 0.3
    for i, it in enumerate(required):
        w = max(0.6, 1.0 - 0.1 * i)
        if it["tag"] in COMMON_TAGS:
            w *= 0.8
        it["weight"] = round(w, 2)
    for it in desired:
        it["weight"] = 0.3

    wf = find_keys(text, WORK_FORMAT_KEYWORDS)
    salary_from, salary_to = parse_salary(text)
    return normalize({
        "direction": direction,
        "grade": grade,
        "stack_required": required,
        "stack_desired": desired,
        "experience_years_min": exp,
        "work_format": max(wf, key=wf.get) if wf else None,
        "salary_from": salary_from,
        "salary_to": salary_to,
        "salary_net": salary_is_net(text) if (salary_from or salary_to) else None,
    }, method="rules")


def normalize(req: dict, method: str) -> dict:
    """Приводим к канону и выкидываем всё, чего нет в справочнике (защита от «фантазий» LLM)."""
    dirs = tag_directions()
    d = req.get("direction") if req.get("direction") in DIRECTIONS else None
    g = req.get("grade") if req.get("grade") in GRADES else None
    seen: set[str] = set()

    def clean(items, default_w) -> list[dict]:
        out = []
        for it in items or []:
            tag = it.get("tag") if isinstance(it, dict) else it
            if tag in dirs and tag not in seen:
                seen.add(tag)
                try:
                    w = float(it.get("weight", default_w)) if isinstance(it, dict) else default_w
                except (TypeError, ValueError):
                    w = default_w
                out.append({"tag": tag, "weight": round(min(max(w, 0.1), 1.0), 2)})
        return out

    required = clean(req.get("stack_required"), 1.0)
    desired = clean(req.get("stack_desired"), 0.3)
    wf = req.get("work_format") if req.get("work_format") in ("office", "hybrid", "remote") else None
    sf, st = req.get("salary_from"), req.get("salary_to")
    sf = sf if isinstance(sf, int) and sf > 0 else None
    st = st if isinstance(st, int) and st > 0 else None
    if sf and st and sf > st:  # одна сторона вилки допустима («от 200 тыс.», «до 300 000 ₽»)
        sf, st = st, sf
    exp = req.get("experience_years_min")
    return {
        "direction": d,
        "grade": g,
        "stack_required": required,
        "stack_desired": desired,
        "experience_years_min": float(exp) if isinstance(exp, (int, float)) else None,
        "work_format": wf,
        "salary_from": sf,
        "salary_to": st,
        "salary_net": bool(req.get("salary_net")) if (sf or st) else None,
        "method": method,
    }


LLM_SYSTEM = (
    "Ты помогаешь структурировать описание вакансии в ИТ. Верни только JSON без пояснений: "
    '{"direction": одно из ["backend","frontend","data_ml","qa","security"] или null, '
    '"grade": одно из ["junior","middle","senior"] или null, '
    '"stack_required": [{"tag": id, "weight": 0.1..1.0}], "stack_desired": [{"tag": id, "weight": 0.1..0.5}], '
    '"experience_years_min": число или null, "work_format": "office"|"hybrid"|"remote"|null}. '
    "Используй только идентификаторы стек-тегов из списка: {tags}. Обязательные — то, без чего кандидат не подходит; "
    "желательные — «будет плюсом». Вес отражает важность."
)


def parse_need(text: str, hint_direction: str | None = None, hint_grade: str | None = None,
               use_llm: bool = True) -> dict:
    rules = parse_rules(text, hint_direction, hint_grade)
    if not use_llm:
        return rules
    from app.modules.resume.pii import redact

    clean_text = redact(text, use_ner=False).text  # контакты из текста вакансии тоже не уходят наружу
    res = chat_json(LLM_SYSTEM.replace("{tags}", ", ".join(sorted(tag_directions()))), clean_text[:6000])
    if not res.ok or not isinstance(res.data, dict):
        rules["llm"] = {"used": False, "reason": res.error}
        return rules
    llm = normalize(res.data, method="llm")
    merged = dict(rules)
    # LLM уточняет направление/грейд, только если правила не справились или подсказки нет
    merged["direction"] = hint_direction or rules["direction"] or llm["direction"]
    merged["grade"] = hint_grade or rules["grade"] or llm["grade"]
    if llm["stack_required"] or llm["stack_desired"]:
        # Объединяем: тег из правил сохраняет зону, вес — среднее; новые теги LLM добавляются
        by_tag = {i["tag"]: ("required", i["weight"]) for i in rules["stack_required"]}
        by_tag.update({i["tag"]: ("desired", i["weight"]) for i in rules["stack_desired"]})
        for zone, items in (("required", llm["stack_required"]), ("desired", llm["stack_desired"])):
            for i in items:
                if i["tag"] in by_tag:
                    z, w = by_tag[i["tag"]]
                    by_tag[i["tag"]] = (z, round((w + i["weight"]) / 2, 2))
                else:
                    by_tag[i["tag"]] = (zone, i["weight"])
        merged["stack_required"] = [{"tag": t, "weight": w} for t, (z, w) in by_tag.items() if z == "required"]
        merged["stack_desired"] = [{"tag": t, "weight": w} for t, (z, w) in by_tag.items() if z == "desired"]
    merged["experience_years_min"] = rules["experience_years_min"] or llm["experience_years_min"]
    merged["work_format"] = rules["work_format"] or llm["work_format"]
    merged["method"] = "llm+rules"
    merged["llm"] = {"used": True, "latency_ms": res.latency_ms}
    return merged
