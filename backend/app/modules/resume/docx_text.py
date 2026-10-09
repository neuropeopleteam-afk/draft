"""Текст из DOCX только средствами stdlib (zipfile + expat) — без новых зависимостей и без импорта приложения.

Модуль самодостаточен: его загружает изолированный процесс разбора (docx_worker.py, python -I, лимиты памяти и
CPU), поэтому здесь нельзя импортировать app.*. Читается только основная часть документа (word/document.xml или
цель связи officeDocument из _rels/.rels): абзацы, списки, таблицы, надписи. Колонтитулы, сноски, комментарии,
встроенные объекты и картинки не читаются; ничего из файла не исполняется и не распаковывается на диск.

Защита (код ошибки — DocxError.code):
- not_docx    — ZIP без признаков документа Word (XLSX, ODT, архив): тип определяется по содержимому, не по имени;
- macros      — документ с макросами или ActiveX (DOCM/DOTM, vbaProject.bin): такие файлы не принимаем вовсе;
- encrypted   — зашифрованная запись ZIP;
- zip_bomb    — слишком много записей, заявленный объём распаковки или степень сжатия вне разумного, либо
                фактически распаковано больше лимита (распаковка идёт потоком и обрывается на лимите — заявленным
                размерам в заголовках ZIP не доверяем);
- dtd         — DOCTYPE/ENTITY в XML (в DOCX их не бывает; так закрыты «миллиард смехов» и внешние сущности);
- unreadable  — повреждённый ZIP или XML.
"""
from __future__ import annotations

import io
import posixpath
import zipfile
from xml.parsers import expat

MAX_ENTRIES = 2000              # в обычном DOCX 10–40 записей; в отчёте с картинками — сотни
MAX_TOTAL_DECLARED = 200 << 20  # заявленный объём всех записей (картинки не читаем, но архив-бомбу отсекаем сразу)
MAX_XML_BYTES = 16 << 20        # фактически распакованный XML основной части; у 50-страничного документа ~2–5 МБ
MAX_RATIO = 200                 # степень сжатия основной части (у XML Word обычно 5–30, у бомбы — тысячи)
RATIO_FROM = 1 << 20            # степень сжатия проверяем начиная с 1 МБ: маленький XML жмётся как угодно
MAX_CHARS = 200_000             # дальше текст не нужен: разбор берёт первые тысячи знаков
_CHUNK = 64 << 10

NS_MAIN = ("http://schemas.openxmlformats.org/wordprocessingml/2006/main",  # Transitional (Word, LibreOffice)
           "http://purl.oclc.org/ooxml/wordprocessingml/main")              # Strict
NS_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
REL_OFFICE = ("http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
              "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument")
WORD_MAIN_TYPES = (b"wordprocessingml.document.main+xml", b"wordprocessingml.template.main+xml",
                   b"ms-word.document.macroenabled.main+xml", b"ms-word.template.macroenabledtemplate.main+xml")


class DocxError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _Stop(Exception):
    """Текста набрано достаточно — дальше не разбираем."""


def _read_small(zf: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int = 1 << 20) -> bytes:
    with zf.open(info) as f:
        data = f.read(cap + 1)
    if len(data) > cap:
        raise DocxError("zip_bomb")
    return data


def _no_dtd(*_a) -> None:
    raise DocxError("dtd")


def _parser() -> expat.XMLParserType:
    p = expat.ParserCreate(namespace_separator=" ")
    p.StartDoctypeDeclHandler = _no_dtd
    p.EntityDeclHandler = _no_dtd
    p.ExternalEntityRefHandler = lambda *a: 0  # внешние сущности не загружаем (0 = ошибка разбора)
    p.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    return p


def _main_part(zf: zipfile.ZipFile, names: dict[str, zipfile.ZipInfo]) -> zipfile.ZipInfo:
    if "word/document.xml" in names:
        return names["word/document.xml"]
    rels = names.get("_rels/.rels")
    if rels is None:
        raise DocxError("not_docx")
    target: list[str] = []

    def start(name: str, attrs: dict) -> None:
        if name.rsplit(" ", 1)[-1] == "Relationship" and attrs.get("Type") in REL_OFFICE and not target:
            target.append(attrs.get("Target") or "")

    p = _parser()
    p.StartElementHandler = start
    try:
        p.Parse(_read_small(zf, rels), True)
    except expat.ExpatError:
        raise DocxError("unreadable") from None
    path = posixpath.normpath(target[0].lstrip("/")) if target else ""
    if not path or path not in names:
        raise DocxError("not_docx")
    return names[path]


def _check_archive(zf: zipfile.ZipFile) -> tuple[zipfile.ZipInfo, dict[str, zipfile.ZipInfo]]:
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        raise DocxError("zip_bomb")
    names = {i.filename: i for i in infos}
    lower = [n.lower() for n in names]
    if "[Content_Types].xml" not in names:
        raise DocxError("not_docx")
    if any(n.endswith("vbaproject.bin") or n.startswith(("word/vba", "word/activex/")) for n in lower):
        raise DocxError("macros")
    ct = _read_small(zf, names["[Content_Types].xml"]).lower()
    if b"macroenabled" in ct or b"vbaproject" in ct or b"activex" in ct:
        raise DocxError("macros")
    if not any(t in ct for t in WORD_MAIN_TYPES):
        raise DocxError("not_docx")  # таблица, презентация, ODT или просто архив
    if sum(i.file_size for i in infos) > MAX_TOTAL_DECLARED:
        raise DocxError("zip_bomb")
    main = _main_part(zf, names)
    if main.flag_bits & 0x1:
        raise DocxError("encrypted")
    if main.file_size > MAX_XML_BYTES:
        raise DocxError("zip_bomb")
    if main.file_size > RATIO_FROM and main.file_size > MAX_RATIO * max(main.compress_size, 1):
        raise DocxError("zip_bomb")
    return main, names


def _val(attrs: dict, name: str = "val") -> str | None:
    return next((v for k, v in attrs.items() if k.rpartition(" ")[2] == name), None)


def _styles(zf: zipfile.ZipFile, names: dict[str, zipfile.ZipInfo]) -> tuple[set[str], set[str]]:
    """Стили абзацев: (списки, заголовки) с учётом наследования basedOn.

    Список — w:numPr с numId ≠ 0 (numId 0 в производном стиле отменяет нумерацию базового). Заголовок — w:outlineLvl
    или имя heading N / Title: пункт с нумерацией заголовка («1. Требования») — заголовок, а не пункт списка.
    """
    info = names.get("word/styles.xml")
    if info is None or info.file_size > 4 << 20:
        return set(), set()
    based: dict[str, str] = {}
    num: dict[str, bool] = {}       # объявлено в самом стиле: True — нумерация есть, False — отменена
    head: set[str] = set()
    cur: list[str] = [""]
    in_num = [False]

    def start(name: str, attrs: dict) -> None:
        ns, _, tag = name.rpartition(" ")
        if ns not in NS_MAIN:
            return
        if tag == "style":
            cur[0] = _val(attrs, "styleId") or ""
        elif not cur[0]:
            return
        elif tag == "basedOn" and _val(attrs):
            based[cur[0]] = _val(attrs)
        elif tag == "name" and (_val(attrs) or "").lower().startswith(("heading", "title", "заголовок")):
            head.add(cur[0])
        elif tag == "outlineLvl" and (_val(attrs) or "9") != "9":
            head.add(cur[0])
        elif tag == "numPr":
            in_num[0] = True
            num.setdefault(cur[0], True)
        elif tag == "numId" and in_num[0]:
            num[cur[0]] = _val(attrs) != "0"

    def end(name: str) -> None:
        tag = name.rpartition(" ")[2]
        if tag == "numPr":
            in_num[0] = False
        elif tag == "style":
            cur[0] = ""

    p = _parser()
    p.StartElementHandler, p.EndElementHandler = start, end
    try:
        p.Parse(_read_small(zf, info, 4 << 20), True)
    except (expat.ExpatError, DocxError):
        return set(), set()  # стили необязательны: без них списки просто без маркеров

    def resolve(sid: str, own) -> bool:
        seen = set()
        while sid and sid not in seen:
            seen.add(sid)
            v = own(sid)
            if v is not None:
                return v
            sid = based.get(sid, "")
        return False

    all_ids = set(based) | set(num) | head
    heads = {x for x in all_ids if resolve(x, lambda i: True if i in head else None)}
    lists = {x for x in all_ids if x not in heads and resolve(x, num.get)}
    return lists, heads


class _Text:
    """Собирает текст из событий expat: абзацы → строки, ячейки таблицы → «a | b | c», пункты списка → «- …»."""

    def __init__(self, list_styles: set[str] | None = None, heading_styles: set[str] | None = None) -> None:
        self.list_styles, self.heading_styles = list_styles or set(), heading_styles or set()
        self.out: list[str] = []
        self.size = 0
        self.paras: list[list[str]] = []      # стек абзацев (надпись внутри абзаца — вложенный абзац)
        self.pinfo: list[dict] = []           # у каждого абзаца: стиль, своя нумерация (None — не задана), заголовок
        self.cells: list[list[str]] = []      # стек ячеек: строки абзацев текущей ячейки
        self.rows: list[list[str]] = []       # стек строк таблицы: тексты ячеек
        self.in_t = 0
        self.in_tabs = 0                      # w:pPr/w:tabs — позиции табуляции, не текст
        self.skip = 0                         # внутри mc:Fallback (дубль надписи) — не читаем

    def _emit(self, line: str) -> None:
        if self.cells:
            self.cells[-1].append(line)
            return
        self.out.append(line)
        self.size += len(line) + 1
        if self.size > MAX_CHARS:
            raise _Stop

    def start(self, name: str, attrs: dict) -> None:
        ns, _, tag = name.rpartition(" ")
        if ns == NS_MC:
            if tag == "Fallback":
                self.skip += 1
            return
        if ns not in NS_MAIN or self.skip:
            return
        if tag == "p":
            self.paras.append([])
            self.pinfo.append({"style": None, "num": None, "outline": False})
        elif tag in ("pStyle", "numPr", "numId", "outlineLvl"):
            if not self.pinfo:
                return
            if tag == "pStyle":
                self.pinfo[-1]["style"] = _val(attrs)
            elif tag == "numPr":
                self.pinfo[-1]["num"] = True
            elif tag == "numId":
                self.pinfo[-1]["num"] = _val(attrs) != "0"  # numId 0 — нумерация стиля отключена у абзаца
            elif (_val(attrs) or "9") != "9":
                self.pinfo[-1]["outline"] = True
        elif tag == "t":
            self.in_t += 1
        elif tag == "tabs":
            self.in_tabs += 1
        elif tag == "tab" and self.paras and not self.in_t and not self.in_tabs:
            self.paras[-1].append("\t")
        elif tag in ("br", "cr") and self.paras:
            self.paras[-1].append("\n")
        elif tag == "noBreakHyphen" and self.paras:
            self.paras[-1].append("-")
        elif tag == "tr":
            self.rows.append([])
        elif tag == "tc":
            self.cells.append([])

    def end(self, name: str) -> None:
        ns, _, tag = name.rpartition(" ")
        if ns == NS_MC:
            if tag == "Fallback" and self.skip:
                self.skip -= 1
            return
        if ns not in NS_MAIN or self.skip:
            return
        if tag == "t":
            self.in_t = max(0, self.in_t - 1)
        elif tag == "tabs":
            self.in_tabs = max(0, self.in_tabs - 1)
        elif tag == "p" and self.paras:
            text = "".join(self.paras.pop()).strip()
            info = self.pinfo.pop()
            heading = info["outline"] or info["style"] in self.heading_styles
            listed = info["num"] if info["num"] is not None else info["style"] in self.list_styles
            bullet = listed and not heading
            if text:
                self._emit(f"- {text}" if bullet else text)
        elif tag == "tc" and self.cells:
            cell = " ".join(x for x in self.cells.pop() if x)
            if self.rows:
                self.rows[-1].append(cell)
            elif cell:
                self._emit(cell)
        elif tag == "tr" and self.rows:
            row = [c for c in self.rows.pop() if c]
            if row:
                self._emit(" | ".join(row))

    def chars(self, data: str) -> None:
        if self.in_t and not self.skip and self.paras:
            self.paras[-1].append(data)


def docx_to_text(data: bytes) -> str:
    """Текст основной части DOCX. Ошибки — DocxError (коды — в описании модуля)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        raise DocxError("unreadable") from None
    with zf:
        try:
            main, names = _check_archive(zf)
            sink = _Text(*_styles(zf, names))
            p = _parser()
            p.StartElementHandler, p.EndElementHandler, p.CharacterDataHandler = sink.start, sink.end, sink.chars
            read, stopped = 0, False
            with zf.open(main) as f:
                while not stopped:
                    chunk = f.read(_CHUNK)
                    read += len(chunk)
                    if read > MAX_XML_BYTES:
                        raise DocxError("zip_bomb")  # заголовок ZIP соврал о размере
                    try:
                        p.Parse(chunk, not chunk)
                    except _Stop:
                        stopped = True
                    if not chunk:
                        break
        except DocxError:
            raise
        except (expat.ExpatError, zipfile.BadZipFile, EOFError, OSError, ValueError, RuntimeError,
                NotImplementedError):
            # битый XML, CRC, неизвестный метод сжатия, запись с паролем (RuntimeError)
            raise DocxError("unreadable") from None
    return "\n".join(sink.out)
