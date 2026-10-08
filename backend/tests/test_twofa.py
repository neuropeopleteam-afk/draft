"""Второй фактор входа (И17): TOTP RFC 6238, резервные коды, обязательность для admin/fsp_analyst, демо жюри."""
from datetime import timedelta
import base64

from sqlalchemy import select

from app.core import totp
from app.core.db import SessionLocal, utcnow
from app.core.enums import UserRole
from app.core.security import hash_password
from app.modules.auth import twofa
from app.modules.auth.models import TwoFactorRecoveryCode, User, UserTwoFactor
from tests.conftest import register_and_verify

H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731


# ------------------------------------------------------------------------------------------------ алгоритм

def test_rfc6238_vectors():
    """Приложение B RFC 6238 (SHA1, секрет «12345678901234567890») и RFC 4226 — наша реализация совпадает."""
    sec = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    for ts, exp in [(59, "94287082"), (1111111109, "07081804"), (1234567890, "89005924"),
                    (2000000000, "69279037"), (20000000000, "65353130")]:
        assert totp.totp(sec, ts, digits=8) == exp
    for counter, exp in [(0, "755224"), (1, "287082"), (9, "520489")]:
        assert totp.hotp(sec, counter) == exp


def test_verify_window_one_step():
    sec = totp.generate_secret()
    now = 1_700_000_000
    code_prev, code_now, code_next = totp.totp(sec, now - 30), totp.totp(sec, now), totp.totp(sec, now + 30)
    assert totp.verify(sec, code_now, now) == totp.step_of(now)
    assert totp.verify(sec, code_prev, now) == totp.step_of(now) - 1
    assert totp.verify(sec, code_next, now) == totp.step_of(now) + 1
    assert totp.verify(sec, totp.totp(sec, now - 60), now) is None  # два шага назад — вне окна
    assert totp.verify(sec, "12345", now) is None and totp.verify(sec, "abcdef", now) is None


def test_secret_encrypted_in_db(client):
    tok = register_and_verify(client, "enc@example.com")
    r = client.post("/api/auth/2fa/setup", headers=H(tok))
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    with SessionLocal() as db:
        tf = db.scalar(select(UserTwoFactor))
        assert secret not in tf.secret_enc and tf.secret_enc.startswith("gAAAA")  # Fernet
        assert twofa.decrypt_secret(tf.secret_enc) == secret


# ------------------------------------------------------------------------------------------------ подключение

def _enable(client, tok):
    r = client.post("/api/auth/2fa/setup", headers=H(tok))
    assert r.status_code == 200, r.text
    setup = r.json()
    assert setup["qr_svg"].startswith("<svg") and setup["otpauth_uri"].startswith("otpauth://totp/")
    # SVG годен как data-URI в <img>: «&» из otpauth-ссылки в атрибуте экранирован
    import xml.dom.minidom
    xml.dom.minidom.parseString(setup["qr_svg"])
    assert setup["secret"].replace(" ", "") == setup["secret_grouped"].replace(" ", "")
    r = client.post("/api/auth/2fa/confirm", json={"code": totp.totp(setup["secret"])}, headers=H(tok))
    assert r.status_code == 200, r.text
    codes = r.json()["recovery_codes"]
    assert len(codes) == 10 and all(len(c) == 9 and c[4] == "-" for c in codes)
    return setup["secret"], codes


def _fresh(secret, _unused=None):
    """Текущий код, пригодный для повторной проверки в том же тесте: защита от повтора помнит последний шаг, поэтому
    «отматываем» его в БД, как будто прошло несколько минут (сам повтор проверяется отдельно, без _fresh)."""
    with SessionLocal() as db:
        for tf in db.scalars(select(UserTwoFactor)):
            tf.last_used_step = totp.step_of() - 100
        db.commit()
    return totp.totp(secret)


def test_setup_confirm_wrong_first_code(client):
    tok = register_and_verify(client, "c1@example.com")
    client.post("/api/auth/2fa/setup", headers=H(tok))
    r = client.post("/api/auth/2fa/confirm", json={"code": "000000"}, headers=H(tok))
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_code"
    st = client.get("/api/auth/2fa", headers=H(tok)).json()
    assert st["enabled"] is False and st["pending_setup"] is True


def test_status_hides_secret_after_enable(client):
    tok = register_and_verify(client, "c2@example.com")
    _enable(client, tok)
    st = client.get("/api/auth/2fa", headers=H(tok))
    assert st.status_code == 200
    body = st.json()
    assert body["enabled"] and body["recovery_codes_left"] == 10 and body["required"] is False and body["can_disable"]
    assert "secret" not in body and "otpauth" not in st.text


# ------------------------------------------------------------------------------------------------ вход

def test_login_requires_code_when_enabled(client):
    tok = register_and_verify(client, "l1@example.com")
    secret, codes = _enable(client, tok)
    r = client.post("/api/auth/login", json={"email": "l1@example.com", "password": "Passw0rd!"})
    assert r.status_code == 200, r.text
    ch = r.json()
    assert ch["second_factor_required"] is True and ch["setup_required"] is False and "access_token" not in ch
    pending = ch["pending_token"]
    # промежуточный токен — не вход
    assert client.get("/api/me", headers=H(pending)).status_code == 401
    assert client.get("/api/me", headers=H(pending)).json()["detail"]["code"] == "second_factor_required"
    # неверный код
    r = client.post("/api/auth/2fa/verify", json={"pending_token": pending, "code": "000000"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_code"
    # верный код → токен
    code = _fresh(secret)
    r = client.post("/api/auth/2fa/verify", json={"pending_token": pending, "code": code})
    assert r.status_code == 200, r.text
    assert r.json()["method"] == "totp"
    access = r.json()["access_token"]
    assert client.get("/api/me", headers=H(access)).status_code == 200
    # повтор того же кода — отклонён, и не считается перебором
    r = client.post("/api/auth/2fa/verify", json={"pending_token": pending, "code": code})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "code_reused"


def test_login_recovery_code_single_use(client):
    tok = register_and_verify(client, "l2@example.com")
    _, codes = _enable(client, tok)
    pending = client.post("/api/auth/login", json={"email": "l2@example.com", "password": "Passw0rd!"}).json()["pending_token"]
    rc = codes[0].lower().replace("-", " ")  # регистр и разделители не важны
    r = client.post("/api/auth/2fa/verify", json={"pending_token": pending, "code": rc})
    assert r.status_code == 200 and r.json()["method"] == "recovery"
    st = client.get("/api/auth/2fa", headers=H(r.json()["access_token"])).json()
    assert st["recovery_codes_left"] == 9
    r = client.post("/api/auth/2fa/verify", json={"pending_token": pending, "code": codes[0]})
    assert r.status_code == 400  # второй раз тот же резервный код не работает
    with SessionLocal() as db:
        rows = db.scalars(select(TwoFactorRecoveryCode)).all()
        assert len(rows) == 10 and sum(1 for x in rows if x.used_at) == 1
        assert not any(codes[0].replace("-", "") in x.code_hash for x in rows)  # хранятся хеши


def test_login_window_accepts_previous_step(client):
    tok = register_and_verify(client, "l3@example.com")
    secret, _ = _enable(client, tok)
    pending = client.post("/api/auth/login", json={"email": "l3@example.com", "password": "Passw0rd!"}).json()["pending_token"]
    # код предыдущего шага (часы телефона отстают на 30 с) — принят; но при подключении уже использован шаг «сейчас»,
    # поэтому защита от повтора его отклонит: сбрасываем last_used_step, как будто подключение было давно
    with SessionLocal() as db:
        tf = db.scalar(select(UserTwoFactor))
        tf.last_used_step = totp.step_of() - 10
        db.commit()
    r = client.post("/api/auth/2fa/verify", json={"pending_token": pending, "code": totp.totp(secret, utcnow().timestamp() - 30)})
    assert r.status_code == 200, r.text
    # а код двух шагов назад — нет
    pending = client.post("/api/auth/login", json={"email": "l3@example.com", "password": "Passw0rd!"}).json()["pending_token"]
    r = client.post("/api/auth/2fa/verify", json={"pending_token": pending, "code": totp.totp(secret, utcnow().timestamp() - 90)})
    assert r.status_code == 400


def test_bruteforce_locks_after_five(client):
    tok = register_and_verify(client, "l4@example.com")
    secret, _ = _enable(client, tok)
    pending = client.post("/api/auth/login", json={"email": "l4@example.com", "password": "Passw0rd!"}).json()["pending_token"]
    for _ in range(5):
        r = client.post("/api/auth/2fa/verify", json={"pending_token": pending, "code": "111111"})
        assert r.status_code == 400
    r = client.post("/api/auth/2fa/verify", json={"pending_token": pending, "code": _fresh(secret)})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "too_many_attempts"  # даже верный код — заблокировано
    st = client.get("/api/auth/2fa", headers=H(tok)).json()
    assert st["locked_until"] is not None
    with SessionLocal() as db:  # блокировка истекла — вход возможен
        tf = db.scalar(select(UserTwoFactor))
        tf.locked_until = utcnow() - timedelta(seconds=1)
        db.commit()
    r = client.post("/api/auth/2fa/verify", json={"pending_token": pending, "code": _fresh(secret)})
    assert r.status_code == 200, r.text


def test_pending_token_expires_and_not_reusable_as_access(client):
    tok = register_and_verify(client, "l5@example.com")
    secret, _ = _enable(client, tok)
    from app.core.security import TOKEN_TYPE_2FA_PENDING, create_access_token

    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "l5@example.com"))
    expired, _ = create_access_token(u.id, "candidate", 0, {"typ": TOKEN_TYPE_2FA_PENDING}, ttl_minutes=-1)
    r = client.post("/api/auth/2fa/verify", json={"pending_token": expired, "code": _fresh(secret)})
    assert r.status_code == 401
    # обычный токен доступа вместо промежуточного — тоже нет
    r = client.post("/api/auth/2fa/verify", json={"pending_token": tok, "code": _fresh(secret)})
    assert r.status_code == 401


def test_oauth2_form_refuses_twofa_accounts(client):
    tok = register_and_verify(client, "l6@example.com")
    _enable(client, tok)
    r = client.post("/api/auth/token", data={"username": "l6@example.com", "password": "Passw0rd!"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "second_factor_required"


# ------------------------------------------------------------------------------------------------ управление

def test_disable_requires_code_and_rotation(client):
    tok = register_and_verify(client, "m1@example.com")
    secret, codes = _enable(client, tok)
    assert client.post("/api/auth/2fa/disable", json={"code": "000000"}, headers=H(tok)).status_code == 400
    # перевыпуск: без кода — нельзя; с кодом — новый ключ, старый действует до подтверждения
    assert client.post("/api/auth/2fa/setup", json={}, headers=H(tok)).status_code == 400
    r = client.post("/api/auth/2fa/setup", json={"code": _fresh(secret)}, headers=H(tok))
    assert r.status_code == 200 and r.json()["rotation"] is True
    new_secret = r.json()["secret"]
    assert new_secret != secret
    assert client.post("/api/auth/2fa/check", json={"code": _fresh(secret)}, headers=H(tok)).status_code == 200  # старый ещё работает
    r = client.post("/api/auth/2fa/confirm", json={"code": _fresh(new_secret)}, headers=H(tok))
    assert r.status_code == 200 and r.json()["recovery_codes"] != codes
    assert client.post("/api/auth/2fa/check", json={"code": _fresh(secret, 2)}, headers=H(tok)).status_code == 400  # старый мёртв
    # новые резервные коды — с кодом
    r = client.post("/api/auth/2fa/recovery-codes", json={"code": _fresh(new_secret)}, headers=H(tok))
    assert r.status_code == 200 and len(r.json()["recovery_codes"]) == 10
    # отключение с верным кодом
    r = client.post("/api/auth/2fa/disable", json={"code": _fresh(new_secret)}, headers=H(tok))
    assert r.status_code == 200
    assert client.get("/api/auth/2fa", headers=H(tok)).json()["enabled"] is False
    r = client.post("/api/auth/login", json={"email": "m1@example.com", "password": "Passw0rd!"})
    assert "access_token" in r.json()  # снова вход без кода
    with SessionLocal() as db:
        assert db.scalars(select(TwoFactorRecoveryCode)).all() == []


# ------------------------------------------------------------------------------------------------ обязательность

def _staff(email, role=UserRole.admin, password="Adm1nPassw0rd!"):
    with SessionLocal() as db:
        u = User(email=email, password_hash=hash_password(password), role=role, is_email_verified=True,
                 email_verified_at=utcnow())
        db.add(u)
        db.commit()
        return u.id


def test_admin_without_twofa_gets_setup_only_token(client):
    _staff("admin@example.com")
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Adm1nPassw0rd!"})
    assert r.status_code == 200, r.text
    ch = r.json()
    assert ch["second_factor_required"] and ch["setup_required"] is True and "access_token" not in ch
    setup_tok = ch["pending_token"]
    # токен подключения — не вход в кабинет и не админ
    assert client.get("/api/me", headers=H(setup_tok)).status_code == 401
    assert client.get("/api/admin/2fa/users", headers=H(setup_tok)).status_code == 401
    assert client.post("/api/auth/2fa/check", json={"code": "123456"}, headers=H(setup_tok)).status_code == 401
    # но подключение по нему идёт
    st = client.get("/api/auth/2fa", headers=H(setup_tok))
    assert st.status_code == 200 and st.json()["required"] is True
    r = client.post("/api/auth/2fa/setup", headers=H(setup_tok))
    assert r.status_code == 200
    secret = r.json()["secret"]
    r = client.post("/api/auth/2fa/confirm", json={"code": totp.totp(secret)}, headers=H(setup_tok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token"] and len(body["recovery_codes"]) == 10
    access = body["token"]["access_token"]
    me = client.get("/api/me", headers=H(access))
    assert me.status_code == 200 and me.json()["role"] == "admin"
    # отключить обязательный фактор нельзя — только перевыпуск
    r = client.post("/api/auth/2fa/disable", json={"code": _fresh(secret)}, headers=H(access))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "twofa_required_role"
    assert client.get("/api/auth/2fa", headers=H(access)).json()["can_disable"] is False
    # следующий вход — с кодом
    ch = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Adm1nPassw0rd!"}).json()
    assert ch["setup_required"] is False


def test_fsp_analyst_required_but_demo_not(client):
    _staff("analyst@example.com", UserRole.fsp_analyst)
    ch = client.post("/api/auth/login", json={"email": "analyst@example.com", "password": "Adm1nPassw0rd!"}).json()
    assert ch["second_factor_required"] and ch["setup_required"]
    # демо-аналитик жюри — вход в один клик без второго фактора, с честной пометкой
    r = client.post("/api/jury/login", json={"persona": "fsp"})
    assert r.status_code == 200 and "access_token" in r.json()
    st = client.get("/api/auth/2fa", headers=H(r.json()["access_token"])).json()
    assert st["required"] is False and st["is_demo"] is True and "второй фактор" in st["demo_note"]


def test_candidate_and_employer_not_forced(client):
    tok = register_and_verify(client, "cand@example.com")
    assert client.get("/api/auth/2fa", headers=H(tok)).json()["required"] is False
    r = client.post("/api/auth/login", json={"email": "cand@example.com", "password": "Passw0rd!"})
    assert "access_token" in r.json()


# ------------------------------------------------------------------------------------------------ жюри и эксперт

def test_jury_persona_with_totp_asks_code_and_keeps_sandbox(client):
    r = client.post("/api/jury/login", json={"persona": "fsp", "scenario": "new"})
    assert r.status_code == 200, r.text
    tok, sid = r.json()["access_token"], r.json()["scenario"]
    assert sid
    secret, _ = _enable(client, tok)
    # вход в один клик под этой персоной теперь просит код
    r = client.post("/api/jury/login", json={"persona": "fsp", "scenario": sid})
    assert r.status_code == 200
    ch = r.json()
    assert ch["second_factor_required"] and ch["persona"] == "fsp" and ch["landing"] == "/fsp" and ch["scenario"] == sid
    r = client.post("/api/auth/2fa/verify", json={"pending_token": ch["pending_token"], "code": _fresh(secret)})
    assert r.status_code == 200, r.text
    assert r.json()["landing"] == "/fsp" and r.json()["scenario"] == sid
    # песочница перенесена в итоговый токен
    from app.core.security import decode_access_token

    assert decode_access_token(r.json()["access_token"]).get("jsc") == sid
    # другие персоны той же песочницы — по-прежнему в один клик
    r = client.post("/api/jury/login", json={"persona": "candidate", "scenario": sid})
    assert "access_token" in r.json()
    # сброс демо пересоздаёт учётки — подключение исчезает
    r = client.post("/api/jury/reset", headers=H(r.json()["access_token"]))
    assert r.status_code == 200, r.text
    r = client.post("/api/jury/login", json={"persona": "fsp", "scenario": sid})
    assert "access_token" in r.json()


def test_expert_invite_link_with_totp(client):
    """Эксперт панели без пароля и реальной почты: персональная ссылка + по желанию код из приложения."""
    import secrets

    from app.modules.experts.models import ExpertPanelist
    from app.modules.experts.service import token_hash

    link_token = secrets.token_urlsafe(24)
    with SessionLocal() as db:  # панелист напрямую — без сборки пакета разметки (он не про вход)
        u = User(email="e1-test@panel.example.com", password_hash=hash_password(secrets.token_urlsafe(24)),
                 role=UserRole.expert, is_email_verified=True, email_verified_at=utcnow())
        db.add(u)
        db.flush()
        db.add(ExpertPanelist(code="E1", slot="E1", team_size=3, user_id=u.id, token_hash=token_hash(link_token),
                              pack="test", assignment={"A": [], "B": [], "C": []}))
        db.commit()
    r = client.post("/api/expert-panel/enter", json={"token": link_token})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    secret, _ = _enable(client, tok)
    r = client.post("/api/expert-panel/enter", json={"token": link_token})
    assert r.status_code == 200 and r.json()["second_factor_required"] and r.json()["landing"] == "/expert"
    r = client.post("/api/auth/2fa/verify", json={"pending_token": r.json()["pending_token"], "code": _fresh(secret)})
    assert r.status_code == 200 and r.json()["code"] == "E1"
    assert client.get("/api/expert-panel/me", headers=H(r.json()["access_token"])).status_code == 200


# ------------------------------------------------------------------------------------------------ администратор

def test_admin_reset_and_matrix(client):
    tok = register_and_verify(client, "victim@example.com")
    _enable(client, tok)
    _staff("root@example.com")
    ch = client.post("/api/auth/login", json={"email": "root@example.com", "password": "Adm1nPassw0rd!"}).json()
    setup = client.post("/api/auth/2fa/setup", headers=H(ch["pending_token"])).json()
    admin_tok = client.post("/api/auth/2fa/confirm", json={"code": totp.totp(setup["secret"])},
                            headers=H(ch["pending_token"])).json()["token"]["access_token"]
    # права: аноним 401, кандидат 403
    assert client.get("/api/admin/2fa/users").status_code == 401
    assert client.get("/api/admin/2fa/users", headers=H(tok)).status_code == 403
    assert client.post("/api/admin/2fa/reset", json={"email": "victim@example.com"}, headers=H(tok)).status_code == 403
    lst = client.get("/api/admin/2fa/users", headers=H(admin_tok)).json()
    assert {i["email"] for i in lst["items"]} == {"victim@example.com", "root@example.com"}
    assert "secret" not in str(lst)
    # сброс: подключение снято, сеансы отозваны, вход снова без кода
    r = client.post("/api/admin/2fa/reset", json={"email": "victim@example.com"}, headers=H(admin_tok))
    assert r.status_code == 200 and r.json()["sessions_revoked"]
    assert client.get("/api/me", headers=H(tok)).status_code == 401
    r = client.post("/api/auth/login", json={"email": "victim@example.com", "password": "Passw0rd!"})
    assert "access_token" in r.json()
    assert client.post("/api/admin/2fa/reset", json={"email": "victim@example.com"}, headers=H(admin_tok)).status_code == 404
    assert client.post("/api/admin/2fa/reset", json={"email": "root@example.com"}, headers=H(admin_tok)).status_code == 409
    assert client.post("/api/admin/2fa/reset", json={"email": "nobody@example.com"}, headers=H(admin_tok)).status_code == 404


def test_cli_add_staff_and_reset(client, monkeypatch):
    from app.modules.auth.__main__ import main

    monkeypatch.setenv("STAFF_PASSWORD", "Sup3rSecretPass!")
    assert main(["add-staff", "--email", "cli-admin@example.com", "--role", "admin"]) == 0
    assert main(["add-staff", "--email", "cli-admin@example.com", "--role", "admin"]) == 1  # уже есть
    ch = client.post("/api/auth/login", json={"email": "cli-admin@example.com", "password": "Sup3rSecretPass!"}).json()
    assert ch["setup_required"] is True
    setup = client.post("/api/auth/2fa/setup", headers=H(ch["pending_token"])).json()
    assert client.post("/api/auth/2fa/confirm", json={"code": totp.totp(setup["secret"])}, headers=H(ch["pending_token"])).status_code == 200
    assert main(["list-2fa"]) == 0
    assert main(["reset-2fa", "--email", "cli-admin@example.com"]) == 0
    assert main(["reset-2fa", "--email", "cli-admin@example.com"]) == 1
    assert client.post("/api/auth/login", json={"email": "cli-admin@example.com", "password": "Sup3rSecretPass!"}).json()["setup_required"] is True
