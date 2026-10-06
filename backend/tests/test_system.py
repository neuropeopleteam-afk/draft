def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "ok", "db": "ok"}  # без режима разработки, почты и версии (аудит, Н5)


def test_openapi_docs_available(client):
    assert client.get("/api/docs").status_code == 200
    spec = client.get("/api/openapi.json").json()
    paths = spec["paths"]
    for p in ["/api/auth/register", "/api/auth/verify-email", "/api/auth/login", "/api/me", "/api/catalog"]:
        assert p in paths
    # коды ошибок задокументированы
    assert "409" in paths["/api/auth/register"]["post"]["responses"]
