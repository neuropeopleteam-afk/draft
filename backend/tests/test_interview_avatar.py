"""В1: свой рисованный образ интервьюера (INTERVIEW_AVATAR_ENABLED) — флаг в /api/meta, отделение от поставщика Anam
(INTERVIEW_ANAM_ENABLED), файлы образа и клипов с происхождением (frontend/public/avatar/)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.modules.interview import engine as e

AVATAR_DIR = Path(__file__).resolve().parents[2] / "frontend" / "public" / "avatar"
STATES = ("idle", "speaking", "listening", "thinking")
MAX_CLIP = 1_500_000  # карточка: каждый клип ≤ 1,5 МБ


def test_meta_avatar_off_by_default(client):
    iv = client.get("/api/meta").json()["interview"]
    assert iv["avatar"] is False and iv["enabled"] is False


def test_meta_avatar_needs_interview_flag(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "interview_avatar_enabled", True)
    assert client.get("/api/meta").json()["interview"]["avatar"] is False  # без INTERVIEW_ENABLED образа нет
    monkeypatch.setattr(get_settings(), "interview_enabled", True)
    monkeypatch.setattr(get_settings(), "interview_engine", "stub")
    iv = client.get("/api/meta").json()["interview"]
    assert iv["enabled"] is True and iv["avatar"] is True
    monkeypatch.setattr(get_settings(), "interview_avatar_enabled", False)
    assert client.get("/api/meta").json()["interview"]["avatar"] is False


def test_avatar_flag_does_not_enable_provider(monkeypatch):
    """INTERVIEW_AVATAR_ENABLED включает только свой образ; канал поставщика (Anam) — отдельный флаг, по умолчанию выкл."""
    monkeypatch.setenv("INTERVIEW_STUB", "0")
    monkeypatch.setenv("INTERVIEW_AVATAR_ENABLED", "1")
    monkeypatch.setenv("ANAM_API_KEY", "k")
    monkeypatch.setenv("ANAM_AVATAR_ID", "av-1")
    e.reset_interview_settings()
    try:
        st = e.status()
        assert st["anam_enabled"] is False and st["channels"]["avatar"] is False
        with pytest.raises(e.EngineError) as ei:
            e.avatar_token()
        assert ei.value.code == "avatar_unavailable"
    finally:
        e.reset_interview_settings()


@pytest.mark.skipif(not AVATAR_DIR.parent.is_dir(), reason="каталога frontend/public нет (прогон только backend)")
def test_avatar_assets_and_provenance():
    assert (AVATAR_DIR / "interviewer.webp").is_file()
    for st in STATES:
        for ext in ("webm", "mp4"):
            f = AVATAR_DIR / f"{st}.{ext}"
            assert f.is_file(), f
            assert 10_000 < f.stat().st_size <= MAX_CLIP, (f, f.stat().st_size)
    prov = (AVATAR_DIR / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "сгенерирован" in prov.lower() and "gpt_image_2_5_flare" in prov and "veo_3_1_fast" in prov
    assert re.search(r"2026-10-11", prov) and "не человек" in prov
