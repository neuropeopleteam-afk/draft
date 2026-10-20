"""Живое распознавание речи для разговора «как по видеосвязи»: WebSocket-мост браузер → потоковое распознавание.

Микрофон включается в браузере один раз (эхоподавление, шумоподавление, автоусиление), AudioWorklet режет звук на кадры
PCM s16le 16 кГц моно по ~100 мс и шлёт их сюда; сервер пересылает кадры поставщику распознавания (ключ остаётся на
сервере, из браузера не виден) и возвращает короткие события:

  {"type": "ready"}                                — канал распознавания открыт
  {"type": "speech_started"}                       — голосовая активность (VAD поставщика)
  {"type": "interim", "text": "..."}               — промежуточный текст (ещё может измениться)
  {"type": "final", "text": "...", "speech_final": bool}  — окончательный текст сегмента; speech_final — пауза после фразы
  {"type": "speech_final_empty"}                   — пауза без нового текста
  {"type": "utterance_end"}                        — длинная пауза после последнего слова
  {"type": "error", "message": "..."}

Сообщения клиента: двоичные кадры звука; текст {"type": "finalize"} — дослать распознанное сразу (конец хода по кнопке).

Ограничения (на процесс): соединений с одного IP — LIVE_STT_PER_IP (по умолчанию 3), всего — LIVE_STT_MAX (40), одно
соединение — не дольше LIVE_STT_MAX_S секунд (900). Только с адресов стенда (Origin).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from urllib.parse import urlencode

from fastapi import WebSocket, WebSocketDisconnect

from app.modules.interview.engine.settings import get_interview_settings

log = logging.getLogger("interview.live_stt")

DG_HOST = "wss://api.deepgram.com/v1/listen"
PER_IP = int(os.environ.get("LIVE_STT_PER_IP", "3"))
MAX_TOTAL = int(os.environ.get("LIVE_STT_MAX", "40"))
MAX_S = int(os.environ.get("LIVE_STT_MAX_S", "900"))
_ALLOWED_ORIGINS = tuple(x.strip() for x in os.environ.get(
    "LIVE_STT_ORIGINS", "https://fsp-draft.ru,https://www.fsp-draft.ru,https://fsp.neuropeople.pro,http://localhost,http://127.0.0.1",
).split(",") if x.strip())

_by_ip: dict[str, int] = {}
_total = 0


# Профиль «guide» (Елена на сайте): слова сайта — распознаются точнее (подсказка ключевых слов поставщику).
GUIDE_KEYTERMS = ("Драфт", "Елена", "работодатель", "работодателя", "кандидат", "кандидата", "Федерация",
                  "ФСП", "грейд", "кабинет", "пропустить", "пропусти", "дальше", "подожди", "вакансия", "приглашение",
                  "зарплатная вилка", "паспорт честности", "устная защита", "карта навыков", "Командный Драфт",
                  "Полигон", "жюри", "тест на грейд", "подборка", "оффер")


def dg_url(profile: str | None = None, keyterms: bool = True) -> str:
    s = get_interview_settings()
    params = {
        "model": os.environ.get("LIVE_STT_MODEL", s.deepgram_model or "nova-3"),
        "language": "ru",
        "encoding": "linear16",
        "sample_rate": "16000",
        "channels": "1",
        "interim_results": "true",
        "smart_format": "true",
        "punctuate": "true",
        # пауза, после которой фраза считается законченной (speech_final); решение о конце хода — на клиенте
        "endpointing": os.environ.get("LIVE_STT_ENDPOINTING", "400"),
        "utterance_end_ms": os.environ.get("LIVE_STT_UTTERANCE_END_MS", "1000"),
        "vad_events": "true",
    }
    pairs = list(params.items())
    if profile == "guide":
        pairs = [(k, os.environ.get("LIVE_STT_GUIDE_ENDPOINTING", "700") if k == "endpointing" else
                  os.environ.get("LIVE_STT_GUIDE_UTTERANCE_END_MS", "1500") if k == "utterance_end_ms" else v)
                 for k, v in pairs]
        if keyterms and os.environ.get("LIVE_STT_GUIDE_KEYTERMS", "1") != "0":
            pairs += [("keyterm", t) for t in GUIDE_KEYTERMS]
    return f"{DG_HOST}?{urlencode(pairs)}"


def _client_ip(ws: WebSocket) -> str:
    h = ws.headers
    fwd = h.get("x-forwarded-for") or h.get("x-real-ip") or ""
    if fwd:
        return fwd.split(",")[0].strip()
    return ws.client.host if ws.client else "?"


def _origin_ok(ws: WebSocket) -> bool:
    origin = (ws.headers.get("origin") or "").rstrip("/")
    if not origin:
        return True  # не браузер (проверки, curl) — ключ всё равно не уходит наружу
    return any(origin == o or origin.startswith(o + ":") for o in _ALLOWED_ORIGINS)


async def _connect_dg(url: str, key: str):
    import websockets  # uvicorn[standard]

    try:
        return await websockets.connect(url, additional_headers={"Authorization": f"Token {key}"},
                                        open_timeout=8, ping_interval=20, max_size=2 ** 22)
    except TypeError:  # старые версии websockets
        return await websockets.connect(url, extra_headers={"Authorization": f"Token {key}"},
                                        open_timeout=8, ping_interval=20, max_size=2 ** 22)


async def bridge(ws: WebSocket) -> None:
    """Один разговор: кадры клиента → поставщик, события поставщика → клиент."""
    global _total
    s = get_interview_settings()
    if not _origin_ok(ws):
        await ws.close(code=1008)
        return
    if not s.deepgram_api_key or s.interview_stub:
        await ws.accept()
        await ws.send_text(json.dumps({"type": "error", "message": "stt_unavailable"}))
        await ws.close(code=1011)
        return
    ip = _client_ip(ws)
    if _by_ip.get(ip, 0) >= PER_IP or _total >= MAX_TOTAL:
        await ws.accept()
        await ws.send_text(json.dumps({"type": "error", "message": "busy"}))
        await ws.close(code=1013)
        return
    _by_ip[ip] = _by_ip.get(ip, 0) + 1
    _total += 1
    t0 = time.monotonic()
    dg = None
    try:
        await ws.accept()
        profile = ws.query_params.get("p") if hasattr(ws, "query_params") else None
        profile = profile if profile in ("guide",) else None
        try:
            try:
                dg = await _connect_dg(dg_url(profile), s.deepgram_api_key)
            except Exception:  # noqa: BLE001 — подсказки слов не приняты: открываем без них
                if profile != "guide":
                    raise
                log.warning("live_stt: профиль guide без подсказок слов")
                dg = await _connect_dg(dg_url(profile, keyterms=False), s.deepgram_api_key)
        except Exception as e:  # noqa: BLE001 — сеть/поставщик
            log.warning("live_stt: поставщик не открылся: %s", type(e).__name__)
            await ws.send_text(json.dumps({"type": "error", "message": "stt_connect"}))
            await ws.close(code=1011)
            return
        log.info("live_stt: открыт за %d мс (%s)", int((time.monotonic() - t0) * 1000), ip)
        await ws.send_text(json.dumps({"type": "ready"}))
        last_audio = time.monotonic()

        async def client_to_dg() -> None:
            nonlocal last_audio
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    return
                data = msg.get("bytes")
                if data:
                    last_audio = time.monotonic()
                    await dg.send(data)
                    continue
                text = msg.get("text")
                if text:
                    try:
                        cmd = json.loads(text)
                    except ValueError:
                        continue
                    if cmd.get("type") == "finalize":
                        await dg.send(json.dumps({"type": "Finalize"}))
                    elif cmd.get("type") == "keepalive":
                        await dg.send(json.dumps({"type": "KeepAlive"}))
                if time.monotonic() - t0 > MAX_S:
                    return

        async def dg_to_client() -> None:
            async for raw in dg:
                try:
                    m = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                kind = m.get("type")
                out: dict | None = None
                if kind == "Results":
                    alt = ((m.get("channel") or {}).get("alternatives") or [{}])[0]
                    text = (alt.get("transcript") or "").strip()
                    if not text:
                        out = {"type": "speech_final_empty"} if m.get("speech_final") else None
                    else:
                        out = {"type": "final" if m.get("is_final") else "interim", "text": text,
                               "speech_final": bool(m.get("speech_final"))}
                elif kind == "UtteranceEnd":
                    out = {"type": "utterance_end"}
                elif kind == "SpeechStarted":
                    out = {"type": "speech_started"}
                if out:
                    await ws.send_text(json.dumps(out, ensure_ascii=False))

        async def keepalive() -> None:
            while True:
                await asyncio.sleep(4)
                if time.monotonic() - last_audio > 4:
                    await dg.send(json.dumps({"type": "KeepAlive"}))
                if time.monotonic() - t0 > MAX_S:
                    return

        tasks = [asyncio.create_task(client_to_dg()), asyncio.create_task(dg_to_client()), asyncio.create_task(keepalive())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                log.info("live_stt: канал закрыт: %s", type(exc).__name__)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("live_stt: сбой %s", type(e).__name__)
    finally:
        _by_ip[ip] = max(0, _by_ip.get(ip, 1) - 1)
        if not _by_ip[ip]:
            _by_ip.pop(ip, None)
        _total = max(0, _total - 1)
        if dg is not None:
            try:
                await dg.send(json.dumps({"type": "CloseStream"}))
            except Exception:  # noqa: BLE001
                pass
            try:
                await dg.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
        log.info("live_stt: закрыт через %d с (%s)", int(time.monotonic() - t0), ip)
