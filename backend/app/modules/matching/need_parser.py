"""Потребность работодателя текстом → структурированные требования.

Основной путь — детерминированный (словарь стек-тегов и правила), он работает всегда.
Если настроен LLM, его ответ используется как уточнение, но проходит ту же нормализацию: неизвестные
теги отбрасываются, направление и грейд — только из справочника. Перед отправкой в LLM из текста
вырезаются контакты (почты, телефоны, ссылки) — см. resume.pii.

Цитаты. У каждого извлечённого требования есть evidence — фрагмент исходного текста (start, end, quote), на
основании которого оно извлечено: у стек-тегов — в самом элементе, у направления, грейда, опыта, формата и
вилки — в req["evidence"]. Требование LLM без цитаты, которую можно найти в тексте, отбрасывается.
Работодатель подтверждает, правит или удаляет требование (status у тега, req["review"] у остальных).

Дискриминация (ст. 64 ТК РФ, модуль bias): фрагменты «до 35 лет», «только мужчины» и т. п. возвращаются в
req["bias"] с предложением переписать; перед разбором они маскируются — требований из них не извлекается.
"""
from __future__ import annotations

import re

from app.modules.catalog.dictionary import (
    DESIRED_CUES,
    DIRECTION_KEYWORDS,
    GRADE_KEYWORDS,
    REQUIRED_CUES,
    WORK_FORMAT_KEYWORDS,
    find_key_span,
    find_keys,
    find_stack,
    find_stack_spans,
)
from app.modules.catalog.seed_data import GRADE_ORDER as GRADES, STACK
from app.modules.llm.client import chat_json
from app.modules.matching import bias as bias_filter

DIRECTIONS = ("backend", "frontend", "data_ml", "qa", "security")
COMMON_TAGS = {"algorithms", "sql", "http", "git", "linux", "docker"}
CITY_ALIASES = {
    "Москва": ["Москва", "Москве", "Москвы"], "Санкт-Петербург": ["Санкт-Петербург", "Петербурге"],
    "Казань": ["Казань", "Казани"], "Новосибирск": ["Новосибирск", "Новосибирске"],
    "Екатеринбург": ["Екатеринбург", "Екатеринбурге"], "Нижний Новгород": ["Нижний Новгород", "Нижнем Новгороде"],
    "Томск": ["Томск", "Томске"], "Самара": ["Самара", "Самаре"], "Краснодар": ["Краснодар", "Краснодаре"],
    "Иннополис": ["Иннополис", "Иннополисе"], "Пермь": ["Пермь", "Перми"],
}


def city_span(text: str, work_format: str | None) -> tuple[str | None, tuple[int, int] | None]:
    """Only an explicit office/hybrid location, never residence inferred from any other mention."""
    if work_format not in ("office", "hybrid"):
        return None, None
    for city, aliases in CITY_ALIASES.items():
        for alias in aliases:
            m = re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text, re.I)
            if m and re.search(r"офис|гибрид", text[max(0, m.start()-100):m.end()+80], re.I):
                return city, m.span()
    return None, None


def tag_directions() -> dict[str, str | None]:
    return {t: v[2] for t, v in STACK.items()}


_SALARY_RE = re.compile(
    r"(?:от\s*)?(\d{2,3}(?:[\s\u00a0]?\d{3})?)\s*(к|k|тыс\.?)?\s*(?:₽|руб\.?|р\.)?\s*(?:—|–|-|до)\s*"
    r"(\d{2,3}(?:[\s\u00a0]?\d{3})?)\s*(?:(к|k|тыс\.?)\s*(?:₽|руб\w*|р\.)?|(?:₽|руб\w*|р\.))",
    re.IGNORECASE,
)
_EXP_RE = re.compile(r"(?:опыт\w*[^\n]{0,100}?|коммерческ\w*[^\n]{0,60}?|(?:Java|Go|Kotlin|PHP)\s+\w+\s+от\s*)"
                     r"(\d{1,2}(?:[.,]\d+)?)(?:\s*(?:до|[-–+])\s*(\d{1,2}(?:[.,]\d+)?))?"
                     r"(?:\s*[-–]?\s*[хx])?\+?\s*(год\w*|лет|месяц\w*)",
                     re.IGNORECASE)
_WORD_EXP_RE = re.compile(r"опыт\w*[^.\n]{0,90}?(?:от|не менее)\s+"
                          r"(года|одного|двух|трех|трёх|четырех|четырёх|пяти|полутора)\s*(?:лет|год\w*)?", re.I)
_ZERO_EXP_RE = re.compile(r"опыт\s+работы\s*:\s*не\s+требуется", re.I)
_TOTAL_EXP_RE = re.compile(r"(?:общий|суммарный)\s+опыт\s+(?:от\s*)?(\d+(?:[.,]\d+)?)\s*(?:лет|год)", re.I)
_REVERSE_EXP_RE = re.compile(r"(?:от\s*)?(\d+(?:[.,]\d+)?)\s*(?:[-–]\s*\d+)?\s*(?:лет|год\w*)"
                            r"\s+коммерческ\w*\s+(?:опыт\w*|разработ\w*)", re.I)
_EXP_WORDS = {"года": 1, "одного": 1, "двух": 2, "трех": 3, "трёх": 3,
              "четырех": 4, "четырёх": 4, "пяти": 5, "полутора": 1.5}


def _money(num: str, suffix: str | None) -> int:
    v = int(re.sub(r"\D", "", num))
    if suffix and suffix.lower().startswith(("к", "k", "тыс")):
        v *= 1000
    elif v < 1000:
        v *= 1000
    return v


_NUM = r"(\d{2,3}(?:[\s\u00a0,]\d{3})+|\d{2,7})"
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
_GENERAL_RANGE_RE = re.compile(rf"(?:от\s*)?{_NUM}\s*{_SUF}?\s*(?:₽|руб\w*|RUB)?\s*"
                               rf"(?:—|–|-|до)\s*{_NUM}\s*{_SUF}?\s*(?:₽|руб\w*|RUB)", re.I)


def _ok(v: int) -> bool:
    return 10_000 <= v <= 5_000_000


def parse_salary(text: str) -> tuple[int | None, int | None]:
    """Вилка из текста: «220–300 тыс.», «от 200 до 250 тыс.», «до 300 000 рублей», «от 150к»,
    одно значение «Зарплата 260 000 ₽ на руки» / «260 тыс. рублей» / «180к» → (260000, 260000)."""
    lo, hi, _span = parse_salary_span(text)
    return lo, hi


def parse_salary_span(text: str) -> tuple[int | None, int | None, tuple[int, int] | None]:
    """То же, что parse_salary, и позиция фрагмента с вилкой в тексте (для цитаты)."""
    # Remove display-only characters without changing evidence offsets.
    text = text.replace("\u200d", " ").replace("*", " ").replace("`", " ")
    m = _GENERAL_RANGE_RE.search(text) or _SALARY_RE.search(text)
    if m:
        lo, hi = _money(m.group(1), m.group(2) or m.group(4)), _money(m.group(3), m.group(4))
        if lo > hi:
            lo, hi = hi, lo
        if _ok(lo) and _ok(hi):
            return lo, hi, m.span()
    kr = _KEYWORD_RANGE_RE.search(text)
    if kr:
        lo, hi = _money(kr.group(1), kr.group(2) or kr.group(4)), _money(kr.group(3), kr.group(4))
        lo, hi = min(lo, hi), max(lo, hi)
        if _ok(lo) and _ok(hi):
            return lo, hi, kr.span()
    one = _ONE_SIDE_RE.search(text)
    if one:
        v = _money(one.group(2), one.group(3))
        if _ok(v):
            return ((v, None) if one.group(1).lower() == "от" else (None, v)) + (one.span(),)
    for rx in (_SINGLE_RE, _KEYWORD_RE):
        for m_ in rx.finditer(text):
            v = _money(m_.group(1), m_.group(2) if rx is _SINGLE_RE else None)
            if _ok(v):
                return v, v, m_.span()
    return None, None, None


def salary_is_net(text: str) -> bool:
    return bool(_NET_RE.search(text))


def parse_experience(text: str) -> float | None:
    return experience_span(text)[0]


def experience_span(text: str) -> tuple[float | None, tuple[int, int] | None]:
    clean = text.replace("*", " ").replace("`", " ")
    if m := _ZERO_EXP_RE.search(clean):
        return 0.0, m.span()
    if m := _TOTAL_EXP_RE.search(clean):
        return float(m.group(1).replace(",", ".")), m.span()
    if m := _REVERSE_EXP_RE.search(clean):
        return float(m.group(1).replace(",", ".")), m.span()
    if m := _EXP_RE.search(clean):
        value = float(m.group(1).replace(",", "."))
        if m.group(3).lower().startswith("месяц"):
            value = round(value / 12, 4)
        return value, m.span()
    if m := _WORD_EXP_RE.search(clean):
        return float(_EXP_WORDS[m.group(1).lower()]), m.span()
    return None, None


def _context(text: str, s: int, e: int) -> str:
    """Предложение (часть до «;»), в котором стоит цитата."""
    cs = max(text.rfind(c, 0, s) for c in ".!?;\n") + 1
    ce_all = [i for i in (text.find(c, e) for c in ".!?;\n") if i >= 0]
    ce = min(ce_all) + 1 if ce_all else len(text)
    return text[cs:ce].strip()[:240]


def _ev(text: str, span: tuple[int, int] | None, source: str = "rules", basis: str | None = None) -> dict | None:
    """Цитата: фрагмент исходного текста и предложение вокруг него (для подсветки и показа работодателю)."""
    if not span:
        return None
    s, e = span
    while e > s and text[e - 1] in " ,;:":
        e -= 1
    out = {"start": s, "end": e, "quote": text[s:e], "context": _context(text, s, e), "source": source}
    if basis:
        out["basis"] = basis
    return out


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
        if any(c in low for c in DESIRED_CUES) and any(c in low for c in REQUIRED_CUES):
            zones.extend(_mixed_zones(start, sent, current))  # «Python, FastAPI обязательно, Kafka будет плюсом»
            continue
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


def _cue(clause: str) -> tuple[str | None, bool]:
    """Маркер в части предложения: вид и стоит ли он перед технологиями (префикс) или после них (постфикс)."""
    low = clause.lower()
    for kind, cues in (("desired", DESIRED_CUES), ("required", REQUIRED_CUES)):
        pos = [low.find(c) for c in cues if c in low]
        if pos:
            return kind, not find_stack(clause[:min(pos)])
    return None, False


def _mixed_zones(start: int, sent: str, default: str) -> list[tuple[int, int, str]]:
    """Предложение с обоими маркерами делим по запятым. Часть без маркера наследует вид от ближайшего маркера-префикса
    слева («обязательно Python, FastAPI») или маркера-постфикса справа («Python, FastAPI обязательно»)."""
    parts, pos = [], 0
    for chunk in re.split(r"(?i)(?<!хорошо,)(?<=,)", sent):  # «хорошо, если» — один маркер
        parts.append((start + pos, start + pos + len(chunk), chunk, *_cue(chunk)))
        pos += len(chunk)
    out = []
    for i, (s, e, _c, kind, _prefix) in enumerate(parts):
        if kind is None:
            left = next((p for p in reversed(parts[:i]) if p[3]), None)
            right = next((p for p in parts[i + 1:] if p[3]), None)
            if left and left[4]:
                kind = left[3]
            elif right and not right[4]:
                kind = right[3]
            else:
                kind = default
        out.append((s, e, kind))
    return out


def parse_rules(text: str, hint_direction: str | None = None, hint_grade: str | None = None) -> dict:
    """Детерминированный разбор. Возвращает требования в каноническом виде (см. normalize) с цитатами.

    text должен быть уже очищен от дискриминационных фрагментов (bias.mask) — позиции совпадают с исходным."""
    spans = find_stack_spans(text)
    tags = {t: sp[0] for t, sp in spans.items()}
    zones = _section_kind(text)
    dirs = tag_directions()

    def zone_of(pos: int) -> str:
        for s, e, k in zones:
            if s <= pos < e:
                return k
        return "neutral"

    # Направление: ключевые слова (вес 3) + голоса стек-тегов (вес 1)
    dk = find_keys(text, DIRECTION_KEYWORDS)
    votes = {d: 3 * n for d, n in dk.items()}
    for t in tags:
        d = dirs.get(t)
        if d:
            votes[d] = votes.get(d, 0) + 1
    # Some public texts start with an introductory line and put the role on the next line.
    head = text[:200].split(":", 1)[0]
    title_dirs = find_keys(head, DIRECTION_KEYWORDS)
    if "qa" in title_dirs:
        title_dirs = {"qa": title_dirs["qa"]}
    # Incidental testing, models or interfaces in responsibilities do not change a developer's role.
    if (not title_dirs or not any(d in title_dirs for d in ("qa", "security"))) and re.search(
            r"(?:Go|Golang|Java|Kotlin|PHP|C#|\.NET)[ -]*(?:разработ|developer)|разработ\w*\s+(?:Go|Java|PHP)", head, re.I):
        title_dirs = {"backend": 1}
    elif not title_dirs:
        if re.search(r"\b(?:Go|Golang|Java|Kotlin|PHP)\b|C#|\.NET", head, re.I):
            title_dirs = {"backend": 1}
    direction = hint_direction or (max(title_dirs, key=title_dirs.get) if title_dirs else
                                   max(votes, key=votes.get) if votes else None)
    ev: dict[str, dict | None] = {}
    if direction and not hint_direction:
        if direction in title_dirs and find_key_span(head, DIRECTION_KEYWORDS[direction]):
            ev["direction"] = _ev(text, find_key_span(head, DIRECTION_KEYWORDS[direction]), basis="title")
        elif direction in dk:
            ev["direction"] = _ev(text, find_key_span(text, DIRECTION_KEYWORDS[direction]), basis="keyword")
        else:  # направление выведено по технологиям — цитата первой из них
            first = min((sp for t, sp in spans.items() if dirs.get(t) == direction), default=None)
            ev["direction"] = _ev(text, first, basis="stack")

    # Грейд: ключевые слова, иначе по требуемому опыту
    gk = find_keys(head, GRADE_KEYWORDS) or find_keys(text[:400], GRADE_KEYWORDS) or find_keys(text, GRADE_KEYWORDS)
    exp, exp_span = experience_span(text)
    if hint_grade:
        grade = hint_grade
    elif gk:
        grade = max(gk, key=lambda g: (gk[g], GRADES.index(g)))
        ev["grade"] = _ev(text, find_key_span(text, GRADE_KEYWORDS[grade]), basis="keyword")
    elif exp is not None:
        grade = "junior" if exp < 1.5 else "middle" if exp < 4 else "senior"
        ev["grade"] = _ev(text, exp_span, basis="experience")
    else:
        grade = None
    if exp_span:
        ev["experience_years_min"] = _ev(text, exp_span)

    required, desired = [], []
    for t, pos in sorted(tags.items(), key=lambda kv: kv[1]):
        z = zone_of(pos)
        item = {"tag": t, "evidence": _ev(text, spans[t], basis=z), "status": "extracted"}
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
    work_format = max(wf, key=wf.get) if wf else None
    work_formats = None
    if re.search(r"офис[^\n.!?]{0,45}или[^\n.!?]{0,20}гибрид|гибрид[^\n.!?]{0,45}или[^\n.!?]{0,20}офис",
                 text, re.I):
        work_formats = ["office", "hybrid"]
    if work_format:
        ev["work_format"] = _ev(text, find_key_span(text, WORK_FORMAT_KEYWORDS[work_format]))
    city, city_pos = city_span(text, work_format)
    if city:
        ev["city"] = _ev(text, city_pos)
    salary_from, salary_to, sal_span = parse_salary_span(text)
    if salary_from or salary_to:
        ev["salary"] = _ev(text, sal_span)
    return normalize({
        "direction": direction,
        "grade": grade,
        "stack_required": required,
        "stack_desired": desired,
        "experience_years_min": exp,
        "work_format": work_format,
        "work_formats": work_formats,
        "city": city,
        "salary_from": salary_from,
        "salary_to": salary_to,
        "salary_net": salary_is_net(text) if (salary_from or salary_to) else None,
        "evidence": ev,
    }, method="rules")


EVIDENCE_KEYS = ("direction", "grade", "experience_years_min", "work_format", "salary", "city")
ITEM_STATUSES = ("extracted", "confirmed", "edited", "manual")
REVIEW_STATUSES = ("extracted", "confirmed", "edited")


def clean_evidence(ev) -> dict | None:
    """Цитата в каноническом виде: только ожидаемые поля и разумные длины (данные могут прийти от клиента)."""
    if not isinstance(ev, dict) or not isinstance(ev.get("quote"), str) or not ev["quote"].strip():
        return None
    out = {"quote": ev["quote"][:300]}
    for k in ("start", "end"):
        if isinstance(ev.get(k), int) and not isinstance(ev.get(k), bool) and ev[k] >= 0:
            out[k] = ev[k]
    if isinstance(ev.get("context"), str):
        out["context"] = ev["context"][:300]
    out["source"] = ev.get("source") if ev.get("source") in ("rules", "llm") else "rules"
    if isinstance(ev.get("basis"), str):
        out["basis"] = ev["basis"][:30]
    return out


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
                item = {"tag": tag, "weight": round(min(max(w, 0.1), 1.0), 2)}
                if isinstance(it, dict):
                    ev = clean_evidence(it.get("evidence"))
                    if ev:
                        item["evidence"] = ev
                    st = it.get("status")
                    item["status"] = st if st in ITEM_STATUSES else ("extracted" if ev else "manual")
                out.append(item)
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
    city = req.get("city") if isinstance(req.get("city"), str) else None
    city = city.strip()[:100] if city and city.strip() else None
    present = {"direction": d, "grade": g, "experience_years_min": exp, "work_format": wf, "salary": sf or st, "city": city}
    raw_ev = req.get("evidence") if isinstance(req.get("evidence"), dict) else {}
    evidence = {k: clean_evidence(raw_ev.get(k)) for k in EVIDENCE_KEYS if present[k] is not None}
    raw_rv = req.get("review") if isinstance(req.get("review"), dict) else {}
    review = {k: raw_rv[k] for k in EVIDENCE_KEYS if present[k] is not None and raw_rv.get(k) in REVIEW_STATUSES}
    return {
        "direction": d,
        "grade": g,
        "stack_required": required,
        "stack_desired": desired,
        "experience_years_min": float(exp) if isinstance(exp, (int, float)) else None,
        "work_format": wf,
        "work_formats": [f for f in req.get("work_formats", []) or [] if f in ("office", "hybrid", "remote")] or None,
        "city": city,
        "salary_from": sf,
        "salary_to": st,
        "salary_net": bool(req.get("salary_net")) if (sf or st) else None,
        "evidence": {k: v for k, v in evidence.items() if v},
        "review": review,
        "method": method,
    }


LLM_SYSTEM = (
    "Ты помогаешь структурировать описание вакансии в ИТ. Верни только JSON без пояснений: "
    '{"direction": одно из ["backend","frontend","data_ml","qa","security"] или null, '
    '"grade": одно из ["intern","junior","middle","senior"] или null (intern — стажёр, без опыта), '
    '"stack_required": [{"tag": id, "weight": 0.1..1.0, "quote": "точный фрагмент текста"}], '
    '"stack_desired": [{"tag": id, "weight": 0.1..0.5, "quote": "точный фрагмент текста"}], '
    '"experience_years_min": число или null, "work_format": "office"|"hybrid"|"remote"|null, '
    '"quotes": {"direction": "фрагмент", "grade": "фрагмент", "experience_years_min": "фрагмент", '
    '"work_format": "фрагмент"}}. '
    "Используй только идентификаторы стек-тегов из списка: {tags}. Обязательные — то, без чего кандидат не подходит; "
    "желательные — «будет плюсом». Вес отражает важность. quote — дословный фрагмент исходного текста (2–8 слов), "
    "на основании которого извлечено требование; без такого фрагмента требование не указывай. "
    "Не извлекай требования к полу, возрасту, внешности, национальности, семье, религии и месту жительства."
)


def bias_report(text: str, req: dict) -> tuple[list[dict], str | None]:
    """Находки фильтра ст. 64 ТК РФ с предложениями и исправленный текст (или None, если нарушений нет)."""
    found = bias_filter.find_bias(text)
    return bias_filter.suggestions(found, req), bias_filter.rewrite(text, found, req)


def _locate(text: str, quote) -> tuple[int, int] | None:
    """Позиция дословной цитаты LLM в тексте (без учёта регистра и пробелов); нет — None."""
    if not isinstance(quote, str):
        return None
    words = re.findall(r"\S+", quote.strip().strip("«»\"'"))[:20]
    if not words:
        return None
    m = re.search(r"\s+".join(re.escape(w) for w in words), text, re.IGNORECASE)
    return m.span() if m else None


def _llm_requirements(raw: dict, masked: str) -> tuple[dict, int]:
    """Ответ LLM → требования с цитатами. Требование без цитаты, найденной в тексте, отбрасывается."""
    dropped = 0
    out = dict(raw)
    for key in ("stack_required", "stack_desired"):
        items = []
        for it in raw.get(key) or []:
            if not isinstance(it, dict):
                dropped += 1
                continue
            span = _locate(masked, it.get("quote"))
            if span is None:
                dropped += 1
                continue
            items.append({**it, "evidence": _ev(masked, span, source="llm")})
        out[key] = items
    quotes = raw.get("quotes") if isinstance(raw.get("quotes"), dict) else {}
    ev = {}
    for key in ("direction", "grade", "experience_years_min", "work_format"):
        if raw.get(key) is None:
            continue
        span = _locate(masked, quotes.get(key))
        if span is None:
            out[key] = None
            dropped += 1
        else:
            ev[key] = _ev(masked, span, source="llm")
    out["evidence"] = ev
    return out, dropped


def _with_quotes_from_original(req: dict, text: str) -> dict:
    """Цитаты строились по маскированному тексту — позиции те же, текст цитаты и контекст берём из исходного."""
    def fix(ev):
        if ev and "start" in ev and "end" in ev:
            ev["quote"] = text[ev["start"]:ev["end"]]
            ev["context"] = _context(text, ev["start"], ev["end"])
        return ev

    for key in ("stack_required", "stack_desired"):
        for it in req.get(key) or []:
            fix(it.get("evidence"))
    for ev in (req.get("evidence") or {}).values():
        fix(ev)
    return req


def parse_need(text: str, hint_direction: str | None = None, hint_grade: str | None = None,
               use_llm: bool = True) -> dict:
    found = bias_filter.find_bias(text)
    masked = bias_filter.mask(text, found)  # из дискриминационных фрагментов ничего не извлекаем
    rules = parse_rules(masked, hint_direction, hint_grade)
    merged = rules
    if use_llm:
        merged = _merge_llm(masked, rules, hint_direction, hint_grade)
    merged = _with_quotes_from_original(merged, text)
    merged["bias"] = bias_filter.suggestions(found, merged)
    merged["suggested_text"] = bias_filter.rewrite(text, found, merged)
    from app.modules.matching.coverage import coverage

    cov = coverage(text)
    if cov:
        merged["coverage"] = cov
        if not hint_direction:
            merged["direction"] = cov["nearest_direction"]
            merged["evidence"]["direction"] = cov["evidence"]
    return merged


def _merge_llm(masked: str, rules: dict, hint_direction: str | None, hint_grade: str | None) -> dict:
    from app.modules.resume.pii import redact

    # Контакты и ФИО контактного лица из текста вакансии тоже не уходят наружу: NER — только имена из 2+ слов
    # (одиночные «Гибрид», «Андроид» NER принимает за имена), плюс имя после «HR:», «рекрутер —» и т. п.
    clean_text = redact(masked, use_ner=True, ner_min_tokens=2, contact_cues=True).text
    res = chat_json(LLM_SYSTEM.replace("{tags}", ", ".join(sorted(tag_directions()))), clean_text[:6000],
                    func="parse_need", validate=lambda d: isinstance(d, dict), max_tokens=2500)
    if not res.ok or not isinstance(res.data, dict):
        rules["llm"] = {"used": False, "reason": res.error, "attempts": res.attempts}
        return rules
    raw, dropped = _llm_requirements(res.data, masked)
    llm = normalize(raw, method="llm")
    merged = dict(rules)
    ev = dict(rules.get("evidence") or {})
    # LLM уточняет направление/грейд, только если правила не справились или подсказки нет
    for key, hint in (("direction", hint_direction), ("grade", hint_grade)):
        merged[key] = hint or rules[key] or llm[key]
        if not hint and not rules[key] and llm[key] and llm["evidence"].get(key):
            ev[key] = llm["evidence"][key]
    if llm["stack_required"] or llm["stack_desired"]:
        # Объединяем: тег из правил сохраняет зону и цитату, вес — среднее; новые теги LLM — со своей цитатой
        by_tag = {i["tag"]: ("required", i) for i in rules["stack_required"]}
        by_tag.update({i["tag"]: ("desired", i) for i in rules["stack_desired"]})
        for zone, items in (("required", llm["stack_required"]), ("desired", llm["stack_desired"])):
            for i in items:
                if i["tag"] in by_tag:
                    z, cur = by_tag[i["tag"]]
                    by_tag[i["tag"]] = (z, {**cur, "weight": round((cur["weight"] + i["weight"]) / 2, 2)})
                else:
                    by_tag[i["tag"]] = (zone, {**i, "status": "extracted"})
        merged["stack_required"] = [i for z, i in by_tag.values() if z == "required"]
        merged["stack_desired"] = [i for z, i in by_tag.values() if z == "desired"]
    for key in ("experience_years_min", "work_format"):
        merged[key] = rules[key] or llm[key]
        if not rules[key] and llm[key] and llm["evidence"].get(key):
            ev[key] = llm["evidence"][key]
    merged["evidence"] = ev
    merged["method"] = "llm+rules"
    for e in [*ev.values(), *(i.get("evidence") for i in merged["stack_required"] + merged["stack_desired"])]:
        if e and e.get("source") == "llm" and res.label:
            e["model"] = res.label  # подпись у цитаты: какая модель её нашла
    # Кто фактически ответил (цепочка провайдеров llm/client.py) — подпись в интерфейсе
    merged["llm"] = {"used": True, "latency_ms": res.latency_ms, "dropped_without_quote": dropped,
                     "provider": res.provider, "model": res.model, "model_label": res.label,
                     "fallback": len(res.attempts) > 1}
    return merged
