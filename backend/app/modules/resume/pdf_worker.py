"""Разбор PDF в отдельном процессе (запускает app.modules.resume.extract.pdf_to_text_safe).

Вход — байты PDF в stdin, аргумент — максимум страниц. Выход — одна строка JSON в stdout:
{"text": ..., "pages": N} | {"error": "too_many_pages", "pages": N} | {"error": "unreadable"}.
Число страниц проверяется ДО извлечения текста: сначала /Count из каталога, затем фактическое дерево страниц.
Тайм-аут и лимит памяти задаёт родительский процесс. Только stdlib и pypdf — импорт приложения не нужен.
"""
import io
import json
import sys


def _extract_visible_page_text(page) -> str:
    """Извлекает только видимый текст страницы PDF (отбрасывает микрошрифт < 2pt и текст за пределами листа)."""
    chunks: list[str] = []

    def visitor(text, cm, tm, font_dict, font_size):
        if not text:
            return
        if not text.strip():
            chunks.append(text)
            return
        try:
            scale_y = abs(float(tm[3])) if tm and len(tm) > 3 else 1.0
            eff_size = float(font_size or 10.0) * (scale_y if scale_y > 0 else 1.0)
            if eff_size < 2.0:
                return  # микрошрифт (накрутка ключевыми словами)
            if tm and len(tm) >= 6:
                x, y = float(tm[4]), float(tm[5])
                if x < -100 or y < -100 or x > 5000 or y > 5000:
                    return  # текст вынесен за пределы видимой области страницы
        except Exception:  # noqa: BLE001
            pass
        chunks.append(text)

    try:
        page.extract_text(visitor_text=visitor)
        if chunks:
            return "".join(chunks)
    except Exception:  # noqa: BLE001
        pass
    return page.extract_text() or ""


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
        text = "\n".join(_extract_visible_page_text(p) for p in reader.pages)
    except Exception:  # noqa: BLE001 — повреждённый или зашифрованный PDF
        print(json.dumps({"error": "unreadable"}))
        return
    print(json.dumps({"text": text, "pages": n}, ensure_ascii=False))


if __name__ == "__main__":
    main()
