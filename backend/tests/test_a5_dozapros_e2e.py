"""Дозапрос (вторая ступень подборки) — сквозь, как у пользователя (условие А15 для строки «с дозапросом»):
потребность → подборка → короткие задания (mode=probe) кандидату → ответы → факты T1 → новая подборка через API.

Проверяем: (1) кандидат, решивший задания по обязательным навыкам, получает в новой подборке больше баллов и строку
«почему» про задание работодателя; (2) кандидат, задания не решивший, не поднимается; (3) самоописание не трогалось.
"""
from __future__ import annotations

import pytest

from tests.test_assignments import facts_of, make_need, solve
from tests.test_day2_rules import H, candidate_with_category, employer, my_ref


@pytest.fixture(autouse=True)
def _v2(monkeypatch):
    monkeypatch.setenv("MATCH_V2", "1")


def _selection(client, te, need_id: str, version: int) -> dict:
    r = client.post(f"/api/employer/needs/{need_id}/selections", json={"parent_version": version, "filters": {}},
                    headers=H(te))
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_dozapros_end_to_end_raises_only_who_solved(client):
    te = employer(client)
    need = make_need(client, te)
    ta = candidate_with_category(client, "solve@example.com")
    tb = candidate_with_category(client, "fail@example.com")
    ra, rb = my_ref(client, ta), my_ref(client, tb)

    before = {x["ref"]: x for x in _selection(client, te, need["id"], 1)["results"]}
    assert ra in before and rb in before

    r = client.post("/api/employer/assignments", json={"need_id": need["id"], "mode": "probe", "candidate_refs": [ra, rb],
                                                       "salary_from": 230000, "salary_to": 300000}, headers=H(te))
    assert r.status_code == 201, r.text
    assert r.json()["sent"] == 2

    def attempt(t):
        items = client.get("/api/candidate/assignments", headers=H(t)).json()["items"]
        assert len(items) == 1 and items[0]["source"] == "probe"
        return items[0]["attempt_id"]

    res_a = solve(client, ta, attempt(ta), 5)  # всё верно
    res_b = solve(client, tb, attempt(tb), 0)  # всё неверно
    assert res_a["correct"] == res_a["total"] == 5 and res_b["correct"] == 0
    assert {k for k, _, _ in facts_of("solve@example.com")} == {"skill", "probe"}

    after = {x["ref"]: x for x in _selection(client, te, need["id"], 2)["results"]}
    assert after[ra]["score"] > before[ra]["score"], (before[ra]["score"], after[ra]["score"])
    assert after[rb]["score"] <= before[rb]["score"], (before[rb]["score"], after[rb]["score"])
    assert after[ra]["rank"] < after[rb]["rank"]
    texts = " ".join(x["text"] for x in after[ra]["reasons"])
    assert "заданием работодателя" in texts, texts
    print("\nДОЗАПРОС: решил", ra, before[ra]["score"], "→", after[ra]["score"], f"(место {before[ra]['rank']} → {after[ra]['rank']});",
          "не решил", rb, before[rb]["score"], "→", after[rb]["score"], f"(место {before[rb]['rank']} → {after[rb]['rank']})")
