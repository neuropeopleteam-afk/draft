"""Движок ИИ-интервьюера «Драфта»: устная защита письменных ответов и короткое ИИ-интервью по непроверенным навыкам.
Публичный интерфейс — engine/CONTRACT.md. Код написан 10.10.2026 в рамках мероприятия; БД и HTTP-роутеров здесь нет."""
from .cost import estimate_cost
from .errors import EngineError
from .evaluate import evaluate, verdict_from_levels, verify_quotes
from .limits import check_limits
from .planning import LIMITS, normalize_spec, plan
from .providers.avatar import avatar_token, ice_servers
from .providers.stt import stt
from .providers.tts import tts
from .schemas import (
    AudioOut,
    AvatarToken,
    Cost,
    DefenseContext,
    InterviewContext,
    PlanItem,
    QuestionVerdict,
    Quote,
    SessionSpec,
    SkillContext,
    TaskContext,
    Transcript,
    Transcription,
    TurnInput,
    TurnOutput,
    Utterance,
    Verdict,
)
from .settings import InterviewSettings, get_interview_settings, reset_interview_settings
from .turn import is_stub, next_turn


def status() -> dict:
    """Сводка для /api/interview/status — без секретов."""
    from app.core.config import get_settings

    s = get_interview_settings()
    stub = is_stub()
    return {
        "stub": stub,
        "channels": {"text": True, "voice": not stub and bool(s.elevenlabs_api_key and s.elevenlabs_voice_id),
                     "stt": not stub and bool(s.deepgram_api_key),
                     "avatar": s.interview_avatar_enabled and not stub and bool(s.anam_api_key and s.anam_avatar_id)},
        "avatar_enabled": s.interview_avatar_enabled,
        "models": {"turn": s.interview_model_turn, "judge": s.interview_model_judge},
        "relay": bool(s.interview_relay_url or getattr(get_settings(), "llm_relay_url", None)),
        "turn_ice": bool(s.turn_urls),
        "interviewer_name": s.interviewer_name,
        "limits": LIMITS,
        "daily_cap_usd": s.interview_daily_cap_usd,
        "label": "модель, не люди",
    }


__all__ = [
    "LIMITS",
    "AudioOut",
    "AvatarToken",
    "Cost",
    "DefenseContext",
    "EngineError",
    "InterviewContext",
    "InterviewSettings",
    "PlanItem",
    "QuestionVerdict",
    "Quote",
    "SessionSpec",
    "SkillContext",
    "TaskContext",
    "Transcript",
    "Transcription",
    "TurnInput",
    "TurnOutput",
    "Utterance",
    "Verdict",
    "avatar_token",
    "check_limits",
    "estimate_cost",
    "evaluate",
    "get_interview_settings",
    "ice_servers",
    "is_stub",
    "next_turn",
    "normalize_spec",
    "plan",
    "reset_interview_settings",
    "status",
    "stt",
    "tts",
    "verdict_from_levels",
    "verify_quotes",
]
