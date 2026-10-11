"""Распознавание речи Deepgram (публичный REST: POST /v1/listen с бинарным телом). Режим «нажми и говори»: клиент
записывает фрагмент (webm/opus или wav) и присылает целиком; потоковое распознавание не используется — проще и
предсказуемее через ретранслятор."""
from __future__ import annotations

from ..cost import estimate_cost
from ..errors import EngineError
from ..schemas import Transcription
from ..settings import get_interview_settings
from . import relay

HOST = "api.deepgram.com"
MAX_BYTES = 6 * 1024 * 1024
MAX_SECONDS = 180


def stt(audio: bytes, mime: str = "audio/webm", *, stub_text: str | None = None) -> Transcription:
    if not audio:
        raise EngineError("bad_request", "Пустая запись")
    if len(audio) > MAX_BYTES:
        raise EngineError("bad_request", "Запись слишком большая (до 6 МБ)")
    s = get_interview_settings()
    if s.interview_stub or not s.deepgram_api_key:
        # Заглушка: текст из тела запроса не извлечь — модуль передаёт его отдельно (поле text в multipart) или
        # возвращаем пусто, и клиент предложит ввести текст вручную (деградация «голос → текст»).
        return Transcription(text=(stub_text or "").strip(), seconds=round(len(audio) / 16000, 2), cost_usd=0.0, stub=True)
    params = f"/v1/listen?model={s.deepgram_model}&language=ru&smart_format=true&punctuate=true"
    resp = relay.request("POST", HOST, params, headers={"Authorization": f"Token {s.deepgram_api_key}", "Content-Type": mime},
                         content=audio, timeout_s=60)
    if resp.status_code >= 400:
        raise EngineError("stt_unavailable", f"Распознавание недоступно ({resp.status_code})")
    try:
        data = resp.json()
        alt = data["results"]["channels"][0]["alternatives"][0]
        text = str(alt.get("transcript") or "").strip()
        seconds = float(data.get("metadata", {}).get("duration") or 0.0)
    except (KeyError, IndexError, ValueError, TypeError):
        raise EngineError("stt_unavailable", "Распознавание вернуло неожиданный ответ")
    seconds = min(seconds, MAX_SECONDS)
    return Transcription(text=text, seconds=round(seconds, 2), cost_usd=estimate_cost("stt", seconds))
