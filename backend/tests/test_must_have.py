"""Ф2 (08.10): «сначала покрывающие обязательное» и условия потребности по умолчанию.

Ярусы подборки по числу непокрытых обязательных (0, 1, ≥ 2), внутри — прежний балл; бонусы ФСП и зонда не переносят
через ярус; навык, не подтверждённый ни у кого, ярус не меняет. Формат и город потребности применяются к подборке
сразу: «удалёнка или офис в Москве» = {удалённо} ∪ {офис/гибрид, Москва}; «показать всех» — один клик.
"""
import uuid

import pytest
from sqlalchemy import delete

from app.core.db import SessionLocal
from app.modules.matching import ranking
from app.modules.matching.need_parser import parse_need
from app.modules.profiles.models import CandidateFact, EvidenceLevel, FactSource
from tests.test_day2_rules import H, candidate_with_category, employer

NEED = ("Backend-разработчик middle: обязательно Python, FastAPI и PostgreSQL. "
        "Желательно Kafka, Docker, Redis и Kubernetes.")
FULL = {"python": 0.67, "fastapi": 0.67, "postgresql": 0.67}  # всё обязательное подтверждено, желательного нет
NO_PG = {"python": 1.0, "fastapi": 1.0, "kafka": 1.0, "docker": 1.0, "redis": 1.0, "kubernetes": 1.0}  # PostgreSQL не проверялся
TWO = {"python": 1.0, "fastapi": 0.33, "kafka": 1.0, "docker": 1.0, "redis": 1.0, "kubernetes": 1.0}  # FastAPI ниже порога


def _cand(client, i: int, skills: dict, **onb) -> tuple[str, uuid.UUID]:
    t = candidate_with_category(client, email=f"mh{i}@example.com", **onb)
    me = client.get("/api/me", headers=H(t)).json()
    uid = uuid.UUID(me["id"])
    with SessionLocal() as db:
        db.execute(delete(CandidateFact).where(CandidateFact.user_id == uid, CandidateFact.kind == "skill"))
        for tag, sc in skills.items():
            db.add(CandidateFact(user_id=uid, kind="skill", key=tag, title=tag, evidence_level=EvidenceLevel.T1,
                                 source=FactSource.test, value={"direction": "backend", "score": sc,
                                                                "correct": round(sc * 3), "total": 3}))
        db.commit()
    return me["candidate"]["public_ref"], uid


def _order(text: str, filters: dict | None = None) -> tuple[list[str], dict]:
    with SessionLocal() as db:
        sel = ranking.build_selection(db, parse_need(text, use_llm=False), filters or {})
    return [r["ref"] for r in sel["results"]], sel


# ---------------------------------------------------------------- ярусы обязательного
def test_tiers_put_full_required_first_and_flag_restores_old_order(client, monkeypatch):
    a, _ = _cand(client, 0, FULL)
    b, _ = _cand(client, 1, NO_PG)
    c, _ = _cand(client, 2, TWO)
    monkeypatch.setenv("MATCH_MUST_FIRST", "0")
    monkeypatch.setenv("RANK_CORE_SKILL", "0")  # Я1: ядро роли проверяется отдельно (test_core_skill)
    monkeypatch.setenv("MATCH_GRADE_ABOVE", "0")  # Я12б: добор ступенью выше — test_grade_above
    old, sel_old = _order(NEED)
    by = {r["ref"]: r for r in sel_old["results"]}
    # предусловие теста: по прежнему баллу кандидат без PostgreSQL выше полностью покрывающего
    assert by[b]["score"] > by[a]["score"] and old.index(b) < old.index(a), old
    assert sel_old["algorithm"] == "match-v1" and not sel_old["must_first"]
    monkeypatch.setenv("MATCH_MUST_FIRST", "1")
    new, sel = _order(NEED)
    assert new == [a, b, c] and sel["algorithm"] == "match-v1.1" and sel["must_first"]
    must = {r["ref"]: r["must"] for r in sel["results"]}
    assert must[a]["tier"] == 0 and must[a]["missing"] == [] and must[a]["required_total"] == 3
    assert must[b]["tier"] == 1 and must[b]["missing"] == ["PostgreSQL"]
    assert must[c]["tier"] == 2 and must[c]["missing"] == ["FastAPI", "PostgreSQL"]
    # баллы не менялись — меняется только порядок
    assert {r["ref"]: r["score"] for r in sel["results"]} == {r["ref"]: r["score"] for r in sel_old["results"]}


def test_bonus_does_not_cross_tier(client, monkeypatch):
    """ФСП и зонд входят в балл (до +0,15); балл сравнивается только внутри яруса."""
    a, _ = _cand(client, 0, FULL)
    b, ub = _cand(client, 1, NO_PG)
    orig = ranking.score_candidate

    def boosted(bundle, req):
        s, comps, reasons = orig(bundle, req)
        return (min(1.0, s + 0.5) if bundle.profile.user_id == ub else s), comps, reasons

    monkeypatch.setattr(ranking, "score_candidate", boosted)
    order, sel = _order(NEED)
    assert order == [a, b]
    by = {r["ref"]: r for r in sel["results"]}
    assert by[b]["score"] > by[a]["score"]  # балл выше, но ярус ниже


def test_nobody_covers_required_keeps_old_order(client, monkeypatch):
    """«Нет данных» ≠ «не умеет»: если обязательное не подтверждено ни у кого, порядок прежний."""
    _cand(client, 0, FULL)
    _cand(client, 1, NO_PG)
    _cand(client, 2, TWO)
    text = "Backend middle: обязательно Kotlin и Go. Желательно Python, Kafka, Docker."
    monkeypatch.setenv("MATCH_MUST_FIRST", "0")
    old, _ = _order(text)
    monkeypatch.setenv("MATCH_MUST_FIRST", "1")
    new, sel = _order(text)
    assert new == old and all(r["must"]["tier"] == 0 for r in sel["results"])
    assert sel["results"][0]["must"]["missing"] == ["Kotlin", "Go"]  # в шапке — честно: не подтверждено


def test_partly_covered_required_counts_only_covered(client):
    """PostgreSQL подтверждён хотя бы у одного — считается; Go не подтверждён ни у кого — ярус не меняет."""
    a, _ = _cand(client, 0, FULL)
    b, _ = _cand(client, 1, NO_PG)
    order, sel = _order("Backend middle: обязательно Python, PostgreSQL и Go. Желательно Kafka и Docker.")
    must = {r["ref"]: r["must"] for r in sel["results"]}
    assert order == [a, b] and must[a]["tier"] == 0 and must[b]["tier"] == 1
    assert must[a]["missing"] == ["Go"] and must[b]["missing"] == ["PostgreSQL", "Go"]


def test_missing_line_lists_up_to_three(client):
    _cand(client, 0, {"python": 1.0})
    _cand(client, 1, {"python": 1.0, "fastapi": 1.0, "postgresql": 1.0, "redis": 1.0, "docker": 1.0})
    _order_, sel = _order("Backend middle: обязательно Python, FastAPI, PostgreSQL, Redis и Docker.")
    m = next(r["must"] for r in sel["results"] if r["must"]["missing_total"])
    assert m["missing"] == ["FastAPI", "PostgreSQL", "Redis"] and m["missing_more"] == 1 and m["tier"] == 2


def test_api_selection_shows_must_and_candidate_detail(client):
    a, _ = _cand(client, 0, FULL)
    b, _ = _cand(client, 1, NO_PG)
    e = employer(client)
    n = client.post("/api/employer/needs", json={"text": NEED}, headers=H(e)).json()
    v1 = client.get(f"/api/employer/needs/{n['id']}/selections/1", headers=H(e)).json()
    assert [r["ref"] for r in v1["results"]] == [a, b] and v1["must_first"] is True
    assert v1["results"][1]["must"]["missing"] == ["PostgreSQL"]
    d = client.get(f"/api/employer/candidates/{b}", params={"need_id": n["id"]}, headers=H(e)).json()
    assert d["match"]["must"]["missing"] == ["PostgreSQL"]


# ---------------------------------------------------------------- условия потребности по умолчанию
def test_conditions_applied_by_default_and_show_all_in_one_click(client):
    x, _ = _cand(client, 0, FULL, work_format="remote", city="Казань")
    y, _ = _cand(client, 1, FULL, work_format="office", city="Москва")
    z, _ = _cand(client, 2, FULL, work_format="office", city="Казань")
    w, _ = _cand(client, 3, FULL, work_format="hybrid", city="Москва")
    e = employer(client)
    text = NEED + " Удалёнка или офис в Москве."
    n = client.post("/api/employer/needs", json={"text": text}, headers=H(e)).json()
    assert n["requirements"]["work_formats"] == ["remote", "office", "hybrid"] and n["requirements"]["city"] == "Москва"
    v1 = client.get(f"/api/employer/needs/{n['id']}/selections/1", headers=H(e)).json()
    assert {r["ref"] for r in v1["results"]} == {x, y, w}  # офис в Казани скрыт; удалёнка — из любого города
    c = v1["conditions"]
    assert c["hidden"] == 1 and c["text"] == "Удалённо или офис/гибрид (Москва)" and not c["off"] and c["from_need"]
    assert "_meta" not in v1["filters"]
    # один клик «Показать всех» — новая версия без условий; прежняя сохранена
    v2 = client.post(f"/api/employer/needs/{n['id']}/selections",
                     json={"parent_version": 1, "filters": {"conditions_off": True}}, headers=H(e))
    assert v2.status_code in (200, 201), v2.text
    v2 = v2.json()
    assert {r["ref"] for r in v2["results"]} == {x, y, z, w} and v2["conditions"]["off"] and not v2["conditions"]["hidden"]
    # рыночный режим (spec 20, А1): у настоящего работодателя real_only=True добавляется по умолчанию
    assert v2["filters"] == {"conditions_off": True, "real_only": True}
    # повторное открытие — снимок версии без пересчёта
    again = client.get(f"/api/employer/needs/{n['id']}/selections/1", headers=H(e)).json()
    assert again["conditions"] == c and again["categories"] == v1["categories"]
    # явный фильтр версии важнее условия потребности
    v3 = client.post(f"/api/employer/needs/{n['id']}/selections",
                     json={"parent_version": 1, "filters": {"work_format": "office"}}, headers=H(e)).json()
    assert {r["ref"] for r in v3["results"]} == {y}


def test_office_only_need_hides_remote_and_other_city(client):
    x, _ = _cand(client, 0, FULL, work_format="remote", city="Москва")
    y, _ = _cand(client, 1, FULL, work_format="office", city="Москва")
    z, _ = _cand(client, 2, FULL, work_format="office", city="Казань", relocation=True)
    order, sel = _order(NEED + " Офис в Москве, удалёнка не рассматривается.")
    assert set(order) == {y, z} and sel["conditions"]["hidden"] == 1  # готов к переезду — проходит по городу
    order, sel = _order(NEED)  # формат не указан — условий нет, никто не скрыт
    assert set(order) == {x, y, z} and sel["conditions"]["text"] is None and sel["conditions"]["hidden"] == 0


# ---------------------------------------------------------------- разбор условий
@pytest.mark.parametrize("text, fmt, fmts, city", [
    ("Удалёнка или офис в Москве", "remote", ["remote", "office", "hybrid"], "Москва"),
    ("Remote or office in Moscow", "remote", ["remote", "office", "hybrid"], "Москва"),
    ("Офис в Санкт-Петербурге или гибрид", "office", ["office", "hybrid"], "Санкт-Петербург"),
    ("Гибрид, Москва", "hybrid", None, "Москва"),
    ("hybrid Moscow", "hybrid", None, "Москва"),
    ("Работа только в офисе, Казань", "office", None, "Казань"),
    ("Формат: удалённо", "remote", None, None),
    ("Удалённая работа из любого города", "remote", None, None),
    ("Офис в Москве, удалёнка не рассматривается", "office", None, "Москва"),
    ("Без удалёнки, офис в Новосибирске", "office", None, "Новосибирск"),
    ("Удалёнка — нет, только офис в Казани", "office", None, "Казань"),
    ("Remote only, no office", "remote", None, None),
    ("Любой формат, кроме удалёнки", "office", ["office", "hybrid"], None),
    ("Любой формат, кроме офиса", "hybrid", ["hybrid", "remote"], None),
    ("Формат любой", None, None, None),
    ("Python, Django, PostgreSQL", None, None, None),
    ("Знание MS Office, работа удалённо", "remote", None, None),
    ("Удалённо или гибридный график с офисом в Москве", "remote", ["remote", "hybrid"], "Москва"),
    ("Работаем в офисе в Москве, 2 дня в неделю удалённо", "hybrid", ["hybrid", "office"], "Москва"),
    ("Офис или удалёнка", "office", ["office", "remote", "hybrid"], None),
    ("Казань или удалённо", "remote", ["remote", "office", "hybrid"], "Казань"),
    ("Удалённо или в Москве", "remote", ["remote", "office", "hybrid"], "Москва"),
    ("Удалённо из Москвы", "remote", None, None),
])
def test_conditions_parser_phrasings(text, fmt, fmts, city):
    r = parse_need("Backend middle: Python. " + text, use_llm=False)
    assert (r["work_format"], r["work_formats"], r["city"]) == (fmt, fmts, city)
    full = "Backend middle: Python. " + text
    for key in ("work_format", "city"):
        ev = r["evidence"].get(key)
        if r[key]:
            assert ev and full[ev["start"]:ev["end"]] == ev["quote"]


def test_conditions_text_and_city_semantics():
    req = parse_need("Backend middle: Python. Удалёнка или офис в Москве", use_llm=False)
    f = ranking.condition_filters(req, {})
    assert f == {"work_formats": ["remote", "office", "hybrid"], "city": "Москва"}
    assert ranking.conditions_text(f) == "Удалённо или офис/гибрид (Москва)"
    assert ranking.condition_filters(req, {"conditions_off": True}) == {}
    assert not ranking.city_applies("remote", f["work_formats"]) and ranking.city_applies("office", f["work_formats"])
    assert not ranking.city_applies("any", f["work_formats"])  # «любой формат» кандидата: может удалённо
    assert ranking.city_applies("any", ["office"])
    # город без формата офиса — не условие (удалённая работа из любого города)
    assert ranking.need_conditions({"work_format": "remote", "city": "Москва"}) == {"work_formats": ["remote"], "city": None}
