"""Обход всех маршрутов приложения FastAPI — общий хелпер тестов безопасности.

FastAPI 0.142: ``app.include_router(...)`` кладёт в ``app.routes`` не APIRoute, а ``_IncludedRouter``; у него
нет ``path``, настоящие маршруты (в том числе вложенных роутеров) отдаёт ``effective_route_contexts()``.
Перебор ``app.routes`` по ``path`` молча пропускает всё, что подключено через роутеры, — то есть почти всё API.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

from starlette.routing import Mount


@dataclass(frozen=True)
class RouteInfo:
    method: str
    path: str
    endpoint: Any
    name: str  # модуль.функция — для подсказок в сообщениях тестов

    @property
    def key(self) -> tuple[str, str]:
        return self.method, self.path


def _walk(routes) -> Iterator[tuple[str, set[str] | None, Any]]:
    for r in routes:
        if type(r).__name__ == "_IncludedRouter":  # fastapi.routing — приватный класс, по имени
            for c in r.effective_route_contexts():
                yield c.path, set(getattr(c, "methods", None) or ()), c.endpoint
        elif isinstance(r, Mount):
            # статика (StaticFiles) — один «виртуальный» маршрут GET <mount>/{path}
            yield r.path.rstrip("/") + "/{path:path}", {"GET"}, getattr(r, "app", None)
            yield from _walk(getattr(r, "routes", None) or [])
        elif hasattr(r, "routes"):  # вложенный Router без контекста включения
            yield from _walk(r.routes)
        else:
            yield getattr(r, "path", None), set(getattr(r, "methods", None) or ()), getattr(r, "endpoint", None)


def iter_routes(app, *, skip_methods: tuple[str, ...] = ("HEAD", "OPTIONS")) -> list[RouteInfo]:
    """Все пары «метод × путь» приложения, включая вложенные роутеры и статику; отсортированы по пути и методу."""
    out: dict[tuple[str, str], RouteInfo] = {}
    for path, methods, endpoint in _walk(app.routes):
        if not path:
            continue
        for m in sorted(methods or {"GET"}):
            if m in skip_methods:
                continue
            name = f"{getattr(endpoint, '__module__', '?')}.{getattr(endpoint, '__name__', type(endpoint).__name__)}"
            out.setdefault((m, path), RouteInfo(m, path, endpoint, name))
    return sorted(out.values(), key=lambda r: (r.path, r.method))


def paths(app, prefix: str = "") -> list[str]:
    """Уникальные пути (с префиксом) — для простых проверок вроде «все /api/admin/* закрыты»."""
    return sorted({r.path for r in iter_routes(app) if r.path.startswith(prefix)})
