"""Аватар Anam — ТОЛЬКО за флагом INTERVIEW_ANAM_ENABLED (по умолчанию выключен; каналы по умолчанию — голос и текст).
Лицо — НАШЕ: сгенерированный портрет несуществующего человека (frontend/public/avatar/PROVENANCE.md), загруженный в Anam
как собственный аватар (POST /v1/avatars, «one-shot» из одного изображения, модель cara-4) — его ID в ANAM_AVATAR_ID
(engine/DEPLOY.md). Стоковые образы поставщика не используются (решение владельца 11.10).
Сеансовый токен (публичный REST: POST /v1/auth/session-token) в режиме передачи звука (enableAudioPassthrough) — реплики
озвучивает наш синтез (ElevenLabs, женский голос, /speech?format=pcm), Anam только рисует лицо и губы; её LLM и голос
не задействованы. Персонаж нейтральный («Интервьюер»). Свой TURN — через
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


def avatar_token(persona_name: str | None = None, director_notes: dict | None = None,
                 avatar_id: str | None = None) -> AvatarToken:
    """avatar_id — своё лицо (Настя-проводник); по умолчанию — ANAM_AVATAR_ID (интервьюер)."""
    s = get_interview_settings()
    name = persona_name or s.interviewer_name
    if not s.interview_anam_enabled:
        raise EngineError("avatar_unavailable", "Канал «аватар» выключен — доступны каналы «голос» и «текст»")
    face = (avatar_id or s.anam_avatar_id or "").strip()
    if s.interview_stub or not s.anam_api_key or not face:
        raise EngineError("avatar_unavailable", "Аватар не настроен — доступны каналы «голос» и «текст»")
    # Режим передачи звука: Anam рисует только лицо; голос — наш синтез, поэтому voiceId и LLM здесь не нужны.
    # Выбор региона у организации недоступен — не шлём. avatarModel — cara-4 (единственная для собственных аватаров).
    body = {"personaConfig": {"name": name, "avatarId": face, "avatarModel": "cara-4",
                              "directorNotes": director_notes or {"expressivity": 0.09},
                              "enableAudioPassthrough": True,
                              "maxSessionLengthSeconds": s.anam_max_session_s},
            # плашки поставщика на видео нет (решение владельца 11.10: под образом только «Интервьюер: говорит / слушает»);
            # videoQuality="high" — поток сразу в высокой чёткости без 20-секундного размытия; запись на стороне поставщика выключена
            "sessionOptions": {"showAIAvatarDisclosure": False, "videoQuality": "high",
                               "sessionReplay": {"enableSessionReplay": False}},
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
