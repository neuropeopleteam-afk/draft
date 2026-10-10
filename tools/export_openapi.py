#!/usr/bin/env python
"""Экспорт спецификации OpenAPI в репозиторий: docs/api/openapi.json (то же, что отдаёт /api/openapi.json).

  python tools/export_openapi.py            # записать docs/api/openapi.json   (make openapi)
  python tools/export_openapi.py --check    # код возврата 1, если файл не совпадает с кодом (тест, CI)
  python tools/export_openapi.py --stdout   # вывести в stdout

Запись каноническая: ключи отсортированы, отступ 2 пробела, UTF-8, перевод строки в конце — один и тот же код даёт
побайтово один и тот же файл, diff показывает только настоящие изменения API. Приложению нужны только импорты:
соединения с БД и сети не открываются. Версия API (info.version) берётся из настроек по умолчанию: переменная
APP_VERSION при экспорте игнорируется, чтобы файл не зависел от окружения.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
DEST = ROOT / "docs" / "api" / "openapi.json"
HINT = "docs/api/openapi.json не совпадает с кодом API — выполните `make openapi` и закоммитьте файл"


def build_spec() -> dict:
    """Схема свежесозданного приложения, как её отдаёт /api/openapi.json."""
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    saved = os.environ.pop("APP_VERSION", None)
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        from app.main import create_app

        return create_app().openapi()
    finally:
        if saved is not None:
            os.environ["APP_VERSION"] = saved
        get_settings.cache_clear()


def render(spec: dict | None = None) -> str:
    from app.core.api_docs import canonical_json

    return canonical_json(spec if spec is not None else build_spec())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="проверить, что файл актуален (ничего не записывать)")
    ap.add_argument("--stdout", action="store_true", help="вывести спецификацию в stdout")
    a = ap.parse_args()
    text = render()
    if a.stdout:
        sys.stdout.write(text)
        return 0
    if a.check:
        if not DEST.exists() or DEST.read_text(encoding="utf-8") != text:
            print(HINT, file=sys.stderr)
            return 1
        print(f"{DEST.relative_to(ROOT)} актуален")
        return 0
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(text, encoding="utf-8")
    print(f"{DEST.relative_to(ROOT)}: {len(text.encode('utf-8')) // 1024} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
