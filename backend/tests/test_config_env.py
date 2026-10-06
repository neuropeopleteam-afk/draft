"""Конфигурация из .env, созданного `make env` из .env.example (найдено сквозной проверкой стека в CI)."""
from app.core.config import Settings
from app.integrations.settings import IntegrationSettings


def test_empty_env_values_fall_back_to_defaults(monkeypatch):
    # .env.example содержит «DEV_MODE=» (пусто — режим разработки включается сам, пока нет ключей Postbox)
    monkeypatch.setenv("DEV_MODE", "")
    monkeypatch.setenv("LLM_DISABLED", "")
    monkeypatch.delenv("POSTBOX_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("POSTBOX_SECRET_ACCESS_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.dev_mode is None
    assert s.llm_disabled is False
    assert s.effective_dev_mode is True


def test_explicit_dev_mode_false_is_respected(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "false")
    assert Settings(_env_file=None).dev_mode is False


def test_integration_settings_ignore_empty_values(monkeypatch):
    monkeypatch.setenv("EGRUL_DISABLED", "")
    monkeypatch.setenv("FSP_OIDC_ISSUER", "")
    s = IntegrationSettings(_env_file=None)
    assert s.egrul_disabled is False
    assert s.fsp_enabled is False
