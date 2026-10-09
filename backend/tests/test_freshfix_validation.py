"""Ф6 (Н7, Н8): подписи /validation и длина теста — из данных (банк, отчёт), без «сейчас» без даты."""
from app.modules.assessment.bank_engine import bank_manifest
from app.modules.validation.provenance import length_info, provenance


def test_provenance_from_bank_and_report():
    m = bank_manifest()
    rep = {"generated_at": "2026-10-06T08:33:00+00:00", "n_per_direction": 400,
           "bank": {"n_families": 128, "content_hash": "old", "commit": "b324325", "synced_at": "2026-10-05T12:35:05+00:00"},
           "calibration": {"status": "ready", "panel": "panel_x", "n_families": 10}}
    p = provenance(rep)
    assert p["bank_now"]["n_families"] == m.get("n_families")  # число семейств — из банка, не из текста
    assert p["report"]["bank_n_families"] == 128 and p["report"]["same_bank"] is (m.get("content_hash") == "old")
    cal = p["calibration"]
    assert cal["source"] == "model_panel" and cal["humans"] is False and cal["used_in_decision"] is False
    assert cal["n_families"] == 10 and cal["of_families"] == m.get("n_families")


def test_length_info_and_route(client):
    assert length_info({"missing": True}) == {"missing": True}
    d = client.get("/api/validation/test-length").json()
    assert d["min_items"] == 8 and d["max_items"] == 16 and d["ext_items"] == 6
    assert 0 < d["sim_extension_share"] <= 1 and d["sim_mean_items"] > d["max_items"]  # в модели дотестирование частое
    assert "не замер на людях" in d["world"]
    r = client.get("/api/validation/report").json()
    assert r["provenance"]["calibration"]["humans"] is False and r["provenance"]["report"]["generated_at"] == r["generated_at"]
