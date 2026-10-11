"""Подписанный паспорт грейда: выпуск после категории, подделка любого поля, отзыв, истечение, ротация ключа, нет ПДн."""
from __future__ import annotations

from datetime import timedelta
import importlib.util
import io
import json
from pathlib import Path
import uuid

import pytest

from app.core.db import SessionLocal, utcnow
from tests.conftest import register_and_verify

ROOT = Path(__file__).resolve().parents[2]


def H(t):
    return {"Authorization": f"Bearer {t}"}


def _verify_tool():
    spec = importlib.util.spec_from_file_location("passport_verify_tool", ROOT / "tools" / "passport" / "verify.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VT = _verify_tool()


def _candidate_with_category(client, email="pass@example.com", theta=1.3, grade="middle", seed=11,
                             name="Пётр Паспортов", pending_left=0):
    """Кандидат с категорией по настоящему тесту банка (демо-респондент, θ выше порога)."""
    from app.modules.jury.seed import run_demo_test
    from app.modules.profiles.models import CandidateProfile
    from tests.test_day2_rules import ONBOARDING

    tok = register_and_verify(client, email)
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(tok)).status_code == 200
    uid = uuid.UUID(client.get("/api/me", headers=H(tok)).json()["id"])
    with SessionLocal() as db:
        p = db.get(CandidateProfile, uid)
        p.full_name, p.phone, p.telegram, p.city = name, "+7 912 345-67-89", "@petr_secret", "Тверь"
        db.commit()
        out = run_demo_test(db, uid, grade, theta, seed, pending_left)
        db.commit()
    assert out["confirmed"], out
    return tok, uid


def _keys(client):
    return client.get("/api/passport/keys").json()["keys"]


def _public(client, pid):
    r = client.get(f"/api/passport/{pid}")
    assert r.status_code == 200, r.text
    return r.json()


def _leaves(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaves(v, path + (i,))
    else:
        yield path, obj


def _set(obj, path, value):
    for k in path[:-1]:
        obj = obj[k]
    obj[path[-1]] = value


def _tampered(v):
    if isinstance(v, bool):
        return not v
    if isinstance(v, (int, float)):
        return v + 1
    if v is None:
        return "x"
    return str(v) + "x"


def test_issued_after_category_and_valid_publicly(client):
    tok, _ = _candidate_with_category(client)
    me = client.get("/api/me/passport", headers=H(tok)).json()
    act = me["active"]
    assert act is not None and act["status"]["state"] == "valid", me
    pid = act["id"]
    # публично, без входа: подписанный документ, статус, ключ
    pub = _public(client, pid)
    assert pub["status"]["state"] == "valid" and pub["status"]["title"] == "Действителен"
    claims = pub["passport"]
    assert claims["id"] == pid and claims["schema"] == "draft.grade-passport/1"
    assert claims["category"]["id"] == "backend.middle" and claims["grade_status"] == "confirmed"
    assert claims["issuer"]["name"] == "Драфт" and claims["issuer"]["test_key"] is True  # в тестах ключа нет
    assert claims["assessment"]["theta"] is not None and claims["assessment"]["test_date"]
    assert 0 <= claims["assessment"]["p_grade_or_higher"] <= 1
    assert claims["skills_t1"], "навыки, подтверждённые заданиями (T1)"
    assert pub["document"].encode() == VT.canonical(claims)  # канон приложения = канон офлайн-проверки
    # офлайн-проверка по опубликованному JWKS
    res = VT.check(pub, _keys(client))
    assert res["signature_valid"] and not res["expired"] and res["test_key"]
    # QR-код ссылки на проверку
    qr = client.get(f"/api/passport/{pid}/qr.svg")
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg")
    # повторное открытие кабинета не перевыпускает паспорт (состав не изменился)
    assert client.get("/api/me/passport", headers=H(tok)).json()["active"]["id"] == pid


def test_no_personal_data_in_passport(client):
    tok, uid = _candidate_with_category(client, email="pii.person@example.com", name="Аграфена Секретова")
    pub = _public(client, client.get("/api/me/passport", headers=H(tok)).json()["active"]["id"])
    doc = pub["document"]
    for secret in ("Аграфена", "Секретова", "pii.person", "example.com", "912 345", "petr_secret", "Тверь", str(uid)):
        assert secret not in doc, secret
    assert set(pub["passport"]) == {"schema", "id", "issuer", "kid", "subject", "category", "grade_status",
                                    "assessment", "skills_t1", "achievements_t2", "methodology_url", "issued_at",
                                    "valid_until"}
    assert set(pub["passport"]["subject"]) == {"public_ref"}


def test_tampering_any_field_breaks_signature(client):
    tok, _ = _candidate_with_category(client)
    pub = _public(client, client.get("/api/me/passport", headers=H(tok)).json()["active"]["id"])
    keys = _keys(client)
    assert VT.check(pub, keys)["signature_valid"]
    leaves = list(_leaves(pub["passport"]))
    assert len(leaves) > 15
    for path, v in leaves:
        doc = json.loads(json.dumps(pub))
        _set(doc["passport"], path, _tampered(v))
        assert not VT.check(doc, keys)["signature_valid"], path
    # добавленное поле — тоже подделка
    doc = json.loads(json.dumps(pub))
    doc["passport"]["grade_status_note"] = "senior"
    assert not VT.check(doc, keys)["signature_valid"]
    # проверка файла на сервере: подлинный — «Действителен», подделанный — «Подпись не сходится»
    ok = client.post("/api/passport/verify", json={"passport": pub["passport"], "signature": pub["signature"]}).json()
    assert ok["signature_valid"] and ok["state"] == "valid" and ok["matches_registry"]
    bad = json.loads(json.dumps(pub))
    bad["passport"]["category"]["grade"] = "senior"
    r = client.post("/api/passport/verify", json={"passport": bad["passport"], "signature": bad["signature"]}).json()
    assert not r["signature_valid"] and r["state"] == "invalid_signature"


def test_file_resaved_by_browser_or_other_json_tool_still_verifies(client):
    """Браузер (JSON.parse/JSON.stringify) пишет 1.0 как 1, часть экспортов — 1 как 1.0: подпись не ломается."""
    from app.passport import crypto

    sample = {"a": 1.0, "b": [2.0, 0.5, -0.0], "c": {"d": 1.714, "e": True, "f": None}}
    js = {"a": 1, "b": [2, 0.5, 0], "c": {"d": 1.714, "e": True, "f": None}}
    assert crypto.canonical(sample) == crypto.canonical(js) == VT.canonical(sample) == VT.canonical(js)
    assert crypto.canonical({"t": True}) != crypto.canonical({"t": 1})  # булево не становится числом
    tok, _ = _candidate_with_category(client)
    pub = _public(client, client.get("/api/me/passport", headers=H(tok)).json()["active"]["id"])
    keys = _keys(client)
    as_js = json.loads(json.dumps(pub), parse_float=lambda x: int(float(x)) if float(x).is_integer() else float(x))
    as_floats = json.loads(json.dumps(pub), parse_int=float)
    assert as_floats["passport"]["assessment"]["answered"] == float(pub["passport"]["assessment"]["answered"])
    for doc in (as_js, as_floats):
        assert VT.check(doc, keys)["signature_valid"]
        body = {"passport": doc["passport"], "signature": doc["signature"]}
        r = client.post("/api/passport/verify", json=body).json()
        assert r["signature_valid"] and r["state"] == "valid" and r["matches_registry"]


def test_passport_signed_with_first_canonical_form_still_verifies(client):
    """Паспорта, подписанные до замены 1.0 → 1 (канон писал «2.0»), проверяются тем же ключом."""
    from app.passport import crypto

    tok, _ = _candidate_with_category(client)
    pub = _public(client, client.get("/api/me/passport", headers=H(tok)).json()["active"]["id"])
    old = json.loads(json.dumps(pub))
    old["passport"]["assessment"]["theta"] = 2.0
    assert crypto.canonical_legacy(old["passport"]) != crypto.canonical(old["passport"])
    old["signature"]["value"] = crypto.b64u(crypto.signing_key().private.sign(crypto.canonical_legacy(old["passport"])))
    assert VT.check(old, _keys(client))["signature_valid"]
    r = client.post("/api/passport/verify", json={"passport": old["passport"], "signature": old["signature"]}).json()
    assert r["signature_valid"] and r["state"] == "differs"  # подпись верна, но в реестре под этим id другой документ
    old["passport"]["assessment"]["theta"] = 3.0  # подделка ломает подпись и в старом каноне
    assert not VT.check(old, _keys(client))["signature_valid"]


def test_tampered_registry_row_shows_signature_mismatch(client):
    from app.passport.models import GradePassport

    tok, _ = _candidate_with_category(client)
    pid = client.get("/api/me/passport", headers=H(tok)).json()["active"]["id"]
    with SessionLocal() as db:
        p = db.get(GradePassport, pid)
        p.document = p.document.replace('"grade":"middle"', '"grade":"senior"')
        db.commit()
    st = _public(client, pid)["status"]
    assert st["state"] == "invalid_signature" and st["title"] == "Подпись не сходится"


def test_candidate_revokes_and_reissues_link(client):
    tok, _ = _candidate_with_category(client)
    old = client.get("/api/me/passport", headers=H(tok)).json()["active"]["id"]
    r = client.post("/api/me/passport/revoke", headers=H(tok))
    assert r.status_code == 200 and r.json()["active"] is None and r.json()["opted_out"]
    st = _public(client, old)["status"]
    assert st["state"] == "revoked" and st["reason"] == "candidate_revoked" and st["revoked_at"]
    # отзыв не отменяется сам при следующем открытии кабинета
    me = client.get("/api/me/passport", headers=H(tok)).json()
    assert me["active"] is None and me["opted_out"] and me["eligible"]
    assert client.post("/api/me/passport/revoke", headers=H(tok)).status_code == 404
    new = client.post("/api/me/passport/reissue", headers=H(tok)).json()["active"]
    assert new["id"] != old and new["status"]["state"] == "valid"
    assert _public(client, old)["status"]["state"] == "revoked"
    hist = client.get("/api/me/passport", headers=H(tok)).json()["history"]
    assert [h["id"] for h in hist][:2] == [new["id"], old]


def test_expired_passport(client):
    from app.passport.models import GradePassport

    tok, _ = _candidate_with_category(client)
    pub = _public(client, client.get("/api/me/passport", headers=H(tok)).json()["active"]["id"])
    with SessionLocal() as db:
        db.get(GradePassport, pub["passport"]["id"]).valid_until = utcnow() - timedelta(minutes=1)
        db.commit()
    assert _public(client, pub["passport"]["id"])["status"]["state"] == "expired"
    # офлайн: срок — подписанное поле valid_until
    from datetime import datetime

    later = datetime.fromisoformat(pub["passport"]["valid_until"].replace("Z", "+00:00")) + timedelta(seconds=1)
    res = VT.check(pub, _keys(client), now=later)
    assert res["signature_valid"] and res["expired"]


def _unlock(db, uid) -> None:
    """Снимает правило 90 дней и с профиля, и со специализаций направлений (И14: источник истины — специализация)."""
    from sqlalchemy import update

    from app.modules.profiles.models import CandidateProfile, CandidateSpecialization

    db.get(CandidateProfile, uid).grade_locked_until = None
    db.execute(update(CandidateSpecialization).where(CandidateSpecialization.user_id == uid).values(locked_until=None))
    db.commit()


def test_retest_downgrade_revokes_and_retest_reissues(client):
    from app.modules.jury.seed import run_demo_test

    tok, uid = _candidate_with_category(client)
    first = client.get("/api/me/passport", headers=H(tok)).json()["active"]["id"]
    with SessionLocal() as db:
        _unlock(db, uid)  # правило 90 дней — не предмет этого теста
        out = run_demo_test(db, uid, "junior", 0.2, 23)
        db.commit()
    assert out["grade_changed"] and out["current_grade"] == "junior"
    st = _public(client, first)["status"]
    assert st["state"] == "revoked" and st["reason"] == "downgraded"
    act = client.get("/api/me/passport", headers=H(tok)).json()["active"]
    assert act["passport"]["category"]["id"] == "backend.junior" and act["status"]["state"] == "valid"
    # пересдача на тот же грейд — перевыпуск, прежний «заменён»
    with SessionLocal() as db:
        _unlock(db, uid)
        run_demo_test(db, uid, "junior", 0.4, 29)
        db.commit()
    again = client.get("/api/me/passport", headers=H(tok)).json()["active"]
    assert again["id"] != act["id"]
    assert _public(client, act["id"])["status"]["reason"] == "superseded"


def test_account_deletion_and_admin_annulment(client):
    from sqlalchemy import delete

    from app.core.enums import UserRole
    from app.modules.auth.models import User

    tok, uid = _candidate_with_category(client)
    pid = client.get("/api/me/passport", headers=H(tok)).json()["active"]["id"]
    tok2, uid2 = _candidate_with_category(client, email="annul@example.com", seed=12)
    pid2 = client.get("/api/me/passport", headers=H(tok2)).json()["active"]["id"]
    # аннулирование — только решением администратора (сигналы античита сами не наказывают)
    assert client.post(f"/api/admin/passports/{pid2}/revoke", json={"reason": "integrity_annulled"},
                       headers=H(tok)).status_code == 403
    adm = register_and_verify(client, "admin.passport@example.com")
    with SessionLocal() as db:
        db.scalar(__import__("sqlalchemy").select(User).where(User.email == "admin.passport@example.com")).role = \
            UserRole.admin
        db.commit()
    r = client.post(f"/api/admin/passports/{pid2}/revoke", json={"reason": "integrity_annulled"}, headers=H(adm))
    assert r.status_code == 200 and r.json()["state"] == "revoked" and r.json()["reason"] == "integrity_annulled"
    # удаление учётной записи: паспорт остаётся в реестре и показывается отозванным
    with SessionLocal() as db:
        db.execute(delete(User).where(User.id == uid))
        db.commit()
    st = _public(client, pid)["status"]
    assert st["state"] == "revoked" and st["reason"] == "account_deleted"


def test_key_rotation_old_passports_verify_by_kid(client, monkeypatch):
    from app.core.config import get_settings
    from app.passport import crypto

    def use_key(seed: bytes):
        monkeypatch.setenv("PASSPORT_SIGNING_KEY", crypto.b64u(seed))
        get_settings.cache_clear()
        crypto.signing_key.cache_clear()

    try:
        use_key(b"\x01" * 32)
        tok1, _ = _candidate_with_category(client, email="rot1@example.com")
        p1 = client.get("/api/me/passport", headers=H(tok1)).json()["active"]
        use_key(b"\x02" * 32)
        tok2, _ = _candidate_with_category(client, email="rot2@example.com", seed=13)
        p2 = client.get("/api/me/passport", headers=H(tok2)).json()["active"]
        k1, k2 = p1["signature"]["kid"], p2["signature"]["kid"]
        assert k1 != k2 and not p1["passport"]["issuer"].get("test_key")
        keys = {k["kid"]: k for k in _keys(client)}
        assert keys[k1].get("retired") and not keys[k2].get("retired")
        for p in (p1, p2):
            assert _public(client, p["id"])["status"]["state"] == "valid"
            assert VT.check(_public(client, p["id"]), list(keys.values()))["signature_valid"]
        # без ключа kid проверка не проходит
        assert not VT.check(_public(client, p1["id"]), [keys[k2]])["signature_valid"]
    finally:
        monkeypatch.delenv("PASSPORT_SIGNING_KEY", raising=False)
        get_settings.cache_clear()
        crypto.signing_key.cache_clear()


def test_offline_tool_cli_on_file(client, tmp_path, capsys):
    tok, _ = _candidate_with_category(client)
    pub = _public(client, client.get("/api/me/passport", headers=H(tok)).json()["active"]["id"])
    f = tmp_path / "passport.json"
    f.write_text(json.dumps(pub, ensure_ascii=False), "utf-8")
    jwks = tmp_path / "keys.json"
    jwks.write_text(json.dumps({"keys": _keys(client)}), "utf-8")
    assert VT.main([str(f), "--jwks", str(jwks)]) == 0
    assert "Действителен" in capsys.readouterr().out
    pub["passport"]["assessment"]["theta"] = 2.5
    f.write_text(json.dumps(pub, ensure_ascii=False), "utf-8")
    assert VT.main([str(f), "--jwks", str(jwks)]) == 1
    assert "Подпись не сходится" in capsys.readouterr().out


def test_employer_card_and_pdf_carry_passport_link(client):
    from pypdf import PdfReader

    r = client.post("/api/jury/login", json={"persona": "candidate", "scenario": "new"})
    assert r.status_code == 200, r.text
    sid, ctok = r.json()["scenario"], r.json()["access_token"]
    me = client.get("/api/me/passport", headers=H(ctok)).json()
    pid = me["active"]["id"]
    ref = me["active"]["passport"]["subject"]["public_ref"]
    etok = client.post("/api/jury/login", json={"persona": "employer", "scenario": sid}).json()["access_token"]
    b = client.get(f"/api/employer/candidates/{ref}/passport", headers=H(etok))
    assert b.status_code == 200, b.text
    assert b.json()["id"] == pid and b.json()["path"] == f"/verify/{pid}" and b.json()["state"] == "valid"
    # кандидат не видит чужой эндпоинт работодателя
    assert client.get(f"/api/employer/candidates/{ref}/passport", headers=H(ctok)).status_code == 403
    for path, tok in ((f"/api/employer/candidates/{ref}/profile.pdf", etok), ("/api/me/profile.pdf", ctok)):
        pdf = client.get(path, headers=H(tok))
        assert pdf.status_code == 200
        text = "".join(pg.extract_text() for pg in PdfReader(io.BytesIO(pdf.content)).pages)
        assert f"/verify/{pid}" in text.replace("\n", ""), path
        assert "Подписанный паспорт грейда" in text


def test_unknown_passport_and_malformed_file(client):
    assert client.get("/api/passport/AAAAAAAAAAAAAAAA").status_code == 404
    assert client.get("/api/passport/x").status_code == 404
    r = client.post("/api/passport/verify", json={"passport": {"id": "nope"}, "signature": {"kid": "k", "value": "AA"}})
    assert r.status_code == 200 and r.json()["state"] == "invalid_signature" and not r.json()["kid_known"]


def test_no_passport_without_category(client):
    tok = register_and_verify(client, "nocat@example.com")
    me = client.get("/api/me/passport", headers=H(tok)).json()
    assert me["active"] is None and not me["eligible"]
    assert client.post("/api/me/passport/reissue", headers=H(tok)).status_code == 409


@pytest.mark.parametrize("value", ["not-base64!!", "AAAA"])
def test_bad_signing_key_does_not_break_test_finish(client, monkeypatch, value):
    from app.core.config import get_settings
    from app.passport import crypto

    monkeypatch.setenv("PASSPORT_SIGNING_KEY", value)
    get_settings.cache_clear()
    crypto.signing_key.cache_clear()
    try:
        tok, _ = _candidate_with_category(client, email=f"badkey{len(value)}@example.com")
        assert client.get("/api/assessment/status", headers=H(tok)).json()["current"]["category_id"] == "backend.middle"
    finally:
        monkeypatch.delenv("PASSPORT_SIGNING_KEY", raising=False)
        get_settings.cache_clear()
        crypto.signing_key.cache_clear()


def _expert(client, email):
    from sqlalchemy import select

    from app.core.enums import UserRole
    from app.modules.auth.models import User

    tok = register_and_verify(client, email)
    with SessionLocal() as db:
        db.scalar(select(User).where(User.email == email)).role = UserRole.expert
        db.commit()
    return tok


def _review_all_pending(client, xtok, ref):
    """Эксперт оценивает все ответы кандидата «на проверке» по всем критериям рубрики на 1."""
    items = [i for i in client.get("/api/expert/queue", headers=H(xtok)).json()["items"] if i["candidate_ref"] == ref]
    assert items, "у кандидата должны быть ответы на проверке"
    for it in items:
        r = client.post("/api/expert/review", headers=H(xtok), json={
            "session_id": it["session_id"], "token": it["token"], "part": it["part"],
            "criteria": {c["id"]: 1.0 for c in it["rubric"]["criteria"]}})
        assert r.status_code == 200 and r.json()["recomputed"], r.text
    return len(items)


def test_expert_review_turns_preliminary_into_confirmed(client):
    """Хук review.recompute: после оценки эксперта паспорт «предварительно» сразу перевыпускается «подтверждён»,
    без захода кандидата в кабинет; прежний — «заменён после экспертной проверки»."""
    from app.passport import service
    from app.passport.models import GradePassport

    tok, uid = _candidate_with_category(client, email="review.pass@example.com", pending_left=1)
    first = client.get("/api/me/passport", headers=H(tok)).json()["active"]
    assert first["passport"]["grade_status"] == "preliminary", first["passport"]
    ref = first["passport"]["subject"]["public_ref"]
    _review_all_pending(client, _expert(client, "expert.passport@example.com"), ref)
    with SessionLocal() as db:  # выпуск сделал хук, а не ленивый ensure_current при открытии кабинета
        cur = service.active(db, uid)
        assert cur is not None and cur.id != first["id"] and cur.grade_status == "confirmed"
        old = db.get(GradePassport, first["id"])
        assert old.revoke_reason == "reviewed" and old.revoked_at is not None
    st = _public(client, first["id"])["status"]
    assert st["state"] == "revoked" and "экспертной проверки" in st["reason_title"]
    new = _public(client, cur.id)
    assert new["status"]["state"] == "valid" and new["passport"]["grade_status"] == "confirmed"
    assert VT.check(new, _keys(client))["signature_valid"]


def test_expert_review_keeps_candidate_revocation(client):
    """Кандидат отозвал ссылку сам — проверка эксперта новый паспорт не выпускает (его выпускает только кандидат)."""
    from app.passport import service

    tok, uid = _candidate_with_category(client, email="review.optout@example.com", pending_left=1, seed=12)
    ref = client.get("/api/me/passport", headers=H(tok)).json()["active"]["passport"]["subject"]["public_ref"]
    assert client.post("/api/me/passport/revoke", headers=H(tok)).status_code == 200
    _review_all_pending(client, _expert(client, "expert.optout@example.com"), ref)
    with SessionLocal() as db:
        assert service.active(db, uid) is None
    me = client.get("/api/me/passport", headers=H(tok)).json()
    assert me["active"] is None and me["opted_out"] and me["eligible"]
    again = client.post("/api/me/passport/reissue", headers=H(tok)).json()["active"]
    assert again["passport"]["grade_status"] == "confirmed" and again["status"]["state"] == "valid"


def test_fix7_one_status_source_category_and_passport(client):
    """FIX7 п. 6 (проход модельных пользователей, выкладка 5): категория — «подтверждён», паспорт — «предварительный»
    без объяснения. Теперь статус паспорта и экран «Категория» — из одного источника (profiles.facts.passport_status):
    открытые ответы на проверке эксперта → в статусе грейда pending_review и passport_status «preliminary», плашка
    и паспорт говорят одно и то же, у паспорта — причина."""
    tok, _uid = _candidate_with_category(client, email="fix7.onesrc@example.com", pending_left=1, seed=13)
    gs = client.get("/api/assessment/status", headers=H(tok)).json()["grade_status"]
    assert gs["status"] == "confirmed" and gs["pending_review"] >= 1, gs
    assert gs["passport_status"] == "preliminary" and "на проверке эксперта" in gs["text"], gs
    me = client.get("/api/me/passport", headers=H(tok)).json()
    assert me["active"]["passport"]["grade_status"] == gs["passport_status"]
    assert "на проверке эксперта" in (me["preliminary_reason"] or ""), me.get("preliminary_reason")
    # без открытых ответов — оба «подтверждён», причины нет
    tok2, _ = _candidate_with_category(client, email="fix7.onesrc2@example.com", seed=14)
    gs2 = client.get("/api/assessment/status", headers=H(tok2)).json()["grade_status"]
    me2 = client.get("/api/me/passport", headers=H(tok2)).json()
    assert gs2["passport_status"] == "confirmed" == me2["active"]["passport"]["grade_status"]
    assert not gs2.get("pending_review") and me2["preliminary_reason"] is None


def test_fix7_skill_confirmed_title_names_real_source():
    """FIX7 п. 9 (P05): навык подтверждён заданием работодателя при тесте 0,4 из 1 — подпись не «подтверждён тестом»."""
    from types import SimpleNamespace as NS

    from app.modules.profiles.facts import skill_confirmed_title

    both_ok = NS(value={"score": 1.0, "parts": {"test": {"correct": 1, "total": 1}, "assignment": {"correct": 1, "total": 1}}}, source_ref="")
    task_only = NS(value={"score": 0.7, "parts": {"test": {"correct": 0.4, "total": 1}, "assignment": {"correct": 1, "total": 1}}}, source_ref="")
    test_only = NS(value={"score": 0.67, "correct": 2, "total": 3}, source_ref="test_session:1")
    assign = NS(value={"score": 1.0, "correct": 1, "total": 1}, source_ref="assignment:1")
    assert skill_confirmed_title(test_only) == "подтверждён тестом (T1)"
    assert skill_confirmed_title(both_ok) == "подтверждён тестом и заданием работодателя (T1)"
    assert skill_confirmed_title(task_only) == "подтверждён заданием работодателя (T1); в тесте — ниже 50 %"
    assert skill_confirmed_title(assign) == "подтверждён заданием работодателя (T1)"
