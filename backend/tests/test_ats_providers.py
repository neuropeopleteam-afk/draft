"""ATS-провайдеры: клиенты Talantix (GraphQL, OAuth-обновление токенов) и «Потока» (REST v3) на моках HTTP,
сверка запросов со схемами из документации (docs/ats/*), сквозной сценарий через демо-заглушки, журнал и повтор."""
from __future__ import annotations

import json
from pathlib import Path
import re
import uuid

from fastapi.testclient import TestClient
import httpx
import pytest

from app.integrations.ats import clients
from app.integrations.ats import profile as prof
from app.integrations.ats.clients import AtsError
from app.integrations.ats.providers import potok as pt
from app.integrations.ats.providers import talantix as tx
from app.integrations.ats.providers.base import LinkState, Target
from app.integrations.settings import get_isettings
from tests.test_day2_rules import INVITE, H, candidate_with_category, employer, my_ref

DOCS = Path(__file__).resolve().parents[2] / "docs" / "ats"


# ------------------------------------------------------------------ моки HTTP

class FakeHttp:
    """Подмена clients._send: очередь ответов по (метод, хвост пути) и журнал запросов."""

    def __init__(self, monkeypatch):
        self.calls: list[dict] = []
        self.routes: list[tuple[str, str, object]] = []
        monkeypatch.setattr(clients, "_send", self)

    def on(self, method: str, path_re: str, *responses):
        for r in responses:
            self.routes.append((method, path_re, r))
        return self

    def __call__(self, method, url, **kw):
        body = kw.get("json")
        call = {"method": method, "url": url, "headers": kw.get("headers") or {}, "json": body,
                "data": kw.get("data"), "params": kw.get("params")}
        if isinstance(body, dict) and "query" in body:
            call["root"] = tx_root(body["query"])
        self.calls.append(call)
        for i, (m, rx, resp) in enumerate(self.routes):
            if m != method or not re.search(rx, url):
                continue
            if resp[0] == "gql":  # GraphQL-ответ для конкретного корневого поля
                if resp[1] != call.get("root"):
                    continue
                resp = resp[2]
            self.routes.pop(i)
            status, payload = resp
            return httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)
        raise AssertionError(f"нет ответа для {method} {url} {call.get('root')}")

    def roots(self) -> list[str]:
        return [c["root"] for c in self.calls if c.get("root")]


def tx_root(query: str) -> str:
    return re.match(r"^\s*(?:query|mutation)\b[^{]*\{\s*(\w+)", query, re.S).group(1)


def gql(root: str, data, status: int = 200):
    return ("gql", root, (status, {"data": {root: data}, "errors": [], "dataPresent": True}))


@pytest.fixture
def http(monkeypatch):
    return FakeHttp(monkeypatch)


def tx_client(tokens=None, **kw):
    base = get_isettings().stub_base + "/api/ats-stub/talantix"  # адрес из allow-list check_url, без DNS
    return tx.TalantixClient(base, "acc-1", "ref-1", on_tokens=(tokens.append if tokens is not None else None), **kw)


DOC = {"candidate": {"ref": "C-7", "category_id": "backend.middle", "category_title": "Backend · Middle",
                     "contacts": {"full_name": "Сергеев Илья Андреевич", "email": "ilya@example.com",
                                  "phone": "+7 (900) 111-22-33", "telegram": "@ilya"},
                     "card": {"test": {"theta": 1.2, "se": 0.4, "correct": 6, "answered": 8, "date": "2026-10-01"},
                              "skills_confirmed": [{"title": "asyncio", "level": "T1"}],
                              "fsp": {"linked": True, "source": "registry",
                                      "achievements": [{"text": "Финалист ICPC 2025", "verified": True}]},
                              "stack_declared": [{"title": "Python"}], "city": "Москва", "work_format": "remote"}},
       "context": {"type": "invitation", "position_title": "Backend-разработчик (платежи)", "salary_from": 240000,
                   "salary_to": 270000, "evidence": [{"level": "T2", "text": "ICPC"}]},
       "links": {"pdf": "https://x/api/ats/profile/t.pdf", "card": "https://x/employer/candidates/C-7"},
       "source": {"url": "https://x", "platform": "Драфт (спецтрек ФСП)"}}


# ------------------------------------------------------------------ Talantix: токены и ошибки

def test_talantix_auth_check_refresh_on_401_and_persist(http):
    http.on("GET", r"/auth_check$", (401, {"type": "invalid_token", "detail": "token_expired"}), (204, None))
    http.on("POST", r"/oauth/token$", (200, {"access_token": "acc-2", "refresh_token": "ref-2", "expires_in": 86400,
                                             "refresh_token_expires_in": 10368000, "token_type": "bearer"}))
    saved = []
    cl = tx_client(saved)
    cl.auth_check()
    get1, post, get2 = http.calls
    assert get1["headers"]["Authorization"] == "Bearer acc-1" and get2["headers"]["Authorization"] == "Bearer acc-2"
    assert post["data"] == {"grant_type": "refresh_token", "refresh_token": "ref-1"}
    assert post["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert all(c["headers"]["User-Agent"].startswith("Draft-ATS/1.0 (") for c in http.calls)
    assert saved and saved[0]["access_token"] == "acc-2" and saved[0]["refresh_token"] == "ref-2"
    assert saved[0]["expires_at"] and cl.refreshed


def test_talantix_proactive_refresh_and_invalid_grant(http):
    from datetime import datetime, timedelta, timezone

    http.on("POST", r"/oauth/token$", (400, {"error": "invalid_grant"}))
    cl = tx_client([], expires_at=datetime.now(timezone.utc) + timedelta(seconds=10))
    with pytest.raises(AtsError) as e:
        cl.auth_check()  # access истекает через 10 с — обновляем заранее; refresh уже использован
    assert e.value.status == 401 and "выпустите новую пару" in str(e.value)
    assert [c["url"].rsplit("/", 1)[-1] for c in http.calls] == ["token"]


def test_talantix_http_and_graphql_errors(http):
    http.on("POST", r"/graphql$", (403, {"type": "api_access", "detail": "insufficient_permissions"}))
    with pytest.raises(AtsError) as e:
        tx_client().me()
    assert e.value.status == 403 and "Оптимальный" in str(e.value)
    http.on("POST", r"/graphql$", (210, {"data": None, "errors": [{"message": "boom", "extensions":
                                                                   {"errorType": "INTERNAL"}}], "dataPresent": False}))
    with pytest.raises(AtsError) as e:
        tx_client().me()
    assert e.value.status == 503  # повторяемая ошибка — журнал сделает ещё попытку
    http.on("POST", r"/graphql$", gql("createPerson", {"__typename": "PersonSaveError", "errorType": "VALIDATION",
                                                        "message": "bad", "errors": [{"field": "vacancyIds",
                                                                                      "violatedConstraints": ["AllowedValues"]}]}))
    with pytest.raises(AtsError) as e:
        tx_client().create_person({"firstName": "Илья"})
    assert e.value.status == 422 and "vacancyIds: AllowedValues" in str(e.value)


def test_parse_tokens_json_from_talantix_link():
    raw = json.dumps({"name": "x", "access_token": "A", "expires_in": 86400, "refresh_token": "R",
                      "refresh_token_expires_in": 10368000, "token_type": "bearer", "created_at": 1_760_000_000_000})
    t = tx.parse_tokens(raw)
    assert t["access_token"] == "A" and t["refresh_token"] == "R"
    assert t["expires_at"].timestamp() == 1_760_000_000 + 86400
    assert tx.parse_tokens("  A2 ", "R2") == {"access_token": "A2", "refresh_token": "R2", "expires_at": None,
                                              "refresh_expires_at": None}
    with pytest.raises(AtsError):
        tx.parse_tokens("{bad json")


# ------------------------------------------------------------------ Talantix: передача и идемпотентность

def test_talantix_push_creates_person_with_profile(http):
    http.on("POST", r"/graphql$", gql("persons", {"items": []}),
            gql("personSources", {"items": []}), gql("createPersonSource", {"__typename": "PersonSource", "id": 77}),
            gql("dictionaries", {"areas": {"items": [{"id": "1", "name": "Москва", "parentId": "113"}]}}),
            gql("createPerson", {"__typename": "PersonItem", "id": 5001}),
            gql("transferPersonsToWorkflowStatus", {"__typename": "PersonsToWorkflowStatusTransferredSuccess"}),
            gql("createPersonComment", {"__typename": "Comment", "id": 9}))
    tx._areas_cache.clear()
    saved, link = [], LinkState(saver=lambda ls: saved.append((ls.external_id, list(ls.vacancies))))
    res = tx.TalantixProvider(tx_client()).push(prof.build(DOC), Target(410101, "Backend", 4101012, "Интервью"), link)
    assert http.roots() == ["persons", "personSources", "createPersonSource", "dictionaries", "createPerson",
                            "transferPersonsToWorkflowStatus", "createPersonComment"]
    person = http.calls[4]["json"]["variables"]["person"]
    assert person["firstName"] == "Илья" and person["lastName"] == "Сергеев" and person["middleName"] == "Андреевич"
    assert person["vacancyIds"] == [410101] and person["sourceId"] == 77 and person["areaId"] == "1"
    assert {"type": "email", "value": "ilya@example.com"} in person["contacts"]
    assert {"type": "telegram", "value": "ilya"} in person["contacts"]
    assert person["customResumes"][0]["type"] == "TMS" and "ICPC" in person["customResumes"][0]["text"]
    sr = person["structuredResume"]
    assert sr["link"] == DOC["links"]["pdf"] and "asyncio" in sr["keySkills"] and "Backend" in sr["title"]
    comment = http.calls[6]["json"]["variables"]["comment"]
    assert comment["vacancyId"] == 410101 and "240" in comment["text"] and comment["commentVisibility"]["visibleForAll"]
    assert res["external_id"] == 5001 and res["dedup"] is None and saved[0][0] == "5001"
    assert link.external_id == "5001" and link.on_vacancy(410101)


def test_talantix_push_dedup_remote_and_link(http):
    # кандидат уже есть в базе Talantix (поиск по почте) → отклик на вакансию, без createPerson
    http.on("POST", r"/graphql$", gql("persons", {"items": [{"id": 42, "contacts": {"items": [
        {"type": "email", "value": "ILYA@example.com"}]}}]}),
        gql("createResponses", {"__typename": "ResponsesCreatedSuccess", "message": "ok"}),
        gql("createPersonComment", {"__typename": "Comment", "id": 1}))
    link = LinkState()
    res = tx.TalantixProvider(tx_client(), source_id=5).push(prof.build(DOC), Target(410101), link)
    assert http.roots() == ["persons", "createResponses", "createPersonComment"] and res["dedup"] == "remote"
    assert http.calls[1]["json"]["variables"] == {"personIds": [42], "vacancyIds": [410101]}
    # повтор с известной связью и той же вакансией — ни одного изменяющего запроса
    http.calls.clear()
    res = tx.TalantixProvider(tx_client()).push(prof.build(DOC), Target(410101), link)
    assert http.calls == [] and res["dedup"] == "link" and res["external_id"] == 42
    # другая вакансия — только createResponses
    http.on("POST", r"/graphql$", gql("createResponses", {"__typename": "ResponsesCreatedSuccess"}),
            gql("createPersonComment", {"__typename": "Comment", "id": 2}))
    tx.TalantixProvider(tx_client()).push(prof.build(DOC), Target(410102), link)
    assert http.roots() == ["createResponses", "createPersonComment"] and link.on_vacancy(410102)


# ------------------------------------------------------------------ сверка со схемой Talantix (документация)

def _sdl() -> tuple[dict, dict, dict]:
    text = (DOCS / "talantix-schema.subset.graphql").read_text()
    types, enums, unions = {}, {}, {}
    for kind, name, body in re.findall(r"^(type|input|enum)\s+(\w+)[^{\n]*\{(.*?)^\}", text, re.S | re.M):
        if kind == "enum":
            enums[name] = set(re.findall(r"^\s*([A-Z_a-z]\w*)\s*$", body, re.M))
            continue
        fields = {}
        for line in body.splitlines():
            m = re.match(r"\s*(\w+)\s*(\((.*)\))?\s*:\s*([\[\]\w!]+)", line)
            if m:
                args = dict(re.findall(r"(\w+)\s*:\s*([\[\]\w!]+)", m.group(3) or ""))
                fields[m.group(1)] = (re.sub(r"[\[\]!]", "", m.group(4)), args)
        types[name] = fields
    for name, members in re.findall(r"^union\s+(\w+)\s*=\s*(.+)$", text, re.M):
        unions[name] = {x.strip() for x in members.split("|")}
    return types, enums, unions


def _tokens(q: str) -> list[str]:
    return re.findall(r"\.\.\.|\$\w+|[A-Za-z_]\w*|[{}():!\[\],=]|\"[^\"]*\"", q)


def _check_selection(tok, i, tname, types, unions, used_vars):
    assert tok[i] == "{"
    i += 1
    while tok[i] != "}":
        if tok[i] == "...":
            assert tok[i + 1] == "on" and tok[i + 2] in unions.get(tname, {tname}) | {tname}, (tname, tok[i + 2])
            i = _check_selection(tok, i + 3, tok[i + 2], types, unions, used_vars)
            continue
        name = tok[i]
        i += 1
        if name == "__typename":
            continue
        assert name in types[tname], f"{tname}.{name} нет в схеме"
        ftype, fargs = types[tname][name]
        if tok[i] == "(":
            depth, j = 1, i + 1
            while depth:
                if tok[j] == "(":
                    depth += 1
                elif tok[j] == ")":
                    depth -= 1
                elif tok[j + 1:j + 2] == [":"] and depth == 1:
                    assert tok[j] in fargs, f"аргумент {tname}.{name}({tok[j]}) нет в схеме"
                    if tok[j + 2].startswith("$"):
                        used_vars[tok[j + 2]] = re.sub(r"[\[\]!]", "", fargs[tok[j]])
                j += 1
            i = j
        if tok[i] == "{":
            i = _check_selection(tok, i, ftype, types, unions, used_vars)
    return i + 1


def test_talantix_queries_match_documented_schema():
    types, enums, unions = _sdl()
    queries = [v for k, v in vars(tx).items() if re.match(r"^[QM]_", k)]
    assert len(queries) >= 10
    for q in queries:
        tok = _tokens(q)
        root = "Query" if tok[0] == "query" else "Mutation"
        declared = dict(re.findall(r"(\$\w+)\s*:\s*\[?(\w+)", q[: q.index("{")]))
        used: dict[str, str] = {}
        _check_selection(tok, tok.index("{"), root, types, unions, used)
        for var, typ in used.items():
            assert declared.get(var) == typ, (q[:40], var, declared.get(var), typ)


def _input_ok(value: dict, tname: str, types: dict, enums: dict) -> None:
    fields = types[tname]
    for k, v in value.items():
        assert k in fields, f"{tname}.{k} нет в схеме"
        ftype = fields[k][0]
        items = v if isinstance(v, list) else [v]
        for it in items:
            if ftype in types and isinstance(it, dict):
                _input_ok(it, ftype, types, enums)
            elif ftype in enums:
                assert it in enums[ftype], f"{ftype}: {it}"


def test_talantix_inputs_match_documented_schema():
    types, enums, _ = _sdl()
    d = prof.build(DOC)
    person = tx.person_input(d, vacancy_id=1, source_id=2, area_id="1")
    _input_ok(person, "PersonCreateInput", types, enums)
    assert {c["type"] for c in person["contacts"]} <= enums["ContactType"]
    _input_ok({"personId": 1, "text": "x", "vacancyId": 1, "commentVisibility": {"visibleForAll": True}},
              "PersonCommentCreateInput", types, enums)
    _input_ok({"search": "a@b.ru", "searchFrom": ["CONTACTS"]}, "PersonFilterInput", types, enums)
    _input_ok({"vacancyStatus": "ACTIVE"}, "VacancyFilterInput", types, enums)


# ------------------------------------------------------------------ «Поток»

def po_client():
    return pt.PotokClient(get_isettings().stub_base + "/api/ats-stub/potok/api/v3", "tok-1")


def _schema_ok(value, schema: dict, path: str = "") -> None:
    if schema.get("type") == "array":
        assert isinstance(value, list), f"{path}: в «Потоке» — список"
    elif schema.get("type") == "object":
        assert isinstance(value, dict), f"{path}: в «Потоке» — объект"
    if isinstance(value, list):
        for x in value:
            _schema_ok(x, schema.get("items") or {}, path + "[]")
        return
    if isinstance(value, dict) and schema.get("properties") is not None:
        for k, v in value.items():
            assert k in schema["properties"], f"{path}.{k} нет в спецификации «Потока»"
            _schema_ok(v, schema["properties"][k], f"{path}.{k}")


def test_potok_applicant_body_matches_openapi_and_push(http):
    spec = json.loads((DOCS / "potok-api-v3.subset.json").read_text())["paths"]
    body = pt.applicant_body(prof.build(DOC), vacancy_id=410101)
    _schema_ok({"applicant": body}, spec["/applicants.json"]["post"]["requestBody"])
    assert body["phones"] == ["79001112233"] and body["emails"] == ["ilya@example.com"]
    assert body["source_type"] == "sourced" and body["source_url"] == get_isettings().public_base_url
    # events — список: объект настоящий «Поток» отклоняет с 500 (проверено на API 07.10.2026)
    assert body["ajs_joins"] == [{"job_id": 410101}] and isinstance(body["events"], list)
    assert body["events"][0]["type"] == "Event::Comment" and body["events"][0]["body"]
    cv = body["resumes"][0]["cv_params"]
    assert cv["certificate"][0]["url"] == DOC["links"]["pdf"] and "asyncio" in cv["skill_set"]
    assert cv["awards"][0]["name"] == "Финалист ICPC 2025" and "T1" in cv["education"]["attestation"][0]["result"]
    assert "workflows" not in body  # согласие на обработку ПДн за кандидата не проставляем

    http.on("POST", r"/applicants\.json$", (200, {"id": 9001, "ajs_joins": [{"id": 77, "job": {"id": 410101},
                                                                             "stage": {"id": 4101011}}]}))
    http.on("POST", r"/ajs_joins/77/change_stage\.json$", (200, {"id": 77}))
    # название этапа для карточки приглашения («Передано: Поток · этап «Интервью»») — из вакансии, если его нет в цели (Ф4)
    http.on("GET", r"/jobs/410101\.json$", (200, {"id": 410101, "stages": [{"id": 4101011, "name": "Новые", "serial": 1},
                                                                          {"id": 4101013, "name": "Интервью", "serial": 3}]}))
    link = LinkState()
    res = pt.PotokProvider(po_client()).push(prof.build(DOC), Target(410101, stage_id=4101013), link)
    assert res["external_id"] == 9001 and res["join_id"] == 77 and link.on_vacancy(410101)["stage_id"] == 4101013
    assert res["stage_title"] == "Интервью"
    assert http.calls[0]["headers"]["Authorization"] == "Bearer tok-1"
    _schema_ok(http.calls[1]["json"], spec["/ajs_joins/{ajs_join_id}/change_stage.json"]["post"]["requestBody"])

    # повтор на другую вакансию: ajs_join; 422 «уже существует» — не ошибка; комментарий — events.json
    http.calls.clear()
    http.on("POST", r"/ajs_joins\.json$", (422, {"ajs_join": ["кандидат на вакансии уже существует"]}))
    res = pt.PotokProvider(po_client()).push(prof.build(DOC), Target(410102), link)
    assert [c["url"].rsplit("/", 1)[-1] for c in http.calls] == ["ajs_joins.json"] and res["dedup"] == "link"
    _schema_ok(http.calls[0]["json"], spec["/ajs_joins.json"]["post"]["requestBody"])
    http.calls.clear()
    http.on("POST", r"/events\.json$", (200, {"id": 1}))
    pt.PotokProvider(po_client()).push(prof.build(DOC), Target(410102), link, force=True)
    ev = http.calls[-1]["json"]
    _schema_ok(ev, spec["/events.json"]["post"]["requestBody"])
    assert ev["event"]["applicant_id"] == 9001 and ev["event"]["type"] == "Event::Comment"


def test_potok_errors(http):
    http.on("GET", r"/jobs\.json$", (402, {"errors": "subscription"}), (429, {}), (401, {}))
    for status in (402, 429, 401):
        with pytest.raises(AtsError) as e:
            po_client().jobs()
        assert e.value.status == status
    assert pt.applicant_body(prof.build({**DOC, "candidate": {**DOC["candidate"], "contacts": {}}}),
                             vacancy_id=None)["first_name"] == "Кандидат"


# ------------------------------------------------------------------ сквозной сценарий через демо-заглушки

@pytest.fixture
def ats_http(monkeypatch):
    from app.main import app

    inner = TestClient(app)
    base = get_isettings().stub_base

    def send(method, url, **kw):
        assert url.startswith(base), url
        kw.pop("timeout", None)
        return inner.request(method, url[len(base):], **kw)

    monkeypatch.setattr(clients, "_send", send)
    return inner


def _accepted(client):
    tc = candidate_with_category(client)
    te = employer(client)
    inv = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": my_ref(client, tc)},
                      headers=H(te)).json()
    return tc, te, inv


def test_demo_all_providers_on_accept_idempotent_and_pdf(client, ats_http):
    tc, te, inv = _accepted(client)
    prov = client.post("/api/employer/ats/demo/connect-all", headers=H(te)).json()
    assert {p["code"]: (p["enabled"], p["mode"]) for p in prov} == {
        "huntflow": (True, "demo"), "talantix": (True, "demo"), "potok": (True, "demo")}
    assert all("access_token" not in json.dumps(p) and "txa." not in json.dumps(p) for p in prov)
    for code in ("huntflow", "talantix", "potok"):
        chk = client.post(f"/api/employer/ats/providers/{code}/check", headers=H(te))
        assert chk.status_code == 200 and chk.json()["ok"], chk.text
    vac = client.get("/api/employer/ats/providers/talantix/vacancies", headers=H(te)).json()
    assert vac[0]["title"] == "Backend-разработчик (платежи)" and {v["status"] for v in vac} == {"active", "archive"}
    st = client.get(f"/api/employer/ats/providers/potok/vacancies/{vac[0]['id']}/stages", headers=H(te)).json()
    assert st[0]["title"] == "Новые" and len(st) == 5
    st = client.get(f"/api/employer/ats/providers/talantix/vacancies/{vac[0]['id']}/stages", headers=H(te)).json()
    assert st[2]["title"] == "Интервью"

    client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc))
    dl = client.get("/api/employer/ats/deliveries", headers=H(te)).json()
    assert {d["target"]: d["status"] for d in dl} == {"huntflow": "ok", "talantix": "ok", "potok": "ok",
                                                      "webhook": "ok"}, dl
    t = next(d for d in dl if d["target"] == "talantix")
    assert t["result"]["vacancy_id"] == 410101 and t["result"]["steps"] and t["target_title"] == "Talantix"
    recs = client.get("/api/employer/ats/stub/records", headers=H(te)).json()
    kinds = [r["kind"] for r in recs]
    assert "talantix_token" not in kinds and kinds.count("talantix_person") == 1 and kinds.count("potok_applicant") == 1
    person = next(r for r in recs if r["kind"] == "talantix_person")["payload"]
    assert person["lastName"] == "Петров" and person["vacancyIds"] == [410101]
    assert person["customResumes"][0]["type"] == "TMS"
    pa = next(r for r in recs if r["kind"] == "potok_applicant")["payload"]
    assert pa["phones"] == ["79001112233"] and pa["ajs_joins"][0]["job_id"] == 410101

    # PDF-профиль по подписанной ссылке из карточки в ATS открывается без входа, контакты раскрыты
    pdf_url = person["structuredResume"]["link"]
    base = get_isettings().public_base_url
    r = client.get(pdf_url[len(base):])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:4] == b"%PDF"
    assert client.get(pdf_url[len(base):].replace(".pdf", "x.pdf")).status_code == 404

    # повтор без force — «уже передано», с force — без дубликатов кандидатов
    again = client.post("/api/employer/ats/push", json={"invitation_id": inv["id"]}, headers=H(te)).json()
    assert len(again) == 4 and all(d.get("already_sent") for d in again)
    forced = client.post("/api/employer/ats/push", json={"invitation_id": inv["id"], "force": True}, headers=H(te)).json()
    assert {d["status"] for d in forced} == {"ok"}
    assert {d["target"]: d["result"].get("dedup") for d in forced if d["target"] != "webhook"} == {
        "huntflow": "link", "talantix": "link", "potok": "link"}
    kinds = [r["kind"] for r in client.get("/api/employer/ats/stub/records", headers=H(te)).json()]
    assert kinds.count("talantix_person") == 1 and kinds.count("potok_applicant") == 1
    assert kinds.count("huntflow_applicant") == 1 and kinds.count("talantix_comment") == 2
    # на другую вакансию в ATS — явный выбор, отклик createResponses к тому же кандидату
    other = client.post("/api/employer/ats/push", json={"invitation_id": inv["id"], "target": "talantix",
                                                        "ats_vacancy_id": 410102}, headers=H(te)).json()
    assert other[0]["status"] == "ok" and other[0]["result"]["vacancy_id"] == 410102
    assert "talantix_response" in [r["kind"] for r in client.get("/api/employer/ats/stub/records", headers=H(te)).json()]


def test_demo_talantix_token_refresh_and_retry_from_journal(client, ats_http):
    from app.core.db import SessionLocal
    from app.integrations.ats import providers, stub_providers
    from app.integrations.ats.models import AtsConnection, AtsSettings

    tc, te, inv = _accepted(client)
    client.post("/api/employer/ats/providers/talantix/demo", headers=H(te))
    p = client.post("/api/employer/ats/providers/potok/demo", headers=H(te)).json()
    assert p["enabled"] and p["vacancy_id"] == 410101
    with SessionLocal() as db:
        st = db.scalars(__import__("sqlalchemy").select(AtsSettings).where(AtsSettings.stub_key.is_not(None))).all()[-1]
        cid, key = st.company_id, st.stub_key
        conn = db.get(AtsConnection, (cid, "talantix"))
        old = providers.secrets_of(conn)
        stub_providers.talantix_expire_access(db, key)  # access «истёк» на стороне Talantix
        conn.token_expires_at = None  # клиент об этом не знает — сработает реактивное обновление по 401
        pc = db.get(AtsConnection, (cid, "potok"))
        providers.set_secrets(pc, {"token": "ptk.wrong"})  # сломанный токен «Потока» — ошибка в журнале
        db.commit()
    client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc))
    dl = {d["target"]: d for d in client.get("/api/employer/ats/deliveries", headers=H(te)).json()}
    assert dl["talantix"]["status"] == "ok" and dl["talantix"]["result"]["token_refreshed"]
    assert dl["potok"]["status"] == "error" and dl["potok"]["http_status"] == 401 and dl["potok"]["attempts"] == 1
    with SessionLocal() as db:
        conn = db.get(AtsConnection, (cid, "talantix"))
        new = providers.secrets_of(conn)
        assert new["refresh_token"] != old["refresh_token"] and conn.token_refreshed_at is not None
    # старый refresh-токен одноразовый — повторно не принимается
    r = ats_http.post("/api/ats-stub/talantix/oauth/token", data={"grant_type": "refresh_token",
                                                                   "refresh_token": old["refresh_token"]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    info = client.get("/api/employer/ats/providers", headers=H(te)).json()
    assert next(x for x in info if x["code"] == "talantix")["token_refreshed_at"]
    # починили токен «Потока» → «Повторить» из журнала: передано, кандидат один
    client.post("/api/employer/ats/providers/potok/demo", headers=H(te))
    rr = client.post(f"/api/employer/ats/deliveries/{dl['potok']['id']}/retry", headers=H(te))
    assert rr.status_code == 200 and rr.json()[0]["status"] == "ok" and rr.json()[0]["trigger"] == "retry"
    again = client.post(f"/api/employer/ats/deliveries/{dl['potok']['id']}/retry", headers=H(te)).json()
    assert again[0]["result"]["dedup"] == "link"
    kinds = [r["kind"] for r in client.get("/api/employer/ats/stub/records", headers=H(te)).json()]
    assert kinds.count("potok_applicant") == 1


def test_provider_settings_real_mode_tokens_encrypted(client):
    te = employer(client)
    r = client.put("/api/employer/ats/providers/talantix", json={"enabled": True, "mode": "real"}, headers=H(te))
    assert r.status_code == 422  # без токенов не включить
    tokens = json.dumps({"access_token": "real-access-123456", "refresh_token": "real-refresh-654321",
                         "expires_in": 86400, "refresh_token_expires_in": 10368000, "created_at": 1_760_000_000_000})
    r = client.put("/api/employer/ats/providers/talantix", json={"enabled": True, "mode": "real", "token": tokens,
                                                                 "vacancy_id": 55679, "vacancy_title": "Python"},
                   headers=H(te)).json()
    assert r["token_set"] and r["refresh_set"] and r["mode"] == "real" and r["base_url"] == "https://api.talantix.ru"
    assert "real-access-123456" not in json.dumps(r) and r["token_masked"].endswith("3456")
    assert r["refresh_expires_at"] and r["vacancy_id"] == 55679
    r = client.put("/api/employer/ats/providers/potok", json={"enabled": True, "mode": "real", "token": "potok-tok-1"},
                   headers=H(te)).json()
    assert r["base_url"] == "https://app.potok.io/api/v3" and r["token_set"]
    from app.core.db import SessionLocal
    from app.integrations.ats.models import AtsConnection

    with SessionLocal() as db:
        raw = [c.secrets_enc for c in db.query(AtsConnection).all()]
    assert raw and all("real-access" not in (x or "") and "potok-tok-1" not in (x or "") for x in raw)
    assert client.put("/api/employer/ats/providers/bitrix", json={}, headers=H(te)).status_code == 404
    bad = client.put("/api/employer/ats/providers/potok", json={"mode": "real", "base_url": "http://10.0.0.1/api"},
                     headers=H(te))
    assert bad.status_code == 422


def test_jury_company_has_demo_ats_and_acceptance_flows(client, ats_http):
    e = client.post("/api/jury/login", json={"persona": "employer"}).json()["access_token"]
    prov = {p["code"]: p for p in client.get("/api/employer/ats/providers", headers=H(e)).json()}
    assert all(p["enabled"] and p["mode"] == "demo" for p in prov.values())
    assert prov["talantix"]["vacancy_title"] == "Backend-разработчик (платежи)"
    c = client.post("/api/jury/login", json={"persona": "candidate_nofsp"}).json()["access_token"]
    inv = client.get("/api/candidate/invitations", headers=H(c)).json()
    inv = inv if isinstance(inv, list) else inv.get("items", [])
    pending = next(i for i in inv if i["status"] == "sent" or i.get("status") == "viewed")
    assert client.post(f"/api/candidate/invitations/{pending['id']}/accept", headers=H(c)).status_code == 200
    dl = client.get("/api/employer/ats/deliveries", headers=H(e)).json()
    assert {d["target"]: d["status"] for d in dl} == {"huntflow": "ok", "talantix": "ok", "potok": "ok",
                                                      "webhook": "ok"}, dl


def test_cli_import_env_masked_and_talantix_not_reimported(client, monkeypatch, capsys):
    from app.integrations.ats import cli

    employer(client, email="ats-cli@corp.ru", company="ООО Импорт")
    tokens = json.dumps({"access_token": "env-access-abcdef", "refresh_token": "env-refresh-123456",
                         "expires_in": 86400, "refresh_token_expires_in": 10368000})
    for k, v in {"TALANTIX_TOKENS_JSON": tokens, "TALANTIX_VACANCY_ID": "55679", "POTOK_TOKEN": "env-potok-777777",
                 "HUNTFLOW_TOKEN": "env-hf-888888", "HUNTFLOW_ACCOUNT_ID": "12"}.items():
        monkeypatch.setenv(k, v)
    get_isettings.cache_clear()
    try:
        cli.main(["import-env", "--employer-email", "ats-cli@corp.ru"])
        out = capsys.readouterr().out
        assert "Talantix" in out and "Поток" in out and "Хантфлоу" in out
        assert "env-access-abcdef" not in out and "env-potok-777777" not in out and "env-hf-888888" not in out
        cli.main(["import-env", "--employer-email", "ats-cli@corp.ru"])
        assert "пропущено" in capsys.readouterr().out  # refresh одноразовый — свежую пару из БД не затираем
        cli.main(["status", "--employer-email", "ats-cli@corp.ru"])
        out = capsys.readouterr().out
        assert "Talantix: включено, режим real" in out and "вакансия 55679" in out and "env-" not in out
    finally:
        get_isettings.cache_clear()


# ------------------------------------------------------------------ регрессия 07.10: реальный «Поток», автопередача, CLI

def _stub_key(client, te) -> str:
    from app.core.db import SessionLocal
    from app.integrations.ats.models import AtsSettings
    from app.modules.matching.router import my_company
    from app.modules.auth.models import User

    with SessionLocal() as db:
        u = db.query(User).filter(User.email == "hr@corp.ru").one()
        return db.get(AtsSettings, my_company(db, u).id).stub_key


def test_potok_stub_events_only_list_like_real_api(client, ats_http):
    """Настоящий «Поток» на events-объект отвечает 500 (проверено 07.10.2026) — заглушка ведёт себя так же."""
    te = employer(client)
    assert client.post("/api/employer/ats/providers/potok/demo", headers=H(te)).status_code == 200
    auth = {"Authorization": f"Bearer ptk.{_stub_key(client, te)}"}
    url = "/api/ats-stub/potok/api/v3/applicants.json"
    obj = {"applicant": {"first_name": "Илья", "last_name": "Петров",
                         "events": {"body": "Комментарий", "type": "Event::Comment"}}}
    assert ats_http.post(url, json=obj, headers=auth).status_code == 500
    ok = ats_http.post(url, json={"applicant": {**obj["applicant"], "events": [obj["applicant"]["events"]]}},
                       headers=auth)
    assert ok.status_code == 200, ok.text
    recs = client.get("/api/employer/ats/stub/records", headers=H(te)).json()
    assert [r["payload"]["body"] for r in recs if r["kind"] == "potok_event"] == ["Комментарий"]
    # и тело, которое строит провайдер, заглушка (как и настоящий API) принимает
    body = pt.applicant_body(prof.build(DOC), vacancy_id=410101)
    assert ats_http.post(url, json={"applicant": body}, headers=auth).status_code == 200


def _real_potok(company_id) -> None:
    from app.core.db import SessionLocal
    from app.integrations.ats.models import AtsConnection

    with SessionLocal() as db:  # как на стенде: «Поток» подключён токеном, строки ats_settings ещё нет
        db.add(AtsConnection(company_id=company_id, provider="potok", enabled=True, mode="real"))
        db.commit()


def _company_of(email: str):
    from app.core.db import SessionLocal
    from app.modules.auth.models import User
    from app.modules.matching.router import my_company

    with SessionLocal() as db:
        return my_company(db, db.query(User).filter(User.email == email).one()).id


def test_auto_push_on_accept_without_settings_row(client, monkeypatch):
    from app.core.db import SessionLocal
    from app.integrations.ats import service
    from app.integrations.ats.models import AtsSettings

    calls = []
    monkeypatch.setattr(service, "deliver", lambda db, cid, **kw: calls.append((cid, kw)) or [])
    monkeypatch.setattr(service, "deliver_bg", lambda cid, **kw: calls.append((cid, kw)))
    tc, te, inv = _accepted(client)
    cid = _company_of("hr@corp.ru")
    _real_potok(cid)
    with SessionLocal() as db:
        assert db.get(AtsSettings, cid) is None
    client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc))
    assert calls == [(cid, {"invitation_id": uuid.UUID(inv["id"]), "trigger": "invitation_accepted"})]
    with SessionLocal() as db:
        assert db.get(AtsSettings, cid).auto_push  # строка создана с автопередачей по умолчанию

    # отклик на вакансию, «Пригласить на интервью» — тот же путь (у новой компании строки настроек тоже нет)
    from tests.test_integrations import VAC

    te2 = employer(client, email="hr2@corp.ru", company="ООО Лютик")
    cid2 = _company_of("hr2@corp.ru")
    _real_potok(cid2)
    v = client.post("/api/employer/vacancies", json=VAC, headers=H(te2)).json()
    a = client.post(f"/api/vacancies/{v['id']}/apply", json={"consent_contacts": True}, headers=H(tc)).json()
    calls.clear()
    r = client.post(f"/api/employer/applications/{a['id']}/status", json={"status": "accepted"}, headers=H(te2))
    assert r.status_code == 200
    assert calls == [(cid2, {"application_id": uuid.UUID(a["id"]), "trigger": "application_accepted"})]


def test_ats_cli_runs_in_fresh_process(client):
    """python -m app.integrations.ats.cli в отдельном процессе: движок БД создаётся сам (было UnboundExecutionError)."""
    import os
    import subprocess
    import sys

    employer(client, email="ats-cli2@corp.ru", company="ООО Консоль")
    root = Path(__file__).resolve().parents[1]
    for mod, args in (("app.integrations.ats.cli", ["status", "--employer-email", "ats-cli2@corp.ru"]),):
        r = subprocess.run([sys.executable, "-m", mod, *args], cwd=root, capture_output=True, text=True, timeout=120,
                           env={**os.environ})
        assert r.returncode == 0, r.stderr[-2000:]
        assert "Поток" in r.stdout and "UnboundExecutionError" not in r.stderr
