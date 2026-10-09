"""Я8: происхождение каждого числа /validation и /criteria — из JSON расчёта, не текстом страницы.

- у каждого числа первого экрана — вид данных (синтетика / модель / люди), дата, SHA алгоритма, банк, команда;
- снимки разных банков разделены: «текущий» (банк в продукте) и «исторический» (с датой);
- рядом с κ повтора — точность к синтетической истине, завышение, занижение, «без категории» из того же JSON.
"""
from __future__ import annotations

import json

from app.modules.assessment.bank_engine import bank_manifest
from app.modules.validation import provenance as PV
from app.modules.validation.headline import headline, retest_vs_truth


def _json(src: str) -> dict:
    return json.loads((PV.DATA / PV.SOURCES[src]["file"]).read_text(encoding="utf-8"))


def test_every_source_has_kind_date_commit_bank_command():
    m = bank_manifest()
    for src in PV.SOURCES:
        p = PV.stamp(src)
        assert p["kind"] in PV.KINDS and p["kind_label"] == PV.KINDS[p["kind"]], src
        assert p["command"] and p["date"], src
        assert p["snapshot"] in {"current", "historical", "no_bank", "bank_unknown"}, src
        if p["bank"]:
            assert p["bank_current"] is (p["bank"] == m["content_hash"]), src
            assert p["snapshot"] == ("current" if p["bank_current"] else "historical"), src
    # отчёт make validate подписи не пишет: коммит честно «не записан», банк — из отчёта, дата — отчёта
    r, rep = PV.stamp("report"), _json("report")
    assert r["commit"] is None and r["bank"] == rep["bank"]["content_hash"] and r["date"] == rep["generated_at"]
    assert r["bank_families"] == rep["bank"]["n_families"]
    assert PV.stamp("demo")["kind"] == "rules"  # демо-500: метки правилами, не синтетика со скрытой истиной
    assert PV.stamp("grader")["kind"] == "model"  # оценщик сверяется с моделью-эталоном, не с людьми


def test_signature_sources_take_commit_and_bank_from_signature():
    for src in ("path", "bench", "attempts", "stability"):
        sig = _json(src)["signature"]
        p = PV.stamp(src)
        assert p["commit"] == sig["commit"] and p["bank"] == sig["bank"] and p["date"] == sig["generated_at"], src
        assert p["command"] == sig["command"], src


def test_historical_snapshot_is_marked(tmp_path, monkeypatch):
    """Расчёт на прошлом банке — «исторический»; на банке в продукте — «текущий»; нет файла — «не посчитано»."""
    m = bank_manifest()
    old = {"signature": {"generated_at": "2026-10-01T00:00:00+00:00", "commit": "abc1234", "bank": "0" * 16,
                         "command": "make path-retest"}}
    assert PV.stamp("path", old)["snapshot"] == "historical"
    now = {"signature": {**old["signature"], "bank": m["content_hash"]}}
    p = PV.stamp("path", now)
    assert p["snapshot"] == "current" and p["bank_families"] == m["n_families"]
    monkeypatch.setitem(PV.SOURCES, "path", {**PV.SOURCES["path"], "file": "nope.json"})
    assert PV.stamp("path")["snapshot"] == "missing"
    unk = {"generated_at": "2026-10-01T00:00:00", "seed": 1}
    assert PV.stamp("intern", unk)["snapshot"] == "bank_unknown" and PV.stamp("intern", unk)["commit"] is None


def test_headline_numbers_carry_provenance():
    h = headline()
    assert h["items"]
    for it in h["items"]:
        p = it["provenance"]
        assert p["kind"] == "synthetic" and p["kind_label"] == "синтетика"
        assert p["commit"] == it["signature"]["commit"] and p["command"] == it["signature"]["command"]
        assert p["bank"] == it["signature"].get("bank") and p["date"] == it["signature"]["generated_at"]
    assert "строка происхождения" in h["how_to_read"] and "модельная панель (не люди)" in h["how_to_read"]


def test_retest_vs_truth_from_saved_json():
    pr = _json("path")
    v = retest_vs_truth(pr)
    tr, pg, ps = pr["total"]["truth"], pr["total"]["path_grade"], pr["total"]["path"]
    assert (v["exact"], v["over"], v["under"], v["no_category"]) == (tr["exact"], tr["over_share"], tr["under_share"],
                                                                       tr["no_category_share"])
    assert v["kappa_w"] == pg["kappa_w"] and v["retest_exact"] == pg["exact"]
    assert v["extension_share"] == ps["extension_share"] and v["accepted_lower"] == ps["status_share"]["accepted_lower"]
    f = lambda x: f"{100 * x:.1f}".replace(".", ",") + "\u00a0%"  # noqa: E731
    assert "повторяемость, а не точность" in v["lead"] and f(tr["exact"]) in v["lead"]
    for x in (tr["over_share"], tr["under_share"], tr["no_category_share"], ps["extension_share"]):
        assert f(x) in v["cost"]
    assert "P ≥ 0,8" in v["cost"] and "дотестирование" in v["cost"] and "вторая попытка" in v["cost"]
    assert retest_vs_truth({**pr, "quick": True}) is None and retest_vs_truth(None) is None
    assert headline()["retest_vs_truth"] == v
    assert "с синтетической истиной" in headline()["items"][0]["note"]


def test_routes_expose_provenance(client):
    d = client.get("/api/validation/provenance").json()
    assert [s["src"] for s in d["sources"]] == list(PV.SOURCES)
    assert d["bank_now"]["content_hash"] == bank_manifest()["content_hash"] and d["code_commit"]
    hist = [s["src"] for s in d["sources"] if s["snapshot"] == "historical"]
    assert d["one_snapshot"] is (not hist and all(s["snapshot"] in ("current", "no_bank") for s in d["sources"]))
    r = client.get("/api/validation/report").json()["provenance"]
    assert r["stamp"]["src"] == "report" and r["demo"]["kind"] == "rules" and r["experts"]["src"] == "experts"
    pr = client.get("/api/validation/path-retest").json()
    assert pr["provenance"]["src"] == "path" and pr["vs_truth"]["exact"] == pr["total"]["truth"]["exact"]
    assert client.get("/api/validation/matching-bench").json()["provenance"]["src"] == "bench"
    assert client.get("/api/validation/junior-stability").json()["provenance"]["src"] == "stability"


def test_experts_stamp_kind_follows_panel():
    assert PV.experts_stamp({"model_panel": True, "source": {"kind": "model", "title": "модель X в трёх ролях"},
                             "panel": [{"last_seen_at": "2026-10-08T10:00:00"}]})["kind"] == "model"
    assert PV.experts_stamp({"model_panel": False, "source": {"kind": "people", "title": "люди"}})["kind"] == "people"
    assert PV.experts_stamp(None)["snapshot"] == "missing" and PV.experts_stamp(None)["date"] is None


def test_experts_heading_names_model_panel_and_role(client):
    """Я8 п. 2: «Модельная панель (Claude Fable 5.1 в трёх ролях) — не люди» — в заголовке; модель разметки ≠ модель продукта."""
    from app.core.db import SessionLocal
    from app.modules.demo.seed import _user
    from app.modules.experts import pack as P
    from app.modules.experts import section as SEC
    from app.modules.experts.models import ExpertPanelist
    from app.modules.experts.service import panel_status, set_source, source_summary
    from app.core.enums import UserRole

    assert "не межэкспертная надёжность людей" in SEC.MODEL_CAVEAT and SEC.MODEL_CAVEAT.startswith("согласие завышено")
    with SessionLocal() as db:
        have = {p.code for p in db.query(ExpertPanelist).all()}
        for code in ("E1", "E2", "E3"):
            if code not in have:
                u = _user(db, f"{code.lower()}@expert.example.com", UserRole.expert, code)
                db.add(ExpertPanelist(code=code, slot=code, user_id=u.id, pack=P.PACK, assignment={}))
        db.commit()
        set_source(db, ["E1", "E2", "E3"], "model", "Claude Fable 5.1", ["тимлид Backend", "Data/ML", "QA/ИБ"])
        s = source_summary(panel_status(db))
        assert s["heading"] == "Модельная панель (Claude Fable 5.1 в трёх ролях) — не люди"
        assert "модель, выполнявшая разметку по экспертному протоколу" in s["role_note"]
        assert "Claude Sonnet 5.5 через OpenRouter" in s["role_note"] and "YandexGPT" in s["role_note"]
        assert "вторая оценка спорных" in s["role_note"]  # Fable 5.1 в продукте есть — без противоречия
    ex = client.get("/api/validation/report").json()
    assert ex["experts"]["source"]["heading"].endswith("— не люди") and ex["provenance"]["experts"]["kind"] == "model"
    with SessionLocal() as db:
        set_source(db, ["E1", "E2", "E3"], "people")
        s = source_summary(panel_status(db))
        assert s["heading"] == "Экспертная разметка людьми" and s["role_note"] is None


def test_test_retest_doc_has_same_phrase():
    """Я8 п. 3: docs/validation/TEST_RETEST.md — из генератора, та же фраза «повтор ≠ точность», что на /validation."""
    from app.modules.validation import path_retest as P

    rep = json.loads(P.OUT.read_text(encoding="utf-8"))
    md = P.DOCS_MD.read_text(encoding="utf-8")
    assert md == P.markdown(rep)
    v = retest_vs_truth(rep)
    assert v["lead"] in md and v["cost"] in md
