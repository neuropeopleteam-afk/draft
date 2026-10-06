"""Разбор PDF в отдельном процессе (запускает app.modules.resume.extract.pdf_to_text_safe).

Вход — байты PDF в stdin, аргумент — максимум страниц. Выход — одна строка JSON в stdout:
{"text": ..., "pages": N} | {"error": "too_many_pages", "pages": N} | {"error": "unreadable"}.
Число страниц проверяется ДО извлечения текста: сначала /Count из каталога, затем фактическое дерево страниц.
Тайм-аут и лимит памяти задаёт родительский процесс. Только stdlib и pypdf — импорт приложения не нужен.
"""
import io
import json
import sys


def main() -> None:
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    data = sys.stdin.buffer.read()
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        try:
            declared = int(reader.trailer["/Root"]["/Pages"]["/Count"])
        except Exception:  # noqa: BLE001 — нет /Count: проверим по дереву страниц
            declared = 0
        if declared > max_pages:
            print(json.dumps({"error": "too_many_pages", "pages": declared}))
            return
        n = len(reader.pages)
        if n > max_pages:
            print(json.dumps({"error": "too_many_pages", "pages": n}))
            return
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:  # noqa: BLE001 — повреждённый или зашифрованный PDF
        print(json.dumps({"error": "unreadable"}))
        return
    print(json.dumps({"text": text, "pages": n}, ensure_ascii=False))


if __name__ == "__main__":
    main()
