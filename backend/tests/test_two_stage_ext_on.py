"""Я26 + Я25: второй этап для Lead/Principal «предварительно» при включённом GRADES_EXT_ENABLED. Запускается из
tests/test_two_stage.py отдельным процессом с GRADES_EXT_ENABLED=1 (флаг читается при импорте seed_data); в обычном
прогоне без флага модуль пропускается. Банк Lead/Principal — подмена ``levels.bank_ext_families`` (как в
tests/test_grades_ext_on.py): backend — Lead и Principal, qa — только Lead.
"""
import uuid
from types import SimpleNamespace

import pytest

from app.modules.catalog import seed_data

pytestmark = pytest.mark.skipif(not seed_data.GRADES_EXT, reason="только с GRADES_EXT_ENABLED=1 (test_two_stage.py)")

from app.core.config import get_settings  # noqa: E402
from app.core.enums import TestSessionStatus  # noqa: E402
from app.modules.assessment import two_stage as ts  # noqa: E402
from app.modules.catalog import levels  # noqa: E402

FAKE_BANK = {"backend": {"lead": ("backend.lead.a", "backend.lead.b"), "principal": ("backend.principal.a",)},
             "qa": {"lead": ("qa.lead.a",)},
             "common": {"lead": ("common.lead.a", "common.lead.b"), "principal": ("common.principal.a", "common.principal.b")}}


@pytest.fixture(autouse=True)
def fake_bank(monkeypatch):
    monkeypatch.setattr(levels, "bank_ext_families", lambda: FAKE_BANK)
    levels._available.cache_clear()
    yield
    levels._available.cache_clear()


@pytest.fixture
def flag(monkeypatch):
    monkeypatch.setenv("ASSESSMENT_TWO_STAGE_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_ext_boundary_second_stage_for_preliminary_lead():
    order = levels.available_grades("backend")
    assert order[-2:] == ("lead", "principal")
    # Lead подтверждён уверенно (P(θ ≥ 2,0) ≈ 0,98): по правилу «на границе» уточнять нечего, но Lead «предварительно» —
    # второй этап у порога своего уровня (Senior/Lead)
    assert ts.boundary(2.6, 0.3, "lead", "lead", level=0.8, order=order) is None
    b = ts.boundary(2.6, 0.3, "lead", "lead", level=0.8, order=order, ext=True)
    assert b and b.kind == "ext" and b.cut_grade == "lead" and b.lower == "senior" and b.cut == 2.0
    assert ts.label(b.as_dict()) == "на границе Senior/Lead"
    # Principal — порог Lead/Principal
    b = ts.boundary(3.6, 0.3, "principal", "principal", level=0.8, order=order, ext=True)
    assert b and b.kind == "ext" and b.cut_grade == "principal" and b.lower == "lead"
    # у самого порога — обычная граница (keep), как у Junior–Senior
    b = ts.boundary(2.1, 0.3, "lead", "lead", level=0.8, order=order, ext=True)
    assert b and b.kind == "keep" and b.cut_grade == "lead"
    # Senior — не «предварительно»: ext не действует
    assert ts.boundary(1.6, 0.25, "senior", "senior", level=0.8, order=order, ext=True) is None
    # заявлен Lead, P(θ ≥ 2,0) ≈ 0,92, но одна сессия с погрешностью 0,63 Lead не присваивает (потолок) — итог Senior;
    # второй этап у порога Lead сужает погрешность
    b = ts.boundary(2.88, 0.63, "senior", "lead", level=0.8, order=order, ext=True)
    assert b and b.kind == "ext" and b.cut_grade == "lead" and b.grade == "senior"
    assert ts.boundary(2.88, 0.63, "senior", "lead", level=0.8, order=order, ext=False) is None
    assert ts.boundary(1.0, 0.5, "senior", "lead", level=0.8, order=order, ext=True) is None  # Lead маловероятен


def test_final_grade_capped_by_direction_scale():
    # Principal выше заявленного Lead — только с P ≥ c↑ и только там, где банк направления его проверяет
    assert ts.final_grade(3.6, 0.2, "lead", 0.45, 0.9, order=levels.available_grades("backend")) == "principal"
    assert ts.final_grade(3.6, 0.2, "lead", 0.45, 0.9, order=levels.available_grades("qa")) == "lead"
    assert ts.final_grade(2.05, 0.3, "lead", 0.45, 0.9, order=levels.available_grades("backend")) == "lead"
    assert ts.final_grade(1.7, 0.3, "lead", 0.45, 0.9, order=levels.available_grades("backend")) == "senior"


def test_offer_text_and_second_stage_flag(flag, monkeypatch):
    assert levels.preliminary_info("lead")["second_stage"]["available"] is True  # флаг двухэтапного включён
    sess = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4(), direction_id="backend", claimed_grade_id="lead",
                           status=TestSessionStatus.finished,
                           result={"engine": "bank", "mode": "full",
                                   "engine_result": {"theta": 2.6, "se": 0.3, "confirmed": True}})
    monkeypatch.setattr(ts, "_refines", lambda db, t: [])
    monkeypatch.setattr(ts, "latest_full", lambda db, uid, d: sess)
    off = ts.offer(None, sess)
    assert off and off["ext"] is True and off["available"] and off["status"] == "offered"
    assert off["boundary"]["kind"] == "ext" and off["boundary"]["cut_grade"] == "lead"
    assert off["text"].startswith("Lead по тесту — предварительно. Второй этап")
    assert "Senior/Lead" in off["text"] and "модель, не люди" in off["text"]
    # заявленный Lead срезан потолком одной сессии — тот же второй этап, свой текст
    capped = SimpleNamespace(**{**vars(sess), "result": {"engine": "bank", "mode": "full",
                                                         "engine_result": {"theta": 2.88, "se": 0.63, "confirmed": False}}})
    monkeypatch.setattr(ts, "latest_full", lambda db, uid, d: capped)
    off = ts.offer(None, capped)
    assert off and off["ext"] and off["boundary"]["grade"] == "senior" and off["boundary"]["cut_grade"] == "lead"
    assert off["text"].startswith("Lead по этому тесту вероятен, но не присвоен")
    # итог уточнения считается по шкале направления (qa — без Principal)
    st = {"claimed_grade": "lead", "direction": "qa",
          "refine": {"grade": "lead", "cut_grade": "lead", "lower": "senior", "cut": 2.0, "p": 0.98, "kind": "ext",
                     "confirm": 0.45, "confirm_up": 0.9}}
    r = ts.refine_result(st, 3.6, 0.2, 6)
    assert r["final_grade"] == "lead" and r["passed"] and r["label"] == "на границе Senior/Lead"
    # общая погрешность шире GRADES_EXT_MAX_SE (0,6) — Lead/Principal и после второго этапа не присваиваются
    r = ts.refine_result(st, 3.6, 0.65, 6)
    assert r["final_grade"] == "senior" and not r["passed"]
    r = ts.refine_result({**st, "direction": "backend"}, 1.7, 0.3, 6)
    assert r["final_grade"] == "senior" and not r["passed"]  # вариант А: итог по двум сессиям может быть ниже
    assert "Senior" in ts.explain(r)
