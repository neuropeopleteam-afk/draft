"""OIDC-клиент ФСП ID (Keycloak): Authorization Code + PKCE (S256), проверка id_token по JWKS.

Два адреса одного Keycloak:
* ``FSP_OIDC_ISSUER`` — публичный (браузер, поле ``iss`` в токенах): https://fsp.neuropeople.pro/auth/realms/fsp;
* ``FSP_OIDC_INTERNAL_BASE`` — внутренний для обмена кода и JWKS из контейнера api: http://keycloak:8080/auth/realms/fsp.
Для настоящего ФСП ID достаточно указать его issuer (внутренний адрес не нужен) и выдать клиенту секрет.
Пути эндпоинтов — стандартные для Keycloak (``/protocol/openid-connect/...``); при FSP_OIDC_DISCOVERY берутся
из ``/.well-known/openid-configuration``.
"""
from __future__ import annotations

import base64
from functools import lru_cache
import hashlib
import secrets
import time
from urllib.parse import urlencode, urlparse

import httpx
import jwt

from app.integrations.settings import get_isettings


class OidcError(Exception):
    pass


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _internal() -> str:
    s = get_isettings()
    return (s.fsp_oidc_internal_base or s.fsp_oidc_issuer or "").rstrip("/")


@lru_cache(maxsize=8)
def _discovery(pub: str, internal: str, bucket: int) -> dict:
    try:
        r = httpx.get(f"{internal}/.well-known/openid-configuration", timeout=10)
        r.raise_for_status()
        ep = r.json()
        if ep.get("issuer") != pub:
            raise OidcError("issuer в OIDC discovery не совпадает с настройкой ФСП ID")
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri", "userinfo_endpoint"):
            value = ep.get(key)
            if not isinstance(value, str) or urlparse(value).scheme not in ("https", "http"):
                raise OidcError(f"В OIDC discovery отсутствует корректный {key}")
        # Только серверные адреса, и только внутри того же issuer. Браузер всегда идёт на публичный.
        for key in ("token_endpoint", "jwks_uri", "userinfo_endpoint"):
            if ep[key].startswith(pub + "/"):
                ep[key] = internal + ep[key][len(pub):]
        return ep
    except (httpx.HTTPError, ValueError) as e:
        raise OidcError(f"OIDC discovery ФСП ID недоступен ({type(e).__name__})") from None


def endpoints() -> dict:
    s = get_isettings()
    pub = (s.fsp_oidc_issuer or "").rstrip("/")
    internal = _internal()
    if s.fsp_oidc_discovery:
        return dict(_discovery(pub, internal, int(time.monotonic() // 300)))
    return {
        "issuer": pub,
        "authorization_endpoint": f"{pub}/protocol/openid-connect/auth",
        "token_endpoint": f"{internal}/protocol/openid-connect/token",
        "jwks_uri": f"{internal}/protocol/openid-connect/certs",
        "userinfo_endpoint": f"{internal}/protocol/openid-connect/userinfo",
        "end_session_endpoint": f"{pub}/protocol/openid-connect/logout",
    }


def redirect_uri() -> str:
    return get_isettings().public_base_url.rstrip("/") + "/api/fsp-id/callback"


def authorize_url(state: str, nonce: str, challenge: str, *, prompt_login: bool = False) -> str:
    s = get_isettings()
    q = {"client_id": s.fsp_oidc_client_id, "response_type": "code", "scope": s.fsp_oidc_scopes,
         "redirect_uri": redirect_uri(), "state": state, "nonce": nonce, "code_challenge": challenge,
         "code_challenge_method": "S256", "ui_locales": "ru"}
    if prompt_login:
        q["prompt"] = "login"
    return endpoints()["authorization_endpoint"] + "?" + urlencode(q)


def exchange_code(code: str, verifier: str) -> dict:
    s = get_isettings()
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
            "client_id": s.fsp_oidc_client_id, "code_verifier": verifier}
    auth = (s.fsp_oidc_client_id, s.fsp_oidc_client_secret) if s.fsp_oidc_client_secret else None
    if s.fsp_oidc_token_auth_method == "client_secret_post":
        auth = None
        data["client_secret"] = s.fsp_oidc_client_secret or ""
    elif s.fsp_oidc_token_auth_method == "none":
        auth = None
    elif s.fsp_oidc_token_auth_method != "client_secret_basic":
        raise OidcError("Неизвестный FSP_OIDC_TOKEN_AUTH_METHOD")
    try:
        r = httpx.post(endpoints()["token_endpoint"], data=data, auth=auth, timeout=10)
    except httpx.HTTPError as e:
        raise OidcError(f"ФСП ID недоступен ({type(e).__name__})") from None
    if r.status_code != 200:
        try:
            desc = r.json().get("error_description") or r.json().get("error")
        except ValueError:
            desc = r.text[:120]
        raise OidcError(f"ФСП ID отклонил код авторизации: {desc}")
    return r.json()


@lru_cache(maxsize=4)
def _jwks_client(uri: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(uri, cache_keys=True, lifespan=3600, timeout=10)


def verify_id_token(id_token: str, nonce: str) -> dict:
    s = get_isettings()
    ep = endpoints()
    try:
        key = _jwks_client(ep["jwks_uri"]).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(id_token, key.key, algorithms=["RS256", "ES256", "PS256"],
                            audience=s.fsp_oidc_client_id, issuer=ep["issuer"], leeway=30,
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]})
    except jwt.PyJWTError as e:
        raise OidcError(f"Подпись или поля id_token не прошли проверку ({type(e).__name__})") from None
    if claims.get("nonce") != nonce:
        raise OidcError("nonce в id_token не совпадает")
    return claims


def userinfo(access_token: str) -> dict:
    try:
        r = httpx.get(endpoints()["userinfo_endpoint"], headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        return r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return {}
