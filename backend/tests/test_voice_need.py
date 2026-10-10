"""Голосовой ввод потребности (app/modules/voice): флаг, согласие, лимиты, заглушка, отказ поставщика, ничего не хранится.

Сеть не используется: распознавание — заглушка движка (INTERVIEW_STUB=1) или подменённый relay.request движка.
"""
from __future__ import annotations

import logging
import time

import httpx
import pytest

from app.core.config import get_settings
from app.modules.interview.engine import reset_interview_settings
from app.modules.interview.engine.providers import relay
from app.modules.voice import router as voice
from tests.conftest import register_and_verify
from tests.test_day2_rules import H, employer

URL = "/api/employer/needs/voice"
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 4000  # заголовок EBML (webm/opus из MediaRecorder) + тело
CT = {"Content-Type": "audio/webm;codecs=opus"}


def env(monkeypatch, **kw):
    base = {"VOICE_NEED_ENABLED": "true", "INTERVIEW_STUB": "true", "DEEPGRAM_API_KEY": None}
    base.update(kw)
    for k, v in base.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, str(v))
    get_settings.cache_clear()
    reset_interview_settings()


@pytest.fixture(autouse=True)
def _reset():
    yield
    get_settings.cache_clear()
    reset_interview_settings()


def send(client, t, body=WEBM, consent=voice.CONSENT_VERSION, headers=None, **params):
    q = {"consent": consent, **params} if consent else params
    return client.post(URL, content=body, params=q, headers={**H(t), **(CT if headers is None else headers)})


def live(monkeypatch, fn):
    """Режим с ключом: запросы к Deepgram идут в подменённый relay.request движка."""
    env(monkeypatch, INTERVIEW_STUB="false", DEEPGRAM_API_KEY="dg-test-SECRET")
    calls = []

    def fake(method, host, path, *, headers=None, json=None, content=None, timeout_s=30.0):
        calls.append({"host": host, "path": path, "headers": headers, "size": len(content or b"")})
        return fn()
    monkeypatch.setattr(relay, "request", fake)
    return calls


def dg(text: str, seconds: float = 7.5) -> httpx.Response:
    return httpx.Response(200, json={"metadata": {"duration": seconds},
                                     "results": {"channels": [{"alternatives": [{"transcript": text}]}]}})


# ------------------------------------------------------------------ флаг и доступ
def test_flag_off_by_default_no_button_and_409(client):
    m = client.get("/api/meta").json()["voice_need"]
    assert m["enabled"] is False and "stub" not in m and m["max_seconds"] == 60
    t = employer(client)
    r = send(client, t)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "voice_need_disabled"


def test_roles(client, monkeypatch):
    env(monkeypatch)
    assert client.post(URL, content=WEBM, headers=CT).status_code == 401
    cand = register_and_verify(client, email="c@example.com")
    assert send(client, cand).status_code == 403


def test_meta_when_enabled_has_no_secrets(client, monkeypatch):
    env(monkeypatch, INTERVIEW_STUB="false", DEEPGRAM_API_KEY="dg-test-SECRET")
    body = client.get("/api/meta").text
    m = client.get("/api/meta").json()["voice_need"]
    assert m["enabled"] is True and m["stub"] is False and m["consent_version"] == voice.CONSENT_VERSION
    assert "Deepgram" in m["consent_text"] and "SECRET" not in body


# ------------------------------------------------------------------ заглушка: детерминированный текст → прежний разбор
def test_stub_text_then_existing_parse(client, monkeypatch):
    env(monkeypatch)
    assert client.get("/api/meta").json()["voice_need"]["stub"] is True
    t = employer(client)
    r = send(client, t, duration_ms=8200)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["text"] == voice.STUB_TEXT and j["stub"] is True and j["truncated"] is False
    assert "Заглушка" in j["note"] and j["chars"] == len(voice.STUB_TEXT)
    # ничего не создано и не отправлено: потребностей нет, разбор — только по кнопке (POST /needs/parse)
    assert client.get("/api/employer/needs", headers=H(t)).json() == []
    p = client.post("/api/employer/needs/parse", json={"text": j["text"]}, headers=H(t)).json()
    tags = {i["tag"] for i in p["stack_required"]}
    assert {"python", "fastapi", "postgresql"} <= tags and p["grade"] == "middle"


def test_stub_without_key_even_if_stub_flag_off(client, monkeypatch):
    env(monkeypatch, INTERVIEW_STUB="false", DEEPGRAM_API_KEY=None)
    t = employer(client)
    j = send(client, t).json()
    assert j["stub"] is True and j["text"] == voice.STUB_TEXT


# ------------------------------------------------------------------ согласие и лимиты
def test_consent_required(client, monkeypatch):
    env(monkeypatch)
    t = employer(client)
    for c in (None, "2020-01-01.v0"):
        r = send(client, t, consent=c)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "voice_consent_required"


def test_duration_and_size_limits(client, monkeypatch):
    env(monkeypatch, VOICE_NEED_MAX_KB="64")
    t = employer(client)
    r = send(client, t, duration_ms=61_000)
    assert r.status_code == 200  # 60 с по часам браузера + запас на остановку
    r = send(client, t, duration_ms=75_000)
    assert r.status_code == 413 and r.json()["detail"]["code"] == "voice_too_long"
    r = send(client, t, body=WEBM + b"\x00" * (64 * 1024))
    assert r.status_code == 413 and r.json()["detail"]["code"] == "voice_too_large"


def test_type_by_content_and_empty(client, monkeypatch):
    env(monkeypatch)
    t = employer(client)
    r = send(client, t, body=b"%PDF-1.7 " + b"x" * 500, headers={"Content-Type": "audio/webm"})
    assert r.status_code == 415 and r.json()["detail"]["code"] == "voice_bad_type"
    r = send(client, t, body=b"")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "voice_empty"
    for body in (b"OggS" + b"\x00" * 200, b"\x00\x00\x00\x1cftypM4A " + b"\x00" * 200,
                 b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 200, b"ID3" + b"\x00" * 200):
        assert send(client, t, body=body, headers={"Content-Type": "application/octet-stream"}).status_code == 200


def test_sniff():
    assert voice.sniff(WEBM) == "audio/webm"
    assert voice.sniff(b"RIFF\x00\x00\x00\x00AVI LIST") is None
    assert voice.sniff(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8) == "audio/mp4"
    assert voice.sniff(b"<html>") is None


def test_rate_limit_per_employer(client, monkeypatch):
    env(monkeypatch, VOICE_NEED_PER_HOUR="2")
    t = employer(client)
    assert [send(client, t).status_code for _ in range(3)] == [200, 200, 429]
    other = employer(client, email="hr2@corp.ru", company="ООО Василёк")
    assert send(client, other).status_code == 200


# ------------------------------------------------------------------ поставщик: успех, отказ, таймаут, мусор
def test_live_provider_text_and_codec_passed(client, monkeypatch):
    calls = live(monkeypatch, lambda: dg("  Ищем   аналитика данных: SQL и Python.  ", 6.2))
    t = employer(client)
    r = send(client, t, duration_ms=6300)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j == {"text": "Ищем аналитика данных: SQL и Python.", "stub": False, "seconds": 6.2, "chars": 36,
                 "truncated": False, "note": j["note"]} and "Проверьте" in j["note"]
    c = calls[0]
    assert c["host"] == "api.deepgram.com" and "language=ru" in c["path"] and c["size"] == len(WEBM)
    assert c["headers"]["Content-Type"] == "audio/webm;codecs=opus"


@pytest.mark.parametrize("fn", [lambda: httpx.Response(500), lambda: httpx.Response(401),
                                lambda: httpx.Response(200, text="<html>not json</html>"),
                                lambda: httpx.Response(200, json={"results": {}})])
def test_provider_error_is_503_not_500(client, monkeypatch, fn):
    live(monkeypatch, fn)
    t = employer(client)
    r = send(client, t)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "voice_unavailable"
    assert "клавиатуры" in r.json()["detail"]["message"]


def test_network_failure_is_503(client, monkeypatch):
    def boom():
        raise httpx.ConnectError("relay down")
    live(monkeypatch, boom)
    r = send(client, employer(client))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "voice_unavailable"


def test_timeout_is_504(client, monkeypatch):
    def slow():
        time.sleep(1.5)
        return dg("поздно")
    live(monkeypatch, slow)
    monkeypatch.setenv("VOICE_NEED_TIMEOUT_S", "0.3")
    get_settings.cache_clear()
    r = send(client, employer(client))
    assert r.status_code == 504 and r.json()["detail"]["code"] == "voice_timeout"


def test_silence_and_too_long_by_provider(client, monkeypatch):
    live(monkeypatch, lambda: dg("   ", 3.0))
    t = employer(client)
    r = send(client, t)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "voice_empty"
    live(monkeypatch, lambda: dg("очень долго", 95.0))
    r = send(client, t)  # браузер не прислал длительность — проверка по ответу распознавания
    assert r.status_code == 413 and r.json()["detail"]["code"] == "voice_too_long"


def test_long_text_is_clipped_to_field(client, monkeypatch):
    live(monkeypatch, lambda: dg("Python " * 2000, 59.0))
    j = send(client, employer(client)).json()
    assert j["truncated"] is True and j["chars"] == voice.TEXT_MAX


def test_nothing_logged_or_stored(client, monkeypatch, caplog):
    live(monkeypatch, lambda: dg("Секретный проект Альфа, звонить Ивану"))
    t = employer(client)
    with caplog.at_level(logging.DEBUG):
        assert send(client, t).status_code == 200
    assert "Альфа" not in caplog.text and "Ивану" not in caplog.text
    assert client.get("/api/employer/needs", headers=H(t)).json() == []


def test_openapi_describes_route(client):
    op = client.get("/api/openapi.json").json()["paths"][URL]["post"]
    assert {"409", "413", "415", "422", "429", "503", "504"} <= set(op["responses"])
    assert op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("VoiceNeedOut")


def test_criteria_lists_voice_only_when_enabled(client, monkeypatch):
    """/criteria: пункт «Надиктовать потребность» в «Что можно проверить только здесь» — только при включённом флаге;
    в docs/CRITERIA.md — заметка после раздела 6 (флаг выкл. по умолчанию)."""
    from app.modules.validation import criteria as C

    env(monkeypatch, VOICE_NEED_ENABLED="false")
    assert all(u["title"] != "Надиктовать потребность" for u in client.get("/api/validation/criteria").json()["unique"])
    env(monkeypatch)
    u = [u for u in client.get("/api/validation/criteria").json()["unique"] if u["title"] == "Надиктовать потребность"]
    assert len(u) == 1 and u[0]["do"][0]["to"] == "/employer/needs#need" and u[0]["do"][0]["as"] == "employer"
    assert "VOICE_NEED_ENABLED" in C.VOICE_NOTE and "docs/VOICE.md" in C.VOICE_NOTE
