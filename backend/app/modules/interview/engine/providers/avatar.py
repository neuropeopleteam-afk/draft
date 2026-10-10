"""Аватар Anam — ТОЛЬКО за флагом INTERVIEW_AVATAR_ENABLED (по умолчанию выключен: решение владельца 10.10, регламент
п. 5.11 — изображения третьих лиц в сдаче не показываем; каналы по умолчанию — голос и текст).
Сеансовый токен (публичный REST: POST /v1/auth/session-token) для стокового образа поставщика в режиме
передачи звука (enableAudioPassthrough) — реплики озвучивает наш синтез, Anam только рисует лицо и губы. Персонаж
нейтральный («Интервьюер»); образ и голос — стоковые, созданы 10.10.2026 (ID в engine/DEPLOY.md). Свой TURN — через
временные учётные данные по общему секрету (стандартная схема coturn use-auth-secret: имя «срок:метка», пароль —
HMAC-SHA1 по имени в base64)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

from ..errors import EngineError
from ..schemas import AvatarToken
from ..settings import get_interview_settings
from . import relay

HOST = "api.anam.ai"


def turn_credentials(secret: str, ttl_s: int = 3600, label: str = "draft") -> tuple[str, str]:
    username = f"{int(time.time()) + ttl_s}:{label}"
    digest = hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()
    return username, base64.b64encode(digest).decode()


def ice_servers() -> list[dict] | None:
    s = get_interview_settings()
    urls = s.turn_urls
    if not urls:
        return None
    out: list[dict] = []
    stun = [u for u in urls if u.startswith("stun:")]
    turn = [u for u in urls if not u.startswith("stun:")]
    if stun:
        out.append({"urls": stun})
    if turn:
        entry: dict = {"urls": turn}
        if s.interview_turn_secret:
            user, pwd = turn_credentials(s.interview_turn_secret)
            entry.update({"username": user, "credential": pwd})
        out.append(entry)
    return out


def avatar_token(persona_name: str | None = None) -> AvatarToken:
    s = get_interview_settings()
    name = persona_name or s.interviewer_name
    if not s.interview_avatar_enabled:
        raise EngineError("avatar_unavailable", "Канал «аватар» выключен — доступны каналы «голос» и «текст»")
    if s.interview_stub or not s.anam_api_key or not s.anam_avatar_id:
        raise EngineError("avatar_unavailable", "Аватар не настроен — доступны каналы «голос» и «текст»")
    # Режим передачи звука: Anam рисует только лицо; голос — наш синтез, поэтому voiceId здесь не нужен (голос персоны
    # записан в самой персоне ANAM_PERSONA_ID на стороне поставщика). Выбор региона у организации недоступен — не шлём.
    body = {"personaConfig": {"name": name, "avatarId": s.anam_avatar_id, "avatarModel": "cara-4",
                              "enableAudioPassthrough": True},
            "sessionOptions": {"showAIAvatarDisclosure": True},  # честная плашка поставщика «это ИИ-аватар»
            "clientLabel": "draft-interview"}
    try:
        resp = relay.request("POST", HOST, "/v1/auth/session-token",
                             headers={"Authorization": f"Bearer {s.anam_api_key}", "Content-Type": "application/json"},
                             json=body, timeout_s=20)
    except Exception as e:  # сеть/ретранслятор
        raise EngineError("avatar_unavailable", f"Аватар недоступен: {type(e).__name__}")
    if resp.status_code >= 400:
        raise EngineError("avatar_unavailable", f"Аватар недоступен ({resp.status_code})")
    try:
        token = str(resp.json()["sessionToken"])
    except (KeyError, ValueError, TypeError):
        raise EngineError("avatar_unavailable", "Аватар: неожиданный ответ поставщика")
    return AvatarToken(session_token=token, max_seconds=s.anam_max_session_s, ice_servers=ice_servers(),
                       relay_only=bool(s.interview_turn_only and s.turn_urls), persona_name=name)
