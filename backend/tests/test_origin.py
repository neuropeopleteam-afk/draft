"""Я8 (п. 4): единые метки происхождения данных интеграций (ФСП, ФНС, ATS) и одна фраза о без-ФСП.

Подписи бэкенда (app/core/origin.py) и фронта (components/Origin.tsx) совпадают; метки приходят в API паспорта ФСП,
индекса доверия и провайдеров ATS; в зонах ФСП/ATS нет абсолютных фраз («никогда», «гарантирует»).
"""
from __future__ import annotations

from pathlib import Path
import re

from app.core.origin import NO_FSP, NO_FSP_SHORT, ORIGIN, ats_origin, fns_origin, fsp_origin
from tests.test_day2_rules import H, candidate_with_category, employer

ROOT = Path(__file__).resolve().parents[2]
FRONT = ROOT / "frontend" / "src"


def test_labels_same_on_backend_and_frontend():
    src = (FRONT / "components" / "Origin.tsx").read_text(encoding="utf-8")
    block = src.split("ORIGIN_LABEL", 1)[1].split("};", 1)[0]
    front = dict(re.findall(r'(\w+): "([^"]+)"', block))
    assert front == ORIGIN
    assert set(ORIGIN.values()) == {"модельные данные", "заглушка по спецификации", "реальный запрос", "не проверено"}
    assert f'NO_FSP = "{NO_FSP}"' in src
    assert NO_FSP.endswith(NO_FSP_SHORT) and "без штрафа" in NO_FSP and "бонус" in NO_FSP


def test_fns_origin_by_registry_status():
    assert fns_origin({"status": "demo_found"})["kind"] == "model"
    assert fns_origin({"status": "demo_not_found"})["kind"] == "model"
    for st in ("found", "not_found", "invalid"):
        o = fns_origin({"status": st, "checked_at": "2026-10-10T09:00:00+00:00"})
        assert o["kind"] == "real" and "egrul.nalog.ru" in o["note"] and "2026-10-10" in o["note"]
    for st in ("captcha", "error", "pending", "no_inn", None):
        assert fns_origin({"status": st} if st else None)["kind"] == "unverified"
    assert fns_origin({"status": "found"})["label"] == "реальный запрос"


def test_fsp_origin_by_link_source_and_registry_mode():
    assert fsp_origin(None) is None
    assert fsp_origin("demo")["kind"] == "model"
    assert fsp_origin("keycloak", {}, fsp_id_demo=True)["kind"] == "stub"
    assert fsp_origin("keycloak", {}, fsp_id_demo=False)["kind"] == "real"
    # синхронизация с реестром: мок — заглушка по спецификации, внешний API — реальный запрос
    assert fsp_origin("keycloak", {"registry": {"mode": "mock", "demo": True}}, fsp_id_demo=False)["kind"] == "stub"
    assert fsp_origin("registry", {"registry": {"mode": "external", "demo": False}})["kind"] == "real"
    assert fsp_origin("registry", {})["kind"] == "unverified"


def test_ats_origin_real_only_after_successful_check():
    assert ats_origin("demo", True)["kind"] == "stub"
    assert ats_origin("demo", False)["kind"] == "stub"
    assert ats_origin("real", False)["kind"] == "unverified"
    assert ats_origin("real", True, None)["kind"] == "unverified"
    assert ats_origin("real", True, False)["kind"] == "unverified"
    assert ats_origin("real", True, True)["kind"] == "real"


def test_origin_in_api_ats_trust_and_fsp(client):
    te = employer(client)
    client.post("/api/employer/ats/providers/potok/demo", headers=H(te))
    info = {p["code"]: p for p in client.get("/api/employer/ats/providers", headers=H(te)).json()}
    assert info["potok"]["origin"]["kind"] == "stub" and info["potok"]["origin"]["label"] == ORIGIN["stub"]
    assert all(p["origin"]["kind"] in ORIGIN for p in info.values())
    trust = client.get("/api/employer/company/trust", headers=H(te)).json()
    assert trust["origin"]["kind"] in ORIGIN
    if (trust.get("registry") or {}).get("status") == "no_inn":
        assert trust["origin"]["kind"] == "unverified"
    tc = candidate_with_category(client)
    p = client.get("/api/me/fsp", headers=H(tc)).json()
    assert not p["linked"] and p["origin"] is None and NO_FSP in p["note"]


def test_no_fsp_phrase_everywhere_and_no_absolutes_in_fsp_ats_zones():
    from app.modules.validation import criteria

    c52 = next(s for c in criteria.build()["criteria"] for s in c["items"] if "без истории ФСП" in s["tz"])
    assert NO_FSP in c52["see"]
    card = (FRONT / "components" / "CandidateCard.tsx").read_text(encoding="utf-8")
    assert "NO_FSP" in card and "OriginTag" in card and "нейтрально\"" not in card
    for doc in ("FSP_INTEGRATION.md", "ATS.md"):
        assert NO_FSP_SHORT in " ".join((ROOT / "docs" / doc).read_text(encoding="utf-8").split()), doc
    zones = [FRONT / "components" / "CandidateCard.tsx", FRONT / "integrations" / "Ats.tsx",
             FRONT / "integrations" / "Trust.tsx", FRONT / "integrations" / "FspId.tsx",
             FRONT / "pages" / "candidate" / "Settings.tsx", FRONT / "components" / "MatchingBench.tsx",
             ROOT / "docs" / "FSP_INTEGRATION.md", ROOT / "docs" / "ATS.md"]
    for f in zones:
        low = f.read_text(encoding="utf-8").lower()
        assert "никогда" not in low and "гарантир" not in low and "не тонут" not in low, f.name
