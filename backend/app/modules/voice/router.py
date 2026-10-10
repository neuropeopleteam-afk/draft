"""POST /api/employer/needs/voice — распознать надиктованную потребность (без сохранения).

Порядок: роль «работодатель» → флаг VOICE_NEED_ENABLED → согласие (версия CONSENT_VERSION в запросе) → лимиты частоты →
размер и длительность → тип записи по содержимому → движок интервью ``stt`` (Deepgram через ретранслятор; заглушка при
INTERVIEW_STUB=1 или без DEEPGRAM_API_KEY) → текст. Ни запись, ни текст на сервере не сохраняются и в журнал не пишутся;
ответ — только текст для поля «Кого вы ищете», который работодатель проверяет и правит сам. Ничего не отправляется
автоматически: разбор — прежний POST /api/employer/needs/parse по кнопке работодателя.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.deps import require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.core.ratelimit import SlidingWindow, hit
from app.modules.auth.models import User

log = logging.getLogger("voice.need")
router = APIRouter(prefix="/api/employer", tags=["employer"])
employer = require_role(UserRole.employer)

CONSENT_VERSION = "2026-10-10.v1"
CONSENT_TEXT = ("Запись голоса уйдёт на распознавание речи поставщику Deepgram (США) через наш сервер и сразу удаляется: "
                "ни запись, ни текст не сохраняются. Текст появится в поле — проверьте и поправьте его; разбор начнётся "
                "только по вашей кнопке. Не называйте в записи имена и контакты.")
# Детерминированный текст заглушки (INTERVIEW_STUB=1 или нет ключа распознавания) — для тестов и e2e
STUB_TEXT = ("Нужен бэкенд-разработчик уровня middle. Обязательно Python, FastAPI и PostgreSQL, опыт от 2 лет. "
             "Желательно Redis и Docker. Удалённо или гибрид, до 280 тысяч рублей.")
TEXT_MAX = 8000  # как у поля потребности (ParseIn.text)
# Тип записи — по первым байтам, не по заголовку: в распознавание уходят только аудиоконтейнеры
_MAGIC = ((b"\x1a\x45\xdf\xa3", "audio/webm"), (b"OggS", "audio/ogg"), (b"RIFF", "audio/wav"), (b"ID3", "audio/mpeg"),
          (b"\xff\xfb", "audio/mpeg"), (b"\xff\xf3", "audio/mpeg"), (b"\xff\xf1", "audio/aac"), (b"\xff\xf9", "audio/aac"))
_windows: dict[tuple[int, int], SlidingWindow] = {}


def _window(limit: int, seconds: int) -> SlidingWindow:
    key = (limit, seconds)
    if key not in _windows:
        _windows[key] = SlidingWindow(limit, seconds)
    return _windows[key]


def sniff(audio: bytes) -> str | None:
    """Аудиоконтейнер по содержимому: webm/ogg/wav/mp3/aac или mp4 (ftyp на 4-м байте); иначе None."""
    if len(audio) >= 12 and audio[4:8] == b"ftyp":
        return "audio/mp4"
    for magic, mime in _MAGIC:
        if audio.startswith(magic):
            if mime == "audio/wav" and audio[8:12] != b"WAVE":
                return None
            return mime
    return None


def is_stub() -> bool:
    from app.modules.interview.engine.settings import get_interview_settings

    iv = get_interview_settings()
    return bool(iv.interview_stub or not iv.deepgram_api_key)


def meta() -> dict:
    """Признак для /api/meta (без секретов): кнопка «Надиктовать» показывается только при enabled."""
    s = get_settings()
    out = {"enabled": bool(s.voice_need_enabled), "max_seconds": s.voice_need_max_seconds,
           "consent_version": CONSENT_VERSION, "consent_text": CONSENT_TEXT}
    if s.voice_need_enabled:
        try:
            out["stub"] = is_stub()
        except Exception:  # noqa: BLE001 — нет движка: кнопка остаётся, ответ будет 503 и клавиатура
            out["stub"] = True
    return out


class VoiceNeedOut(BaseModel):
    text: str = Field(description="Распознанный текст для поля «Кого вы ищете» — работодатель проверяет и правит")
    stub: bool = Field(description="Заглушка: распознавание не подключено, подставлен пример текста")
    seconds: float = Field(description="Длительность записи по данным распознавания (у заглушки — оценка)")
    chars: int
    truncated: bool = Field(description="Текст длиннее поля потребности — обрезан")
    note: str


async def _read_limited(request: Request, max_bytes: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise api_error(413, "voice_too_large", "Запись слишком большая — надиктуйте короче или введите текст")
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > max_bytes:
            raise api_error(413, "voice_too_large", "Запись слишком большая — надиктуйте короче или введите текст")
    return bytes(buf)


def _stt(audio: bytes, mime: str):
    from app.modules.interview import engine

    return engine.stt(audio, mime, stub_text=STUB_TEXT)


@router.post("/needs/voice", response_model=VoiceNeedOut,
             summary="Надиктовать потребность: запись → текст в поле (без сохранения, разбор — по кнопке)",
             description="Тело — запись целиком (audio/webm, audio/ogg, audio/mp4, audio/wav, audio/mpeg), до "
                         "VOICE_NEED_MAX_SECONDS (60) секунд и VOICE_NEED_MAX_KB. Параметр consent — версия согласия "
                         "из /api/meta → voice_need.consent_version. Распознавание — функция движка интервью stt "
                         "(Deepgram nova-3, ru, через ретранслятор); заглушка (INTERVIEW_STUB=1 или нет ключа) отвечает "
                         "фиксированным текстом и stub=true. Ни запись, ни текст на сервере не сохраняются; ответ "
                         "ничего не создаёт и не отправляет — разбор POST /needs/parse по кнопке работодателя.",
             responses={401: err("Не выполнен вход"), 403: err("Только для работодателя"),
                        409: err("Голосовой ввод выключен на этой установке (VOICE_NEED_ENABLED)"),
                        413: err("Запись длиннее 60 секунд или больше предела размера"),
                        415: err("Не аудиозапись"), 422: err("Нет согласия или речь не распознана"),
                        429: err("Слишком много записей"), 503: err("Распознавание недоступно — введите текст"),
                        504: err("Распознавание не ответило вовремя — введите текст")})
async def need_voice(request: Request, user: User = Depends(employer),
                     consent: str | None = Query(None, max_length=32, description="Версия согласия"),
                     duration_ms: int | None = Query(None, ge=0, le=3_600_000,
                                                     description="Длительность записи по часам браузера")) -> dict:
    s = get_settings()
    if not s.voice_need_enabled:
        raise api_error(409, "voice_need_disabled", "Голосовой ввод выключен на этой установке — введите текст")
    if consent != CONSENT_VERSION:
        raise api_error(422, "voice_consent_required", "Нужно согласие на распознавание записи — или введите текст")
    hit(_window(s.voice_need_per_hour, 3600), str(user.id), "voice_rate", "Слишком много записей")
    hit(_window(s.voice_need_daily, 24 * 3600), "all", "voice_rate", "Дневной предел голосового ввода исчерпан")
    limit_s = s.voice_need_max_seconds
    if duration_ms is not None and duration_ms > limit_s * 1000 + 1500:
        raise api_error(413, "voice_too_long", f"Запись длиннее {limit_s} секунд — надиктуйте короче или введите текст")
    audio = await _read_limited(request, s.voice_need_max_kb * 1024)
    if len(audio) < 64:
        raise api_error(422, "voice_empty", "Пустая запись — попробуйте ещё раз или введите текст")
    mime = sniff(audio)
    if mime is None:
        raise api_error(415, "voice_bad_type", "Это не аудиозапись — запишите ещё раз или введите текст")
    declared = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if declared.startswith("audio/") and declared.split("/")[1].removeprefix("x-") == mime.split("/")[1]:
        mime = request.headers["content-type"].strip()  # с кодеком (audio/webm;codecs=opus) — как прислал браузер
    from app.modules.interview.engine.errors import EngineError

    try:
        tr = await asyncio.wait_for(run_in_threadpool(_stt, audio, mime), timeout=s.voice_need_timeout_s)
    except TimeoutError:
        log.warning("распознавание потребности: нет ответа за %s с", s.voice_need_timeout_s)
        raise api_error(504, "voice_timeout", "Распознавание не ответило вовремя — введите текст с клавиатуры") from None
    except EngineError as e:
        log.warning("распознавание потребности: %s", e.code)  # без текста и записи
        raise api_error(503, "voice_unavailable", "Распознавание речи недоступно — введите текст с клавиатуры") from None
    except Exception as e:  # noqa: BLE001 — сеть, ретранслятор, неожиданный ответ: не 500, а клавиатура
        log.warning("распознавание потребности: сбой %s", type(e).__name__)
        raise api_error(503, "voice_unavailable", "Распознавание речи недоступно — введите текст с клавиатуры") from None
    if not tr.stub and tr.seconds > limit_s + 3:
        raise api_error(413, "voice_too_long", f"Запись длиннее {limit_s} секунд — надиктуйте короче или введите текст")
    text = " ".join((tr.text or "").split())
    if not text:
        raise api_error(422, "voice_empty", "Речь не распознана — говорите ближе к микрофону или введите текст")
    truncated = len(text) > TEXT_MAX
    text = text[:TEXT_MAX]
    note = ("Заглушка: распознавание не подключено, подставлен пример текста — поправьте его под свою вакансию."
            if tr.stub else "Проверьте расшифровку и поправьте ошибки распознавания — затем «Разобрать требования».")
    return {"text": text, "stub": tr.stub, "seconds": round(float(tr.seconds or 0), 1), "chars": len(text),
            "truncated": truncated, "note": note}
