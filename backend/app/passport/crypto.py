"""Ключи и подпись паспорта грейда: Ed25519 (cryptography), канонический JSON, JWK (RFC 8037), kid — отпечаток RFC 7638.

Канонический вид (подписывается именно он, байт в байт):
    json.dumps(claims, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
В составе — только строки, целые, булевы, null и десятичные дроби с ≤ 3 знаками (θ, SE, доли): их кратчайшая запись
одинакова в Python и JavaScript, поэтому паспорт можно проверить и не нашим кодом. Та же функция — в
tools/passport/verify.py (без зависимостей от приложения); тест сверяет, что они совпадают.

Ключ подписи — PASSPORT_SIGNING_KEY (base64url 32-байтного seed или PEM PKCS#8; генератор tools/passport/genkey.py).
Без ключа (разработка, тесты) — эфемерный ключ процесса с пометкой «тестовый ключ» в паспорте и в JWK.
Открытые ключи всех когда-либо подписывавших ключей сохраняются в таблице passport_keys (ротация по kid: старые
паспорта проверяются своим ключом); PASSPORT_RETIRED_PUBLIC_KEYS — дополнительные открытые ключи через запятую.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import logging
import threading

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app.core.config import get_settings

log = logging.getLogger(__name__)
ALG = "EdDSA"
SCHEMA = "vstrechny.grade-passport/1"


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64u_dec(s: str) -> bytes:
    s = s.strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def public_raw(pub: Ed25519PublicKey) -> bytes:
    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def kid_for(pub_b64: str) -> str:
    """Отпечаток JWK по RFC 7638 (SHA-256 канонического {crv, kty, x}), первые 16 символов base64url."""
    thumb = json.dumps({"crv": "Ed25519", "kty": "OKP", "x": pub_b64}, sort_keys=True, separators=(",", ":"))
    return "ed25519-" + b64u(hashlib.sha256(thumb.encode()).digest())[:16]


def jwk(pub_b64: str, *, test_key: bool = False, retired: bool = False) -> dict:
    out = {"kty": "OKP", "crv": "Ed25519", "x": pub_b64, "kid": kid_for(pub_b64), "alg": ALG, "use": "sig"}
    if test_key:
        out["test_key"] = True  # эфемерный ключ разработки: паспорт с ним — не доказательство
    if retired:
        out["retired"] = True  # больше не подписывает, но паспорта с этим kid проверяются
    return out


def parse_private(value: str) -> Ed25519PrivateKey:
    v = value.strip()
    if v.startswith("-----BEGIN"):
        key = serialization.load_pem_private_key(v.encode(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("PASSPORT_SIGNING_KEY: нужен ключ Ed25519")
        return key
    raw = b64u_dec(v)
    if len(raw) != 32:
        raise ValueError("PASSPORT_SIGNING_KEY: ожидается base64url 32-байтного seed Ed25519 (tools/passport/genkey.py)")
    return Ed25519PrivateKey.from_private_bytes(raw)


def parse_public(value: str) -> str:
    """Открытый ключ (base64url 32 байт или PEM SubjectPublicKeyInfo) → base64url."""
    v = value.strip()
    if v.startswith("-----BEGIN"):
        key = serialization.load_pem_public_key(v.encode())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("нужен открытый ключ Ed25519")
        return b64u(public_raw(key))
    raw = b64u_dec(v)
    if len(raw) != 32:
        raise ValueError("открытый ключ Ed25519 — 32 байта в base64url")
    return b64u(raw)


@dataclass(frozen=True)
class SigningKey:
    kid: str
    private: Ed25519PrivateKey
    public_b64: str
    test_key: bool


_mx = threading.Lock()


@lru_cache
def signing_key() -> SigningKey:
    """Текущий ключ подписи. Кэш сбрасывается signing_key.cache_clear() (тесты ротации)."""
    with _mx:
        value = get_settings().passport_signing_key
        if value:
            priv, test = parse_private(value), False
        else:
            priv, test = Ed25519PrivateKey.generate(), True
            log.warning("PASSPORT_SIGNING_KEY не задан: паспорта подписываются эфемерным тестовым ключом процесса")
        pub = b64u(public_raw(priv.public_key()))
        return SigningKey(kid=kid_for(pub), private=priv, public_b64=pub, test_key=test)


def retired_public_keys() -> list[str]:
    raw = get_settings().passport_retired_public_keys or ""
    out = []
    for part in raw.replace("\n", ",").split(","):
        if part.strip():
            try:
                out.append(parse_public(part))
            except ValueError:
                log.warning("PASSPORT_RETIRED_PUBLIC_KEYS: пропущен неверный ключ")
    return out


def sign(claims: dict, key: SigningKey | None = None) -> tuple[str, str]:
    """(канонический JSON как строка, подпись base64url)."""
    key = key or signing_key()
    body = canonical(claims)
    return body.decode("utf-8"), b64u(key.private.sign(body))


def verify(document: str | bytes, signature_b64: str, public_b64: str) -> bool:
    try:
        pub = Ed25519PublicKey.from_public_bytes(b64u_dec(public_b64))
        pub.verify(b64u_dec(signature_b64), document.encode("utf-8") if isinstance(document, str) else document)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
