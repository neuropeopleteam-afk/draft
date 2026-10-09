"""Экспортирует контракт мока из реального OpenAPI, без ручного дублирования схем."""
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.main import create_app  # noqa: E402


def contract():
    schema = create_app().openapi()
    paths = {k: v for k, v in schema["paths"].items() if k.startswith("/api/fsp-registry/v1/")}
    names = set()

    def visit(node):
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].rsplit("/", 1)[-1]
                if name not in names:
                    names.add(name)
                    visit(schema["components"]["schemas"][name])
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(paths)
    return {"openapi": schema["openapi"], "info": {
        "title": "Предложение API реестра ФСП · синтетический мок", "version": "1.0",
        "description": "Не официальный API ФСП. Контракт команды «Встречный»: места, разряды, дисциплины ЕВСК, "
                       "командные результаты и даты. Мок содержит только FSP-770012, FSP-770013, FSP-770014; "
                       "весь паспорт — один ограниченный снимок (до 1000 достижений). Реальный реестр потребует "
                       "сервисной авторизации, согласования кодов ЕВСК и пагинации. Поле evsk_code в моках пустое: "
                       "официальные коды не придумываем. Обоснование — разбор видео организаторов (53:44–55:16)."},
        "servers": [{"url": "http://127.0.0.1:8106", "description": "Локальный мок исполнителя И6"}],
        "paths": paths, "components": {"schemas": {n: schema["components"]["schemas"][n] for n in sorted(names)}},
        "x-proposed-production-auth": "Authorization: Bearer <service-token> (FSP_REGISTRY_TOKEN)"}


if __name__ == "__main__":
    dest = ROOT / "docs" / "fsp_registry_api.yaml"
    dest.write_text(yaml.safe_dump(contract(), allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(dest)
