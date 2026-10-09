"""И23 п. 2: релевантность дисциплины ФСП специализации — мягкий коэффициент за флагом FSP_DISCIPLINE_RELEVANCE."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.modules.catalog.constants import FSP_DISCIPLINES
from app.modules.catalog.seed_data import DIRECTIONS
from app.modules.fsp import relevance
from app.modules.fsp.rating import POLICY, details
from app.modules.profiles.facts import fsp_strength
from tests.test_day2_rules import H, employer
from tests.test_employer_matching import NEED, _seeded_need

TODAY = date(2026, 10, 9)


def ach(discipline: str, place: int | None = 1, name: str = "Кубок", **extra):
    return SimpleNamespace(verified=True, event_name=name, event_date=TODAY, place=place, discipline=discipline,
                           event_level="national", result_title="победитель" if place == 1 else "", **extra)


def test_disciplines_equal_and_soft():
    # каждая дисциплина ФСП описана и где-то «близко»: ни одна не лучше другой сама по себе
    assert {d["id"] for d in FSP_DISCIPLINES} == set(relevance.AFFINITY)
    assert relevance.every_discipline_is_close_somewhere()
    for disc in relevance.AFFINITY:
        for direction in DIRECTIONS:
            assert relevance.coef(disc, direction) in (relevance.CLOSE, relevance.NEAR, relevance.FAR)
    # пример организаторов (E08): ИБ-специалист с соревнованиями по ИБ релевантнее, чем с робототехникой
    assert relevance.coef("security", "security") == 1.0 > relevance.coef("robotics", "security")
    # примеры карточки И23: продуктовое — к Backend/Frontend, БАС — к Data/ML (embedded/robotics в MVP нет)
    assert relevance.coef("product", "backend") == relevance.coef("product", "frontend") == 1.0
    assert relevance.coef("uav", "data_ml") == 1.0
    # неизвестная дисциплина/направление — без штрафа и без подписи «близко»
    assert relevance.coef("chess", "backend") == relevance.coef("security", None) == 1.0
    assert relevance.explain("security", None) == {"coef": 1.0, "title": ""}
    assert relevance.explain("security", "security") == {"coef": 1.0, "title": "близко к специализации"}
    assert relevance.explain("robotics", "security")["title"] == "дальше от специализации"


def test_details_flag_off_is_byte_identical():
    rows = [ach("security"), ach("robotics", 2, "Чемпионат"), ach("product", 7, "Онлайн-отбор")]
    base = details(rows, today=TODAY)
    assert details(rows, today=TODAY, direction="backend", relevance=False) == base
    assert "relevance" not in base and base["policy"] == POLICY


@pytest.mark.parametrize("direction", list(DIRECTIONS))
def test_details_flag_on_bounded(direction):
    rows = [ach("security"), ach("robotics", 2, "Чемпионат"), ach("uav", None, "Онлайн-отбор")]
    off = details(rows, today=TODAY)["strength"]
    on = details(rows, today=TODAY, direction=direction, relevance=True)
    assert 0.8 * off - 1e-3 <= on["strength"] <= off + 1e-9
    assert on["relevance"]["enabled"] and on["relevance"]["direction"] == direction
    assert on["policy"].startswith(POLICY) and "смежной — 0,9" in on["policy"]


def test_close_discipline_beats_far_one_with_flag():
    sec, rob = [ach("security")], [ach("robotics")]
    assert details(sec, today=TODAY)["strength"] == details(rob, today=TODAY)["strength"]  # без флага равны
    s_sec = details(sec, today=TODAY, direction="security", relevance=True)
    s_rob = details(rob, today=TODAY, direction="security", relevance=True)
    assert s_sec["strength"] > s_rob["strength"]
    assert s_sec["relevance"]["best"] == {"discipline": "security", "coef": 1.0, "title": "близко к специализации"}
    # для Data/ML робототехника, наоборот, близко — дисциплины равны, важна только пара
    assert details(rob, today=TODAY, direction="data_ml", relevance=True)["strength"] == s_sec["strength"]


def test_fsp_strength_reads_flag(monkeypatch):
    rows = [ach("robotics")]
    assert fsp_strength(rows, "security") == 0.8
    monkeypatch.setattr(get_settings(), "fsp_discipline_relevance", True)
    assert fsp_strength(rows, "security") == pytest.approx(0.8 * 0.8, abs=1e-3)
    assert fsp_strength(rows, "data_ml") == 0.8


def _selection(client, te, seed=False):
    if seed:
        need = _seeded_need(client, te, NEED)
    else:
        n = client.post("/api/employer/needs", json={"text": NEED}, headers=H(te))
        assert n.status_code == 201, n.text
        need = n.json()
    r = client.get(f"/api/employer/needs/{need['id']}/selections/1", headers=H(te))
    assert r.status_code == 200, r.text
    return r.json()["results"]


def _fsp_reasons(results):
    return [x["text"] for r in results for x in r["reasons"] if x["requirement"] == "Достижения ФСП"
            and x["status"] == "confirmed"]


def test_selection_and_card_flag_off_then_on(client, monkeypatch):
    te = employer(client)
    off = _selection(client, te, seed=True)
    assert _fsp_reasons(off), "в демо-мире должны быть подтверждённые достижения ФСП"
    assert not any("коэффициент" in t for t in _fsp_reasons(off))
    assert not any("relevance" in a for r in off for a in (r["card"].get("fsp") or {}).get("achievements") or [])

    monkeypatch.setattr(get_settings(), "fsp_discipline_relevance", True)
    on = _selection(client, te)
    texts = _fsp_reasons(on)
    assert any("Соревнования по «" in t and "специализации кандидата (коэффициент" in t for t in texts), texts[:3]
    cards = [a for r in on for a in (r["card"].get("fsp") or {}).get("achievements") or []]
    assert cards and all("relevance" in a and 0.8 <= a["relevance"]["coef"] <= 1.0 for a in cards)
    # сила ФСП с флагом не растёт ни у кого (коэффициент ≤ 1), скор подбора меняется не больше чем на 0,10 × 0,2
    by_ref = {r["ref"]: r for r in off}
    for r in on:
        if r["ref"] in by_ref:
            assert r["components"]["fsp"] <= by_ref[r["ref"]]["components"]["fsp"] + 1e-9
            assert abs(r["score"] - by_ref[r["ref"]]["score"]) <= 0.02 + 1e-6
