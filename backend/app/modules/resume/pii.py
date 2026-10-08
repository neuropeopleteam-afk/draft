"""Локальное вырезание персональных данных до любой отправки текста во внешние сервисы (LLM).

Два слоя:
1. Регулярные выражения — почты, телефоны РФ и международные, ники и ссылки на мессенджеры и соцсети,
   даты рождения, ИНН/СНИЛС/паспорт.
2. Natasha (MIT, локальная модель NER, без сети) — имена людей (PER). Модель грузится лениво, один раз
   на процесс; если библиотека недоступна — остаются регулярки и эвристика «ФИО в первой строке».

Найденные значения возвращаются отдельно, чтобы кандидат мог перенести их в свой профиль (контакты
скрыты от работодателя до принятия приглашения). В БД сохраняется только текст с плейсхолдерами
и счётчики по типам.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
import threading

log = logging.getLogger("resume.pii")

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
    ("birthdate", re.compile(r"(?:дата рождения|родил(?:ся|ась)|д\.р\.)\s*:?\s*\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}", re.I),
     "[дата рождения]"),
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
_NAME_LINE_EN = re.compile(r"^\s*([A-Z][a-z]+\s+[A-Z][a-z]+)\s*$")


def redact(text: str, use_ner: bool = True, ner_min_tokens: int = 1, contact_cues: bool = False) -> Redaction:
    """ner_min_tokens=2 — имена NER только из двух и более слов («Иванова Мария»): в текстах вакансий одиночные
    слова с заглавной («Гибрид», «Андроид») NER часто принимает за имена. contact_cues — имя после подсказки
    контакта («HR: Ольга»)."""
    found: dict[str, list[str]] = {}
    out = text
    for kind, pat, placeholder in PATTERNS:
        vals = [m.group(0).strip() for m in pat.finditer(out)]
        if vals:
            found.setdefault(kind, []).extend(vals)
            out = pat.sub(placeholder, out)

    ner_used = False
    names: list[str] = []
    if use_ner:
        persons = _ner_persons(out)
        ner_used = _ner is not None
        for s, e, val in sorted(persons, key=lambda x: -x[0]):
            if len(val.split()) < ner_min_tokens:
                continue
            names.append(val)
            out = out[:s] + "[ФИО]" + out[e:]
    if contact_cues:
        for m in reversed(list(CONTACT_CUE.finditer(out))):
            val = m.group(1).strip()
            names.append(val)
            out = out[:m.start(1)] + "[ФИО]" + out[m.end(1):]
    # Эвристика: первая непустая строка резюме вида «Фамилия Имя [Отчество]» или «ФИО: …»
    lines = out.split("\n")
    for i, line in enumerate(lines[:6]):
        stripped = LABEL_HINTS.sub("", line)
        m = _NAME_LINE.match(stripped) or _NAME_LINE_EN.match(stripped)
        if m and "[" not in stripped:
            names.append(m.group(1))
            lines[i] = line.replace(m.group(1), "[ФИО]")
            break
    out = "\n".join(lines)
    # Повторные упоминания уже найденных имён (например, в подписи)
    for n in set(names):
        for part in [n] + [p for p in n.split() if len(p) > 3]:
            out = re.sub(rf"(?<!\w){re.escape(part)}(?!\w)", "[ФИО]", out)
    if names:
        found["person"] = list(dict.fromkeys(names))
    return Redaction(text=re.sub(r"(\[ФИО\]\s*){2,}", "[ФИО] ", out), found=found, ner_used=ner_used)
