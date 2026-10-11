"""Я1 (09.10): ядро роли — основной язык / определяющий фреймворк или навык потребности.

Пункт 1: ядро из потребности правилами и словарём (без LLM), объяснимо; нет ядра — признак не действует.
Пункт 2: состояние у кандидата (подтверждено тестом / заявлено / отсутствует) и порядок — за флагом RANK_CORE_SKILL.
"""
from types import SimpleNamespace
import uuid

import pytest

from app.modules.matching import core_skill as C
from app.modules.matching.need_parser import parse_need
from app.modules.profiles.facts import Bundle


def _core(text: str):
    return C.role_core(parse_need(text, use_llm=False))


# ---------------------------------------------------------------- пункт 1: ядро из потребности
@pytest.mark.parametrize("text,kind,tags", [
    ("Senior Go-разработчик для маршрутизации: Go, PostgreSQL, Kafka, Docker. От 5 лет опыта.", "language", ["go"]),
    ("Ищем бэкенд-разработчика уровня middle: обязательно Python, FastAPI и PostgreSQL, опыт с Redis.", "language",
     ["python"]),
    ("Нужен senior Java-разработчик для платёжного ядра: Java, PostgreSQL, Kafka, gRPC обязательно.", "language",
     ["java"]),
    ("Senior Java или Kotlin разработчик, PostgreSQL, Kafka", "language", ["java", "kotlin"]),
    ("ML-инженер senior: PyTorch, компьютерное зрение (CV), MLOps, Python. Желательно Spark.", "specialization", ["cv"]),
    ("Senior frontend: TypeScript, React, state management, доступность (a11y), тестирование фронтенда.", "framework",
     ["react"]),
    ("Frontend-разработчик middle: React, TypeScript, HTML/CSS обязательно; Next.js будет плюсом.", "framework",
     ["react"]),  # Next.js — семейство React: одно ядро «React»
    ("Автоматизатор тестирования senior: Python, pytest, Selenium или Playwright, CI/CD.", "language", ["python"]),
])
def test_role_core_from_need(text, kind, tags):
    c = _core(text)
    assert c and c["kind"] == kind and c["tags"] == tags, c
    assert c["label"] == C.KIND_TITLE[kind]


@pytest.mark.parametrize("text", [
    "Data Scientist middle: Python, pandas, scikit-learn, статистика, SQL. Желательно Airflow и ClickHouse.",
    "Senior SOC-аналитик: SIEM/SOC, форензика, сетевая безопасность, Linux. Удалённо.",
    "QA-инженер middle: тест-дизайн, API-тестирование, pytest; желательно Playwright и Allure.",
    "Backend-разработчик senior для платёжного шлюза: обязательно PostgreSQL, Kafka и Linux.",
    "Junior frontend: JavaScript, HTML/CSS. Офис.",  # JS/HTML — основа направления, роль не различают
    "Стажёр frontend без опыта: HTML/CSS, JavaScript, основы Git; обучим React и TypeScript.",  # «обучим» — не ядро
])
def test_no_core_feature_off(text):
    assert _core(text) is None


def test_core_title_and_language_only_from_required():
    c = _core("Senior Java или Kotlin разработчик, PostgreSQL, Kafka")
    assert c["title"] == "Java или Kotlin"
    # язык только «плюсом» — не ядро
    assert _core("Backend middle: обязательно PostgreSQL и Kafka. Будет плюсом Go.") is None


# ---------------------------------------------------------------- пункт 2: состояние у кандидата
def _b(skills: dict | None = None, declared: tuple = (), grade_status: str = "confirmed") -> Bundle:
    uid = uuid.uuid4()
    b = Bundle(profile=SimpleNamespace(user_id=uid, public_ref=str(uid)[:8]))
    for t, s in (skills or {}).items():
        b.skills_t1[t] = SimpleNamespace(value={"score": s, "correct": s * 3, "total": 3})
    for t in declared:
        b.t0["stack"].append(SimpleNamespace(key=t))
    return b


GO = {"kind": "language", "tags": ["go"], "title": "Go", "label": C.KIND_TITLE["language"]}
PY = {"kind": "language", "tags": ["python"], "title": "Python", "label": C.KIND_TITLE["language"]}


def test_state_confirmed_declared_absent():
    assert C.state(_b({"go": 0.67}), GO)["state"] == "confirmed"
    assert C.state(_b({}, ("go", "postgresql")), GO)["state"] == "declared"
    low = C.state(_b({"go": 0.33}, ("go",)), GO)
    assert low["state"] == "declared" and low["tested_low"] == "go"
    assert C.state(_b({"java": 1.0, "postgresql": 1.0}, ("java", "postgresql")), GO)["state"] == "absent"
    tested_not_declared = C.state(_b({"go": 0.0}), GO)
    assert tested_not_declared["state"] == "absent" and tested_not_declared["tested_low"] == "go"


def test_state_implied_by_framework():
    st = C.state(_b({"fastapi": 1.0}), PY)
    assert st["state"] == "confirmed" and st["via"] == "fastapi" and st["implied"]
    assert C.state(_b({}, ("django",)), PY)["state"] == "declared"
    react = {"kind": "framework", "tags": ["react"], "title": "React", "label": C.KIND_TITLE["framework"]}
    assert C.state(_b({"nextjs": 0.5}), react)["state"] == "confirmed"


def test_assess_pool_texts_and_key(monkeypatch):
    req = parse_need("Senior Go-разработчик: Go, PostgreSQL, Kafka, Docker.", use_llm=False)
    a, d, x = _b({"go": 1.0}, ("go",)), _b({}, ("go",)), _b({"java": 1.0, "kafka": 1.0}, ("java", "kafka"))
    off = C.assess_pool([a, d, x], req, on=False)
    assert [off[b.profile.user_id]["key"] for b in (a, d, x)] == [0, 0, 0]  # флаг выкл. — порядок не меняется
    on = C.assess_pool([a, d, x], req, on=True)
    assert [on[b.profile.user_id]["key"] for b in (a, d, x)] == [0, 0, 1]
    assert on[x.profile.user_id]["headline"] == "Основной язык роли — Go: не заявлен"
    assert on[a.profile.user_id]["headline"] == "Основной язык роли — Go: подтверждён тестом"
    assert "ниже тех, у кого ядро роли заявлено или подтверждено" in on[x.profile.user_id]["text"]
    assert "ниже" not in off[x.profile.user_id]["text"]  # без флага не обещаем того, чего нет
    r = C.reason(on[x.profile.user_id])
    assert r["requirement"] == "Основной язык роли: Go" and r["status"] == "mismatch" and r["core"]
    monkeypatch.delenv(C.FLAG, raising=False)
    assert C.enabled()  # по умолчанию включён после замера (п. 7 карточки Я1)


def test_no_data_in_pool_feature_inactive():
    """«Нет данных» ≠ «не умеет»: ядро не заявлено ни у кого в пуле — признак не действует."""
    req = parse_need("Senior Go-разработчик: Go, PostgreSQL, Kafka, Docker.", use_llm=False)
    pool = [_b({"java": 1.0}, ("java",)), _b({"php": 1.0}, ("php",))]
    res = C.assess_pool(pool, req, on=True)
    assert all(v["key"] == 0 and not v["active"] for v in res.values())
    assert "ни у кого" in next(iter(res.values()))["text"]
    assert C.assess_pool(pool, parse_need("Data Scientist: pandas, SQL.", use_llm=False), on=True) == {}


def test_sort_key_policies_and_cap():
    # group: без ядра — ниже даже при меньшем ярусе обязательного и большем балле
    rows = [(0, 0, 0.9, 1), (0, 1, 0.5, 0)]  # (ярус грейда, ярус обязательного, балл, ядро отсутствует)
    assert sorted(rows, key=lambda r: C.sort_key(*r, policy="group")) == [rows[1], rows[0]]
    assert sorted(rows, key=lambda r: C.sort_key(*r, policy="within")) == [rows[0], rows[1]]
    # ярус статуса грейда старше признака
    rows2 = [(1, 0, 0.9, 0), (0, 0, 0.1, 1)]
    assert sorted(rows2, key=lambda r: C.sort_key(*r, policy="group"))[0] == rows2[1]
    # потолок места: без ядра не выше места cap + 1, пока кандидатов с ядром хватает
    absent = [True, False, True, False, False]
    assert C.cap_positions(absent, cap=2) == [1, 3, 0, 2, 4]
    assert C.cap_positions([True, True], cap=2) == [0, 1]


# ---------------------------------------------------------------- пункты 2–3: подборка, карточка, сравнение
GO_NEED = "Senior Go-разработчик для маршрутизации: Go, PostgreSQL, Kafka, Docker. Удалённо."


def _go_world(client):
    """Три кандидата Backend · Middle: у A Go подтверждён тестом, у B Go только заявлен, у C (сильнее всех по
    подтверждённому) Go нет вовсе — Java, PostgreSQL, Kafka, Docker."""
    from sqlalchemy import delete

    from app.core.db import SessionLocal
    from app.modules.profiles.facts import set_t0_facts
    from app.modules.profiles.models import CandidateFact, EvidenceLevel, FactSource
    from tests.test_day2_rules import H, candidate_with_category

    plan = {"a": ({"go": 0.67, "postgresql": 0.67}, ["go", "postgresql"]),
            "b": ({"postgresql": 1.0, "kafka": 1.0}, ["go", "postgresql", "kafka"]),
            "c": ({"java": 1.0, "postgresql": 1.0, "kafka": 1.0, "docker": 1.0}, ["java", "postgresql", "kafka", "docker"])}
    refs = {}
    for name, (skills, stack) in plan.items():
        t = candidate_with_category(client, email=f"core_{name}@example.com")
        me = client.get("/api/me", headers=H(t)).json()
        uid = uuid.UUID(me["id"])
        with SessionLocal() as db:
            db.execute(delete(CandidateFact).where(CandidateFact.user_id == uid, CandidateFact.kind == "skill"))
            set_t0_facts(db, uid, FactSource.self_report, stack=stack)
            set_t0_facts(db, uid, FactSource.resume, stack=[])
            for tag, sc in skills.items():
                db.add(CandidateFact(user_id=uid, kind="skill", key=tag, title=tag, evidence_level=EvidenceLevel.T1,
                                     source=FactSource.test, value={"direction": "backend", "score": sc,
                                                                    "correct": round(sc * 3), "total": 3}))
            db.commit()
        refs[name] = me["candidate"]["public_ref"]
    return refs


def _selection(text: str):
    from app.core.db import SessionLocal
    from app.modules.matching import ranking

    req = parse_need(text, use_llm=False)
    req["grade"] = "middle"  # кандидаты тестов — Backend · Middle
    with SessionLocal() as db:
        return ranking.build_selection(db, req, {"conditions_off": True})


def test_selection_flag_off_keeps_order_flag_on_moves_absent_core_down(client, monkeypatch):
    refs = _go_world(client)
    monkeypatch.setenv(C.FLAG, "0")
    off = _selection(GO_NEED)
    order_off = [r["ref"] for r in off["results"]]
    by = {r["ref"]: r for r in off["results"]}
    # предусловие: без признака Java-кандидат (Go нет вовсе) выше заявившего Go
    assert order_off.index(refs["c"]) < order_off.index(refs["b"]), order_off
    assert by[refs["c"]]["core"]["state"] == "absent" and by[refs["c"]]["core"]["key"] == 0
    assert off["core"] == {"label": "Основной язык роли", "title": "Go", "kind": "language", "on": False,
                           "policy": C.POLICY, "active": True, "counts": {"confirmed": 1, "declared": 1, "absent": 1}}
    monkeypatch.setenv(C.FLAG, "1")
    on = _selection(GO_NEED)
    order_on = [r["ref"] for r in on["results"]]
    assert order_on.index(refs["c"]) > order_on.index(refs["b"]) and order_on.index(refs["c"]) > order_on.index(refs["a"])
    assert len(order_on) == len(order_off)  # из выдачи никто не выпал
    rc = {r["ref"]: r for r in on["results"]}[refs["c"]]
    line = next(x for x in rc["reasons"] if x.get("core"))
    assert line["requirement"] == "Основной язык роли: Go" and line["status"] == "mismatch"
    assert "ниже тех, у кого ядро роли заявлено или подтверждено" in line["text"]
    assert rc["core"]["headline"] == "Основной язык роли — Go: не заявлен"
    assert {r["ref"]: r for r in on["results"]}[refs["a"]]["core"]["headline"].endswith("подтверждён тестом")
    from app.modules.matching import grade_above as GA  # Я12б: добор ступенью выше — match-v1.3 (здесь не действует)
    assert off["algorithm"] == "match-v1.1" + ("+above" if GA.enabled() else "")
    assert on["algorithm"] == (GA.ALGORITHM if GA.enabled() else "match-v1.2")
    assert not on["grade_above"]["applied"]
    monkeypatch.delenv(C.FLAG)
    assert C.enabled() and [r["ref"] for r in _selection(GO_NEED)["results"]] == order_on  # по умолчанию включён


def test_need_without_core_order_unchanged(client, monkeypatch):
    _go_world(client)
    text = "Backend-разработчик middle: обязательно PostgreSQL, Kafka и Docker."
    monkeypatch.setenv(C.FLAG, "0")
    off = _selection(text)
    monkeypatch.setenv(C.FLAG, "1")
    on = _selection(text)
    assert [r["ref"] for r in on["results"]] == [r["ref"] for r in off["results"]]
    assert on["core"] is None and all(r["core"] is None for r in on["results"])


def test_card_and_compare_show_core(client, monkeypatch):
    from tests.test_day2_rules import H, employer

    monkeypatch.setenv(C.FLAG, "1")
    refs = _go_world(client)
    te = employer(client)
    n = client.post("/api/employer/needs", json={"text": GO_NEED.replace("Senior", "Middle")}, headers=H(te))
    assert n.status_code == 201, n.text
    need = n.json()
    card = client.get(f"/api/employer/candidates/{refs['c']}", params={"need_id": need["id"]}, headers=H(te)).json()
    assert card["match"]["core"]["headline"] == "Основной язык роли — Go: не заявлен"
    assert any(x.get("core") for x in card["match"]["reasons"])
    cmp = client.get(f"/api/employer/needs/{need['id']}/compare", params={"refs": [refs["a"], refs["c"]]},
                     headers=H(te)).json()
    row = next(r for r in cmp["rows"] if r["key"] == "core")
    assert row["group"] == "Ядро роли" and row["requirement"] == "Go"
    cells = {c["ref"]: c["cells"]["core"] for c in cmp["candidates"]}
    assert cells[refs["a"]]["text"] == "Подтверждён тестом" and cells[refs["a"]]["level"] == "T1"
    assert cells[refs["c"]]["text"] == "Не заявлен — смежное направление" and cells[refs["c"]]["state"] == "absent"
    notes = [w.get("core_note") for w in cmp["why"] if w.get("core_note")]
    assert notes and "у " in notes[0] and "не заявлен" in notes[0]
