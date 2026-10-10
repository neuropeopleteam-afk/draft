"""HTTP-клиент api.hh.ru: тайм-ауты, кэш на диске, ограничение частоты на все воркеры, понятные ошибки.

* Заголовки (требование hh.ru): ``Authorization: Bearer <HH_APP_TOKEN>``, ``HH-User-Agent`` и ``User-Agent`` =
  ``HH_USER_AGENT``. Токен приложения выдан один раз; повторный запрос токена по client id/secret ОТЗЫВАЕТ
  действующий — клиент этого не делает никогда (только читает HH_APP_TOKEN из secrets/hh.env).
* Не чаще 1 запроса в ``hh_min_interval_s`` (1 с) на ВСЕ процессы: файловая блокировка ``fcntl`` и метка времени
  последнего запроса в ``<hh_cache_dir>/.rate`` (у api два воркера uvicorn в одном контейнере).
* Кэш ответов — JSON-файлы в ``hh_cache_dir`` (ключ — sha256 пути и параметров, без токена); срок — у вызова.
  При сбое hh.ru (сеть, 5xx, 429) отдаём просроченную запись с пометкой ``stale`` — честно с датой.
* Ошибки — ``HhError(status, code, message)`` с текстом для человека; токен в сообщения и логи не попадает.
* HH_STUB=1 — тот же клиент поверх ``httpx.MockTransport`` с фикстурой (``app.modules.hh.stub``): сеть не нужна.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

from app.core.config import Settings, get_settings

log = logging.getLogger(__name__)
LOCK_WAIT_S = 30.0  # дольше ждать очередь к hh.ru не имеет смысла — пользователь увидит «повторите»


class HhError(Exception):
    """Ошибка hh.ru для человека: status — код ответа нашего API, code — машинный код, message — текст."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def available(s: Settings | None = None) -> bool:
    return (s or get_settings()).hh_available


def _key(path: str, params) -> str:
    items = sorted((str(k), str(v)) for k, v in (params.items() if isinstance(params, dict) else params or []))
    return hashlib.sha256(f"{path}?{urlencode(items)}".encode()).hexdigest()


def _hh_message(r: httpx.Response) -> str:
    try:
        d = r.json()
    except ValueError:
        return ""
    errs = d.get("errors") or []
    parts = [str(e.get("value") or e.get("type") or "") for e in errs if isinstance(e, dict)]
    return ", ".join(p for p in parts if p)[:200]


def error_for(r: httpx.Response) -> HhError:
    """Код ответа hh.ru → понятная ошибка нашего API."""
    st, why = r.status_code, _hh_message(r)
    if st == 404:
        return HhError(404, "hh_not_found", "На hh.ru такой вакансии нет: проверьте номер или ссылку "
                                            "(вакансия могла быть удалена)")
    if st == 400:
        return HhError(422, "hh_bad_request", f"hh.ru не принял запрос{': ' + why if why else ''}")
    if st == 429:
        return HhError(429, "hh_rate_limited", "hh.ru ограничил частоту запросов — повторите через минуту")
    if st in (401, 403):
        if "captcha" in why:
            return HhError(502, "hh_captcha", "hh.ru просит капчу для запросов приложения — повторите позже")
        return HhError(502, "hh_forbidden", "hh.ru отклонил токен приложения (код "
                                            f"{st}) — сообщите администратору платформы")
    return HhError(502, "hh_unavailable", f"hh.ru временно недоступен (код {st}) — повторите позже")


class HhClient:
    def __init__(self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None,
                 min_interval_s: float | None = None):
        self.s = settings or get_settings()
        self.stub = self.s.hh_stub and transport is None
        if self.stub:
            from app.modules.hh.stub import transport as stub_transport
            transport = stub_transport()
        self.transport = transport
        self.interval = (0.0 if self.stub else self.s.hh_min_interval_s) if min_interval_s is None else min_interval_s
        self.dir = Path(self.s.hh_cache_dir)

    # ---------------------------------------------------------------- кэш
    def _path(self, key: str) -> Path:
        return self.dir / ("stub" if self.stub else "live") / key[:2] / f"{key}.json"

    def _read(self, key: str) -> dict | None:
        p = self._path(key)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write(self, key: str, entry: dict) -> None:
        p = self._path(key)
        try:
            p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = p.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, p)
        except OSError as e:  # кэш — оптимизация: без него работаем, только медленнее
            log.warning("hh: кэш не записан (%s)", type(e).__name__)

    # ---------------------------------------------------------------- частота
    @contextlib.contextmanager
    def _throttle(self):
        """Не чаще 1 запроса в interval на все процессы: блокировка файла + метка последнего запроса."""
        if self.interval <= 0:
            yield
            return
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(self.dir / ".rate", "a+", encoding="utf-8") as f:
            deadline = time.monotonic() + LOCK_WAIT_S
            while True:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        raise HhError(503, "hh_busy", "Очередь запросов к hh.ru занята — повторите через минуту") from None
                    time.sleep(0.05)
            try:
                f.seek(0)
                try:
                    last = float(f.read().strip() or 0)
                except ValueError:
                    last = 0.0
                wait = last + self.interval - time.time()
                if wait > 0:
                    time.sleep(min(wait, self.interval))
                yield
            finally:
                f.seek(0)
                f.truncate()
                f.write(f"{time.time():.3f}")
                f.flush()
                fcntl.flock(f, fcntl.LOCK_UN)

    # ---------------------------------------------------------------- запрос
    def _headers(self) -> dict:
        ua = self.s.hh_user_agent or "platform-dev/0.1 (stub)"
        h = {"HH-User-Agent": ua, "User-Agent": ua, "Accept": "application/json"}
        if self.s.hh_app_token:
            h["Authorization"] = f"Bearer {self.s.hh_app_token}"
        return h

    def get(self, path: str, params=None, *, ttl_s: int, allow_stale: bool = True) -> dict:
        """GET api.hh.ru (или заглушки) с кэшем. Ответ: {data, fetched_at, cached, stale, stub}."""
        if not (self.stub or self.transport is not None or (self.s.hh_app_token and self.s.hh_user_agent)):
            raise HhError(404, "hh_disabled", "Интеграция с hh.ru не настроена")
        key = _key(path, params)
        hit = self._read(key)
        now = time.time()
        if hit and ttl_s > 0 and now - float(hit.get("ts", 0)) < ttl_s:
            return {"data": hit["data"], "fetched_at": hit["fetched_at"], "cached": True, "stale": False,
                    "stub": self.stub}
        try:
            data = self._fetch(path, params)
        except HhError as e:
            if allow_stale and hit and e.code not in ("hh_not_found", "hh_bad_request"):
                log.warning("hh: %s — отдаём кэш от %s", e.code, hit.get("fetched_at"))
                return {"data": hit["data"], "fetched_at": hit["fetched_at"], "cached": True, "stale": True,
                        "stub": self.stub}
            raise
        entry = {"ts": time.time(), "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "path": path, "data": data}
        self._write(key, entry)
        return {"data": data, "fetched_at": entry["fetched_at"], "cached": False, "stale": False, "stub": self.stub}

    def _fetch(self, path: str, params) -> dict:
        t = self.s.hh_timeout_s
        timeout = httpx.Timeout(t, connect=min(5.0, t))
        with self._throttle():
            try:
                with httpx.Client(base_url=self.s.hh_base_url, timeout=timeout, transport=self.transport,
                                  headers=self._headers(), follow_redirects=False) as c:
                    r = c.get(path, params=params)
            except httpx.TimeoutException:
                raise HhError(504, "hh_timeout", f"hh.ru не ответил за {t:.0f} с — повторите позже") from None
            except httpx.HTTPError as e:
                raise HhError(502, "hh_unavailable", f"hh.ru недоступен ({type(e).__name__}) — повторите позже") from None
        if r.status_code != 200:
            raise error_for(r)
        try:
            return r.json()
        except ValueError:
            raise HhError(502, "hh_bad_response", "hh.ru вернул ответ не в формате JSON — повторите позже") from None


def client() -> HhClient:
    return HhClient()
