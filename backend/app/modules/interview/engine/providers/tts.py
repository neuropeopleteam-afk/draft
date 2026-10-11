"""Синтез речи ElevenLabs (публичный REST: POST /v1/text-to-speech/{voice_id}?output_format=…). Форматы: mp3 для
канала «голос» (проигрывается в браузере) и pcm_16000 — для канала «аватар» (Anam принимает pcm_s16le 16 кГц моно,
клиент режет на куски и шлёт в поток звука аватара)."""
from __future__ import annotations

import math

from ..cost import estimate_cost
from ..errors import EngineError
from ..schemas import AudioOut
from ..settings import get_interview_settings
from . import relay

HOST = "api.elevenlabs.io"
FORMATS = {"mp3": ("mp3_22050_32", "audio/mpeg", None), "pcm_16000": ("pcm_16000", "audio/pcm", 16000)}
MAX_CHARS = 1200


def _stub_audio(text: str, fmt: str) -> AudioOut:
    """Тишина нужной длительности (~ 15 знаков/с), чтобы клиент и тесты работали без поставщика."""
    seconds = max(0.4, min(20.0, len(text) / 15))
    if fmt == "mp3":
        return AudioOut(data=b"", mime="audio/mpeg", format="mp3", sample_rate=None, chars=len(text), cost_usd=0.0, stub=True)
    data = bytes(2 * int(16000 * seconds))
    return AudioOut(data=data, mime="audio/pcm", format="pcm_16000", sample_rate=16000, chars=len(text), cost_usd=0.0, stub=True)


def tts(text: str, fmt: str = "mp3") -> AudioOut:
    text = " ".join((text or "").split())[:MAX_CHARS]
    if not text:
        raise EngineError("bad_request", "Нечего озвучивать")
    if fmt not in FORMATS:
        raise EngineError("bad_request", f"Неизвестный формат озвучки: {fmt}")
    s = get_interview_settings()
    if s.interview_stub or not s.elevenlabs_api_key or not s.elevenlabs_voice_id:
        return _stub_audio(text, fmt)
    out_fmt, mime, rate = FORMATS[fmt]
    body = {"text": text, "model_id": s.elevenlabs_model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "speed": 1.0}}
    resp = relay.request("POST", HOST, f"/v1/text-to-speech/{s.elevenlabs_voice_id}?output_format={out_fmt}",
                         headers={"xi-api-key": s.elevenlabs_api_key, "Content-Type": "application/json", "Accept": mime},
                         json=body, timeout_s=40)
    if resp.status_code >= 400 or not resp.content:
        raise EngineError("bad_request", f"Озвучка недоступна ({resp.status_code})", status=503)
    return AudioOut(data=resp.content, mime=mime, format=fmt, sample_rate=rate, chars=len(text),
                    cost_usd=estimate_cost("tts", len(text)))


def pcm_seconds(data: bytes, rate: int = 16000) -> float:
    return math.floor(len(data) / 2 / rate * 100) / 100
