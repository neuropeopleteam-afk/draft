def test_catalog_has_15_categories(client):
    r = client.get("/api/catalog")
    assert r.status_code == 200
    data = r.json()
    assert {d["id"] for d in data["directions"]} == {"backend", "frontend", "data_ml", "qa", "security"}
    assert [g["id"] for g in data["grades"]] == ["junior", "middle", "senior"]
    assert len(data["categories"]) == 15
    for c in data["categories"]:
        assert 0 < c["market_salary_from"] <= c["market_salary_to"]
    common = {t["id"] for t in data["stack_tags"] if t["direction_id"] is None}
    assert {"algorithms", "sql", "http", "git", "linux"} <= common
    assert len(data["fsp_disciplines"]) == 5


def test_stack_tags_filter_includes_common_block(client):
    tags = client.get("/api/catalog/stack-tags", params={"direction": "frontend"}).json()
    dirs = {t["direction_id"] for t in tags}
    assert dirs == {None, "frontend"}
    assert any(t["id"] == "react" for t in tags)
