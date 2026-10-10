"""Реквизиты оператора ПД — как на сайте компании (подвал и политика обработки ПД, 10.10, решение владельца): юридический
адрес в полной редакции, e-mail info@ (общий и для обращений по ПД); фактического адреса и ФИО руководителя в коде и
ответах API нет (на сайте они не опубликованы)."""
from __future__ import annotations

from app.core import legal
from app.modules.proctor import service as proctor

HIDDEN_KEYS = ("director", "actual_address")
EXPECTED_FIELDS = {"full_name", "short_name", "inn", "kpp", "ogrn", "legal_address", "email", "storage"}


def test_operator_matches_company_site():
    o = legal.OPERATOR
    assert o["short_name"] == "ООО «НЕЙРОПИПЛ»"
    assert (o["inn"], o["kpp"], o["ogrn"]) == ("9701316954", "770101001", "1257700372820")
    assert "вн. тер. г. муниципальный округ Басманный" in o["legal_address"]
    assert o["legal_address"].startswith("105082, г. Москва") and o["legal_address"].endswith("помещ. 3А/1/14")
    assert o["email"] == "info@neuropeople.shop" and "email_general" not in o


def test_no_director_and_actual_address_anywhere(client):
    assert not any(k in legal.OPERATOR for k in HIDDEN_KEYS)
    meta = client.get("/api/meta").json()["operator"]
    assert not any(k in meta for k in HIDDEN_KEYS) and meta["email"] == "info@neuropeople.shop"
    for kind in ("processing", "publication"):
        c = client.get(f"/api/legal/consents/{kind}").json()
        assert not any(k in c["operator"] for k in HIDDEN_KEYS), kind
        assert c["version"] == legal.CONSENT_VERSION
    # в ответах — только перечень полей реквизитов с сайта компании, ничего сверх него
    assert set(meta) == EXPECTED_FIELDS and set(legal.OPERATOR) == EXPECTED_FIELDS
    for kind in ("processing", "publication"):
        assert set(client.get(f"/api/legal/consents/{kind}").json()["operator"]) == EXPECTED_FIELDS


def test_consent_texts_carry_site_requisites(client):
    proc = client.get("/api/legal/consents/processing").json()["text"]
    assert "муниципальный округ Басманный" in proc and "info@neuropeople.shop" in proc
    assert "ИНН 9701316954" in proc and "ОГРН 1257700372820" in proc
    cam = proctor.consent_text()["operator"]
    assert cam == ("Общество с ограниченной ответственностью «НЕЙРОПИПЛ» (ООО «НЕЙРОПИПЛ»), ИНН 9701316954, "
                   "адрес для обращений: info@neuropeople.shop")
    assert proctor.CONSENT_VERSION == legal.CONSENT_VERSION  # обе редакции пересмотрены 10.10 вместе
