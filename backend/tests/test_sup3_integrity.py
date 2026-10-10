"""Я11 (С3-5): тест на телефоне — полноэкранный режим недоступен (fs_na), это не причина снижения достоверности."""
from __future__ import annotations

from app.modules.assessment import integrity


def _item(**sig):
    base = {"focus_lost": 0, "hidden_ms": 0, "paste": 0, "paste_chars": 0, "copy": 0,
            "fs_ms": 0, "fs_out_ms": 0, "fs_exit": 0}
    return {"format": "open_answer", "canary": False, "time_s": 120.0, "time_limit_s": 300, "score": 0.8,
            "signals": {**base, **sig}}


def _fs_reasons(r: dict) -> list[str]:
    return [x for x in r["reasons"] if "полноэкранн" in x]


def test_phone_old_client_time_outside_is_not_exit():
    # прежний клиент на iPhone: fs_na = 1, но всё время задания — в fs_out_ms (8 × 2 мин = 16 мин «вне режима»)
    r = integrity.assess([_item(fs_na=1, fs_out_ms=120_000) for _ in range(8)])
    assert r["level"] == "high" and r["points"] == 0 and not _fs_reasons(r)
    assert r["signals"]["fs_out_s"] == 0 and r["signals"]["fs_never"] is False


def test_phone_new_client():
    r = integrity.assess([_item(fs_na=1) for _ in range(8)])
    assert r["level"] == "high" and not _fs_reasons(r)


def test_desktop_rules_unchanged():
    never = integrity.assess([_item(fs_na=0) for _ in range(6)])
    assert never["points"] == 1 and "без полноэкранного режима" in never["reasons"][0]
    out = integrity.assess([_item(fs_na=0, fs_ms=60_000, fs_exit=1, fs_out_ms=30_000) for _ in range(3)])
    assert out["points"] == 1 and "Выход из полноэкранного режима: 3 раза" in out["reasons"][0]
    # смешанно (часть заданий на компьютере): считаются только задания, где режим был доступен
    mix = integrity.assess([_item(fs_na=0, fs_ms=10_000, fs_exit=3, fs_out_ms=40_000)] * 2
                           + [_item(fs_na=1, fs_out_ms=600_000)] * 4)
    assert mix["signals"]["fs_exits"] == 6 and mix["signals"]["fs_out_s"] == 80.0
    assert mix["points"] == 2 and "6 раз" in _fs_reasons(mix)[0]
