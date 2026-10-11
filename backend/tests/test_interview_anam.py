"""Живой аватар Anam с нашим лицом (feat/anam-own): маршрут токена за флагом INTERVIEW_ANAM_ENABLED (выкл. по умолчанию → 503,
клиент тихо остаётся на портрете), /speech?format=pcm для передачи звука, channels.avatar, учёт avatar_usd."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.modules.interview import port as pt
from tests.test_day2_rules import H, candidate_with_category
from tests.test_interview import _fake_engine, _with_open_answers


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(get_settings(), "interview_enabled", True)
    monkeypatch.setattr(get_settings(), "interview_engine", "stub")
    return get_settings()


def _session(client, on, monkeypatch, eng):
    monkeypatch.setattr(pt, "get_port", lambda: pt.EnginePort(eng))
    t = candidate_with_category(client)
    ts = _with_open_answers(client, t)
    sid = client.post(f"/api/interview/defense/{ts}", json={"name": "Иван", "consent": True}, headers=H(t)).json()["id"]
    return t, sid


def test_avatar_token_and_pcm_speech(client, on, monkeypatch):
    eng = _fake_engine()
    fmts: list[str] = []

    def tts(text, fmt="mp3"):
        fmts.append(fmt)
        if fmt == "pcm_16000":
            return SimpleNamespace(data=b"\x00\x00" * 1600, mime="audio/pcm", cost_usd=0.003, stub=False)
        return SimpleNamespace(data=b"ID3fake", mime="audio/mpeg", cost_usd=0.003, stub=False)
    eng.tts = tts
    eng.avatar_token = lambda: SimpleNamespace(model_dump=lambda mode="json": {
        "session_token": "tok", "max_seconds": 600, "ice_servers": None, "relay_only": False, "persona_name": "Интервьюер"})
    t, sid = _session(client, on, monkeypatch, eng)
    # до начала разговора токен выдаётся (экран может поднимать поток заранее), после закрытия — нет
    r = client.post(f"/api/interview/sessions/{sid}/avatar-token", headers=H(t))
    assert r.status_code == 200 and r.json() == {"session_token": "tok", "max_seconds": 600, "ice_servers": None,
                                                 "relay_only": False, "persona_name": "Интервьюер"}
    s = client.post(f"/api/interview/sessions/{sid}/begin", json={"channel": "voice"}, headers=H(t)).json()
    assert s["conversation"]["channels"]["avatar"] is True
    sp = client.get(f"/api/interview/sessions/{sid}/speech?format=pcm", headers=H(t))
    assert sp.status_code == 200 and sp.headers["content-type"] == "audio/pcm" and len(sp.content) == 3200
    assert client.get(f"/api/interview/sessions/{sid}/speech", headers=H(t)).headers["content-type"] == "audio/mpeg"
    assert client.get(f"/api/interview/sessions/{sid}/speech?format=wav", headers=H(t)).status_code == 422
    assert fmts == ["pcm_16000", "mp3"]
    client.post(f"/api/interview/sessions/{sid}/finish", headers=H(t))  # без ответов — разговор закрыт
    assert client.post(f"/api/interview/sessions/{sid}/avatar-token", headers=H(t)).status_code == 409


def test_avatar_token_off_by_default(client, on, monkeypatch):
    """Флаг движка выключен → EngineError(avatar_unavailable) → 503; channels.avatar=false — экран не трогает поставщика."""
    from app.modules.interview.engine.errors import EngineError
    eng = _fake_engine()
    eng.status = lambda: {"stub": False, "channels": {"text": True, "voice": True, "stt": True, "avatar": False}}

    def avatar_token():
        raise EngineError("avatar_unavailable", "Канал «аватар» выключен")
    eng.avatar_token = avatar_token
    t, sid = _session(client, on, monkeypatch, eng)
    s = client.post(f"/api/interview/sessions/{sid}/begin", json={"channel": "voice"}, headers=H(t)).json()
    assert s["conversation"]["channels"]["avatar"] is False
    r = client.post(f"/api/interview/sessions/{sid}/avatar-token", headers=H(t))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "avatar_unavailable"


def test_avatar_token_needs_login(client, on):
    assert client.post("/api/interview/sessions/00000000-0000-0000-0000-000000000000/avatar-token").status_code in (401, 403)


def test_own_face_only():
    """Лицо — только наше: в коде нет стокового id поставщика, документация — наш аватар; плашек поставщика нет."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    src = (root / "backend/app/modules/interview/engine/providers/avatar.py").read_text(encoding="utf-8")
    assert "19d18eb0" not in src and '"showAIAvatarDisclosure": False' in src and '"enableAudioPassthrough": True' in src
    deploy = (root / "backend/app/modules/interview/engine/DEPLOY.md").read_text(encoding="utf-8")
    assert "e98c6f5f-445f-4935-a920-97879c41a799" in deploy and "PROVENANCE.md" in deploy
    ui = (root / "frontend/src/components/voice/AnamAvatar.tsx").read_text(encoding="utf-8")
    assert "disableInputAudio: true" in ui and "sendAudioChunk" in ui and "InterviewerAvatar" in ui  # передача звука и откат на портрет
    assert "@anam-ai/js-sdk" in (root / "frontend/package.json").read_text(encoding="utf-8")
