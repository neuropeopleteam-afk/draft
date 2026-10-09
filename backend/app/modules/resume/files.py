"""Текст из загруженного файла — для резюме кандидата (PDF, DOCX) и вакансии работодателя (PDF, DOCX, TXT).

Тип определяется по содержимому (сигнатуре), а не по имени и не по Content-Type из запроса: «резюме.pdf», который на
деле EXE или ZIP, отклоняется. PDF и DOCX разбираются в отдельном процессе с тайм-аутом и лимитами памяти и CPU
(extract.pdf_to_text_safe / docx_to_text_safe), TXT — декодируется на месте (UTF-8, UTF-16 с BOM, CP1251).
Исходный файл нигде не сохраняется. Ошибки — FileTextError с HTTP-статусом, кодом и понятным сообщением.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import threading

from app.modules.resume import extract as _ex  # через модуль: тесты подменяют extract.pdf_to_text_safe
from app.modules.resume.extract import PdfError

KIND_TITLES = {"pdf": "PDF", "docx": "DOCX", "txt": "TXT"}
# Один разбор в отдельном процессе одновременно на воркер API — общий для резюме и вакансий
# (процесс разбора ~40 МБ, предел адресного пространства 256 МБ — укладывается в лимит памяти api в docker-compose.yml)
parse_slots = threading.BoundedSemaphore(1)

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # старый DOC/XLS, а также DOCX/PDF под паролем (контейнер Office)
_ZIP = (b"PK\x03\x04", b"PK\x05\x06")
# Явные двоичные форматы (остальные двоичные файлы отсекает проверка на нулевые байты)
_BINARY = (b"\x7fELF", b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"Rar!", b"7z\xbc\xaf", b"\x1f\x8b", b"\xca\xfe\xba\xbe",
           b"\xcf\xfa\xed\xfe", b"OggS", b"RIFF")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_BULLET = re.compile(r"^[ \t]*[•●▪■◦○∙·‣⁃\uf0b7\uf0a7\uf076\uf0d8\uf0fc–—]\s*", re.M)


@dataclass
class FileText:
    text: str
    kind: str          # pdf | docx | txt
    pages: int | None  # у PDF — страниц; у DOCX и TXT — None


class FileTextError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def safe_filename(name: str | None, default: str) -> str:
    """Имя файла для показа и БД: без пути и управляющих символов, не длиннее 120 знаков."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = _CTRL.sub("", base).strip().strip(".") or default
    return base[-120:]


def sniff(data: bytes) -> str:
    """pdf | zip | ole | rtf | html | binary | text — по первым байтам файла."""
    head = data[:1024]
    if head.startswith(b"%PDF-") or (b"%PDF-" in head and not head.startswith(_ZIP)):
        return "pdf"
    if head.startswith(_ZIP):
        return "zip"
    if head.startswith(_OLE):
        return "ole"
    if head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"{\\rtf"):
        return "rtf"
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "text"  # UTF-16 с BOM
    if head.startswith(_BINARY) or b"\x00" in data[:65536]:
        return "binary"
    low = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if low.startswith((b"<!doctype html", b"<html", b"<?xml")):
        return "html"
    return "text"


def decode_text(data: bytes) -> str:
    """TXT: UTF-8 (с BOM и без), UTF-16 с BOM, иначе CP1251. Двоичное содержимое — FileTextError."""
    if data.startswith(b"\xef\xbb\xbf"):
        s = data[3:].decode("utf-8", errors="replace")
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        s = data.decode("utf-16", errors="replace")
    else:
        if b"\x00" in data:
            raise FileTextError(415, "binary_file", "Файл не похож на текст. Загрузите PDF, DOCX или TXT")
        try:
            s = data.decode("utf-8")
        except UnicodeDecodeError:
            s = data.decode("cp1251", errors="replace")
    sample = s[:20000]
    bad = sum(1 for ch in sample if (ord(ch) < 32 and ch not in "\t\n\r\f") or ch == "\ufffd")
    if sample and bad / len(sample) > 0.02:
        raise FileTextError(415, "binary_file", "Файл не похож на текст. Загрузите PDF, DOCX или TXT")
    return s


def clean_text(s: str, headings: bool = False) -> str:
    """Нормализация извлечённого текста: переводы строк, невидимые символы, маркеры списков, пустые строки.

    headings — дописать двоеточие заголовкам разделов (для текста вакансии, см. mark_headings).
    """
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\u00ad", "").replace("\u2028", "\n").replace("\u2029", "\n")
    s = _CTRL.sub("", s.replace("\f", "\n"))
    s = _BULLET.sub("- ", s)
    s = re.sub(r"[ \t\u00a0]+\n", "\n", s)
    s = re.sub(r"[ \u00a0]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = s.strip()
    return mark_headings(s) if headings else s


_HEAD_WORDS = re.compile(r"(?i)^(?:требования|обязательно|обязательные\s+требования|необходимо|что\s+(?:нужно|важно|мы\s+ждём|"
                         r"ждём)|мы\s+ждём|ждём\s+от\s+вас|будет\s+плюсом|плюсом\s+будет|желательно|"
                         r"будет\s+преимуществом|преимуществом\s+будет|задачи|обязанности|чем\s+предстоит\s+заниматься|"
                         r"условия|мы\s+предлагаем|что\s+мы\s+предлагаем|о\s+нас|о\s+команде|о\s+компании|стек|"
                         r"технологии|навыки|ключевые\s+навыки|опыт\s+работы|образование)$")


def mark_headings(s: str) -> str:
    """Заголовок раздела без двоеточия («Будет плюсом» перед списком) → «Будет плюсом:».

    В файлах заголовки обычно без двоеточия, а разбор потребности различает «обязательно» и «желательно» по
    заголовку раздела с двоеточием, как в набранном тексте. Двоеточие ставится только короткой строке без знака
    препинания в конце, за которой идёт пункт списка, или известному заголовку раздела.
    """
    lines = s.split("\n")
    for i, line in enumerate(lines):
        t = line.strip()
        if not t or len(t) > 60 or t.startswith("- ") or t[-1] in ".:;,!?…»)" or not re.search(r"[A-Za-zА-Яа-яЁё]", t):
            continue
        nxt = next((x.strip() for x in lines[i + 1:] if x.strip()), "")
        if (nxt.startswith("- ") and len(t.split()) <= 6) or _HEAD_WORDS.match(t.rstrip()):
            lines[i] = ("\n" if i and lines[i - 1].strip() else "") + line.rstrip() + ":"  # пустая строка перед разделом
    return "\n".join(lines)


def clip(s: str, limit: int) -> tuple[str, bool]:
    """Обрезка до limit знаков по границе абзаца или строки (если она не слишком далеко от предела)."""
    if len(s) <= limit:
        return s, False
    cut = s[:limit]
    for sep in ("\n\n", "\n", ". "):
        i = cut.rfind(sep)
        if i >= limit * 0.6:
            return cut[:i].rstrip(), True
    return cut.rstrip(), True


_PDF_ERR = {
    "too_many_pages": (422, "pdf_too_many_pages", None),
    "timeout": (422, "pdf_timeout", "PDF слишком сложный: разбор не уложился в отведённое время"),
    "unreadable": (422, "pdf_unreadable", "Не удалось прочитать PDF: файл повреждён или защищён паролем"),
}
_DOCX_ERR = {
    "macros": (415, "docx_macros", "Документ содержит макросы или элементы ActiveX — такие файлы не принимаем. "
                                   "Сохраните его как обычный DOCX без макросов или как PDF"),
    "encrypted": (422, "docx_encrypted", "Документ защищён паролем. Снимите пароль или сохраните как PDF"),
    "zip_bomb": (422, "docx_too_large", "Документ распаковывается в слишком большой объём — похоже на повреждённый "
                                        "или вредоносный файл. Сохраните его заново или загрузите PDF"),
    "dtd": (422, "docx_unsafe", "В документе есть конструкции XML, которых не бывает в файлах Word (DOCTYPE). "
                                "Файл отклонён из соображений безопасности"),
    "not_docx": (415, "docx_not_word", "Это архив или документ другой программы (например, таблица), а не документ "
                                       "Word. Загрузите {want}"),
    "timeout": (422, "docx_timeout", "Документ слишком сложный: разбор не уложился в отведённое время"),
    "unreadable": (422, "docx_unreadable", "Не удалось прочитать DOCX: файл повреждён"),
}


def _want(allowed: tuple[str, ...]) -> str:
    t = [KIND_TITLES[k] for k in allowed]
    return t[0] if len(t) == 1 else ", ".join(t[:-1]) + " или " + t[-1]


def _unsupported(kind: str, allowed: tuple[str, ...]) -> FileTextError:
    want = _want(allowed)
    if kind == "ole":
        return FileTextError(415, "old_office", "Старый формат Word (DOC) или файл под паролем не поддерживается. "
                                                f"Сохраните документ как {want} без пароля")
    if kind == "rtf":
        return FileTextError(415, "rtf_unsupported", f"Формат RTF не поддерживается. Сохраните документ как {want}")
    if kind == "html":
        return FileTextError(415, "html_unsupported", f"Это веб-страница или XML. Сохраните текст как {want}")
    if allowed == ("pdf",):
        return FileTextError(415, "not_pdf", "Нужен файл PDF")
    return FileTextError(415, "unsupported_type", f"Нужен файл {want}: тип определяется по содержимому, не по имени")


def file_to_text(data: bytes, allowed: tuple[str, ...], *, max_bytes: int, max_pages: int, timeout_s: float,
                 memory_mb: int, slot_timeout_s: float = 15.0) -> FileText:
    """Байты файла → текст. allowed — допустимые типы из pdf | docx | txt (порядок — для сообщения об ошибке)."""
    if not data:
        raise FileTextError(422, "file_empty", "Файл пустой")
    if len(data) > max_bytes:
        raise FileTextError(413, "file_too_large", f"Файл больше {max_bytes // (1024 * 1024)} МБ")
    kind = sniff(data)
    kind = {"zip": "docx", "text": "txt"}.get(kind, kind)
    if kind not in allowed:
        raise _unsupported(kind, allowed)
    if kind == "txt":
        return FileText(decode_text(data), "txt", None)
    if not parse_slots.acquire(timeout=slot_timeout_s):  # разбор длится секунды (тайм-аут 10 с) — очередь дождётся
        raise FileTextError(503, "parse_busy", "Сервер разбирает другие файлы, повторите через минуту")
    try:
        if kind == "pdf":
            try:
                text, pages = _ex.pdf_to_text_safe(data, max_pages, timeout_s, memory_mb)
            except PdfError as e:
                status, code, msg = _PDF_ERR.get(e.code, _PDF_ERR["unreadable"])
                if e.code == "too_many_pages":
                    msg = f"В PDF {e.pages} страниц — допускается не больше {max_pages}"
                raise FileTextError(status, code, msg) from None
            return FileText(text, "pdf", pages)
        try:
            return FileText(_ex.docx_to_text_safe(data, timeout_s, memory_mb), "docx", None)
        except PdfError as e:
            status, code, msg = _DOCX_ERR.get(e.code, _DOCX_ERR["unreadable"])
            raise FileTextError(status, code, msg.replace("{want}", _want(allowed))) from None
    finally:
        parse_slots.release()


def no_text_error(kind: str) -> FileTextError:
    if kind == "pdf":
        return FileTextError(422, "pdf_no_text", "В PDF нет текстового слоя (скан). Загрузите файл с текстом или "
                                                 "вставьте текст вручную")
    return FileTextError(422, f"{kind}_no_text", "В файле почти нет текста. Проверьте файл или вставьте текст вручную")
