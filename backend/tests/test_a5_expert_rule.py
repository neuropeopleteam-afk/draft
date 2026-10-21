"""Правило экспертов жюри (20.10.2026): категория и фильтр грейда — только по тесту, самооценка не подмешивается,
стек и условия — фильтры. Доказываем на трёх путях: поиск, подборка под потребность, «Принесите свой набор».
"""
import json
import re
from types import SimpleNamespace

import pytest

from app.modules.assessment import engine as em
from tests.conftest import register_and_verify
from tests.test_day2_rules import ONBOARDING, H, employer, pass_test


@pytest.fixture
def theta(monkeypatch):
    box = {"v": (0.5, 0.3)}
    monkeypatch.setattr(em, "eap_theta", lambda responses: box["v"])
    return box


def _onboard(client, email, **extra):
    t = register_and_verify(client, email=email)
    assert client.put("/api/me/onboarding", json={**ONBOARDING, **extra}, headers=H(t)).status_code == 200
    return t


def _ref(client, t):
    return client.get("/api/me", headers=H(t)).json()["candidate"]["public_ref"]


def _world(client, theta):
    """Подтверждённый Middle; два без теста — заявили Middle и Senior (иначе одинаковые); провал Middle-теста."""
    t_mid = _onboard(client, "rule-mid@example.com")
    theta["v"] = (0.5, 0.3)
    assert pass_test(client, t_mid, "middle")["confirmed"]
    t_cl_mid = _onboard(client, "rule-claim-mid@example.com")
    t_cl_sen = _onboard(client, "rule-claim-sen@example.com", experience_years=9)  # заявленный — Senior
    return {"mid": _ref(client, t_mid), "cl_mid": _ref(client, t_cl_mid), "cl_sen": _ref(client, t_cl_sen)}


def test_search_grade_filter_uses_only_tested_grade(client, theta):
    w = _world(client, theta)
    e = employer(client)
    for grade in ("middle", "senior"):
        r = client.get("/api/employer/candidates", params={"grade": grade}, headers=H(e)).json()
        refs = {c["ref"] for c in r["items"]}
        # заявившие Middle/Senior без теста в фильтр грейда не попадают — их грейд не проверен
        assert w["cl_mid"] not in refs and w["cl_sen"] not in refs and r["unconfirmed"] == 0
    assert w["mid"] in {c["ref"] for c in client.get("/api/employer/candidates", params={"grade": "middle"},
                                                     headers=H(e)).json()["items"]}
    # без фильтра грейда — видны (видео №6: показывать, не скрывать), строго ниже подтверждённых
    r = client.get("/api/employer/candidates", params={"direction": "backend"}, headers=H(e)).json()
    st = [c["status"]["status"] for c in r["items"]]
    assert st[0] == "confirmed" and st.count("unconfirmed") == 2 and st[-2:] == ["unconfirmed", "unconfirmed"]


def test_selection_claimed_grade_neither_filters_nor_scores(client, theta):
    w = _world(client, theta)
    e = employer(client)
    need = client.post("/api/employer/needs", json={
        "text": "Ищем бэкенд-разработчика middle: обязательно Python и PostgreSQL. Удалённо, 200–280 тыс."},
        headers=H(e)).json()
    v1 = client.get(f"/api/employer/needs/{need['id']}/selections/1", headers=H(e)).json()
    by_ref = {r["ref"]: r for r in v1["results"]}
    # заявивший Senior попадает в подборку Middle наравне с заявившим Middle — заявленный грейд не фильтрует
    assert w["cl_mid"] in by_ref and w["cl_sen"] in by_ref
    a, b = by_ref[w["cl_mid"]], by_ref[w["cl_sen"]]
    # и не даёт баллов: при одинаковых данных балл одинаков, тестовая часть — ноль
    assert a["score"] == b["score"] and a["components"]["test"] == 0 == b["components"]["test"]
    assert [r["grade_status"] for r in v1["results"]][0] == "confirmed"
    assert all(r["grade_status"] == "unconfirmed" for r in v1["results"][1:])


def test_legacy_flag_restores_claim_filter(client, theta, monkeypatch):
    w = _world(client, theta)
    e = employer(client)
    monkeypatch.setenv("MATCH_UNCONFIRMED_BY_CLAIM", "1")
    refs = {c["ref"] for c in client.get("/api/employer/candidates", params={"grade": "middle"},
                                         headers=H(e)).json()["items"]}
    assert w["cl_mid"] in refs and w["cl_sen"] not in refs


def test_score_ignores_self_description_and_claimed_grade():
    """T0 (самоописание: стек резюме, заявленный грейд) не меняет балл; подтверждённый тестом стек — меняет."""
    from app.modules.matching import ranking
    from app.modules.profiles.facts import Bundle

    req = {"direction": "backend", "grade": "middle", "stack_required": [{"tag": "python", "weight": 1.0}]}

    def b(claimed, t0_stack):
        p = SimpleNamespace(current_direction_id=None, current_grade_id=None, current_category_id=None,
                            grade_provisional=False, work_format=None, privacy={}, rating_score=None,
                            public_ref="K-T0", city=None, relocation=False, salary_min=None)
        x = Bundle(profile=p, survey=SimpleNamespace(direction_id="backend", claimed_grade_id=claimed))
        x.t0["stack"] = [SimpleNamespace(key=t, value={}) for t in t0_stack]
        return x

    s1, c1, _ = ranking.score_candidate(b("junior", []), req)
    s2, c2, _ = ranking.score_candidate(b("lead", ["python", "postgresql", "kafka", "kubernetes"]), req)
    assert s1 == s2 and c1["test"] == c2["test"] == 0


def test_bench_upload_rule_and_no_invented_numbers():
    from app.modules.matching import bench_upload as bu

    ds = {
        "needs": [{"id": "n1", "text": "Backend middle: обязательно Python и PostgreSQL. Удалённо.",
                   "direction": "backend", "grade": "middle"}],
        "candidates": [
            {"id": "c-test-mid", "direction": "backend", "grade": "middle", "theta": 0.6, "se": 0.3,
             "skills": [{"tag": "python", "correct": 4, "total": 5}]},
            {"id": "c-test-sen", "direction": "backend", "grade": "senior", "theta": 1.4, "se": 0.3,
             "skills": [{"tag": "python", "correct": 5, "total": 5}]},
            # «подтверждён» без θ и навыки без результата — не подтверждён; заявленный Senior не мешает отбору
            {"id": "c-claim-sen", "direction": "backend", "grade": "senior", "grade_status": "confirmed",
             "skills": ["python", "postgresql"]},
        ],
        "labels": [{"need_id": "n1", "candidate_id": "c-test-mid", "relevance": 3}],
    }
    out = bu.evaluate_uploaded_dataset(json.dumps(ds), "json", k=5)
    rows = out["per_need"][0]["results"]
    refs = [r["ref"] for r in rows]
    assert "c-test-sen" not in refs                     # проверенный грейд Senior ≠ Middle — не в категории
    assert refs[0] == "c-test-mid" and "c-claim-sen" in refs
    claim = next(r for r in rows if r["ref"] == "c-claim-sen")
    assert claim["grade_status"] == "unconfirmed" and claim["components"]["test"] == 0
    txt = json.dumps(out, ensure_ascii=False)
    assert not re.search(r"(?<!\d)8 из 10(?!\d)", txt) and "4 из 5 верно" not in txt
    assert any("без theta" in w for w in out["warnings"]) and any("без результата теста" in w for w in out["warnings"])
