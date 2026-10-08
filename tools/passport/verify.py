#!/usr/bin/env python3
"""Офлайн-проверка паспорта грейда «Встречный» без нашей БД: подпись Ed25519 по открытому ключу (JWKS).

    python tools/passport/verify.py passport.json                       # файл (скачан со страницы проверки)
    python tools/passport/verify.py passport.json --jwks keys.json      # с заранее сохранёнными ключами
    python tools/passport/verify.py https://fsp.neuropeople.pro/verify/<id>   # ссылка или /api/passport/<id>
    python tools/passport/verify.py passport.json --json                # машиночитаемый итог

Что проверяется: подпись над каноническим JSON поля passport (json.dumps(sort_keys=True, separators=(",", ":"),
ensure_ascii=False), UTF-8) ключом с kid из подписи; срок действия valid_until. Для ссылки дополнительно
показывается статус реестра (отзыв), который сообщает сервер, — отзыв подписью не проверяется по определению.
Ключи: --jwks (файл или URL) — доверенный источник; без него для ссылки берутся <origin>/api/passport/keys, для
файла — ключи, вложенные в сам файл (с предупреждением: так проверяется целостность, но не издатель).

Коды выхода: 0 — подпись верна и срок не истёк (и реестр не сообщил об отзыве); 1 — подпись не сходится или ключ
неизвестен; 2 — срок истёк; 3 — отозван по данным реестра; 4 — ошибка ввода. Зависимость — только cryptography.
"""
from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def _ints(v):
    """1.0 → 1 во всей глубине (браузер и многие JSON-библиотеки не отличают целую дробь от целого)."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, dict):
        return {k: _ints(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_ints(x) for x in v]
    return v


def canonical_legacy(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def canonical(obj) -> bytes:
    """Подписывается именно это: JSON с сортировкой ключей, без пробелов, UTF-8; 1.0 записывается как 1."""
    return canonical_legacy(_ints(obj))


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _get_json(url: str) -> dict:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "vstrechny-passport-verify/1"})
    with urlopen(req, timeout=20) as r:  # noqa: S310 — адрес задаёт сам проверяющий
        return json.loads(r.read().decode("utf-8"))


def _api_url(url: str) -> tuple[str, str]:
    u = urlparse(url)
    origin = f"{u.scheme}://{u.netloc}"
    m = re.search(r"/(?:verify|api/passport)/([A-Za-z0-9_-]{8,32})", u.path)
    if not m:
        raise ValueError("в ссылке нет id паспорта (/verify/<id> или /api/passport/<id>)")
    return f"{origin}/api/passport/{m.group(1)}", origin


def load_keys(src: str) -> list[dict]:
    data = _get_json(src) if src.startswith(("http://", "https://")) else json.loads(Path(src).read_text("utf-8"))
    keys = data.get("keys", data if isinstance(data, list) else [data])
    return [k for k in keys if isinstance(k, dict) and k.get("kty") == "OKP" and k.get("crv") == "Ed25519"]


def check(doc: dict, keys: list[dict], now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    passport, sig = doc.get("passport"), doc.get("signature") or {}
    if not isinstance(passport, dict) or not sig.get("value"):
        raise ValueError("в файле нет полей passport и signature")
    kid = sig.get("kid") or passport.get("kid")
    key = next((k for k in keys if k.get("kid") == kid), None)
    ok = False
    if key is not None:
        try:
            pub, value = Ed25519PublicKey.from_public_bytes(b64u_dec(key["x"])), b64u_dec(sig["value"])
            # канон; для паспортов, подписанных до замены 1.0 → 1, — их исходный канон
            for body in dict.fromkeys((canonical(passport), canonical_legacy(passport))):
                try:
                    pub.verify(value, body)
                    ok = passport.get("kid") == kid
                    break
                except InvalidSignature:
                    continue
        except (ValueError, KeyError, TypeError):
            ok = False
    until = passport.get("valid_until")
    try:
        expired = not until or datetime.fromisoformat(str(until).replace("Z", "+00:00")) <= now
    except ValueError:
        expired = True  # срок не читается — паспорт не считается действующим
    return {"id": passport.get("id"), "kid": kid, "kid_known": key is not None, "signature_valid": ok,
            "expired": expired, "valid_until": until, "test_key": bool((passport.get("issuer") or {}).get("test_key")
                                                                       or (key or {}).get("test_key")),
            "category": (passport.get("category") or {}).get("title"), "grade_status": passport.get("grade_status"),
            "public_ref": (passport.get("subject") or {}).get("public_ref"),
            "skills_t1": len(passport.get("skills_t1") or []), "achievements_t2": len(passport.get("achievements_t2") or [])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Офлайн-проверка подписанного паспорта грейда «Встречный»")
    ap.add_argument("source", help="файл паспорта (JSON) или ссылка /verify/<id>, /api/passport/<id>")
    ap.add_argument("--jwks", help="доверенные открытые ключи: файл или URL (по умолчанию — см. описание)")
    ap.add_argument("--json", action="store_true", help="итог в JSON")
    a = ap.parse_args(argv)
    notes: list[str] = []
    registry = None
    try:
        if a.source.startswith(("http://", "https://")):
            api, origin = _api_url(a.source)
            doc = _get_json(api)
            registry = doc.get("status")
            keys = load_keys(a.jwks or f"{origin}/api/passport/keys")
        else:
            doc = json.loads(Path(a.source).read_text("utf-8"))
            if a.jwks:
                keys = load_keys(a.jwks)
            else:
                keys = [k for k in doc.get("keys") or [] if isinstance(k, dict)]
                notes.append("ключ взят из самого файла: проверена целостность; сверьте kid с опубликованными "
                             "ключами издателя (--jwks https://fsp.neuropeople.pro/api/passport/keys)")
        res = check(doc, keys)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 4
    revoked = bool(registry and registry.get("state") == "revoked")
    code = 1 if not res["signature_valid"] else 2 if res["expired"] else 3 if revoked else 0
    verdict = {0: "Действителен", 1: "Подпись не сходится", 2: "Истёк", 3: "Отозван"}[code]
    if code == 1 and not res["kid_known"]:
        notes.append(f"ключ {res['kid']} не найден среди переданных открытых ключей")
    if res["test_key"]:
        notes.append("подписан тестовым ключом стенда разработки — не доказательство")
    if registry:
        notes.append(f"реестр издателя: {registry.get('title')}"
                     + (f" — {registry.get('reason_title')}" if registry.get("reason_title") else ""))
    else:
        notes.append("статус отзыва не проверялся (офлайн): откройте ссылку /verify/<id>")
    if a.json:
        print(json.dumps({**res, "verdict": verdict, "exit_code": code, "registry": registry, "notes": notes},
                         ensure_ascii=False, indent=2))
    else:
        print(f"{verdict}: паспорт {res['id']} · {res['category'] or '—'} ({res['grade_status'] or '—'}) · "
              f"кандидат {res['public_ref'] or '—'}")
        print(f"  подпись: {'верна' if res['signature_valid'] else 'не сходится'} (kid {res['kid']}); "
              f"действителен до {res['valid_until']}; навыков T1: {res['skills_t1']}, достижений T2: "
              f"{res['achievements_t2']}")
        for n in notes:
            print(f"  · {n}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
