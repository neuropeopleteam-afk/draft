"""Подпись мира у каждого числа /validation (консилиум 07.10, п. 7.1): seed, hash конфигурации, коммит, банк.

Подпись кладётся в каждый JSON расчёта (``signature(...)``) и показывается рядом с числом на /validation, чтобы
читатель видел, на каком мире и какой версии кода получено число. Коммит — переменная окружения ``GIT_COMMIT``
(Makefile передаёт её на сервер проверок, где нет .git), иначе ``git rev-parse``, иначе «unknown».
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2]
REPO = BACKEND.parent


def config_hash(obj) -> str:
    """Короткий sha256 канонического JSON конфигурации (12 знаков, как у бенчмарка подбора)."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:12]


def git_commit() -> str:
    env = (os.environ.get("GIT_COMMIT") or "").strip()
    if env:
        return env[:12]
    try:
        out = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=REPO, capture_output=True, text=True,
                             timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def bank_hash() -> str | None:
    p = BACKEND / "assessment_bank" / "BANK_SYNC.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d.get("content_hash")


def signature(*, seed, config: dict, world: str, command: str, n: int | None = None) -> dict:
    """Подпись расчёта: мир (словами), seed, hash конфигурации, коммит кода, версия банка, когда и чем посчитано."""
    return {"world": world, "seed": seed, "config_hash": config_hash(config), "commit": git_commit(),
            "bank": bank_hash(), "n": n, "command": command,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def short(sig: dict | None) -> str:
    """Подпись одной строкой: «мир …, seed …, конфигурация …, коммит …»."""
    if not sig:
        return "подписи нет"
    parts = [sig.get("world") or "", f"seed {sig.get('seed')}", f"конфигурация {sig.get('config_hash')}",
             f"коммит {sig.get('commit')}"]
    return ", ".join(p for p in parts if p)
