"""Ф5: текст из файла — вакансия работодателя (PDF, DOCX, TXT) и резюме кандидата (PDF, DOCX).

Тип по содержимому, лимит размера, изолированный процесс разбора с тайм-аутом и лимитом памяти, zip-бомбы, DTD,
макросы, битые и вредные файлы; навыки из резюме — только T0 («заявлено»); ПДн не уходят в модель.
"""
from __future__ import annotations

import io
from pathlib import Path
import zipfile

import pytest

from app.modules.resume import docx_text, files
from app.modules.resume.docx_text import DocxError, docx_to_text
from app.modules.resume.extract import PdfError, docx_to_text_safe
from app.modules.resume.files import FileTextError, clean_text, clip, decode_text, file_to_text, mark_headings, sniff
from tests.test_day2_rules import H, _pdf_bytes, employer
from tests.conftest import register_and_verify

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CT_DOCX = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
           '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
           '<Default Extension="xml" ContentType="application/xml"/>'
           '<Override PartName="/word/document.xml" ContentType="application/'
           'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
RELS = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="{target}"/></Relationships>')
LIMITS = dict(max_bytes=5 << 20, max_pages=20, timeout_s=10.0, memory_mb=256)


def p(text: str, bullet: bool = False, style: str | None = None) -> str:
    ppr = ""
    if bullet or style:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + \
              ('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>' if bullet else "") + "</w:pPr>"
    return f"<w:p>{ppr}<w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def body(*parts: str, ns: str = W) -> str:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{ns}" '
            f'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"><w:body>{"".join(parts)}'
            f"</w:body></w:document>")


def make_docx(document: str | bytes | None, *, ct: str = CT_DOCX, extra: dict[str, bytes | str] | None = None,
              main: str = "word/document.xml", rels: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct.replace("/word/document.xml", "/" + main))
        if rels:
            z.writestr("_rels/.rels", RELS.replace("{target}", main))
        if document is not None:
            z.writestr(main, document)
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return buf.getvalue()


VACANCY = body(
    p("Python-разработчик (middle)"),
    p("Обязательно"), p("Python от 3 лет", True), p("FastAPI и PostgreSQL", True),
    p("Будет плюсом"), p("Redis", True), p("Kafka", True),
    '<w:tbl><w:tr><w:tc>' + p("Формат") + '</w:tc><w:tc>' + p("удалённо") + '</w:tc></w:tr>'
    '<w:tr><w:tc>' + p("Вилка") + '</w:tc><w:tc>' + p("250 000 – 300 000 ₽") + '</w:tc></w:tr></w:tbl>',
)


# ---------------------------------------------------------------- DOCX: текст

def test_docx_paragraphs_lists_tables():
    t = docx_to_text(make_docx(VACANCY))
    assert t.splitlines() == ["Python-разработчик (middle)", "Обязательно", "- Python от 3 лет", "- FastAPI и PostgreSQL",
                              "Будет плюсом", "- Redis", "- Kafka", "Формат | удалённо", "Вилка | 250 000 – 300 000 ₽"]


def test_docx_runs_tabs_breaks_fallback_deleted_fields():
    doc = body(
        '<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs></w:pPr>'
        '<w:r><w:t>Py</w:t></w:r><w:r><w:t>thon</w:t></w:r><w:r><w:tab/><w:t>Go</w:t><w:br/><w:t>SQL</w:t></w:r>'
        '<w:del><w:r><w:delText>Java</w:delText></w:r></w:del>'
        '<w:r><w:instrText> HYPERLINK "http://x" </w:instrText></w:r></w:p>',
        # надпись: в mc:Choice и дубль в mc:Fallback — текст один раз
        '<w:p><w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:txbxContent>' + p("Docker") +
        '</w:txbxContent></mc:Choice><mc:Fallback><w:txbxContent>' + p("Docker") +
        '</w:txbxContent></mc:Fallback></mc:AlternateContent></w:r></w:p>',
    )
    t = docx_to_text(make_docx(doc))
    assert t == "Python\tGo\nSQL\nDocker"
    assert "Java" not in t and "HYPERLINK" not in t


def test_docx_list_style_from_styles_xml_and_strict_namespace():
    styles = (f'<w:styles xmlns:w="{W}"><w:style w:type="paragraph" w:styleId="ListBullet"><w:pPr><w:numPr>'
              '<w:numId w:val="3"/></w:numPr></w:pPr></w:style><w:style w:type="paragraph" w:styleId="MyList">'
              '<w:basedOn w:val="ListBullet"/></w:style></w:styles>')
    doc = body(p("Навыки"), p("Python", style="MyList"), p("Docker", style="ListBullet"), p("Итого", style="Normal"))
    assert docx_to_text(make_docx(doc, extra={"word/styles.xml": styles})).splitlines() == \
        ["Навыки", "- Python", "- Docker", "Итого"]
    strict = body(p("Строгий OOXML"), ns="http://purl.oclc.org/ooxml/wordprocessingml/main")
    assert docx_to_text(make_docx(strict)) == "Строгий OOXML"


def test_docx_heading_styles_are_not_list_items():
    """Заголовок с нумерацией стиля (LibreOffice: numPr с numId 0, outlineLvl) — заголовок, а не «- пункт»."""
    styles = (f'<w:styles xmlns:w="{W}"><w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>'
              '<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="0"/></w:numPr><w:outlineLvl w:val="1"/></w:pPr>'
              '</w:style><w:style w:type="paragraph" w:styleId="Num"><w:pPr><w:numPr><w:numId w:val="2"/></w:numPr>'
              '</w:pPr></w:style><w:style w:type="paragraph" w:styleId="NoNum"><w:basedOn w:val="Num"/><w:pPr><w:numPr>'
              '<w:numId w:val="0"/></w:numPr></w:pPr></w:style></w:styles>')
    doc = body(p("Требования", style="Heading2"), p("Go", style="Num"), p("Обычный", style="NoNum"),
               p("1. Условия", bullet=True, style="Heading2"))
    assert docx_to_text(make_docx(doc, extra={"word/styles.xml": styles})).splitlines() == \
        ["Требования", "- Go", "Обычный", "1. Условия"]


@pytest.mark.parametrize("name", ["vacancy_go_pandoc.docx", "vacancy_go_libreoffice.docx"])
def test_docx_real_generators(name):
    """DOCX из pandoc и из LibreOffice (тот же текст, tests/fixtures_fileparse/vacancy_go.md) читаются одинаково."""
    from app.modules.matching.need_parser import parse_need

    raw = (Path(__file__).parent / "fixtures_fileparse" / name).read_bytes()
    t = clean_text(docx_to_text(raw), headings=True)
    assert "Требования:\n- Go от 5 лет" in t and "Будет плюсом:\n- Kubernetes" in t and "Вилка | от 400 000 ₽" in t
    r = parse_need(t, use_llm=False)
    assert (r["direction"], r["grade"]) == ("backend", "senior")
    assert [i["tag"] for i in r["stack_required"]] == ["go", "postgresql", "kafka", "grpc"]
    assert [i["tag"] for i in r["stack_desired"]] == ["kubernetes", "clickhouse"]


def test_docx_main_part_from_rels():
    assert docx_to_text(make_docx(body(p("Из document2")), main="word/document2.xml")) == "Из document2"
    with pytest.raises(DocxError) as e:  # нет ни word/document.xml, ни связи officeDocument
        docx_to_text(make_docx(body(p("x")), main="word/document2.xml", rels=False))
    assert e.value.code == "not_docx"


def test_docx_real_example_from_docs():
    t = clean_text(docx_to_text((EXAMPLES / "vacancy_python_middle.docx").read_bytes()), headings=True)
    assert "Обязательно:" in t and "Будет плюсом:" in t and "- Redis для кэша и очередей;" in t
    assert "Формат | удалённо или гибрид (офис в Москве)" in t


# ---------------------------------------------------------------- DOCX: вредные и битые файлы

def _code(data: bytes) -> str:
    with pytest.raises(DocxError) as e:
        docx_to_text(data)
    return e.value.code


def test_docx_macros_rejected():
    assert _code(make_docx(VACANCY, extra={"word/vbaProject.bin": b"\xd0\xcf\x11\xe0 macro"})) == "macros"
    docm = CT_DOCX.replace("officedocument.wordprocessingml.document.main+xml", "ms-word.document.macroEnabled.main+xml")
    assert _code(make_docx(VACANCY, ct=docm)) == "macros"
    assert _code(make_docx(VACANCY, extra={"word/activeX/activeX1.xml": "<x/>"})) == "macros"


def test_docx_not_word():
    xlsx_ct = CT_DOCX.replace("wordprocessingml.document.main+xml", "spreadsheetml.sheet.main+xml")
    assert _code(make_docx(VACANCY, ct=xlsx_ct)) == "not_docx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "просто архив")
    assert _code(buf.getvalue()) == "not_docx"


def test_docx_zip_bomb_by_size_ratio_entries():
    # 20 МБ XML, сжатого в килобайты: отказ по заявленному размеру, до распаковки
    big = body(p("A" * 1000) * 20_000).encode()
    assert len(big) > docx_text.MAX_XML_BYTES
    assert _code(make_docx(big)) == "zip_bomb"
    # 3 МБ однообразного XML — степень сжатия больше 200
    assert _code(make_docx(body(p("Б") * 120_000))) == "zip_bomb"
    many = {f"word/media/i{i}.png": b"x" for i in range(docx_text.MAX_ENTRIES + 1)}
    assert _code(make_docx(VACANCY, extra=many)) == "zip_bomb"


def test_docx_lying_header_stops_at_real_limit(monkeypatch):
    """Заявленным размерам не доверяем: распаковка обрывается на фактическом лимите."""
    monkeypatch.setattr(docx_text, "MAX_XML_BYTES", 200_000)
    monkeypatch.setattr(docx_text, "RATIO_FROM", 10 << 20)  # проверку степени сжатия выключаем
    data = make_docx(body(p("В" * 500) * 400))  # ~420 КБ XML
    # подделываем размер в центральном каталоге: «распакуется в 100 байт»
    info = zipfile.ZipFile(io.BytesIO(data)).getinfo("word/document.xml")
    assert info.file_size > 200_000
    raw = bytearray(data)
    hdr = raw.find(b"word/document.xml", raw.find(b"PK\x01\x02")) - 46  # имя файла — со смещения 46 заголовка
    assert raw[hdr:hdr + 4] == b"PK\x01\x02"
    raw[hdr + 24:hdr + 28] = (100).to_bytes(4, "little")
    assert _code(bytes(raw)) in ("zip_bomb", "unreadable")


def test_docx_dtd_billion_laughs_and_external_entity():
    lol = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;">]>'
           f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>&lol2;</w:t></w:r></w:p></w:body></w:document>')
    assert _code(make_docx(lol)) == "dtd"
    xxe = ('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
           f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>&x;</w:t></w:r></w:p></w:body></w:document>')
    assert _code(make_docx(xxe)) == "dtd"


def test_docx_encrypted_broken_truncated():
    raw = bytearray(make_docx(VACANCY))  # запись «под паролем»: бит 0 флагов в центральном каталоге (смещение 8)
    hdr = raw.find(b"word/document.xml", raw.find(b"PK\x01\x02")) - 46
    assert raw[hdr:hdr + 4] == b"PK\x01\x02"
    raw[hdr + 8] |= 0x1
    assert _code(bytes(raw)) == "encrypted"
    assert _code(make_docx("<w:document><w:body><w:p>незакрытый")) == "unreadable"
    good = make_docx(VACANCY)
    assert _code(good[: len(good) // 2]) == "unreadable"
    assert _code(b"PK\x03\x04" + b"\x00" * 100) == "unreadable"


def test_docx_text_capped(monkeypatch):
    monkeypatch.setattr(docx_text, "MAX_CHARS", 1000)
    t = docx_to_text(make_docx(body(*(p(f"Строка {i} про Python") for i in range(5000)))))
    assert 1000 < len(t) < 1100


# ---------------------------------------------------------------- изолированный процесс

def test_docx_worker_isolated_with_limits():
    assert docx_to_text_safe(make_docx(VACANCY)).startswith("Python-разработчик (middle)")
    with pytest.raises(PdfError) as e:
        docx_to_text_safe(make_docx(VACANCY, extra={"word/vbaProject.bin": b"x"}))
    assert e.value.code == "macros"
    with pytest.raises(PdfError) as e:  # процесс не может взять память сверх лимита — отказ, а не OOM воркера API
        docx_to_text_safe(make_docx(VACANCY), memory_mb=16)
    assert e.value.code == "unreadable"
    with pytest.raises(PdfError) as e:
        docx_to_text_safe(make_docx(VACANCY), timeout_s=0.01)
    assert e.value.code == "timeout"


# ---------------------------------------------------------------- тип по содержимому, TXT, нормализация

@pytest.mark.parametrize("data,kind", [
    (b"%PDF-1.7\n...", "pdf"), (b"\n\n%PDF-1.4 junk", "pdf"), (b"PK\x03\x04rest", "zip"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 20, "ole"), (b"{\\rtf1\\ansi hello}", "rtf"),
    (b"\x7fELF\x02\x01", "binary"), (b"MZ\x90\x00\x03\x00\x00\x00", "binary"), (b"\x89PNG\r\n\x1a\n", "binary"),
    (b"<!DOCTYPE html><html>", "html"), ("Ищем Python-разработчика".encode(), "text"),
    ("\ufeffТекст".encode("utf-16"), "text"), ("Ищем".encode("cp1251"), "text"),
])
def test_sniff(data, kind):
    assert sniff(data) == kind


def test_decode_text_encodings_and_binary():
    s = "Ищем Python-разработчика, опыт от 3 лет"
    for raw in (s.encode(), b"\xef\xbb\xbf" + s.encode(), s.encode("utf-16"), s.encode("cp1251")):
        assert decode_text(raw) == s
    with pytest.raises(FileTextError) as e:
        decode_text(bytes(range(1, 32)) * 50)
    assert e.value.code == "binary_file"


def test_clean_text_and_headings_and_clip():
    raw = "Задачи\r\n• писать код\u00ad\r\n\r\n\r\n\r\nБудет плюсом\n\uf0b7 Kafka\u200b\nПросто строка в конце."
    t = clean_text(raw, headings=True)
    assert t == "Задачи:\n- писать код\n\nБудет плюсом:\n- Kafka\nПросто строка в конце."
    assert clean_text(raw).startswith("Задачи\n- писать код")  # для резюме двоеточия не дописываем
    assert mark_headings("Требования\nPython, Docker") == "Требования:\nPython, Docker"
    assert mark_headings("Иван Петров\nPython") == "Иван Петров\nPython"  # не заголовок раздела и не перед списком
    assert mark_headings("Уже с точкой.\n- пункт") == "Уже с точкой.\n- пункт"
    text = ("Абзац про компанию. " * 30 + "\n\n") * 20
    c, cut = clip(text, 8000)
    assert cut and len(c) <= 8000 and c.endswith(".") and text.startswith(c)
    assert clip("короткий", 8000) == ("короткий", False)


def test_file_to_text_types_and_errors():
    assert file_to_text(make_docx(VACANCY), ("pdf", "docx", "txt"), **LIMITS).kind == "docx"
    ft = file_to_text(_pdf_bytes(["Python FastAPI PostgreSQL"]), ("pdf", "docx"), **LIMITS)
    assert ft.kind == "pdf" and ft.pages == 1 and "FastAPI" in ft.text

    def err(data: bytes, allowed=("pdf", "docx", "txt"), **kw) -> tuple[int, str, str]:
        with pytest.raises(FileTextError) as e:
            file_to_text(data, allowed, **{**LIMITS, **kw})
        return e.value.status, e.value.code, e.value.message

    assert err(b"")[:2] == (422, "file_empty")
    assert err(b"x" * 101, max_bytes=100)[:2] == (413, "file_too_large")
    assert err(b"MZ\x90\x00" + b"\x00" * 200)[:2] == (415, "unsupported_type")  # EXE под именем .pdf
    assert err(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600)[:2] == (415, "old_office")
    assert err(b"{\\rtf1 text}")[:2] == (415, "rtf_unsupported")
    assert err("Текст резюме".encode(), ("pdf", "docx")) == (
        415, "unsupported_type", "Нужен файл PDF или DOCX: тип определяется по содержимому, не по имени")
    s, code, msg = err(make_docx(VACANCY, extra={"word/vbaProject.bin": b"x"}))
    assert (s, code) == (415, "docx_macros") and "макрос" in msg
    s, code, msg = err(make_docx(VACANCY, ct=CT_DOCX.replace("wordprocessingml.document", "spreadsheetml.sheet")),
                       ("pdf", "docx"))
    assert (s, code) == (415, "docx_not_word") and msg.endswith("Загрузите PDF или DOCX")
    assert err(b"%PDF-1.4\nbroken")[:2] == (422, "pdf_unreadable")
    assert err(make_docx(body(p("A" * 1000) * 20_000)))[:2] == (422, "docx_too_large")


def test_parse_slot_busy(monkeypatch):
    assert files.parse_slots.acquire(timeout=1)
    try:
        with pytest.raises(FileTextError) as e:
            file_to_text(make_docx(VACANCY), ("docx",), **LIMITS, slot_timeout_s=0.05)
        assert e.value.status == 503
    finally:
        files.parse_slots.release()


# ---------------------------------------------------------------- API: файл вакансии

def _upload(client, t, name: str, data: bytes, path="/api/employer/needs/file"):
    return client.post(path, files={"file": (name, data, "application/octet-stream")}, headers=H(t))


@pytest.mark.parametrize("ext", ["docx", "pdf", "txt"])
def test_need_file_examples_parse_like_typed_text(client, ext):
    t = employer(client)
    r = _upload(client, t, f"vacancy.{ext}", (EXAMPLES / f"vacancy_python_middle.{ext}").read_bytes())
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["kind"] == ext and j["kind_title"] == ext.upper() and not j["truncated"] and j["limit"] == 8000
    assert (j["pages"] == 1) if ext == "pdf" else j["pages"] is None
    assert "Обязательно:" in j["text"] and "Будет плюсом:" in j["text"]
    req = client.post("/api/employer/needs/parse", json={"text": j["text"]}, headers=H(t)).json()
    assert (req["direction"], req["grade"]) == ("backend", "middle")
    assert {"python", "fastapi", "postgresql", "docker"} <= {i["tag"] for i in req["stack_required"]}
    assert {"redis", "kafka"} <= {i["tag"] for i in req["stack_desired"]}
    assert (req["salary_from"], req["salary_to"]) == (230_000, 290_000)
    for i in req["stack_required"] + req["stack_desired"]:  # цитаты — из текста, который видит работодатель
        ev = i["evidence"]
        assert j["text"][ev["start"]:ev["end"]] == ev["quote"]
    # потребность сохраняется тем же путём, что набранный текст
    n = client.post("/api/employer/needs", json={"text": j["text"]}, headers=H(t))
    assert n.status_code == 201 and n.json()["raw_text"] == j["text"]


def test_need_file_contacts_do_not_reach_llm(client, monkeypatch):
    from app.modules.llm.client import LLMResult
    from app.modules.matching import need_parser

    from app.modules.matching import fast_parse

    sent: list[str] = []
    monkeypatch.setattr(need_parser, "chat_json",
                        lambda system, user, **k: (sent.append(user), LLMResult(ok=False, error="mock"))[1])
    # И27: модель вызывается в фоновой задаче, если провайдер настроен — здесь задача выполняется внутри запроса
    monkeypatch.setattr(fast_parse.llm_client, "available", lambda func=None: True)
    monkeypatch.setattr(fast_parse, "_spawn", lambda fn, *a: fn(*a))
    t = employer(client)
    j = _upload(client, t, "v.docx", (EXAMPLES / "vacancy_python_middle.docx").read_bytes()).json()
    assert "hr@example.invalid" in j["text"]  # работодатель видит свой текст целиком
    client.post("/api/employer/needs/parse", json={"text": j["text"]}, headers=H(t))
    assert sent and "hr@example.invalid" not in sent[0] and "900 000-00-00" not in sent[0]
    assert "Котова" not in sent[0]


def test_need_file_errors_in_plain_words(client, monkeypatch):
    t = employer(client)
    cases = [
        ("v.docm", make_docx(VACANCY, extra={"word/vbaProject.bin": b"x"}), 415, "docx_macros"),
        ("v.pdf", b"MZ\x90\x00" + b"\x00" * 500, 415, "unsupported_type"),
        ("v.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, 415, "old_office"),
        ("v.docx", make_docx(body(p("A" * 1000) * 20_000)), 422, "docx_too_large"),
        ("v.docx", make_docx(VACANCY)[:300], 422, "docx_unreadable"),
        ("v.pdf", _pdf_bytes([""]), 422, "pdf_no_text"),
        ("v.txt", b"", 422, "file_empty"),
        ("v.txt", "Мало".encode(), 422, "txt_no_text"),
    ]
    for name, data, status, code in cases:
        r = _upload(client, t, name, data)
        assert r.status_code == status and r.json()["detail"]["code"] == code, (name, r.text)
        assert r.json()["detail"]["message"] and "Traceback" not in r.text
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "resume_max_bytes", 1000)
    r = _upload(client, t, "big.txt", "Ищем Python-разработчика. ".encode() * 100)
    assert r.status_code == 413 and "МБ" in r.json()["detail"]["message"]


def test_need_file_long_text_clipped(client):
    t = employer(client)
    text = "Python-разработчик middle.\n\n" + ("О компании: мы делаем сервис доставки и растём. " * 20 + "\n\n") * 15
    r = _upload(client, t, "long.txt", text.encode("cp1251"))
    j = r.json()
    assert r.status_code == 200 and j["truncated"] and len(j["text"]) <= 8000 < j["chars_total"]
    assert client.post("/api/employer/needs/parse", json={"text": j["text"]}, headers=H(t)).status_code == 200


def test_need_file_roles_and_rate(client, monkeypatch):
    data = (EXAMPLES / "vacancy_python_middle.txt").read_bytes()
    assert client.post("/api/employer/needs/file", files={"file": ("v.txt", data)}).status_code == 401
    cand = register_and_verify(client, "cand-file@example.com")
    assert _upload(client, cand, "v.txt", data).status_code == 403
    from app.modules.matching import router as mr

    monkeypatch.setattr(mr._need_file_attempts, "limit", 2)
    t = employer(client)
    assert [_upload(client, t, "v.txt", data).status_code for _ in range(3)] == [200, 200, 429]


# ---------------------------------------------------------------- API: резюме DOCX

RESUME = body(p("Смирнова Анна Викторовна"), p("Frontend-разработчик"), p("anna.smirnova@yandex.ru, +7 999 123-45-67"),
              p("Опыт работы 3 года"), p("Навыки"), p("React", True), p("TypeScript", True), p("Next.js", True),
              p("Коммуникабельна, умею работать в команде."))


def test_resume_docx_redacts_extracts_and_skills_stay_declared(client, monkeypatch):
    from app.modules.llm.client import LLMResult
    from app.modules.resume import extract

    sent: list[str] = []
    monkeypatch.setattr(extract, "chat_json", lambda system, user, **k: (
        sent.append(user), LLMResult(ok=True, data={"stack": ["docker"], "roles": [], "soft_skills": []}))[1])
    t = register_and_verify(client, "docx-cv@example.com")
    r = _upload(client, t, "cv.docx", make_docx(RESUME), path="/api/me/resume")
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["kind"] == "docx" and j["pages"] == 0 and j["evidence_level"] == "T0"
    assert j["pii_found"]["email"] == "anna.smirnova@yandex.ru" and j["pii_found"]["phone"]
    assert "anna.smirnova" not in j["text_preview"] and "123-45-67" not in j["text_preview"]
    assert {"react", "typescript", "docker"} <= {s["tag"] for s in j["extracted"]["stack"]}
    # ПДн не уходят в модель
    assert sent and all(x not in sent[0] for x in ("anna.smirnova", "123-45-67", "Смирнова", "Анна"))
    last = client.get("/api/me/resume", headers=H(t)).json()
    assert last["kind"] == "docx" and last["filename"] == "cv.docx"
    # «Добавить в профиль» — навыки только как заявленные (T0), не подтверждённые тестом
    assert client.post(f"/api/me/resume/{j['id']}/apply", json={}, headers=H(t)).status_code == 200
    card = client.get("/api/me/card", headers=H(t)).json()
    declared = {s["tag"]: s for s in card["stack_declared"]}
    assert {"react", "typescript", "docker"} <= set(declared)
    assert all(declared[k]["level"] == "T0" and declared[k]["source"] == "resume" for k in ("react", "docker"))
    assert not card["skills_confirmed"]
    from app.core.db import SessionLocal
    from app.core.enums import EvidenceLevel, FactSource
    from app.modules.profiles.models import CandidateFact

    with SessionLocal() as db:
        facts = db.query(CandidateFact).filter(CandidateFact.source == FactSource.resume).all()
        assert facts and all(f.evidence_level == EvidenceLevel.T0 for f in facts)


def test_resume_rejects_txt_macros_and_other_types(client):
    t = register_and_verify(client, "cv-bad@example.com")
    cases = [("cv.txt", "Резюме: Python, Django, опыт 3 года".encode(), 415, "unsupported_type"),
             ("cv.docm", make_docx(RESUME, extra={"word/vbaProject.bin": b"x"}), 415, "docx_macros"),
             ("cv.pdf", make_docx(RESUME), 201, None),  # DOCX под именем .pdf — разбирается как DOCX (по содержимому)
             ("cv.docx", make_docx(body(p("коротко"))), 422, "docx_no_text")]
    for name, data, status, code in cases:
        r = _upload(client, t, name, data, path="/api/me/resume")
        assert r.status_code == status, (name, r.text)
        if code:
            assert r.json()["detail"]["code"] == code
