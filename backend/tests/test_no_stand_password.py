"""Пароль стенда не лежит в репозитории и не показывается в интерфейсе (Ф1, С-2)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_stand_password_not_in_repository():
    needle = ("Hak" + "aton").lower()
    skip = {".git", "node_modules", "dist", ".venv", ".venv_bank", "__pycache__", ".pytest_cache", "reports"}
    hits = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in files:
            p = Path(base) / name
            if p.is_symlink() or p.stat().st_size > 3_000_000:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if needle in text.lower():
                hits.append(str(p.relative_to(ROOT)))
    assert not hits, f"пароль стенда в файлах: {hits}"


def test_ui_points_to_submission_materials_and_screen_has_no_password():
    for rel in ("frontend/src/pages/Landing.tsx", "frontend/src/pages/Login.tsx"):
        assert "в материалах сдачи" in (ROOT / rel).read_text(encoding="utf-8"), rel
    screen = (ROOT / "frontend/src/ideas/live/Screen.tsx").read_text(encoding="utf-8").lower()
    assert "парол" not in screen.replace("без пароля стенда (базовая авторизация nginx)", "")  # в тексте экрана — ни слова
