def test_catalog_has_20_categories(client):
    r = client.get("/api/catalog")
    assert r.status_code == 200
    data = r.json()
    assert {d["id"] for d in data["directions"]} == {"backend", "frontend", "data_ml", "qa", "security"}
    assert [g["id"] for g in data["grades"]] == ["intern", "junior", "middle", "senior"]
    assert len(data["categories"]) == 20
    for c in data["categories"]:
        assert 0 < c["market_salary_from"] <= c["market_salary_to"]
    interns = {c["id"]: c for c in data["categories"] if c["grade_id"] == "intern"}
    assert set(interns) == {f"{d}.intern" for d in ("backend", "frontend", "data_ml", "qa", "security")}
    juniors = {c["direction_id"]: c for c in data["categories"] if c["grade_id"] == "junior"}
    for cid, c in interns.items():
        assert c["title"].endswith("· Стажёр")
        assert "Intern" in (c["market_source"] or "") and c["market_as_of"] == "2026-10-05"
        # оплата стажировки ниже рынка Junior того же направления
        assert c["market_salary_median"] < juniors[c["direction_id"]]["market_salary_median"]
    common = {t["id"] for t in data["stack_tags"] if t["direction_id"] is None}
    assert {"algorithms", "sql", "http", "git", "linux"} <= common
    assert len(data["fsp_disciplines"]) == 5


def test_stack_tags_filter_includes_common_block(client):
    tags = client.get("/api/catalog/stack-tags", params={"direction": "frontend"}).json()
    dirs = {t["direction_id"] for t in tags}
    assert dirs == {None, "frontend"}
    assert any(t["id"] == "react" for t in tags)
