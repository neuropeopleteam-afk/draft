#!/usr/bin/env python3
"""Генератор ключа подписи паспортов грейда (Ed25519).

    python tools/passport/genkey.py > secrets/passport.env      # на сервере: /opt/spectrek_fsp/secrets/passport.env
    chmod 600 secrets/passport.env

Печатает PASSPORT_SIGNING_KEY (base64url 32-байтного seed — секрет, в репозиторий и в чат не попадает) и в
комментариях — kid и открытый ключ (их можно публиковать). Ротация: новый ключ в PASSPORT_SIGNING_KEY; открытые
ключи прежних сохраняются в БД автоматически (таблица passport_keys), поэтому старые паспорта проверяются по своему
kid. Если БД переносится без этой таблицы — добавьте прежний открытый ключ в PASSPORT_RETIRED_PUBLIC_KEYS.
Зависимость — только cryptography.
"""
import base64
import hashlib
import json
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def main() -> int:
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())
    pub = b64u(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
    thumb = json.dumps({"crv": "Ed25519", "kty": "OKP", "x": pub}, sort_keys=True, separators=(",", ":"))
    kid = "ed25519-" + b64u(hashlib.sha256(thumb.encode()).digest())[:16]
    print("# Ключ подписи паспортов грейда «Драфт» (Ed25519). Секрет: chmod 600, не коммитить.")
    print(f"# kid: {kid}")
    print(f"# открытый ключ (base64url, можно публиковать): {pub}")
    print(f"PASSPORT_SIGNING_KEY={b64u(seed)}")
    print(f"kid: {kid}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
