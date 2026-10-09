"""Локальное вырезание персональных данных до любой отправки текста во внешние сервисы (LLM).

Слои (по порядку):
1. Регулярные выражения — почты, телефоны РФ и международные, ники и ссылки на мессенджеры и соцсети,
   даты рождения с подписью, ИНН/СНИЛС/паспорт, почтовые адреса (улица/дом/корпус/квартира/офис, индекс; город
   остаётся — он нужен подбору), возраст с подписью («мне 34 года», «Возраст: 34»).
2. Шапка резюме (первые 10 непустых строк, только header=True): дата без подписи → [дата], «34 года» → [возраст],
   «Мужчина/Женщина» → [пол]. Периоды («2019–2023», «03.2020 — н. в.») не трогаются.
3. Natasha (MIT, локальная модель NER, без сети) — имена людей (PER). Модель грузится лениво, один раз
   на процесс; если библиотека недоступна — остаются регулярки и эвристики.
4. Словари (resume/names.py): имя латиницей «Ivan Petrov» / «Petrov Ivan» (частые имена и транслит), одиночное имя
   рядом с контактом или глаголом связи («Ольга, [телефон]», «пишите Ольге в tg») → [имя]. Слова словаря стека
   («Spring Boot», «React Native», «Apache Kafka») именами не считаются.

Найденные значения возвращаются отдельно, чтобы кандидат мог перенести их в свой профиль (контакты
скрыты от работодателя до принятия приглашения). В БД сохраняется только текст с плейсхолдерами
и счётчики по типам.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import logging
import re
import threading

from app.modules.resume import names as NM

log = logging.getLogger("resume.pii")

_SP = r"[ \t\u00a0]"
_MONTHS_RU = r"(?:январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-я]*"
_MONTHS_EN = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_DATE_NUM = r"\d{1,2}[./\-]\d{1,2}[./\-](?:\d{4}|\d{2})(?![\d.])"
_DATE_WORD = (rf"\d{{1,2}}{_SP}+{_MONTHS_RU}{_SP}+(?:19|20)\d{{2}}(?:{_SP}*(?:г\.|года?)(?![а-яё]))?"
              rf"|\d{{1,2}}{_SP}+{_MONTHS_EN}{_SP}+(?:19|20)\d{{2}}|{_MONTHS_EN}{_SP}+\d{{1,2}},?{_SP}+(?:19|20)\d{{2}}")

# ---------------------------------------------------------------- адреса (город не режется)
_SNAME = r"(?:\d{1,3}(?:-?(?:я|й|го|ая|ий|ый|ое))?[ \t\u00a0]+)?[А-ЯЁ][а-яё]+(?:-[А-ЯЁа-яё][а-яё]*)*" \
         r"(?:[ \t\u00a0]+[А-ЯЁ][а-яё]+(?:-[А-ЯЁа-яё][а-яё]*)*){0,2}"
# номер дома без подписи — не «3 года», «5 дней», «150 тыс.»
_NOT_UNIT = rf"(?!{_SP}*(?:дн|лет|год|мес|раз|час|тыс|руб|₽|%|чел|минут|шт|км|м\b))"
_HOUSE = rf"(?:(?i:д|дом)\.?{_SP}*)?\d{{1,4}}(?:[а-яА-Я](?![а-яёА-ЯЁ]))?(?:/\d{{1,4}}(?:[а-я](?![а-яё]))?)?(?:-\d{{1,4}})?(?!\d){_NOT_UNIT}"
_UNIT = (rf"(?i:корп(?:ус)?\.?|к\.|стр(?:оение)?\.?|кв(?:артира)?\.?|оф(?:ис)?\.?|пом(?:ещение)?\.?|лит(?:ера?)?\.?|"
         rf"эт(?:аж)?\.?){_SP}*\d{{1,4}}(?:[а-яА-Я](?![а-яё]))?(?!\d)")
_TAIL = rf"(?:{_SP}*,?{_SP}*{_HOUSE})?(?:{_SP}*,?{_SP}*{_UNIT})*"
_TYPE_BEFORE = (r"(?i:(?:ул|пр-т|пр-кт|б-р|пр-д)\.?|(?:просп|пер|наб|пл|мкр|туп|ш|бул)\.|улица|проспект|переулок|бульвар|"
                r"набережная|шоссе|площадь|проезд|тупик|микрорайон|аллея)")
_ADJ = r"(?:[А-ЯЁ][а-яё]+[ \t\u00a0]+)?[А-ЯЁ][а-яё]+(?:ий|ый|ой|ая|ое|яя|ее|ья)"
ADDRESS_PATTERNS: list[re.Pattern] = [
    # индекс: «Индекс: 101000», «101000, г. Москва», в начале строки или после «Россия,» перед городом
    re.compile(r"(?i:индекс)[ \t]*:?[ \t]*[1-6]\d{5}(?!\d)"),
    re.compile(r"(?m)(?:^|(?<=Россия,\s)|(?<=РФ,\s)|(?<=Russia,\s))[ \t]*[1-6]\d{5}(?=[ \t]*,[ \t]*(?:г\.|город|[А-ЯЁA-Z]))"),
    re.compile(r"(?<![\d\w])[1-6]\d{5}(?=[ \t]*,[ \t]*(?:г\.|город\b))"),
    # «ул. Ленина, д. 5, кв. 3», «проспект Мира 10», «пер. Сивцев Вражек, 3, стр. 1»
    re.compile(rf"(?<![\w\-]){_TYPE_BEFORE}{_SP}*{_SNAME}{_TAIL}"),
    # «Ленинский пр-т, 45», «Пресненская наб., 12», «Варшавское ш.»
    re.compile(rf"(?<![\w\-]){_ADJ}{_SP}+(?i:(?:пр-т|пр-кт|б-р|пр-д)\.?|(?:просп|пер|наб|ш|ул|пл)\.|проспект|бульвар|набережная|"
               rf"переулок|улица)(?![\w]){_TAIL}"),
    # «Дмитровское шоссе, 9», «Новый проезд 3» — полные слова «шоссе/проезд/площадь» только с номером дома
    re.compile(rf"(?<![\w\-]){_ADJ}{_SP}+(?i:шоссе|проезд|площадь|аллея|тупик){_SP}*,?{_SP}*{_HOUSE}(?:{_SP}*,?{_SP}*{_UNIT})*"),
    # «д. 5, кв. 3» без улицы — только вместе с корпусом/квартирой/офисом
    re.compile(rf"(?<![\w.])(?i:д\.|дом){_SP}*\d{{1,4}}(?:[а-я](?![а-яё]))?(?:/\d{{1,4}})?(?:{_SP}*,?{_SP}*{_UNIT})+"),
]

PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("email", re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+", re.I), "[почта]"),
    ("url_messenger", re.compile(r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|wa\.me|vk\.com|vk\.ru|ok\.ru|instagram\.com|"
                                 r"facebook\.com|linkedin\.com/in|hh\.ru/resume|career\.habr\.com|github\.com|gitlab\.com|"
                                 r"habr\.com/(?:ru/|en/)?users|leetcode\.com/(?:u/)?|stackoverflow\.com/users|kaggle\.com|"
                                 r"codeforces\.com/profile|gitflic\.ru|x\.com|twitter\.com|behance\.net|dribbble\.com)"
                                 r"/[\w\-./?=&%]+", re.I), "[ссылка]"),
    ("phone", re.compile(r"(?<!\d)(?:\+7|8|\+\d{1,3})[\s\-\u00a0(]*\d{3}[\s\-\u00a0)]*\d{3}[\s\-\u00a0]*\d{2}[\s\-\u00a0]*\d{2}(?!\d)"),
     "[телефон]"),
    ("telegram", re.compile(r"(?:(?<=\s)|^|(?<=[(:,]))@[A-Za-z][\w]{3,31}\b"), "[ник]"),
    ("birthdate", re.compile(rf"(?:дата{_SP}+рождения|родил(?:ся|ась)|д\.{_SP}?р\.|date{_SP}+of{_SP}+birth|birth{_SP}*date|"
                              rf"birthday|born|dob)\s*:?\s*(?:{_DATE_WORD}|{_DATE_NUM})", re.I), "[дата рождения]"),
    ("snils", re.compile(r"\b\d{3}-\d{3}-\d{3}[\s-]\d{2}\b"), "[снилс]"),
    ("passport", re.compile(r"(?:паспорт\w*\s*:?\s*)\d{2}\s?\d{2}\s?\d{6}", re.I), "[паспорт]"),
    ("inn", re.compile(r"(?:инн\s*:?\s*)\d{10,12}", re.I), "[инн]"),
]
LABEL_HINTS = re.compile(r"^(?:фио|имя|name|кандидат)\s*[:\-]\s*", re.I)
# Текст вакансии: имя контактного лица после подсказки («HR: Ольга», «рекрутер — Пётр Сидоров»)
CONTACT_CUE = re.compile(r"(?:(?<=\s)|^)(?i:контактное\s+лицо|контакт|hr(?:-менеджер|-партн[её]р)?|рекрутер|"
                         r"менеджер\s+по\s+подбору|нанимающий\s+менеджер|пишите|звоните|обращаться\s+к)\b"
                         r"\s*[:—–\-]?\s*([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){0,2})(?![\w-])", re.M)


@dataclass
class Redaction:
    text: str
    found: dict[str, list[str]] = field(default_factory=dict)  # тип → значения (не сохраняются в БД)
    ner_used: bool = False

    @property
    def summary(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.found.items() if v}


_ner_lock = threading.Lock()
_ner: tuple | None = None
_ner_failed = False


def _get_ner():
    global _ner, _ner_failed
    if _ner is not None or _ner_failed:
        return _ner
    with _ner_lock:
        if _ner is None and not _ner_failed:
            try:
                from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter  # noqa: F401

                emb = NewsEmbedding()
                _ner = (Segmenter(), NewsNERTagger(emb))
            except Exception:  # noqa: BLE001 — без NER работаем на регулярках
                log.exception("Natasha недоступна, вырезание ФИО только эвристиками")
                _ner_failed = True
    return _ner


def _ner_persons(text: str) -> list[tuple[int, int, str]]:
    ner = _get_ner()
    if ner is None:
        return []
    from natasha import Doc

    seg, tagger = ner
    out = []
    # NER на длинных текстах медленный — обрабатываем кусками
    for offset in range(0, len(text), 4000):
        chunk = text[offset : offset + 4000]
        doc = Doc(chunk)
        doc.segment(seg)
        doc.tag_ner(tagger)
        for sp in doc.spans:
            if sp.type != "PER":
                continue
            # Спаны не должны пересекать строки: «Иванов Иван\nPython-разработчик» → «Иванов Иван»
            val = sp.text.split("\n")[0].rstrip(" ,;")
            if not val or not val[0].isupper() or len(val) < 3:
                continue
            out.append((offset + sp.start, offset + sp.start + len(val), val))
    return out


_NAME_LINE = re.compile(r"^\s*([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s*$")
_NAME_LINE_EN = re.compile(r"^\s*([A-Z][a-z]+(?:-[A-Z][a-z]+)?\s+[A-Z][a-z]+(?:-[A-Z][a-z]+)?(?:\s+[A-Z][a-z]+)?)\s*$")

# ---------------------------------------------------------------- адрес с подписью: «Адрес: Москва, Ленина 5-3»
ADDRESS_LABEL = re.compile(r"(?im)^([ \t]*(?:адрес[а-я]*(?:[ \t]+[а-яё]+){0,2}|address|home[ \t]+address|место[ \t]+жительства|"
                           r"проживаю|проживает|проживание|прописка)[ \t]*[:\-—–][ \t]*)([^\n]+)$")
_REGION = re.compile(r"(?i:\b(?:область|обл\.|край|республика|респ\.|округ)\b)")
_CITY_HEAD = re.compile(r"^(?:(?:г\.|город)[ \t]*)?([А-ЯЁA-Z][а-яёa-z]+(?:[- ][А-ЯЁа-яё][а-яё]+){0,2})")


def _city_part(p: str) -> str | None:
    """Часть адреса, которую оставляем: город («г. Москва», «Казань»), страна, регион. Иначе None."""
    if p.lower() in {"россия", "рф", "russia", "российская федерация"} or _REGION.search(p) and not re.search(r"\d", p):
        return p
    m = _CITY_HEAD.match(p)
    if not m:
        return None
    if p.lower().startswith(("г.", "город")) or m.group(1).lower() in NM.city_words():
        return m.group(0).strip()
    return None


def _address_labels(out: str, found: dict) -> str:
    def repl(m: re.Match) -> str:
        val = m.group(2)
        parts = [x.strip() for x in val.split(",") if x.strip()]
        keep, cut = [], False
        for part in parts:
            c = _city_part(part)
            if c is not None and c not in keep:
                keep.append(c)
                cut = cut or c != part
            elif part != "[адрес]" or not cut:
                cut = True
        if not cut:
            return m.group(0)
        found.setdefault("address", []).append(val.strip())
        return m.group(1) + ", ".join(keep + ["[адрес]"])

    return ADDRESS_LABEL.sub(repl, out)


# ---------------------------------------------------------------- возраст и шапка резюме
AGE_CUES = [
    re.compile(rf"(?i:возраст){_SP}*[:\-—–]?{_SP}*(\d{{2}})(?:{_SP}*(?:год|года|лет)(?![а-яё]))?"),
    re.compile(rf"(?<![\w])(?i:age){_SP}*[:\-—–]{_SP}*(\d{{2}})"),
    re.compile(rf"(?<![\w])(?i:мне){_SP}+(\d{{2}}){_SP}*(?:год|года|лет)(?![а-яё])"),
    re.compile(rf"(?<![\d.,])(\d{{2}}){_SP}*(?i:y\.?{_SP}?o\.?|years?{_SP}+old)(?![a-z])"),
]
_HEAD_AGE = re.compile(rf"(?<![\d.,:/\-–—])(\d{{2}}){_SP}*(?:год|года|лет)(?![а-яё])")
_AGE_NOT_BEFORE = re.compile(r"(?i:опыт|стаж|experience|работ|более|менее|свыше|больше|меньше|около|\bот|\bдо)")
_HEAD_DATE = re.compile(rf"(?<![\d./\-])(?:{_DATE_WORD}|\d{{1,2}}[./\-]\d{{1,2}}[./\-](?:19|20)\d{{2}}(?![\d.]))")
_RANGE_NEAR = re.compile(r"[-–—]|(?<![а-яё])(?:по|до|н\.\s?в|наст|present|now|сейчас)(?![а-яё])", re.I)
_GENDER = re.compile(r"^([ \t]*)(Мужчина|Женщина|Male|Female)(?=[ \t]*(?:,|$))", re.M)
HEADER_LINES = 10


def _age_cues(out: str, found: dict) -> str:
    for pat in AGE_CUES:
        def repl(m: re.Match) -> str:
            if not 14 <= int(m.group(1)) <= 90:
                return m.group(0)
            found.setdefault("age", []).append(m.group(0).strip())
            return m.group(0)[: m.start(1) - m.start(0)] + "[возраст]" if pat is not AGE_CUES[3] else "[возраст]"
        out = pat.sub(repl, out)
    return out


def _header(out: str, found: dict, today: date | None = None) -> str:
    """Шапка резюме: дата без подписи → [дата], «34 года» → [возраст], пол → [пол]. Только первые 10 непустых строк."""
    year_max = (today or date.today()).year - 14
    lines = out.split("\n")
    seen = 0
    for i, line in enumerate(lines):
        if seen >= HEADER_LINES:
            break
        if not line.strip():
            continue
        seen += 1
        line = _GENDER.sub(lambda m: (found.setdefault("gender", []).append(m.group(2)), m.group(1) + "[пол]")[1], line)

        def date_repl(m: re.Match, ln: str = line) -> str:
            year = int(re.findall(r"(?:19|20)\d{2}", m.group(0))[-1])
            before, after = ln[max(0, m.start() - 6): m.start()], ln[m.end(): m.end() + 8]
            if not 1930 <= year <= year_max or _RANGE_NEAR.search(before) or _RANGE_NEAR.search(after):
                return m.group(0)  # период работы/учёбы или слишком поздний год — не дата рождения
            found.setdefault("birthdate", []).append(m.group(0))
            return "[дата]"
        line = _HEAD_DATE.sub(date_repl, line)

        def age_repl(m: re.Match, ln: str = line) -> str:
            n = int(m.group(1))
            before, after = ln[: m.start()], ln[m.end(): m.end() + 14]
            if not 14 <= n <= 80 or _AGE_NOT_BEFORE.search(before) or re.match(r"\s*\d+\s*(?:мес|month)", after, re.I):
                return m.group(0)
            found.setdefault("age", []).append(m.group(0))
            return "[возраст]"
        line = _HEAD_AGE.sub(age_repl, line)
        lines[i] = line
    return "\n".join(lines)


# ---------------------------------------------------------------- имена: латиница и одиночные рядом с контактом
_LAT_TOKEN = re.compile(r"[A-Za-z][A-Za-z']*(?:-[A-Za-z][A-Za-z']*)?")
_SURNAME_RU = re.compile(r"(?:ов|ова|ев|ева|ёв|ёва|ин|ина|ын|ына|ский|ская|цкий|цкая|енко|ук|юк|ич|ян|дзе|швили|их|ых)$")


def _norm(tok: str) -> str:
    return "-".join(p.capitalize() for p in tok.split("-"))


def _cap(tok: str) -> bool:
    return tok[0].isupper() and (tok[1:].replace("-", "").replace("'", "").islower() or (tok.isupper() and len(tok) >= 3)
                                 or bool(re.fullmatch(r"[A-Z][a-z]+-[A-Z][a-z]+", tok)))


def _wordlike(tok: str) -> bool:
    """Слово с заглавной, которое может быть фамилией: не технология, не роль, не служебное слово, не город."""
    return _cap(tok) and len(tok) >= 2 and not any(p.lower() in NM.not_name_lower() for p in tok.split("-"))


def _is_first(tok: str) -> bool:
    return _cap(tok) and _norm(tok) in NM.latin_first()


def latin_names(text: str, header_end: int = 0) -> list[tuple[int, int, str]]:
    """Имена латиницей: «Ivan Petrov», «Petrov Ivan Sergeevich», «IVAN PETROV» (имя — из словаря частых имён и
    транслита). header_end — граница шапки: там достаточно фамильного окончания у неизвестного имени."""
    out: list[tuple[int, int, str]] = []
    toks = list(_LAT_TOKEN.finditer(text))
    i = 0
    while i < len(toks) - 1:
        a, b = toks[i], toks[i + 1]
        if not re.fullmatch(r"[ \t\u00a0]+", text[a.end():b.start()]) or text[a.start() - 1: a.start()] in ("@", "/", ".", "_"):
            i += 1
            continue
        ta, tb = a.group(0), b.group(0)
        hit = None
        if _is_first(ta) and (_wordlike(tb) or _is_first(tb)) and tb.lower() not in NM.not_name_lower():
            hit = [a, b]
        elif _wordlike(ta) and _is_first(tb) and (NM.SURNAME_LAT.search(ta) or a.start() < header_end):
            hit = [a, b]
        if hit:
            c = toks[i + 2] if i + 2 < len(toks) else None
            if (c is not None and re.fullmatch(r"[ \t\u00a0]+", text[b.end():c.start()]) and _wordlike(c.group(0))
                    and (NM.PATRONYMIC_LAT.search(tb) or NM.PATRONYMIC_LAT.search(c.group(0)))):
                hit.append(c)
            out.append((hit[0].start(), hit[-1].end(), text[hit[0].start():hit[-1].end()]))
            i += len(hit)
            continue
        i += 1
    return out


_CONTACT_PH = re.compile(r"\[(?:телефон|почта|ник|ссылка)\]")
_CAPWORD = re.compile(r"(?<![\w\-\[@])([А-ЯЁ][а-яё]+|[A-Z][a-z]+)(?![\w\-\]])")
_VERB_CUE = re.compile(
    r"(?<![\w])(?i:пиши\w*|напиш\w*|звони\w*|позвон\w*|обращ\w*|свяж\w*|присыл\w*|пришл\w*|отправл\w*|направл\w*|"
    r"спрашива\w*|спросит\w*|уточн\w*|write|contact|call|ask)"
    r"(?:[ \t]+(?i:резюме|cv|свои|своё|свое|отклик\w*|вопрос\w*|сообщени\w*|в[ \t]+(?:личку|лс|tg|телеграм\w*|telegram)))*"
    r"(?:[ \t]+(?i:к|у|на[ \t]+имя|для|to))?[ \t]*[:—–\-,]?[ \t]*([А-ЯЁ][а-яё]+|[A-Z][a-z]+)(?![\w-])")
_ROLE_AFTER = re.compile(r"(?<![\w\-\[])([А-ЯЁ][а-яё]+|[A-Z][a-z]+)[ \t]*(?:\(|,|—|–|-)[ \t]*"
                         r"(?i:hr\b|hrbp|рекрутер\w*|recruiter|менеджер\w*|руководител\w*|тимлид\w*|team[ \t]*lead|техлид\w*)")
_SIGN_CUE = re.compile(r"(?i:best[ \t]+regards|kind[ \t]+regards|regards|sincerely|cheers|thanks|thank[ \t]+you|с[ \t]+уважением|"
                       r"спасибо)[ \t]*[,.!]?[ \t]*\n?[ \t]*([А-ЯЁ][а-яё]+|[A-Z][a-z]+)(?![\w-])")


def _first_name(w: str) -> bool:
    return w in NM.ru_name_forms() or w in NM.latin_first()


def single_names(text: str) -> list[tuple[int, int, str]]:
    """Одиночное имя из словаря рядом с контактом (±40 знаков в той же строке), после глагола связи («пишите
    Ольге»), перед ролью («Ольга (HR)») или в подписи письма. Слово не из словаря имён не режется никогда."""
    spans: dict[int, tuple[int, int, str]] = {}
    for m in _CONTACT_PH.finditer(text):
        ls = text.rfind("\n", 0, m.start()) + 1
        le = text.find("\n", m.end())
        le = len(text) if le < 0 else le
        for w in _CAPWORD.finditer(text, max(ls, m.start() - 40), min(le, m.end() + 40)):
            if _first_name(w.group(1)) and not re.search(r"(?:г\.|город)[ \t]*$", text[max(0, w.start() - 7):w.start()]):
                spans[w.start(1)] = (w.start(1), w.end(1), w.group(1))
    for pat in (_VERB_CUE, _ROLE_AFTER, _SIGN_CUE):
        pos = 0
        while (m := pat.search(text, pos)) is not None:  # с перекрытием: «спасибо. Regards, Ksenia»
            if _first_name(m.group(1)):
                spans[m.start(1)] = (m.start(1), m.end(1), m.group(1))
            pos = m.start(1) if m.start(1) > m.start() else m.end()
    out = []
    for s, e, w in sorted(spans.values()):
        # фамилия рядом («Ольга Иванова, [телефон]», если NER не поймал) — вместе с именем
        nxt = re.match(r"[ \t\u00a0]+([А-ЯЁ][а-яё]+|[A-Z][a-z]+)(?![\w-])", text[e:])
        if nxt and (_SURNAME_RU.search(nxt.group(1)) or NM.SURNAME_LAT.search(nxt.group(1))) \
                and nxt.group(1).lower() not in NM.not_name_lower():
            e += nxt.end()
        out.append((s, e, text[s:e]))
    return out


def _header_end(text: str, n: int = 6) -> int:
    pos, seen = 0, 0
    for line in text.split("\n"):
        pos += len(line) + 1
        if line.strip():
            seen += 1
            if seen >= n:
                break
    return pos


def _not_name(val: str) -> bool:
    """Все слова — технологии, роли, служебные слова или города: это не имя (защита словаря стека)."""
    parts = [p for p in re.split(r"[\s\-]+", val) if p]
    return bool(parts) and all(p.lower() in NM.not_name_lower() for p in parts)


def redact(text: str, use_ner: bool = True, ner_min_tokens: int = 1, contact_cues: bool = False,
           header: bool = True) -> Redaction:
    """ner_min_tokens=2 — имена NER только из двух и более слов («Иванова Мария»): в текстах вакансий одиночные
    слова с заглавной («Гибрид», «Андроид») NER часто принимает за имена. contact_cues — имя после подсказки
    контакта («HR: Ольга»). header — эвристики шапки резюме (дата без подписи, возраст, пол в первых 10 строках);
    для текста вакансии и ответа на задание — False."""
    found: dict[str, list[str]] = {}
    out = text
    for kind, pat, placeholder in PATTERNS:
        vals = [m.group(0).strip() for m in pat.finditer(out)]
        if vals:
            found.setdefault(kind, []).extend(vals)
            out = pat.sub(placeholder, out)
    for pat in ADDRESS_PATTERNS:
        vals = [m.group(0).strip() for m in pat.finditer(out)]
        if vals:
            found.setdefault("address", []).extend(vals)
            out = pat.sub("[адрес]", out)
    out = _address_labels(out, found)
    out = re.sub(r"\[адрес\](?:[ \t]*,?[ \t]*\[адрес\])+", "[адрес]", out)
    out = _age_cues(out, found)
    if header:
        out = _header(out, found)

    ner_used = False
    names: list[str] = []
    singles: list[str] = []
    if use_ner:
        persons = _ner_persons(out)
        ner_used = _ner is not None
        for s, e, val in sorted(persons, key=lambda x: -x[0]):
            if len(val.split()) < ner_min_tokens or _not_name(val) or "[" in val:
                continue
            names.append(val)
            out = out[:s] + "[ФИО]" + out[e:]
    if contact_cues:
        for m in reversed(list(CONTACT_CUE.finditer(out))):
            val = m.group(1).strip()
            if _not_name(val):
                continue
            single = len(val.split()) == 1
            (singles if single else names).append(val)
            out = out[:m.start(1)] + ("[имя]" if single else "[ФИО]") + out[m.end(1):]
    for s, e, val in reversed(single_names(out)):
        single = len(val.split()) == 1
        (singles if single else names).append(val)
        out = out[:s] + ("[имя]" if single else "[ФИО]") + out[e:]
    for s, e, val in reversed(latin_names(out, _header_end(out) if header else 0)):
        names.append(val)
        out = out[:s] + "[ФИО]" + out[e:]
    # Эвристика: первая строка резюме вида «Фамилия Имя [Отчество]» / «Ivan Petrov» или «ФИО: …» (не роль, не город,
    # не технология: «Нижний Новгород», «Frontend Developer», «Spring Boot» — не имена)
    lines = out.split("\n")
    for i, line in enumerate(lines[:6]):
        stripped = LABEL_HINTS.sub("", line)
        m = _NAME_LINE.match(stripped) or _NAME_LINE_EN.match(stripped)
        if m and "[" not in stripped and not any(p.lower() in NM.not_name_lower() for p in re.split(r"[\s\-]+", m.group(1))):
            if _NAME_LINE_EN.match(stripped) and not (any(_is_first(t) for t in m.group(1).split())
                                                      or any(NM.SURNAME_LAT.search(t) for t in m.group(1).split())):
                continue
            names.append(m.group(1))
            lines[i] = line.replace(m.group(1), "[ФИО]")
            break
    out = "\n".join(lines)
    # Повторные упоминания уже найденных имён (например, в подписи); технологии и города не трогаем
    for n in set(names):
        for part in [n] + [p for p in n.split() if len(p) > 3]:
            if part.lower() in NM.not_name_lower():
                continue
            out = re.sub(rf"(?<!\w){re.escape(part)}(?!\w)", "[ФИО]", out)
    for n in set(singles):
        if n.lower() not in NM.not_name_lower():
            out = re.sub(rf"(?<![\w\[]){re.escape(n)}(?![\w\]])", "[имя]", out)
    if names or singles:
        found["person"] = list(dict.fromkeys(names + singles))
    return Redaction(text=re.sub(r"(\[ФИО\]\s*){2,}", "[ФИО] ", out), found=found, ner_used=ner_used)
