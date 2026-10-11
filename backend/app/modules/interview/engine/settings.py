"""Настройки движка интервью — свой класс, чтобы не трогать app/core/config.py. Все значения из окружения
(secrets/interview.env на стенде). Ключи наружу не отдаются (см. status())."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class InterviewSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    interview_stub: bool = False
    interviewer_name: str = "Интервьюер"
    interview_model_turn: str = "anthropic/claude-sonnet-4.6"
    interview_model_judge: str = "anthropic/claude-fable-5.1"
    interview_turn_timeout_s: float = 25.0
    interview_judge_timeout_s: float = 90.0

    # Ретранслятор для зарубежных API поставщиков голоса/распознавания/аватара. Пусто — общий LLM_RELAY_URL/TOKEN
    # из настроек продукта (тот же сервер «Мадрид», тот же закреплённый CA LLM_RELAY_CA_FILE).
    interview_relay_url: str | None = None
    interview_relay_token: str | None = None

    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None  # стоковый голос поставщика; выбирается на стенде (engine/DEPLOY.md)
    elevenlabs_model: str = "eleven_multilingual_v2"
    deepgram_api_key: str | None = None
    deepgram_model: str = "nova-3"
    # Решение владельца 10.10 (регламент п. 5.11, изображения третьих лиц): лицо стокового аватара поставщика (Anam) в сдаче
    # не показываем. Канал «аватар» поставщика существует только за INTERVIEW_ANAM_ENABLED и по умолчанию выключен; без него —
    # голос и текст. INTERVIEW_AVATAR_ENABLED (11.10) — флаг продукта для собственного рисованного образа интервьюера
    # (app/core/config.py, docs/INTERVIEW.md, раздел 2.2) и к поставщику отношения не имеет.
    interview_anam_enabled: bool = False
    anam_api_key: str | None = None
    anam_avatar_id: str | None = None  # стоковый образ поставщика (engine/DEPLOY.md)
    anam_persona_id: str | None = None  # персона «Интервьюер», создана 10.10.2026 через API (для учёта; в сессии не нужна)
    anam_max_session_s: int = 600

    interview_turn_urls: str | None = None  # stun:/turn:/turns: через запятую, адреса по IP
    interview_turn_secret: str | None = None
    interview_turn_only: bool = False
    interview_jury_avatar: bool = False

    interview_daily_cap_usd: float = Field(default=15.0, ge=0)
    interview_price_tts_1000: float = Field(default=0.15, ge=0)  # USD за 1000 знаков
    interview_price_stt_min: float = Field(default=0.0077, ge=0)  # USD за минуту
    interview_price_avatar_min: float = Field(default=0.15, ge=0)  # USD за минуту видео

    @property
    def turn_urls(self) -> list[str]:
        return [u.strip() for u in (self.interview_turn_urls or "").split(",") if u.strip()]


@lru_cache
def get_interview_settings() -> InterviewSettings:
    return InterviewSettings()


def reset_interview_settings() -> None:
    """Для тестов: сбросить кэш после подмены окружения."""
    get_interview_settings.cache_clear()
