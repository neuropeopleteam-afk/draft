"""Реквизиты оператора ПД — как на сайте компании (подвал и политика обработки ПД, 10.10, решение владельца): юридический
адрес в полной редакции, e-mail по вопросам ПД — legal@, общий — info@ (как в подвале); фактического адреса и ФИО
руководителя в коде и ответах API нет (на сайте они не опубликованы)."""
from __future__ import annotations

import json

from app.core import legal
from app.modules.proctor import service as proctor

HIDDEN_KEYS = ("director", "actual_address")


def test_operator_matches_company_site():
    o = legal.OPERATOR
    assert o["short_name"] == "команда Neuropeople"
    assert (o["inn"], o["kpp"], o["ogrn"]) == ("<реквизит>", "770101001", "<реквизит>")
    assert "вн. тер. г. муниципальный округ Басманный" in o["legal_address"]
    assert o["legal_address"].startswith("105082, г. Москва") and o["legal_address"].endswith("помещ. 3А/1/14")
    assert o["email"] == "<форма обратной связи>" and o["email_general"] == "<форма обратной связи>"


def test_no_director_and_actual_address_anywhere(client):
    assert not any(k in legal.OPERATOR for k in HIDDEN_KEYS)
    meta = client.get("/api/meta").json()["operator"]
    assert not any(k in meta for k in HIDDEN_KEYS) and meta["email"] == "<форма обратной связи>"
    for kind in ("processing", "publication"):
        c = client.get(f"/api/legal/consents/{kind}").json()
        assert not any(k in c["operator"] for k in HIDDEN_KEYS), kind
        assert c["version"] == legal.CONSENT_VERSION
    # ни ФИО руководителя, ни фактический адрес не попадают в ответы целиком (проверка по ключам и по тексту)
    blob = json.dumps([meta, client.get("/api/legal/consents/processing").json()], ensure_ascii=False)
    assert "Пресненская" not in blob and "офис 445" not in blob


def test_consent_texts_carry_site_requisites(client):
    proc = client.get("/api/legal/consents/processing").json()["text"]
    assert "муниципальный округ Басманный" in proc and "<форма обратной связи>" in proc
    assert "ИНН <реквизит>" in proc and "ОГРН <реквизит>" in proc and "<форма обратной связи>" not in proc
    cam = proctor.consent_text()["operator"]
    assert cam == ("команда Neuropeople (команда Neuropeople), ИНН <реквизит>, "
                   "адрес для обращений: <форма обратной связи>")
    assert proctor.CONSENT_VERSION == legal.CONSENT_VERSION  # обе редакции пересмотрены 10.10 вместе
