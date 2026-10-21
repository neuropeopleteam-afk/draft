"""А4: ответы /api/validation/*, которые рисует интерфейс, не называют модели и поставщиков (решение штаба 21.10).

Тот же критерий, что у А12 (tests/test_ui_no_vendor_names.py): в строках — ни имён моделей, ни компаний; служебные
идентификаторы вида anthropic/… в полях provider/model_reported не проверяются. Данные с полными именами остаются в
файлах validation/data и в docs/ (воспроизводимость), на экран — через validation/no_vendor.scrub.
"""
from __future__ import annotations

import re

import pytest

from app.modules.validation.no_vendor import scrub

VENDOR = re.compile(r"claude|sonnet|fable|anthropic|openai|\bgpt|gemini|yandex|deepseek|grok|kimi|openrouter", re.I)
ID = re.compile(r"^(?:[\w.\-]+/)+[\w.\-:]+$|^gpt://")
INTERNAL_KEYS = {"provider", "model_reported"}


def leaks(obj, path="") -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in INTERNAL_KEYS:
                out += leaks(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out += leaks(v, f"{path}[{i}]")
    elif isinstance(obj, str) and VENDOR.search(obj) and not ID.match(obj.strip()):
        out.append(f"{path}: {obj[:120]}")
    return out


def test_scrub_keeps_links_and_roles():
    d = {"models": [{"key": "yandex", "label": "YandexGPT 5.1"}, {"key": "sonnet", "label": "Claude Sonnet 5.5"},
                    {"key": "rules", "label": "Правила"}],
         "rows": {"yandex": 1, "sonnet": 2, "rules": 3},
         "note": "кросс-вендорная панель (Anthropic + Google), Claude Fable 5.1 в трёх ролях; режим «только YandexGPT»",
         "vendors": ["Anthropic", "Google"], "list": ["deepseek/deepseek-v4-flash", "x-ai/grok-4.7", "deepseek/deepseek-v4-flash"]}
    s = scrub(d)
    assert not leaks(s), leaks(s)
    keys = [m["key"] for m in s["models"]]
    assert set(keys) == set(s["rows"])  # ключи в значениях и в словаре переименованы одинаково
    assert keys[0] == "российская модель" and keys[1] == "модель стенда" and keys[2] == "rules"
    assert s["list"][0] == s["list"][2] != s["list"][1]
    assert "две компании" in s["note"] and "вторая модель в трёх ролях" in s["note"] and "только российская модель" in s["note"]
    assert s["vendors"] == ["компания А", "компания Б"]


@pytest.mark.parametrize("path", ["/api/validation/headline", "/api/validation/criteria", "/api/validation/llm-models",
                                  "/api/validation/ru-llm", "/api/validation/strongest", "/api/validation/grader-check"])
def test_validation_screens_have_no_vendor_names(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text
    found = leaks(r.json())
    assert not found, "\n".join(found[:20])
