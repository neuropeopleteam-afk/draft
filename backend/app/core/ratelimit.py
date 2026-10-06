"""Ограничение частоты для служебных и тяжёлых эндпоинтов (скользящее окно в памяти процесса).

Счётчики живут в памяти воркера uvicorn: при двух воркерах фактический предел — до двух значений лимита.
Для защиты демо этого достаточно; там, где важна точность между воркерами и перезапусками (загрузки резюме),
лимит считается по БД.

Адрес клиента: внешний nginx дописывает настоящий адрес в X-Forwarded-For, nginx контейнера web — адрес
хоста (частная сеть Docker). Берём самый правый публичный адрес цепочки: подделанные клиентом значения стоят
левее и не учитываются (см. аудит, Н11).
"""
from __future__ import annotations

from collections import deque
import ipaddress
import threading
import time

from fastapi import Request

from app.core.errors import api_error

_MAX_KEYS = 50_000
_ALL: list["SlidingWindow"] = []


class SlidingWindow:
    def __init__(self, limit: int, window_s: float):
        self.limit, self.window_s = limit, window_s
        self._hits: dict[str, deque[float]] = {}
        self._mx = threading.Lock()
        _ALL.append(self)

    def retry_after(self, key: str, now: float | None = None) -> int:
        """0 — можно (и попытка засчитана); иначе — через сколько секунд повторить."""
        now = time.monotonic() if now is None else now
        with self._mx:
            if len(self._hits) > _MAX_KEYS:  # защита памяти: старые ключи отбрасываем
                self._hits.clear()
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                return max(1, int(self.window_s - (now - q[0])) + 1)
            q.append(now)
            return 0

    def reset(self) -> None:
        with self._mx:
            self._hits.clear()


def reset_all() -> None:
    """Сбросить все счётчики (тесты)."""
    for w in _ALL:
        w.reset()


def hit(limiter: SlidingWindow, key: str, code: str, message: str) -> None:
    left = limiter.retry_after(key)
    if left:
        exc = api_error(429, code, f"{message}. Повторите через {_human(left)}")
        exc.headers = {"Retry-After": str(left)}
        raise exc


def _human(s: int) -> str:
    if s < 90:
        return f"{s} с"
    m = (s + 59) // 60
    return f"{m} мин" if m < 90 else f"{(m + 59) // 60} ч"


def _public(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.strip())
    except ValueError:
        return False
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_unspecified)


def client_ip(request: Request) -> str:
    chain = [x.strip() for x in request.headers.get("x-forwarded-for", "").split(",") if x.strip()]
    for ip in reversed(chain):
        if _public(ip):
            return ip
    real = request.headers.get("x-real-ip", "").strip()
    if real and _public(real):
        return real
    return chain[-1] if chain else (request.client.host if request.client else "unknown")
