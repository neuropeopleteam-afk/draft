"""Живой переключатель конкурсного режима жюри (jury-mode on|off|status).

Проверяет наличие флаг-файла /run/spectrek/jury_off (примонтированный каталог с хоста /opt/spectrek_fsp/runtime)
или /tmp/spectrek_jury_off с коротким кэшем 0,4 с, чтобы переключение работало за < 1 с без перезапуска контейнеров.
"""
from __future__ import annotations

import os
import time

from app.core.config import get_settings

_PATHS = (
    os.environ.get("JURY_OFF_FLAG", "/run/spectrek/jury_off"),
    "/opt/spectrek_fsp/runtime/jury_off",
    "/tmp/spectrek_jury_off",
)
_cache: tuple[float, bool] = (0.0, False)


def jury_off() -> bool:
    global _cache
    now = time.monotonic()
    if now - _cache[0] > 0.4:
        off = any(os.path.exists(p) for p in _PATHS)
        _cache = (now, off)
    return _cache[1]


def jury_on() -> bool:
    return bool(get_settings().jury_mode_available) and not jury_off()
