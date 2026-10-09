"""Разбор DOCX в отдельном процессе (запускает app.modules.resume.extract.docx_to_text_safe).

Вход — байты DOCX в stdin. Выход — одна строка JSON в stdout: {"text": ...} | {"error": "<код DocxError>"}.
Тайм-аут, лимит памяти и CPU задаёт родительский процесс (как у pdf_worker.py). Только stdlib: модуль docx_text
лежит рядом и загружается по пути — python -I не добавляет каталог скрипта в sys.path, импорт приложения не нужен.
"""
import json
from pathlib import Path
import sys


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from docx_text import DocxError, docx_to_text

    data = sys.stdin.buffer.read()
    try:
        text = docx_to_text(data)
    except DocxError as e:
        print(json.dumps({"error": e.code}))
        return
    except Exception:  # noqa: BLE001 — любой неожиданный сбой разбора = нечитаемый файл
        print(json.dumps({"error": "unreadable"}))
        return
    print(json.dumps({"text": text}, ensure_ascii=False))


if __name__ == "__main__":
    main()
