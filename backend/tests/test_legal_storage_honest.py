"""Честное описание контура обработки (поле operator.storage в /api/meta) и неизменность версии согласий.

Решение владельца 09.10: основная модель — Claude Sonnet 5.5 через OpenRouter (разрешено организаторами), запасная —
YandexGPT; данные хранятся на сервере в Москве. Прежняя формулировка «языковая модель — Yandex AI Studio (РФ)» была неверной.
Поле storage в текст согласий не входит, поэтому редакция согласия (CONSENT_VERSION) не меняется — повторного подтверждения
у пользователей не требуется.
"""
from app.core import legal


def test_meta_storage_is_honest_about_models_and_location(client):
    st = client.get("/api/meta").json()["operator"]["storage"]
    assert "Москве" in st and "HOSTKEY" in st
    assert "Claude Sonnet 5.5" in st and "OpenRouter" in st
    assert "YandexGPT" in st and "запасная" in st
    assert "вырезанными контактами" in st
    assert "языковая модель — Yandex AI Studio" not in st


def test_consent_texts_do_not_depend_on_storage_field(client):
    # версия согласий прежняя — пользователи стенда не получат повторный запрос согласия из-за правки storage
    assert legal.CONSENT_VERSION == "2026-10-06"
    for kind in ("processing", "publication"):
        c = client.get(f"/api/legal/consents/{kind}").json()
        assert c["version"] == legal.CONSENT_VERSION
        assert "OpenRouter" not in c["text"] and "HOSTKEY" not in c["text"]
        # в тексте согласия на обработку — честные утверждения о хранении в РФ и вырезании ПДн до модели
    proc = client.get("/api/legal/consents/processing").json()["text"]
    assert "серверах в Российской Федерации" in proc and "языковой моделью ФИО и контакты вырезаются" in proc
