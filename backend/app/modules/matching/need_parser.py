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
    find_unsupported_spans,
)
from app.modules.catalog import levels as grade_levels
from app.modules.catalog.seed_data import GRADE_ORDER as GRADES, GRADES_EXT, STACK
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
# Английские и разговорные написания (И18): «hybrid Moscow», «офис в Питере», «СПб»
CITY_ALIASES["Москва"] += ["Moscow", "Мск"]  # «офис в мск»; «по МСК» (часовой пояс) — не город, см. _city_matches
CITY_ALIASES["Санкт-Петербург"] += ["Saint Petersburg", "St. Petersburg", "СПб", "Питер", "Питере"]
CITY_ALIASES["Казань"] += ["Kazan"]


# ---------------------------------------------------------------- условия: формат работы и город (Ф2)
_FORMAT_RE = {
    "remote": re.compile(r"удал[её]нн\w*|удал[её]нк\w*|remote\w*|дистанцион\w*|из дома|work from home|\bwfh\b", re.I),
    "hybrid": re.compile(r"гибрид\w*|hybrid", re.I),
    "office": re.compile(r"(?<![\w-])офис\w*|(?<![\w-])office\b|on-?site|на(?:\s|\u00a0)месте работодателя", re.I),
}
_NOT_FORMAT_AFTER = re.compile(r"^\w*\s+(?:пакет|приложен|программ|техник|мебел|365|suite)"
                               r"|^офис\w*\s*(?:№\s*)?\d+(?![\d\s]*(?:дн|раз|day))", re.I)  # «офис 15» в адресе (Я11)
_NOT_FORMAT_BEFORE = re.compile(r"(?:\bms|microsoft|\bback|бэк|фронт|front)[\s-]*$", re.I)
_FMT_NEG_BEFORE = re.compile(r"(?:\bкроме|\bбез|\bисключая|\bexcept|\bno|\bnot|\bnon|\bне\s+(?:рассматрива\w*|предлага\w*)"
                         r"|(?<!\w)не)\s*(?:(?:полн\w*|чист\w*|full|fully)\s+)?[«\"]?$", re.I)
# Я11 (С3-1): «Удалёнка не предусмотрена», «удалённой работы нет», «удалённый формат у нас не практикуется»,
# «удалённо не работаем» — между упоминанием и отрицанием до двух служебных слов («работы», «формат», «у нас», «пока»)
_FMT_NEG_AFTER = re.compile(r"^[»\"]?\s*(?:[—–-]\s*|:\s*)?"
                        r"(?:(?:работ\w*|формат\w*|режим\w*|вариант\w*|у\s+нас|в\s+компании|пока|к\s+сожалению|"
                        r"сейчас|тоже|также)[\s,]+){0,2}"
                        r"(?:не\s+(?:рассматрива|предлага|подход|возможн|обсужда|вариант|интересн|допуска|предусм|"
                        r"практику|планиру|работа|получ|бывает|будет)|нет\b|отсутству|исключ|запрещ|невозможн|"
                        r"is not|not (?:possible|available|an option|offered))", re.I)
# «только офис», «работа исключительно из офиса», «строго on-site» — допустим только этот формат (Я11, С3-1)
_FMT_ONLY_BEFORE = re.compile(r"(?:\bтолько|\bисключительно|\bстрого|\bonly|\bstrictly)\s+(?:(?:в|из|на|in|from)\s+)?"
                              r"(?:(?:формат\w*|режим\w*)\s+)?[«\"]?$", re.I)
_HYBRID_DAYS = re.compile(r"(?:\d|один|два|две|три|четыре)\s*(?:дн\w*|раз\w*)\s+в\s+неделю[^.;\n]{0,30}(?:удал|офис|дома)"
                          r"|(?:удал|офис|дома)\w*[^.;\n]{0,30}?(?:\d|один|два|две|три|четыре)\s*(?:дн\w*|раз\w*)\s+в\s+неделю",
                          re.I)
_ANY_FORMAT = re.compile(r"любой\s+формат|формат(?:\s+работы)?\s*(?:[:—–-]\s*)?(?:любой|не важен|неважен)|any format"
                         r"|формат\s+на\s+(?:ваш|выбор)", re.I)


def format_mentions(text: str) -> list[tuple[str, int, int, bool]]:
    """Упоминания формата работы: (формат, начало, конец, отрицание) по порядку в тексте. «MS Office», «бэк-офис»,
    «офисный пакет» — не формат; «без удалёнки», «кроме офиса», «удалёнка не рассматривается» — отрицание."""
    out = []
    for fmt, rx in _FORMAT_RE.items():
        for m in rx.finditer(text):
            s, e = m.span()
            if fmt == "office" and (_NOT_FORMAT_AFTER.match(text[s:s + 40]) or _NOT_FORMAT_BEFORE.search(text[max(0, s - 12):s])):
                continue
            neg = bool(_FMT_NEG_BEFORE.search(text[max(0, s - 32):s]) or _FMT_NEG_AFTER.match(text[e:e + 60]))
            out.append((fmt, s, e, neg))
    out.sort(key=lambda x: x[1])
    # «гибридный график с офисом», «гибрид (3 дня офис / 2 дня удалённо)» — офис и удалёнка здесь описывают гибрид
    hyb = [(s, e) for f, s, e, _ in out if f == "hybrid"]
    return [m for m in out if m[0] == "hybrid" or not any(
        0 <= m[1] - he <= 45 and not re.search(r"[.;!?\n]", text[he:m[1]]) for _, he in hyb)]


def parse_conditions(text: str) -> dict:
    """Формат и город из текста потребности. Несколько допустимых форматов — объединение: «удалёнка или офис в Москве»
    = {удалённо} ∪ {офис/гибрид, Москва} (город — только для офиса и гибрида). «Любой формат» без исключений или
    формат не упомянут — условия нет; все три формата в тексте — условие показывается, но никого не скрывает. Возвращает work_format (первый допустимый по тексту), work_formats (если допустимых больше одного),
    city и цитаты."""
    mentions = format_mentions(text)
    pos = list(dict.fromkeys(f for f, _, _, neg in mentions if not neg))
    neg = {f for f, _, _, n in mentions if n} - set(pos)
    only = list(dict.fromkeys(f for f, s, _, n in mentions if not n and _FMT_ONLY_BEFORE.search(text[max(0, s - 30):s])))
    if only:  # «только офис»: остальные форматы исключены, даже если упомянуты без отрицания
        neg |= set(pos) - set(only)
        pos = only
        mentions = [m for m in mentions if m[0] in only]
    any_m = _ANY_FORMAT.search(text)
    if any_m and not neg:
        return {"work_format": None, "work_formats": None, "city": None, "format_span": None, "city_span": None,
                "formats_excluded": []}
    if any_m or (not pos and neg):
        allowed = [f for f in (pos or []) + ["office", "hybrid", "remote"] if f not in neg]
    else:
        allowed = pos
    allowed = list(dict.fromkeys(allowed))
    if not any_m and _HYBRID_DAYS.search(text) and allowed:
        allowed = ["hybrid", "office"]  # «офис, 2 дня в неделю удалённо» — это гибрид, а не «удалённо или офис»
    alt_city = _city_or_remote(text, mentions) if allowed == ["remote"] else None
    if alt_city:
        allowed += ["office", "hybrid"]  # «Казань или удалённо» — на месте в Казани или удалённо
    if "remote" in allowed and "office" in allowed and "hybrid" not in allowed:
        allowed.append("hybrid")  # удалённо или офис — гибрид между ними тоже подходит
    city, city_pos = alt_city or city_span(text, allowed)
    spans = [(s, e) for f, s, e, n in mentions if f in allowed and not n]
    if any_m and allowed:
        spans.append(any_m.span())
    span = None
    if spans:
        s0, e0 = min(spans)
        ends = [e for s, e in spans if s - e0 <= 60]
        span = (s0, max([e0, *ends]))
    return {"work_format": allowed[0] if allowed else None,
            "work_formats": allowed if len(allowed) > 1 else None,
            "city": city, "format_span": span, "city_span": city_pos,
            "formats_excluded": sorted({"office", "hybrid", "remote"} - set(allowed)) if allowed else sorted(neg)}


_TZ_BEFORE = re.compile(r"(?:\b(?:по|до|с)|\bврем\w*|\bчас\w*|\bграфик\w*|\d)[\s(]*$", re.I)


def _city_matches(text: str, alias: str):
    """Упоминания города; «мск» после «по», «времени», «график» или часа («10–19 по МСК») — часовой пояс, не город."""
    for m in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", text, re.I):
        if alias == "Мск" and _TZ_BEFORE.search(text[max(0, m.start() - 20):m.start()]):
            continue
        yield m


def _city_or_remote(text: str, mentions: list) -> tuple[str, tuple[int, int]] | None:
    """«Казань или удалённо», «удалённо или Москва»: город — альтернатива удалёнке, то есть работа на месте."""
    remote = [(s, e) for f, s, e, n in mentions if f == "remote" and not n]
    for city, aliases in CITY_ALIASES.items():
        for alias in aliases:
            for m in _city_matches(text, alias):
                for s, e in remote:
                    gap = text[m.end():s] if m.end() <= s else text[e:m.start()] if e <= m.start() else None
                    if gap is not None and re.fullmatch(r"[\s,]*(?:или|либо|or)\s+(?:в\s+|in\s+)?", gap, re.I):
                        return city, m.span()
    return None


def city_span(text: str, work_format) -> tuple[str | None, tuple[int, int] | None]:
    """Only an explicit office/hybrid location, never residence inferred from any other mention. work_format — формат
    или список допустимых форматов (Ф2: «удалёнка или офис в Москве» — город относится к офису)."""
    formats = work_format if isinstance(work_format, (list, tuple, set)) else [work_format]
    if not any(f in ("office", "hybrid") for f in formats):
        return None, None
    best = None
    for city, aliases in CITY_ALIASES.items():
        for alias in aliases:
            for m in _city_matches(text, alias):
                if re.search(r"офис|гибрид|office|hybrid|on-?site", text[max(0, m.start()-100):m.end()+80], re.I):
                    if best is None or m.start() < best[1][0]:
                        best = (city, m.span())
                    break
    return best if best else (None, None)


def tag_directions() -> dict[str, str | None]:
    return {t: v[2] for t, v in STACK.items()}


_SALARY_RE = re.compile(
    r"(?:от\s*)?(\d{2,3}(?:[\s\u00a0]?\d{3})?)\s*(к|k|тыс\.?|т\.\s?р\.?)?\s*(?:₽|руб\.?|р\.)?\s*(?:—|–|-|до)\s*"
    r"(\d{2,3}(?:[\s\u00a0]?\d{3})?)\s*(?:(к|k|тыс\.?|т\.\s?р\.?)\s*(?:₽|руб\w*|р\.)?|(?:₽|руб\w*|р\.))",
    re.IGNORECASE,
)
_EXP_RE = re.compile(r"(?:опыт\w*[^\n]{0,100}?|коммерческ\w*[^\n]{0,60}?|(?:Java|Go|Kotlin|PHP)\s+\w+\s+от\s*)"
                     r"(\d{1,2}(?:[.,]\d+)?)(?:\s*(?:до|[-–+])\s*(\d{1,2}(?:[.,]\d+)?))?"
                     r"(?:\s*[-–]?\s*[хx])?\+?\s*(год\w*|лет|месяц\w*)",
                     re.IGNORECASE)
_WORD_EXP_RE = re.compile(r"опыт\w*[^.\n]{0,90}?(?:от|не менее)\s+"
                          r"(полугода|года|одного|двух|трех|трёх|четырех|четырёх|пяти|полутора)\s*(?:лет|год\w*)?", re.I)
# «Опыт работы: не требуется», «опыт не требуется», «опыт не обязателен», «можно без опыта», «без опыта — научим»;
# «без опыта кандидаты не рассматриваются» — наоборот, не ноль (Я11, С3-2)
_ZERO_EXP_RE = re.compile(
    r"опыт(?:\s+работы)?\s*(?::\s*|[—–-]\s*)?(?:не\s+(?:требуется|обязателен|обязательно|нужен|важен|критичен|принципиален)"
    r"|необязателен)"
    r"|(?:можно|рассмотрим|рассматриваем|подойд\w*|возьм\w*|берём|берем|готовы\s+взять|ждём|ждем)[^.;\n]{0,40}?"
    r"без\s+опыта(?:\s+работы)?"
    r"|(?<![\w-])без\s+опыта(?:\s+работы)?(?=\s*(?:[.,;!)\n—–-]|$|тоже|также|можно|научим|подойд|подход|рассматрива))"
    r"(?![^.;\n]{0,30}\bне\s+(?:рассматр|подход|подойд|берём|берем|возьм))"
    r"|no\s+(?:prior\s+)?experience\s+(?:is\s+)?(?:required|needed)", re.I)
_TOTAL_EXP_RE = re.compile(r"(?:общий|суммарный)\s+опыт\s+(?:от\s*)?(\d+(?:[.,]\d+)?)\s*(?:лет|год)", re.I)
_REVERSE_EXP_RE = re.compile(r"(?:от\s*)?(\d+(?:[.,]\d+)?)\s*(?:[-–]\s*\d+)?\s*(?:лет|год\w*)"
                            r"\s+коммерческ\w*\s+(?:опыт\w*|разработ\w*)", re.I)
# «5+ лет опыта», «от 3 лет опыта в разработке», «3 года опыта» — число перед словом «опыт» (И18)
_FWD_EXP_RE = re.compile(r"(?:от\s*)?(\d{1,2}(?:[.,]\d+)?)\s*\+?\s*(?:лет|года?)\s+(?:опыт\w*|коммерческ\w*|в\s+разработк\w*)",
                         re.I)
_EXP_WORDS = {"полугода": 0.5, "года": 1, "одного": 1, "двух": 2, "трех": 3, "трёх": 3,
              "четырех": 4, "четырёх": 4, "пяти": 5, "полутора": 1.5}


def _money(num: str, suffix: str | None) -> int:
    v = int(re.sub(r"\D", "", num))
    if suffix and suffix.lower().startswith(("к", "k", "тыс", "т")):
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
# «200 000 - 250 000» без валюты: обе границы с группой «000» — почти наверняка вилка (И18)
_GROUPED_RANGE_RE = re.compile(r"(?<![\d.,])(\d{2,3}[\s\u00a0]000)\s*(?:—|–|-|до)\s*(\d{2,3}[\s\u00a0]000)(?![\d])")
# «… Екатеринбург. 150 000» — одно число с группой «000» отдельной фразой в конце предложения
_GROUPED_SINGLE_RE = re.compile(r"(?:^|[.;:\n]\s*)(\d{2,3}[\s\u00a0]000)\s*(?=[.;\n]|$)")
# «2,4 млн в год» — годовая сумма → в месяц
_ANNUAL_RE = re.compile(r"(?:(от|до)\s*)?(\d{1,2}(?:[.,]\d{1,2})?)\s*млн\.?\s*(?:₽|руб\w*|р\.)?\s*(?:в|/)\s*год",
                        re.IGNORECASE)
# Валюта не рубли: вилку не подставляем, но и не молчим
_FOREIGN_RE = re.compile(r"(?:[$€]\s?\d[\d\s\u00a0.,]*(?:k|к)?(?:\s*(?:—|–|-|до)\s*[$€]?\s?\d[\d\s\u00a0.,]*(?:k|к)?)?"
                         r"|\d[\d\s\u00a0.,]*(?:k|к)?\s*(?:—|–|-|до)?\s*(?:\d[\d\s\u00a0.,]*(?:k|к)?)?\s*"
                         r"(?:[$€]|usd|eur|долл\w*|евро)(?![a-zа-я]))", re.IGNORECASE)
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
    if _FOREIGN_RE.search(text) and not re.search(r"₽|руб|rub|тыс", text, re.I):
        return None, None, None  # вилка в долларах/евро — не выдаём её за рубли (подсказка — salary_note)
    if am := _ANNUAL_RE.search(text):
        v = int(round(float(am.group(2).replace(",", ".")) * 1_000_000 / 12, -3))
        if _ok(v):
            side = (am.group(1) or "").lower()
            return ((v, None) if side == "от" else (None, v) if side == "до" else (v, v)) + (am.span(),)
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
    if gr := _GROUPED_RANGE_RE.search(text):
        lo, hi = sorted((_money(gr.group(1), None), _money(gr.group(2), None)))
        if _ok(lo) and _ok(hi):
            return lo, hi, gr.span()
    for rx in (_SINGLE_RE, _KEYWORD_RE):
        for m_ in rx.finditer(text):
            v = _money(m_.group(1), m_.group(2) if rx is _SINGLE_RE else None)
            if _ok(v):
                if text[m_.end():m_.end() + 1] == "+":  # «350k+», «от 400к+» — нижняя граница, не точное значение
                    return v, None, (m_.start(), m_.end() + 1)
                return v, v, m_.span()
    if gs := _GROUPED_SINGLE_RE.search(text):
        v = _money(gs.group(1), None)
        if _ok(v):
            return v, v, gs.span(1)
    return None, None, None


def salary_note(text: str) -> dict | None:
    """Вилка не в рублях: не подставляем её, а честно говорим, что сравнить с рынком нельзя (И18)."""
    if re.search(r"₽|руб|rub|тыс", text, re.I):
        return None
    m = _FOREIGN_RE.search(text)
    if not m:
        return None
    return {"code": "currency", "text": "Вилка указана не в рублях — платформа сравнивает вилку с рынком категории в рублях. "
                                        "Укажите её в рублях вручную.", "evidence": _ev(text, m.span())}


def salary_is_net(text: str) -> bool:
    return bool(_NET_RE.search(text))


def parse_experience(text: str) -> float | None:
    return experience_span(text)[0]


def experience_span(text: str) -> tuple[float | None, tuple[int, int] | None]:
    clean = text.replace("*", " ").replace("`", " ")
    for m in _ZERO_EXP_RE.finditer(clean):  # «не возьмём без опыта» — не ноль (Я11)
        if not re.search(r"(?<![а-яё])(?:не(?:\s+\w+)?|нельзя)\s*$", clean[max(0, m.start() - 25):m.start()], re.I):
            return 0.0, m.span()
    if m := _TOTAL_EXP_RE.search(clean):
        return float(m.group(1).replace(",", ".")), m.span()
    if m := _REVERSE_EXP_RE.search(clean):
        return float(m.group(1).replace(",", ".")), m.span()
    for m in _EXP_RE.finditer(clean):
        # «опыт до 1 года» — верхняя граница (типично для Junior), а не «от»: минимума нет (И18)
        lead = clean[m.start():m.start(1)]
        if re.search(r"(?<![а-яё])до\s*$", lead, re.I) and not re.search(r"(?<![а-яё])от(?![а-яё])", lead, re.I):
            continue
        value = float(m.group(1).replace(",", "."))
        if m.group(3).lower().startswith("месяц"):
            value = round(value / 12, 4)
        return value, m.span()
    if m := _WORD_EXP_RE.search(clean):
        return float(_EXP_WORDS[m.group(1).lower()]), m.span()
    if m := _FWD_EXP_RE.search(clean):
        return float(m.group(1).replace(",", ".")), m.span()
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
            post = _postfix_desired(start, sent, current)
            if post:  # «Python, Django, Docker, k8s будет плюсом» — плюсом только k8s, остальное как было (И18)
                zones.extend(post)
                continue
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


def _postfix_desired(start: int, sent: str, default: str) -> list[tuple[int, int, str]] | None:
    """Предложение только с маркером «желательно», стоящим после технологий в своей части перечня: маркер относится
    к этой части, а не ко всему перечню слева. Маркер-префикс («Будет плюсом: Kafka, Redis») — None, как раньше."""
    parts, pos = [], 0
    for chunk in re.split(r"(?i)(?<!хорошо,)(?<=,)", sent):
        parts.append((start + pos, start + pos + len(chunk), chunk))
        pos += len(chunk)
    first = next((i for i, p in enumerate(parts) if _cue(p[2])[0] == "desired"), None)
    if first is None or first == 0 or _cue(parts[first][2])[1] or not any(find_stack(p[2]) for p in parts[:first]):
        return None
    return [(s, e, default if i < first else "desired" if i == first else default) for i, (s, e, _c) in enumerate(parts)]


_NEG_AFTER = re.compile(r"^[^,.;:\n]{0,25}?\bне\s+(?:нужен|нужна|нужно|нужны|требуется|требуются|обязател\w*|важ\w*|критич\w*)",
                        re.I)
_NEG_BEFORE = re.compile(r"(?:\bбез|\bне\s+(?:нужен|нужна|нужно|требуется|обязател\w*))\s+(?:коммерческ\w+\s+)?"
                         r"(?:опыт\w*\s+|знани\w*\s+)?(?:работы\s+)?(?:с\s+|на\s+)?$", re.I)


_NEG_BUT_PLUS = re.compile(r"^\s*,?\s*(?:но|однако|а)\s+(?:будет\s+)?(?:плюс|желательн|приветству|преимуществ)", re.I)


def negated_tags(text: str, spans: dict[str, tuple[int, int]]) -> dict[str, tuple[int, int]]:
    """Технологии, про которые сказано «не нужен», «без …», «не требуется …» → фрагмент с отрицанием (И18).
    «Докер не обязателен, но плюс» — не отрицание, а «желательно» (И27, Н1)."""
    out = {}
    for tag, (s, e) in spans.items():
        if (m := _NEG_AFTER.search(text[e:e + 60])) and not _NEG_BUT_PLUS.match(text[e + m.end():e + m.end() + 40]):
            out[tag] = (s, e + m.end())
        elif m := _NEG_BEFORE.search(text[max(0, s - 45):s]):
            out[tag] = (max(0, s - 45) + m.start(), e)
    return out


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


_DIR_NEG_BEFORE = re.compile(r"(?:\bбез|\bкроме|\bне\s+(?:нужен|нужна|нужно|требуется|ищем))\s+(?:\w+\s+)?$", re.I)


def negated_directions(text: str) -> str:
    """Текст для голосования направления: ключевые слова направления под отрицанием («фронтенд не нужен», «без
    фронтенда») заменены пробелами (позиции сохраняются) — отрицание не выбирает профессию (И27, Н1)."""
    low, out = text.lower(), list(text)
    for words in DIRECTION_KEYWORDS.values():
        for w in words:
            for m in re.finditer(re.escape(w), low):
                s, e = m.start(), m.end()
                while e < len(text) and text[e].isalpha():
                    e += 1
                neg = _NEG_AFTER.search(text[e:e + 60])
                if neg and not _NEG_BUT_PLUS.match(text[e + neg.end():e + neg.end() + 40]) \
                        or _DIR_NEG_BEFORE.search(text[max(0, s - 30):s]):
                    out[s:e] = " " * (e - s)
    return "".join(out)


# ---------------------------------------------------------------- веса навыков по перечислениям (Я11, С3-3)
ORDER_WEIGHT_RULE = ("Вес навыка — по правилу, одинаково для словаря и модели: обязательные — по порядку упоминания в "
                     "тексте: 1,0; 0,9; 0,8 … не ниже 0,6; общий навык (Git, SQL, Linux, Docker, HTTP, алгоритмы) — ×0,8: "
                     "он есть почти у всех; «желательно» — 0,3. Модель находит навыки и цитаты, вес не задаёт. Поправить "
                     "вес можно вручную.")
LIST_WEIGHT_RULE = ("Вес навыка — по правилу, одинаково для словаря и модели: навыки одного перечисления «обязательно» "
                    "(одно предложение или один список под заголовком) — один вес; первое перечисление — 1,0, каждое "
                    "следующее — на 0,1 ниже, не ниже 0,6; «желательно» — 0,3. Модель находит навыки и цитаты, вес "
                    "не задаёт. Поправить вес можно вручную.")
_BULLET = re.compile(r"^\s*(?:[-–—•*·▪●◦]|\d{1,2}[.)])\s+")


def list_weights_on() -> bool:
    """Флаг NEED_LIST_WEIGHTS (по умолчанию выключен): «1» — один вес на перечисление (LIST_WEIGHT_RULE), иначе —
    по порядку упоминания (ORDER_WEIGHT_RULE, прежнее правило). По умолчанию выключен: на бенчмарке MRR −0,005 в двух мирах
    (docs/LLM.md, раздел 10.4, «Замер»)."""
    import os

    return os.environ.get("NEED_LIST_WEIGHTS", "0").strip().lower() in ("1", "true", "yes", "on")


def weight_rule() -> str:
    """Текст действующего правила весов — для подсказки у весов в карточке потребности."""
    return LIST_WEIGHT_RULE if list_weights_on() else ORDER_WEIGHT_RULE


def enumerations(text: str) -> list[tuple[int, int]]:
    """Границы перечислений: предложение до «.», «!», «?» или конца строки (точка с запятой перечисление не
    рвёт); строки-пункты списка («- Python», «2) SQL») подряд и под заголовком с двоеточием — одно перечисление."""
    out: list[tuple[int, int]] = []
    pos, prev_joinable = 0, False
    for part in re.split(r"(?<=[.!?\n])", text):
        s, e = pos, pos + len(part)
        pos = e
        if not part.strip():
            continue
        bullet = bool(_BULLET.match(part))
        if out and bullet and prev_joinable:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
        prev_joinable = bullet or part.rstrip().endswith(":")
    return out


def apply_list_weights(text: str, required: list[dict], desired: list[dict]) -> None:
    """Веса по LIST_WEIGHT_RULE (на месте). Навык без цитаты (добавлен вручную) — с прежним весом."""
    bounds = enumerations(text)

    def group(it: dict) -> int | None:
        s = (it.get("evidence") or {}).get("start")
        if s is None:
            return None
        return next((i for i, (a, b) in enumerate(bounds) if a <= s < b), len(bounds))

    order = sorted({g for it in required if (g := group(it)) is not None})
    rank = {g: i for i, g in enumerate(order)}
    for it in required:
        g = group(it)
        if g is not None:
            it["weight"] = round(max(0.6, 1.0 - 0.1 * rank[g]), 2)
    for it in desired:
        if group(it) is not None:
            it["weight"] = 0.3


def apply_weights(text: str, required: list[dict], desired: list[dict]) -> None:
    """Веса по действующему правилу (weight_rule) на месте; навык без цитаты (добавлен вручную) — с прежним весом."""
    if list_weights_on():
        apply_list_weights(text, required, desired)
        return
    pos = [it for it in required if (it.get("evidence") or {}).get("start") is not None]
    for i, it in enumerate(sorted(pos, key=lambda it: it["evidence"]["start"])):
        it["weight"] = round(max(0.6, 1.0 - 0.1 * i) * (0.8 if it["tag"] in COMMON_TAGS else 1.0), 2)
    for it in desired:
        if (it.get("evidence") or {}).get("start") is not None:
            it["weight"] = 0.3


def parse_rules(text: str, hint_direction: str | None = None, hint_grade: str | None = None) -> dict:
    """Детерминированный разбор. Возвращает требования в каноническом виде (см. normalize) с цитатами.

    text должен быть уже очищен от дискриминационных фрагментов (bias.mask) — позиции совпадают с исходным."""
    spans = find_stack_spans(text)
    # «Kotlin, Spring» — Spring здесь не означает Java (И8: Kotlin ≠ Java); Java остаётся, если названа явно
    if "kotlin" in spans and "java" in spans and text[slice(*spans["java"])].lower().startswith("spring") \
            and not re.search(r"(?<![\w-])java(?![a-z])", text, re.I):
        spans.pop("java")
    excluded = negated_tags(text, spans)
    for t in excluded:
        spans.pop(t)
    tags = {t: sp[0] for t, sp in spans.items()}
    zones = _section_kind(text)
    dirs = tag_directions()

    def zone_of(pos: int) -> str:
        for s, e, k in zones:
            if s <= pos < e:
                return k
        return "neutral"

    # Направление: ключевые слова (вес 3) + голоса стек-тегов (вес 1); слова под отрицанием не голосуют
    dtext = negated_directions(text)
    dk = find_keys(dtext, DIRECTION_KEYWORDS)
    votes = {d: 3 * n for d, n in dk.items()}
    for t in tags:
        d = dirs.get(t)
        if d:
            votes[d] = votes.get(d, 0) + 1
    # Some public texts start with an introductory line and put the role on the next line.
    head = dtext[:200].split(":", 1)[0]
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
            ev["direction"] = _ev(text, find_key_span(dtext, DIRECTION_KEYWORDS[direction]), basis="keyword")
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
    if list_weights_on():
        apply_list_weights(text, required, desired)
    else:  # прежнее правило (флаг NEED_LIST_WEIGHTS=0): 1.0 → 0.6 по порядку упоминания, общий навык ×0.8
        for i, it in enumerate(required):
            w = max(0.6, 1.0 - 0.1 * i)
            if it["tag"] in COMMON_TAGS:
                w *= 0.8
            it["weight"] = round(w, 2)
        for it in desired:
            it["weight"] = 0.3

    cond = parse_conditions(text)  # Ф2: объединение форматов, отрицания, «любой формат»
    work_format, work_formats, city = cond["work_format"], cond["work_formats"], cond["city"]
    if work_format:
        ev["work_format"] = _ev(text, cond["format_span"])
    if city:
        ev["city"] = _ev(text, cond["city_span"])
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
    }, method="rules") | {"excluded": [{"tag": t, "evidence": _ev(text, sp)} for t, sp in excluded.items()]}


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
    for k in ("model", "confirmed_by"):  # И27: какая модель нашла цитату / подтвердила тег словаря
        if isinstance(ev.get(k), str) and ev[k].strip():
            out[k] = ev[k][:60]
    return out


def normalize(req: dict, method: str) -> dict:
    """Приводим к канону и выкидываем всё, чего нет в справочнике (защита от «фантазий» LLM)."""
    dirs = tag_directions()
    d = req.get("direction") if req.get("direction") in DIRECTIONS else None
    g = req.get("grade") if req.get("grade") in GRADES else None
    g_capped = None
    if GRADES_EXT and g:  # Lead/Principal — только там, где банк направления их проверяет (catalog.levels)
        g_top = grade_levels.cap(d, g)
        if g_top != g:
            g, g_capped = g_top, g
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
    } | ({"grade_capped_from": g_capped} if g_capped else {})


LLM_SYSTEM = (
    "Ты помогаешь структурировать описание вакансии в ИТ. Верни только JSON без пояснений: "
    '{"direction": одно из ["backend","frontend","data_ml","qa","security"] или null, '
    '"grade": одно из [' + ",".join(f'"{g}"' for g in GRADES) + '] или null (intern — стажёр, без опыта'
    + ('; lead — тимлид, техлид, архитектор; principal — principal или staff-инженер, главный архитектор' if GRADES_EXT
       else '') + '), '
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


# И27: короткий запрос-дельта — модели текст и то, что уже нашёл словарь; просим только недостающее и исправления
DELTA_SYSTEM = (
    "Ты проверяешь и дополняешь разбор описания вакансии в ИТ, который уже сделал словарь. Верни только JSON по "
    "схеме. stack_required (обязательно) и stack_desired («будет плюсом») — ТОЛЬКО технологии, которых нет в «уже "
    "найдено»: tag — идентификатор из списка, weight 0.1–1.0 (важность), quote — дословный фрагмент текста 2–8 слов. "
    "Сленг, опечатки и английские названия сопоставляй с идентификаторами (кафка → kafka, k8s → kubernetes, "
    "постгрес → postgresql). confirm — теги из «уже найдено», которые по тексту действительно требуются. remove — "
    "теги из «уже найдено», которые по тексту НЕ требуются (отрицание, пример, другая роль): reason — коротко, "
    "quote — фрагмент. unknown_required — обязательные требования (технологии, платформы, инструменты), которых НЕТ "
    "среди идентификаторов: term — название, quote — фрагмент; известное списку сюда не пиши. Тот же фрагмент, который "
    "словарь уже сопоставил с тегом, вторым тегом не дублируй (REST → http — rest-api к тому же «REST» не добавляй); "
    "технологию, которую фрагмент подразумевает отдельно (DRF → rest-api), добавляй. "
    "direction, grade, experience_years_min, work_format — только если словарь не нашёл (нет в "
    "«уже найдено») или ошибся, иначе null; quotes — дословные фрагменты для них. Без цитаты требование не указывай. "
    "Не извлекай требования к полу, возрасту, внешности, национальности, семье, религии и месту жительства. "
    "Идентификаторы тегов: {tags}."
)


def delta_schema() -> dict:
    """Жёсткая JSON-схема ответа-дельты (structured output OpenRouter): теги и значения — только из справочника."""
    tags = sorted(tag_directions())
    item = {"type": "object", "additionalProperties": False, "required": ["tag", "weight", "quote"],
            "properties": {"tag": {"type": "string", "enum": tags}, "weight": {"type": "number"},
                           "quote": {"type": "string"}}}
    opt = lambda values: {"anyOf": [{"type": "string", "enum": list(values)}, {"type": "null"}]}  # noqa: E731
    qs = ("direction", "grade", "experience_years_min", "work_format")
    schema = {"type": "object", "additionalProperties": False,
              "required": ["stack_required", "stack_desired", "confirm", "remove", "unknown_required", *qs, "quotes"],
              "properties": {
                  "stack_required": {"type": "array", "items": item},
                  "stack_desired": {"type": "array", "items": item},
                  "confirm": {"type": "array", "items": {"type": "string", "enum": tags}},
                  "remove": {"type": "array", "items": {
                      "type": "object", "additionalProperties": False, "required": ["tag", "reason", "quote"],
                      "properties": {"tag": {"type": "string", "enum": tags}, "reason": {"type": "string"},
                                     "quote": {"type": "string"}}}},
                  "unknown_required": {"type": "array", "items": {
                      "type": "object", "additionalProperties": False, "required": ["term", "quote"],
                      "properties": {"term": {"type": "string"}, "quote": {"type": "string"}}}},
                  "direction": opt(DIRECTIONS), "grade": opt(GRADES),
                  "experience_years_min": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                  "work_format": opt(("office", "hybrid", "remote")),
                  "quotes": {"type": "object", "additionalProperties": False, "required": list(qs),
                             "properties": {k: {"anyOf": [{"type": "string"}, {"type": "null"}]} for k in qs}}}}
    return {"type": "json_schema", "json_schema": {"name": "need_delta", "strict": True, "schema": schema}}


def _rules_summary(rules: dict) -> str:
    """«Уже найдено правилами» для запроса-дельты: только идентификаторы и значения справочника, без цитат и ПДн."""
    lines = [f"{k}: {rules[k]}" for k in ("direction", "grade", "experience_years_min", "work_format")
             if rules.get(k) is not None]
    if rules.get("work_formats"):
        lines.append(f"допустимые форматы работы: {', '.join(rules['work_formats'])}")
    for zone in ("stack_required", "stack_desired"):
        tags = [i["tag"] for i in rules.get(zone) or []]
        if tags:
            lines.append(f"{zone}: {', '.join(tags)}")
    excluded = [x["tag"] for x in rules.get("excluded") or []]
    if excluded:
        lines.append(f"исключено отрицанием в тексте (не добавлять): {', '.join(excluded)}")
    return "\n".join(lines) or "ничего"


def _call_llm(clean_text: str, rules: dict, full: bool = False):
    """Запрос к модели: дельта (по умолчанию, И27) или прежний полный разбор (mode=full)."""
    tags = ", ".join(sorted(tag_directions()))
    if full:
        return chat_json(LLM_SYSTEM.replace("{tags}", tags), clean_text[:6000],
                         func="parse_need", validate=lambda d: isinstance(d, dict), max_tokens=2500)
    user = f"ТЕКСТ ВАКАНСИИ:\n{clean_text[:6000]}\n\nУЖЕ НАЙДЕНО СЛОВАРЁМ:\n{_rules_summary(rules)}"
    return chat_json(DELTA_SYSTEM.replace("{tags}", tags), user, func="parse_need", max_tokens=900,
                     validate=lambda d: isinstance(d, dict), response_format=delta_schema())


def _llm_review(merged: dict, rules: dict, llm: dict, raw: dict, masked: str, hints: dict, label: str | None,
                replaced: set[str] = frozenset()) -> None:
    """И27: происхождение и предложения модели. Тег словаря, который модель подтвердила (confirm или тот же тег в
    ответе) — evidence.confirmed_by; «убрать тег» и несогласие со значением словаря — только предложения
    (llm_remove, llm_suggest), сами по себе в требования не попадают."""
    confirmed = {t for t in raw.get("confirm") or [] if isinstance(t, str)}
    confirmed |= {i["tag"] for i in llm["stack_required"] + llm["stack_desired"]}
    rule_tags = {i["tag"] for i in rules["stack_required"] + rules["stack_desired"]}
    for i in merged["stack_required"] + merged["stack_desired"]:
        if i["tag"] in confirmed and i["tag"] in rule_tags and i.get("evidence") and label:
            i["evidence"] = {**i["evidence"], "confirmed_by": label}
    remove = []
    for x in raw.get("remove") or []:
        # «убрать http» вместе с rest-api к тому же фрагменту «REST» — замена тега словаря, а не отрицание (Н4)
        if isinstance(x, dict) and x.get("tag") in rule_tags and x["tag"] not in confirmed and x["tag"] not in replaced:
            span = _locate(masked, x.get("quote"))
            remove.append({"tag": x["tag"], "reason": str(x.get("reason") or "")[:200],
                           "evidence": _ev(masked, span, source="llm") if span else None})
    suggest = []
    for key in ("direction", "grade", "experience_years_min", "work_format"):
        v = llm.get(key)
        if key == "work_format" and v in (rules.get("work_formats") or []):
            continue  # «офис или гибрид»: словарь уже принял несколько форматов — замена одним сузила бы условие
        if key == "work_format" and v in parse_conditions(masked)["formats_excluded"]:
            continue  # Я11: «удалёнка не предусмотрена» — формат, исключённый текстом, модель не предлагает
        if v is not None and not hints.get(key) and rules.get(key) is not None and v != rules[key] \
                and llm["evidence"].get(key):
            suggest.append({"field": key, "value": v, "current": rules[key], "evidence": llm["evidence"][key]})
    for e in [x["evidence"] for x in remove + suggest if x.get("evidence")]:
        e["model"] = label
    merged["llm_remove"], merged["llm_suggest"] = remove, suggest


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


def _unknown_from_model(text: str, items, known: set[str], taken: list[tuple[int, int]] = ()) -> list[dict]:
    """Требования вне справочника, которые назвала модель (И27, Н2): только с цитатой, найденной в тексте; термин,
    который словарь знает как тег, сюда не попадает. Сохраняются при записи потребности (источник llm)."""
    out = []
    stack_spans = list(find_stack_spans(text).values()) + list(taken)  # теги словаря и уже найденное вне его
    for u in items or []:
        if not isinstance(u, dict):
            continue
        term = re.sub(r"\s+", " ", str(u.get("term") or "")).strip()[:80]
        ev = u.get("evidence") if isinstance(u.get("evidence"), dict) else {}
        low = term.lower()
        if not term or any(k in low or low in k for k in known) or find_stack(term) or ev.get("source") != "llm":
            continue  # «1С:Предприятие» при найденном словарём «1С» — то же требование
        span = _locate(text, term) or _locate(text, ev.get("quote"))
        if span is None or any(s < span[1] and span[0] < e for s, e in stack_spans):
            continue
        known.add(term.lower())
        model = str(ev.get("model") or "")[:60]
        out.append({"term": term, "evidence": {**_ev(text, span, "llm"), **({"model": model} if model else {})}})
    return out[:8]


def text_notes(text: str, req: dict, extra: list | None = None) -> dict:
    """Что из текста не попало в подбор, — честно (И18): технологии вне справочника, исключённые отрицанием, вилка
    не в рублях. Считается по тексту и итоговым требованиям; в ранжирование не входит. extra — требования вне
    справочника, найденные моделью (И27): «вне справочника — проверить вручную», не теряются при сохранении."""
    masked = bias_filter.mask(text, bias_filter.find_bias(text))
    unknown = [{"term": name, "evidence": _ev(text, sp)}
               for name, sp in sorted(find_unsupported_spans(masked).items(), key=lambda kv: kv[1][0])][:12]
    unknown += _unknown_from_model(text, extra, {u["term"].lower() for u in unknown},
                                   [(u["evidence"]["start"], u["evidence"]["end"]) for u in unknown if u.get("evidence")])
    used = {i["tag"] for i in (req.get("stack_required") or []) + (req.get("stack_desired") or [])}
    excluded = [x for x in (req.get("excluded") or []) if isinstance(x, dict) and x.get("tag") in STACK
                and x["tag"] not in used]
    if not excluded and "excluded" not in req:
        excluded = [{"tag": t, "evidence": _ev(text, sp)} for t, sp in negated_tags(masked, find_stack_spans(masked)).items()
                    if t not in used]
    return {"unknown_terms": unknown, "excluded": excluded, "salary_note": salary_note(text)}


def parse_need(text: str, hint_direction: str | None = None, hint_grade: str | None = None,
               use_llm: bool = True, full: bool = False) -> dict:
    found = bias_filter.find_bias(text)
    masked = bias_filter.mask(text, found)  # из дискриминационных фрагментов ничего не извлекаем
    rules = parse_rules(masked, hint_direction, hint_grade)
    merged = rules
    if use_llm:
        merged = _merge_llm(masked, rules, hint_direction, hint_grade, full=full)
    merged = _with_quotes_from_original(merged, text)
    for x in (merged.get("llm_remove") or []) + (merged.get("llm_suggest") or []):  # И27: предложения модели
        if x.get("evidence"):
            x["evidence"] = {**x["evidence"], **_ev(text, (x["evidence"]["start"], x["evidence"]["end"]), "llm")}
    for x in rules.get("excluded") or []:
        x["evidence"] = _ev(text, (x["evidence"]["start"], x["evidence"]["end"])) if x.get("evidence") else None
    merged["excluded"] = rules.get("excluded") or []
    merged.update(text_notes(text, merged, extra=merged.pop("unknown_llm", None)))
    merged["bias"] = bias_filter.suggestions(found, merged)
    merged["suggested_text"] = bias_filter.rewrite(text, found, merged)
    from app.modules.matching.coverage import coverage

    cov = coverage(text)
    if cov:
        merged["coverage"] = cov
        if not hint_direction:
            merged["direction"] = cov["nearest_direction"]
            merged["evidence"]["direction"] = cov["evidence"]
    merged["weight_rule"] = weight_rule()  # Я11 (С3-3): правило весов — рядом с весами в карточке
    return merged


def _same_fragment(masked: str, item: dict, rules: dict) -> set[str]:
    """Новый тег модели, чья цитата накрывает фрагмент, уже сопоставленный словарём с другим тегом, а сам тег в цитате
    словарём не находится («проектирование REST» → rest-api при REST → http): это тот же фрагмент, не второе
    требование (И27, Н4). Возвращает теги словаря под цитатой (пусто — тег самостоятельный)."""
    ev = item.get("evidence") or {}
    s, e = ev.get("start"), ev.get("end")
    if s is None or e is None or item["tag"] in find_stack_spans(masked[s:e]):
        return set()
    return {i["tag"] for i in rules["stack_required"] + rules["stack_desired"]
            if (r := i.get("evidence") or {}).get("start") is not None and r["start"] < e and s < r["end"]}


def _merge_llm(masked: str, rules: dict, hint_direction: str | None, hint_grade: str | None,
               full: bool = False) -> dict:
    from app.modules.resume.pii import redact

    # Контакты и ФИО контактного лица из текста вакансии тоже не уходят наружу: NER — только имена из 2+ слов
    # (одиночные «Гибрид», «Андроид» NER принимает за имена), плюс имя после «HR:», «рекрутер —» и т. п.
    clean_text = redact(masked, use_ner=True, ner_min_tokens=2, contact_cues=True, header=False).text  # П1: шапка не ищется
    res = _call_llm(clean_text, rules, full)  # И27: вызов модели вынесен (кэш, фон)
    if not res.ok or not isinstance(res.data, dict):
        rules["llm"] = {"used": False, "reason": res.error, "attempts": res.attempts}
        return rules
    raw, dropped = _llm_requirements(res.data, masked)
    llm = normalize(raw, method="llm")
    merged = dict(rules)
    replaced: set[str] = set()
    same_fragment = 0
    ev = dict(rules.get("evidence") or {})
    # LLM уточняет направление/грейд, только если правила не справились или подсказки нет
    for key, hint in (("direction", hint_direction), ("grade", hint_grade)):
        merged[key] = hint or rules[key] or llm[key]
        if not hint and not rules[key] and llm[key] and llm["evidence"].get(key):
            ev[key] = llm["evidence"][key]
    if llm["stack_required"] or llm["stack_desired"]:
        # Объединяем: тег из правил сохраняет зону, цитату и вес; новые теги LLM — со своей цитатой
        by_tag = {i["tag"]: ("required", i) for i in rules["stack_required"]}
        by_tag.update({i["tag"]: ("desired", i) for i in rules["stack_desired"]})
        for zone, items in (("required", llm["stack_required"]), ("desired", llm["stack_desired"])):
            for i in items:
                over = _same_fragment(masked, i, rules) if i["tag"] not in by_tag else set()
                if over:  # Н4: «REST» словарь уже сопоставил с http — rest-api к тому же фрагменту не дублируем
                    replaced |= over
                    same_fragment += 1
                    continue
                if i["tag"] not in by_tag:  # Я11 (С3-3): у тега словаря вес не усредняется с весом модели (был 0,53)
                    by_tag[i["tag"]] = (zone, {**i, "status": "extracted"})
        merged["stack_required"] = [i for z, i in by_tag.values() if z == "required"]
        merged["stack_desired"] = [i for z, i in by_tag.values() if z == "desired"]
    for key in ("experience_years_min", "work_format"):
        # «Опыт работы: не требуется» — 0, а не «пусто»: значение словаря (в т. ч. 0) модель не перезаписывает,
        # её несогласие — предложение (llm_suggest); модель заполняет только то, чего словарь не нашёл (None)
        merged[key] = rules[key] if rules[key] is not None else llm[key]
        if rules[key] is None and llm[key] is not None and llm["evidence"].get(key):
            ev[key] = llm["evidence"][key]
    # Я11 (С3-3): навыкам, добавленным моделью, — вес по тому же правилу (weight_rule) по месту в тексте; навыки словаря
    # сохраняют свой вес
    rules_w = {i["tag"]: i["weight"] for i in rules["stack_required"] + rules["stack_desired"]}
    apply_weights(masked, merged["stack_required"], merged["stack_desired"])
    for i in merged["stack_required"] + merged["stack_desired"]:
        if i["tag"] in rules_w:
            i["weight"] = rules_w[i["tag"]]
    excluded = {x["tag"] for x in rules.get("excluded") or []}
    if excluded:  # «Angular не нужен»: тег, исключённый отрицанием в тексте, LLM обратно не добавляет (И18)
        merged["stack_required"] = [i for i in merged["stack_required"] if i["tag"] not in excluded]
        merged["stack_desired"] = [i for i in merged["stack_desired"] if i["tag"] not in excluded]
    merged["evidence"] = ev
    merged["method"] = "llm+rules"
    for e in [*ev.values(), *(i.get("evidence") for i in merged["stack_required"] + merged["stack_desired"])]:
        if e and e.get("source") == "llm" and res.label:
            e["model"] = res.label  # подпись у цитаты: какая модель её нашла
    _llm_review(merged, rules, llm, res.data, masked, {"direction": hint_direction, "grade": hint_grade}, res.label,
                replaced)
    merged["unknown_llm"] = [{"term": x.get("term"), "evidence": {"quote": x.get("quote"), "source": "llm",
                                                                  "model": res.label}}
                             for x in (res.data.get("unknown_required") or [])[:12] if isinstance(x, dict)]
    # Кто фактически ответил (цепочка провайдеров llm/client.py) — подпись в интерфейсе
    merged["llm"] = {"used": True, "latency_ms": res.latency_ms, "dropped_without_quote": dropped,
                     "same_fragment": same_fragment,
                     "provider": res.provider, "model": res.model, "model_label": res.label,
                     "fallback": len(res.attempts) > 1}
    return merged
