"""Я12б: hh.ru сильнее — снимок рынка в индексе доверия (n ≥ 10, регион), «Что сейчас просит рынок», замер подбора
на вакансиях hh.ru и спрос (/api/validation/hh-match), данные в репозитории — только агрегаты."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.integrations.egrul import trust
from app.modules.hh import directions, market_skills, snapshot

DATA = Path(snapshot.__file__).resolve().parent / "data"
ROOT = Path(__file__).resolve().parents[2]

SNAP = {"as_of": "2026-10-10T18:00:00+00:00", "areas": {"113": "Россия", "1": "Москва", "88": "Казань"}, "basis": "net",
        "categories": {
            "backend.middle": {"113": {"n": 80, "median": 200_000, "p25": 160_000, "p75": 250_000, "by": "name"},
                               "1": {"n": 40, "median": 250_000, "p25": 200_000, "p75": 300_000, "by": "name"},
                               "88": {"n": 6, "median": 150_000, "p25": 140_000, "p75": 170_000, "by": "experience"}},
            "qa.intern": {"113": {"n": 7, "median": 50_000, "p25": 40_000, "p75": 60_000, "by": "experience"}}}}
SKILLS = {"as_of": "2026-10-10", "min_n_category": 10, "method": "тест",
          "directions": {"backend": {"n": 48, "top": [{"tag": "python", "title": "Python", "share": 0.6, "n": 29},
                                                      {"tag": "postgresql", "title": "PostgreSQL", "share": 0.5, "n": 24},
                                                      {"tag": "docker", "title": "Docker", "share": 0.4, "n": 19},
                                                      {"tag": "kafka", "title": "Kafka", "share": 0.2, "n": 10}]}},
          "categories": {"backend.middle": {"n": 12, "top": [{"tag": "go", "title": "Go", "share": 0.5, "n": 6}]},
                         "backend.senior": {"n": 4, "top": [{"tag": "java", "title": "Java", "share": 0.5, "n": 2}]}}}


@pytest.fixture
def hh_snap(monkeypatch):
    monkeypatch.setenv("HH_ENABLED", "true")
    get_settings.cache_clear()
    data = {"market_snapshot.json": SNAP, "skills.json": SKILLS, "demand.json": {"as_of": "2026-10-10", "directions": {}}}
    monkeypatch.setattr(snapshot, "_load", lambda name: data.get(name))
    yield
    get_settings.cache_clear()


# ------------------------------------------------------------------ запросы hh.ru по направлениям
def test_directions_cover_catalog_and_four_new():
    from app.modules.catalog.seed_data import DIRECTIONS

    assert set(DIRECTIONS) <= set(directions.HH_DIRECTIONS)
    assert set(directions.NEW_DIRECTIONS) == {"devops", "data_eng", "mobile", "analyst"}
    t = directions.search_text("backend", "middle")
    assert t.startswith("NAME:(backend OR") and "AND NAME:(middle OR мидл)" in t and " NOT NAME:(frontend" in t
    assert directions.search_text("devops") is None  # роль 160 узкая сама
    p = dict(directions.search_params("analyst", None, "113", with_salary=True))
    assert p["only_with_salary"] == "true" and p["area"] == "113"
    assert [v for k, v in directions.search_params("analyst", None, "113") if k == "professional_role"] == ["148", "150"]
    assert '"react native"' in directions.search_text("mobile")


def test_market_role_query_extended_for_new_directions_only():
    from app.modules.hh.market import ROLE_QUERY

    assert ROLE_QUERY["backend"][0] == ["96"] and ROLE_QUERY["qa"] == (["124"], None)  # прежние — как в Я12
    assert ROLE_QUERY["devops"] == (["160"], None) and "android" in ROLE_QUERY["mobile"][1]


# ------------------------------------------------------------------ снимок рынка и вилка
def test_snapshot_region_and_fallback(hh_snap):
    m = snapshot.market_for("backend.middle", "Москва")
    assert m["area_name"] == "Москва" and m["n"] == 40 and m["conclusive"] and m["fallback"] is None
    k = snapshot.market_for("backend.middle", "г. Казань")
    assert k["area_name"] == "Россия" and k["fallback"] == {"area": "Казань", "n": 6} and k["conclusive"]
    assert snapshot.market_for("backend.middle", "Москва", remote=True)["area_name"] == "Россия"
    assert snapshot.market_for("backend.middle", "Тула")["area_name"] == "Россия"
    assert snapshot.market_for("frontend.senior") is None


def test_salary_vs_hh_statuses(hh_snap):
    ok = snapshot.salary_vs_hh(180_000, 220_000, "net", "backend.middle")
    assert ok["status"] == "ok" and ok["position"] == "inside" and "n = 80" in ok["text"] and "10.10.2026" in ok["text"]
    bait = snapshot.salary_vs_hh(300_000, 600_000, "net", "backend.middle")
    assert bait["status"] == "warn" and bait["position"] == "above" and "приманк" in bait["text"]
    low = snapshot.salary_vs_hh(60_000, 90_000, "net", "backend.middle")
    assert low["status"] == "warn" and low["position"] == "below"
    msk = snapshot.salary_vs_hh(300_000, 600_000, "net", "backend.middle", "Москва")
    assert msk["status"] == "ok" and msk["area"] == "Москва"  # в Москве рынок выше — не приманка
    few = snapshot.salary_vs_hh(10_000, 900_000, "net", "qa.intern")
    assert few["status"] == "unknown" and not few["conclusive"] and "мало данных" in few["text"] and "n = 7" in few["text"]


def test_trust_salary_check_market_flag_off_is_unchanged(monkeypatch):
    monkeypatch.delenv("HH_ENABLED", raising=False)
    get_settings.cache_clear()
    cat = SimpleNamespace(id="backend.middle", title="Backend · Middle", market_salary_from=150_000, market_salary_to=250_000)
    for args in ((180_000, 220_000), (300_000, 900_000), (20_000, 40_000)):
        st, txt, hh = trust.salary_check_market(*args, cat, "net")
        assert (st, txt) == trust.salary_check(*args, cat, "net") and hh is None


def test_trust_salary_check_market_uses_hh_when_enough_data(hh_snap):
    cat = SimpleNamespace(id="backend.middle", title="Backend · Middle", market_salary_from=150_000, market_salary_to=250_000)
    # по Хабру верх 520 000 > 2 × 250 000 — «приманка»; по рынку Москвы hh.ru (p75 300 000) — в пределах
    assert trust.salary_check(260_000, 520_000, cat, "net")[0] == "warn"
    st, txt, hh = trust.salary_check_market(260_000, 520_000, cat, "net", city="Москва")
    assert st == "ok" and hh["conclusive"] and "hh.ru" in txt and "Москва" in txt
    qa = SimpleNamespace(id="qa.intern", title="QA · Стажёр", market_salary_from=40_000, market_salary_to=60_000)
    st, txt, hh = trust.salary_check_market(45_000, 55_000, qa, "net")
    assert st == "ok" and not hh["conclusive"] and "мало данных" in txt and "без вывода" in txt  # вывод — по Хабру


# ------------------------------------------------------------------ «Что сейчас просит рынок»
def _bundle(t1: dict[str, float], t0: set[str]):
    return SimpleNamespace(skills_t1={t: SimpleNamespace(value={"score": s}) for t, s in t1.items()}, stack_t0=t0)


def test_market_skills_off_without_flag(monkeypatch):
    monkeypatch.delenv("HH_ENABLED", raising=False)
    get_settings.cache_clear()
    assert market_skills.block("backend", "middle", _bundle({}, set()), frozenset()) is None


def test_market_skills_statuses_and_actions(hh_snap, monkeypatch):
    monkeypatch.setattr(market_skills, "_task_tags", lambda d, g, tags: {"docker"})
    b = _bundle({"python": 0.8, "postgresql": 0.3}, {"kafka"})
    m = market_skills.block("backend", "junior", b, frozenset({"python", "postgresql"}))
    assert m["scope"] == "direction" and m["n"] == 48 and m["source"] == "hh.ru"
    by = {x["tag"]: x for x in m["items"]}
    assert by["python"]["status"] == "confirmed" and by["python"]["action"] is None
    assert by["postgresql"]["status"] == "weak" and by["postgresql"]["action"]["href"] == "/candidate/assessment"
    assert by["docker"]["status"] == "missing" and by["docker"]["action"]["href"] == "/candidate/assignments"
    assert by["kafka"]["status"] == "declared" and by["kafka"]["action"]["href"] is None
    assert m["not_confirmed"] == 3 and "10.10.2026" in m["note"]
    # категория с n ≥ 10 — свои навыки; n < 10 — направление
    assert market_skills.block("backend", "middle", b, frozenset())["scope"] == "category"
    assert market_skills.block("backend", "senior", b, frozenset())["scope"] == "direction"
    assert market_skills.block("frontend", "middle", b, frozenset()) is None


# ------------------------------------------------------------------ /validation/hh-match и данные в репозитории
def test_validation_hh_match_endpoint(client):
    r = client.get("/api/validation/hh-match")
    assert r.status_code == 200
    d = r.json()
    assert d.get("missing") or (d["n"] >= 300 and "модельные" in d["label_note"])
    if not d.get("missing"):
        assert set(d["directions"]) >= {"devops", "data_eng", "mobile", "analyst"}


def _walk(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)


@pytest.mark.parametrize("path", ["backend/app/modules/hh/data/market_snapshot.json", "backend/app/modules/hh/data/skills.json",
                                  "backend/app/modules/hh/data/demand.json", "docs/realdata/hh_match_corpus.json",
                                  "backend/app/modules/validation/data/hh_match.json"])
def test_repo_data_has_no_vacancy_texts(path):
    p = ROOT / path
    if not p.exists():
        pytest.skip("снимок ещё не собран")
    d = json.loads(p.read_text(encoding="utf-8"))
    keys = set(_walk(d))
    assert not keys & {"description", "snippet", "requirement", "responsibility", "employer", "contacts", "text"}
    assert len(p.read_text(encoding="utf-8")) < 600_000
