"""KF1 «Паспорт-щит»: QR ссылки на проверку, JWKS по стандартному адресу, файл офлайн-проверки (подпись Ed25519
проверяется только по содержимому файла — без обращения к серверу), kid в кратком виде паспорта и демо жюри
(паспорт демо-кандидата выпускается при первом запросе, «Отозвать» / «Выпустить заново»)."""
from __future__ import annotations

import base64
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.core.config import get_settings
from app.jury_live import qr
from app.passport import service
from tests.conftest import register_and_verify
from tests.test_passport import H, _candidate_with_category


def _b64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _pid(client, tok) -> str:
    return client.get("/api/me/passport", headers=H(tok)).json()["active"]["id"]


def _offline_ok(bundle: dict) -> bool:
    """Офлайн-проверка «как у работодателя»: подписанная строка + открытый ключ из файла, сервер не нужен."""
    if json.loads(bundle["document"]) != bundle["passport"]:
        return False  # показанный паспорт не тот, что подписан
    key = next(k for k in bundle["jwks"]["keys"] if k["kid"] == bundle["signature"]["kid"])
    try:
        Ed25519PublicKey.from_public_bytes(_b64u(key["x"])).verify(_b64u(bundle["signature"]["value"]),
                                                                    bundle["document"].encode("utf-8"))
        return True
    except InvalidSignature:
        return False


# ------------------------------------------------------------------ QR, JWKS, офлайн-файл

def test_qr_svg_encodes_verify_link(client):
    tok, _ = _candidate_with_category(client, email="kf1-qr@example.com")
    pid = _pid(client, tok)
    r = client.get(f"/api/passport/{pid}/qr.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert r.text.lstrip().startswith("<svg") and r.text.rstrip().endswith("</svg>")
    url = service.verify_url(pid)
    assert url.endswith(f"/verify/{pid}")
    assert r.text == qr.svg(url)  # именно ссылка на страницу проверки /verify/{id}
    assert len(qr.matrix(url)) >= 21  # настоящий QR (версия 1+ — от 21×21 модуля)
    assert client.get("/api/passport/nope-nope-nope/qr.svg").status_code == 404


def test_well_known_jwks_matches_keys(client):
    _candidate_with_category(client, email="kf1-jwks@example.com")
    keys = client.get("/api/passport/keys").json()["keys"]
    for path in ("/.well-known/jwks.json", "/api/.well-known/jwks.json"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("application/jwk-set+json")
        assert r.headers["access-control-allow-origin"] == "*"  # проверяющий скрипт с любого сайта
        body = r.json()
        assert body["keys"] == keys and body["alg"] == "EdDSA"
        assert all(k["kty"] == "OKP" and k["crv"] == "Ed25519" and "d" not in k for k in body["keys"])


def test_offline_bundle_verifies_without_server(client):
    tok, _ = _candidate_with_category(client, email="kf1-off@example.com")
    pid = _pid(client, tok)
    r = client.get(f"/api/passport/{pid}/offline.json")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == f'attachment; filename="passport-{pid}.json"'
    bundle = r.json()
    assert bundle["passport"]["id"] == pid and bundle["signature"]["alg"] == "EdDSA"
    assert bundle["jwks_url"].endswith("/.well-known/jwks.json") and bundle["verify_url"].endswith(f"/verify/{pid}")
    assert "HMAC" in bundle["why_ed25519"] and "JWKS" in bundle["why_ed25519"]
    assert _offline_ok(bundle)  # подпись сходится по одному файлу
    forged = json.loads(json.dumps(bundle))
    forged["passport"]["category"]["grade"] = "senior"
    assert not _offline_ok(forged)  # подмена грейда в паспорте — не совпадает с подписанным
    forged["document"] = json.dumps(forged["passport"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert not _offline_ok(forged)  # и пересобранный документ — подпись не сходится
    # файл с тем же содержимым принимает и серверная проверка
    v = client.post("/api/passport/verify", json={"passport": bundle["passport"], "signature": bundle["signature"]})
    assert v.status_code == 200 and v.json()["signature_valid"] is True
    assert client.get("/api/passport/nope-nope-nope/offline.json").status_code == 404


def test_brief_has_kid_and_qr_for_employer_badge(client):
    from tests.test_day2_rules import employer, my_ref

    tok, _ = _candidate_with_category(client, email="kf1-brief@example.com")
    pid = _pid(client, tok)
    te = employer(client, email="kf1-hr@corp.ru")
    r = client.get(f"/api/employer/candidates/{my_ref(client, tok)}/passport", headers=H(te))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["id"] == pid and b["state"] == "valid" and b["signature_valid"] is True
    assert b["kid"].startswith("ed25519-") and b["alg"] == "EdDSA"
    assert b["qr_path"] == f"/api/passport/{pid}/qr.svg" and b["path"] == f"/verify/{pid}"
    assert b["kid"] == client.get(f"/api/passport/{pid}").json()["signature"]["kid"]


# ------------------------------------------------------------------ демо жюри: паспорт демо-кандидата

def _jury(client, persona="candidate", scenario="new"):
    r = client.post("/api/jury/login", json={"persona": persona, "scenario": scenario})
    assert r.status_code == 200, r.text
    return r.json()


def test_demo_passport_issue_revoke_reissue(client):
    j = _jury(client)
    sid, tok = j["scenario"], j["access_token"]
    r = client.get(f"/api/passport/demo?scenario={sid}")
    assert r.status_code == 200, r.text
    d = r.json()
    p = d["passport"]
    assert p and p["state"] == "valid" and p["kid"].startswith("ed25519-")
    assert p["qr_path"] == f"/api/passport/{p['id']}/qr.svg" and p["path"] == f"/verify/{p['id']}"
    assert d["jwks_url"] == "/.well-known/jwks.json" and d["opted_out"] is False
    # повторный запрос — тот же паспорт (не выпускает новый каждый раз)
    assert client.get(f"/api/passport/demo?scenario={sid}").json()["passport"]["id"] == p["id"]
    # совпадает с паспортом, который видит сам демо-кандидат
    assert _pid(client, tok) == p["id"]
    assert client.get(p["qr_path"]).status_code == 200

    # «Отозвать паспорт»: старая ссылка показывает «Отозван», демо-запрос не выпускает новый сам
    rv = client.post("/api/passport/demo/revoke", headers=H(tok))
    assert rv.status_code == 200, rv.text
    assert rv.json()["passport"] is None and rv.json()["opted_out"] is True
    assert client.get(f"/api/passport/{p['id']}").json()["status"]["state"] == "revoked"
    assert client.get(f"/api/passport/demo?scenario={sid}").json()["passport"] is None
    assert client.post("/api/passport/demo/revoke", headers=H(tok)).status_code == 200  # повтор — без ошибки

    # «Выпустить заново»: новая ссылка, тот же ключ платформы
    ri = client.post("/api/passport/demo/reissue", headers=H(tok))
    assert ri.status_code == 200, ri.text
    np_ = ri.json()["passport"]
    assert np_["id"] != p["id"] and np_["state"] == "valid" and np_["kid"] == p["kid"]
    assert client.get(f"/api/passport/demo?scenario={sid}").json()["passport"]["id"] == np_["id"]


def test_demo_passport_sandbox_isolation_and_access(client):
    a, b = _jury(client), _jury(client)
    pa = client.get(f"/api/passport/demo?scenario={a['scenario']}").json()["passport"]
    pb = client.get(f"/api/passport/demo?scenario={b['scenario']}").json()["passport"]
    assert pa["id"] != pb["id"]  # у каждого эксперта — свой демо-кандидат
    # работодатель песочницы A отзывает паспорт кандидата своей песочницы, B не трогает
    emp_a = _jury(client, "employer", a["scenario"])
    assert client.post("/api/passport/demo/revoke", headers=H(emp_a["access_token"])).status_code == 200
    assert client.get(f"/api/passport/{pa['id']}").json()["status"]["state"] == "revoked"
    assert client.get(f"/api/passport/{pb['id']}").json()["status"]["state"] == "valid"
    # без входа — 401, обычная учётка — 403, неверная песочница — 422
    assert client.post("/api/passport/demo/revoke").status_code == 401
    other = register_and_verify(client, "kf1-stranger@example.com")
    r = client.post("/api/passport/demo/reissue", headers=H(other))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "jury_only"
    assert client.get("/api/passport/demo?scenario=../../etc").status_code == 422


def test_demo_passport_disabled_without_jury_mode(client, monkeypatch):
    j = _jury(client)
    monkeypatch.setattr(get_settings(), "jury_mode_available", False)
    assert client.get(f"/api/passport/demo?scenario={j['scenario']}").status_code == 404
    assert client.post("/api/passport/demo/revoke", headers=H(j["access_token"])).status_code == 404
