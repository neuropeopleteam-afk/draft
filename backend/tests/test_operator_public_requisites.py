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
    assert o["short_name"] == "ООО «НЕЙРОПИПЛ»"
    assert (o["inn"], o["kpp"], o["ogrn"]) == ("9701316954", "770101001", "1257700372820")
    assert "вн. тер. г. муниципальный округ Басманный" in o["legal_address"]
    assert o["legal_address"].startswith("105082, г. Москва") and o["legal_address"].endswith("помещ. 3А/1/14")
    assert o["email"] == "legal@neuropeople.shop" and o["email_general"] == "info@neuropeople.shop"


def test_no_director_and_actual_address_anywhere(client):
    assert not any(k in legal.OPERATOR for k in HIDDEN_KEYS)
    meta = client.get("/api/meta").json()["operator"]
    assert not any(k in meta for k in HIDDEN_KEYS) and meta["email"] == "legal@neuropeople.shop"
    for kind in ("processing", "publication"):
        c = client.get(f"/api/legal/consents/{kind}").json()
        assert not any(k in c["operator"] for k in HIDDEN_KEYS), kind
        assert c["version"] == legal.CONSENT_VERSION
    # ни ФИО руководителя, ни фактический адрес не попадают в ответы целиком (проверка по ключам и по тексту)
    blob = json.dumps([meta, client.get("/api/legal/consents/processing").json()], ensure_ascii=False)
    assert "Пресненская" not in blob and "офис 445" not in blob


def test_consent_texts_carry_site_requisites(client):
    proc = client.get("/api/legal/consents/processing").json()["text"]
    assert "муниципальный округ Басманный" in proc and "legal@neuropeople.shop" in proc
    assert "ИНН 9701316954" in proc and "ОГРН 1257700372820" in proc and "info@neuropeople.shop" not in proc
    cam = proctor.consent_text()["operator"]
    assert cam == ("Общество с ограниченной ответственностью «НЕЙРОПИПЛ» (ООО «НЕЙРОПИПЛ»), ИНН 9701316954, "
                   "адрес для обращений: legal@neuropeople.shop")
    assert proctor.CONSENT_VERSION == legal.CONSENT_VERSION  # обе редакции пересмотрены 10.10 вместе
