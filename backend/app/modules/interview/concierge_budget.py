"""Ограничения расходов живого проводника Насти (стенд открыт всем).

Что стоит денег: минуты видеопотока (каждый токен сессии — до 10 минут у поставщика), ходы модели (/concierge/turn),
знаки синтеза голоса вне кэша (/concierge/speech, ответы модели). Поэтому считаем в сутки (по московскому времени):
  • токены видеопотока — на всех (CONCIERGE_DAILY_SESSIONS) и с одного адреса (CONCIERGE_IP_SESSIONS), не больше
    CONCIERGE_CONV_TOKENS на один разговор (плановая пересадка на свежую сессию);
  • ходы модели — на всех (CONCIERGE_DAILY_TURNS) и с одного адреса (CONCIERGE_IP_TURNS); сверх лимита Настя отвечает
    без модели — командами сценария и ответами из базы знаний;
  • знаки синтеза вне кэша — на всех (CONCIERGE_DAILY_TTS_CHARS) и с одного адреса (CONCIERGE_IP_TTS_CHARS).
Плюс короткое окно от всплесков с одного адреса (CONCIERGE_BURST_PER_MIN запросов в минуту на адрес). Счётчики — маленький
JSON на общем диске кэша (API работает в нескольких процессах) под файловой блокировкой; всплески — в памяти процесса.
Нули в переменных окружения выключают соответствующий лимит.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("interview.concierge")

MSK = timezone(timedelta(hours=3))

DAILY_SESSIONS = int(os.environ.get("CONCIERGE_DAILY_SESSIONS", "100"))
IP_SESSIONS = int(os.environ.get("CONCIERGE_IP_SESSIONS", "30"))
CONV_TOKENS = int(os.environ.get("CONCIERGE_CONV_TOKENS", "6"))
DAILY_TURNS = int(os.environ.get("CONCIERGE_DAILY_TURNS", "2000"))
IP_TURNS = int(os.environ.get("CONCIERGE_IP_TURNS", "500"))
DAILY_TTS_CHARS = int(os.environ.get("CONCIERGE_DAILY_TTS_CHARS", "80000"))
IP_TTS_CHARS = int(os.environ.get("CONCIERGE_IP_TTS_CHARS", "30000"))
BURST_PER_MIN = int(os.environ.get("CONCIERGE_BURST_PER_MIN", "80"))
# Адреса без лимитов (владелец, жюри на защите): через запятую, точные адреса или префиксы вида «10.0.»
TRUSTED = tuple(x.strip() for x in os.environ.get("CONCIERGE_TRUSTED_IPS", "").split(",") if x.strip())

_LIMITS = {"sessions": (DAILY_SESSIONS, IP_SESSIONS), "turns": (DAILY_TURNS, IP_TURNS), "tts": (DAILY_TTS_CHARS, IP_TTS_CHARS)}


def _dir() -> Path:
    from app.modules.interview.concierge import _CACHE

    p = _CACHE / "budget"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def today() -> str:
    return datetime.now(MSK).strftime("%Y-%m-%d")


def trusted(ip: str | None) -> bool:
    if not ip:
        return False
    return any(ip == t or (t.endswith(".") and ip.startswith(t)) for t in TRUSTED)


def _load(fp: Path) -> dict:
    try:
        d = json.loads(fp.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(fp: Path, d: dict) -> None:
    tmp = fp.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, fp)
    except OSError as e:
        log.warning("concierge budget save: %s", e)


def _cleanup(root: Path) -> None:
    cutoff = (datetime.now(MSK) - timedelta(days=7)).strftime("%Y-%m-%d")
    try:
        for f in root.glob("*.json"):
            if f.stem < cutoff:
                f.unlink(missing_ok=True)
    except OSError:
        pass


def take(kind: str, ip: str | None, n: int = 1, conv: str | None = None) -> tuple[bool, str | None]:
    """Списать n единиц (токен, ход, знаки) на сегодня. (True, None) — можно; (False, причина) — лимит исчерпан.
    kind: sessions | turns | tts. conv — id разговора (для sessions: не больше CONV_TOKENS на разговор)."""
    if kind not in _LIMITS:
        return True, None
    if trusted(ip):
        return True, None
    daily, per_ip = _LIMITS[kind]
    root = _dir()
    fp = root / f"{today()}.json"
    lock_fp = root / ".lock"
    fh = None
    try:
        fh = open(lock_fp, "a+")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except OSError:
        fh = None
    try:
        d = _load(fp)
        tot = d.setdefault("total", {})
        ips = d.setdefault("ip", {})
        convs = d.setdefault("conv", {})
        me = ips.setdefault(ip or "?", {}) if ip else {}
        if daily and tot.get(kind, 0) + n > daily:
            return False, f"{kind}_daily"
        if per_ip and ip and me.get(kind, 0) + n > per_ip:
            return False, f"{kind}_ip"
        if kind == "sessions" and conv and CONV_TOKENS and convs.get(conv, 0) + n > CONV_TOKENS:
            return False, "sessions_conv"
        tot[kind] = tot.get(kind, 0) + n
        if ip:
            me[kind] = me.get(kind, 0) + n
        if kind == "sessions" and conv:
            convs[conv] = convs.get(conv, 0) + n
            if len(convs) > 500:
                for k in list(convs)[:100]:
                    convs.pop(k, None)
        _save(fp, d)
        if int(time.time()) % 50 == 0:
            _cleanup(root)
        return True, None
    finally:
        if fh is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                fh.close()
            except OSError:
                pass


def usage() -> dict:
    """Сегодняшние счётчики (для журнала и проверки владельцем)."""
    d = _load(_dir() / f"{today()}.json")
    return {"date": today(), "total": d.get("total", {}), "ips": len(d.get("ip", {})),
            "limits": {"sessions": DAILY_SESSIONS, "ip_sessions": IP_SESSIONS, "turns": DAILY_TURNS, "ip_turns": IP_TURNS,
                       "tts_chars": DAILY_TTS_CHARS, "ip_tts_chars": IP_TTS_CHARS}}


# ------------------------------------------------------------------ всплески (в памяти процесса)

_BURST: dict[str, list[float]] = {}
_BURST_LOCK = threading.Lock()


def burst_ok(ip: str | None, weight: int = 1) -> bool:
    """Не больше BURST_PER_MIN запросов в минуту с одного адреса (на процесс API — реальный предел чуть выше)."""
    if not BURST_PER_MIN or not ip or trusted(ip):
        return True
    now = time.time()
    with _BURST_LOCK:
        q = _BURST.setdefault(ip, [])
        while q and now - q[0] > 60:
            q.pop(0)
        if len(q) + weight > BURST_PER_MIN:
            return False
        q.extend([now] * weight)
        if len(_BURST) > 2000:
            for k in [k for k, v in _BURST.items() if not v or now - v[-1] > 120][:500]:
                _BURST.pop(k, None)
        return True


def client_ip(request) -> str | None:
    """Адрес посетителя за nginx: X-Forwarded-For (первый адрес) или X-Real-IP, иначе адрес соединения."""
    try:
        h = request.headers
        fwd = h.get("x-forwarded-for") or h.get("x-real-ip") or ""
        if fwd:
            return fwd.split(",")[0].strip()[:64]
        return request.client.host if request.client else None
    except Exception:  # noqa: BLE001
        return None
