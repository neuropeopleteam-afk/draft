"""Каталог шире (волна 7): 4 новых направления за флагом CATALOG_EXT_ENABLED и проверенным банком (catalog/ext.py).

Без флага — всё как с пятью направлениями (API, опрос, разбор потребности); с флагом видны только направления, чей
банк прошёл проверку (здесь готовность задаётся CATALOG_EXT_FORCE_READY — банк новых направлений в тестах не нужен).
"""
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.modules.catalog import ext
from tests.conftest import register_and_verify

EXT = ("devops", "data_eng", "mobile", "analyst")
BASE = ("backend", "frontend", "data_ml", "qa", "security")


@pytest.fixture
def ext_on(monkeypatch):
    monkeypatch.setenv("CATALOG_EXT_ENABLED", "1")
    monkeypatch.setenv("CATALOG_EXT_FORCE_READY", ",".join(EXT))
    get_settings.cache_clear()
    ext.reset_cache()
    yield
    monkeypatch.delenv("CATALOG_EXT_ENABLED")
    monkeypatch.delenv("CATALOG_EXT_FORCE_READY")
    get_settings.cache_clear()
    ext.reset_cache()


def _login(client, email):
    return {"Authorization": f"Bearer {register_and_verify(client, email)}"}


def _onboarding(direction, stack):
    return {"direction": direction, "stack": [{"tag": t, "level": 2} for t in stack], "experience_years": 2,
            "roles": [], "work_format": "any", "consent_publication": True, "privacy": {}}


# ------------------------------------------------------------------ флаг выключен: как прежде

def test_flag_off_catalog_unchanged(client):
    data = client.get("/api/catalog").json()
    assert [d["id"] for d in data["directions"]] == list(BASE)
    assert len(data["categories"]) == 20
    assert not {t["direction_id"] for t in data["stack_tags"]} & set(EXT)
    tags = client.get("/api/catalog/stack-tags", params={"direction": "devops"}).json()
    assert {t["direction_id"] for t in tags} == {None}  # только общий блок, как до расширения
    meta = client.get("/api/meta").json()["catalog"]
    assert meta["ext_enabled"] is False and meta["ext"] == [] and meta["directions"] == list(BASE)


def test_flag_off_parser_keeps_nearest_category():
    from app.modules.matching.need_parser import parse_need

    r = parse_need("DevOps-инженер\nТребования: Kubernetes, Terraform, Prometheus, Linux", use_llm=False)
    assert r["direction"] == "backend" and r["coverage"]["role"] == "devops"
    assert "terraform" not in {i["tag"] for i in r["stack_required"]}
    assert "Terraform" in {u["term"] for u in r["unknown_terms"]}
    r = parse_need("Data Engineer (Middle)\nТребования: Spark, Airflow, SQL", use_llm=False)
    assert r["direction"] == "data_ml"


def test_flag_off_onboarding_rejects_new_direction(client):
    h = _login(client, "ext-off@example.com")
    r = client.put("/api/me/onboarding", json=_onboarding("devops", ["linux"]), headers=h)
    assert r.status_code == 422


def test_flag_on_bank_not_ready_still_hidden(monkeypatch, client):
    monkeypatch.setenv("CATALOG_EXT_ENABLED", "1")
    monkeypatch.setenv("CATALOG_EXT_MIN_FAMILIES", "100000")  # банк любого размера «не готов»
    get_settings.cache_clear()
    ext.reset_cache()
    try:
        assert ext.visible_ext() == ()
        assert [d["id"] for d in client.get("/api/catalog").json()["directions"]] == list(BASE)
        assert client.get("/api/catalog/stack-tags", params={"direction": "mobile"}).json()
        assert {t["direction_id"] for t in client.get("/api/catalog/stack-tags",
                                                      params={"direction": "mobile"}).json()} == {None}
        assert client.get("/api/meta").json()["catalog"]["ext"] == []
    finally:
        monkeypatch.delenv("CATALOG_EXT_ENABLED")
        monkeypatch.delenv("CATALOG_EXT_MIN_FAMILIES")
        get_settings.cache_clear()
        ext.reset_cache()


def test_sync_bank_rule_matches_settings():
    """tools/sync_bank.py пишет directions_verified по тому же правилу, что catalog/ext.py."""
    import importlib.util
    from pathlib import Path

    from app.core.config import Settings

    path = Path(__file__).resolve().parents[2] / "tools" / "sync_bank.py"
    spec = importlib.util.spec_from_file_location("sync_bank_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    f = Settings.model_fields
    assert mod.READY_MIN_FAMILIES == f["catalog_ext_min_families"].default
    assert mod.READY_MIN_PER_GRADE == f["catalog_ext_min_per_grade"].default


# ------------------------------------------------------------------ правило готовности банка

def _spec(d, grades, canary=False):
    return SimpleNamespace(direction=d, target_grades=grades, canary=canary)


def test_readiness_rule_needs_families_and_every_grade():
    full = [_spec("devops", ["intern", "junior"]) for _ in range(9)] + \
           [_spec("devops", ["middle", "senior"]) for _ in range(9)]
    no_senior = [_spec("mobile", ["intern", "junior", "middle"]) for _ in range(20)]
    few = [_spec("analyst", ["intern", "junior", "middle", "senior"]) for _ in range(5)]
    canary = [_spec("data_eng", ["intern", "junior", "middle", "senior"], canary=True) for _ in range(30)]
    r = ext.readiness_rule(full + no_senior + few + canary, min_families=18, min_per_grade=3)
    assert r["devops"]["ready"] and r["devops"]["families"] == 18
    assert not r["mobile"]["ready"] and r["mobile"]["per_grade"]["senior"] == 0
    assert not r["analyst"]["ready"]
    assert not r["data_eng"]["ready"] and r["data_eng"]["families"] == 0  # канарейки не считаются


def test_allow_list_limits_visible(monkeypatch, ext_on):
    monkeypatch.setenv("CATALOG_EXT_DIRECTIONS", "devops,mobile")
    get_settings.cache_clear()
    assert ext.visible_ext() == ("devops", "mobile")
    monkeypatch.delenv("CATALOG_EXT_DIRECTIONS")
    get_settings.cache_clear()


# ------------------------------------------------------------------ флаг включён, банк готов

def test_flag_on_catalog_has_9_directions(client, ext_on):
    data = client.get("/api/catalog").json()
    assert [d["id"] for d in data["directions"]] == list(BASE + EXT)
    assert len(data["categories"]) == 36
    cats = {c["id"]: c for c in data["categories"]}
    for d in EXT:
        for g in ("intern", "junior", "middle", "senior"):
            c = cats[f"{d}.{g}"]
            assert 0 < c["market_salary_from"] <= c["market_salary_median"] <= c["market_salary_to"]
            assert c["market_as_of"] == "2026-10-10" and "Хабр Карьера" in c["market_source"]
        assert cats[f"{d}.intern"]["market_salary_median"] <= cats[f"{d}.junior"]["market_salary_median"]
        assert cats[f"{d}.middle"]["market_salary_median"] < cats[f"{d}.senior"]["market_salary_median"]
    tags = client.get("/api/catalog/stack-tags", params={"direction": "data_eng"}).json()
    ids = [t["id"] for t in tags]
    assert {"etl", "dwh", "dbt"} <= set(ids) and {"spark", "airflow", "kafka"} <= set(ids) and "sql" in ids
    assert ids.index("etl") < ids.index("spark") < ids.index("sql")  # свои → связанные → общий блок
    meta = client.get("/api/meta").json()["catalog"]
    assert meta["ext"] == list(EXT) and meta["ext_titles"]["devops"] == "DevOps / SRE"


@pytest.mark.parametrize("text, direction, tag", [
    ("DevOps-инженер\nТребования: Kubernetes, Terraform, Prometheus и Grafana, Linux", "devops", "terraform"),
    ("SRE-инженер (Senior)\nSLO и error budget, дежурства, Kubernetes", "devops", "sre"),
    ("Data Engineer (Middle)\nТребования: Spark, Airflow, dbt, DWH на Greenplum", "data_eng", "dbt"),
    ("Инженер данных\nETL-конвейеры, Kafka, ClickHouse, качество данных", "data_eng", "etl"),
    ("Android-разработчик (Kotlin)\nJetpack Compose, корутины, MVVM", "mobile", "jetpack-compose"),
    ("iOS-разработчик\nSwift, SwiftUI, UIKit", "mobile", "swift"),
    ("Системный аналитик (Middle)\nUML, BPMN, проектирование интеграций, SQL", "analyst", "bpmn"),
    ("Бизнес-аналитик\nСбор требований, user story и критерии приёмки", "analyst", "requirements"),
])
def test_flag_on_parser_uses_own_direction(ext_on, text, direction, tag):
    from app.modules.matching.need_parser import parse_need

    r = parse_need(text, use_llm=False)
    assert r["direction"] == direction, r["direction"]
    assert "coverage" not in r
    assert tag in {i["tag"] for i in r["stack_required"] + r["stack_desired"]}
    assert r["evidence"].get("direction")


def test_flag_on_data_analyst_stays_nearest(ext_on):
    from app.modules.matching.need_parser import parse_need

    r = parse_need("Аналитик данных\nSQL, pandas, A/B-тесты", use_llm=False)
    assert r["direction"] == "data_ml" and r["coverage"]["role"] == "analytics"


def test_react_native_is_not_react(ext_on):
    from app.modules.catalog.dictionary import find_stack_spans

    assert "react" not in find_stack_spans("Мобильный разработчик React Native")
    spans = find_stack_spans("React Native и веб на React")
    assert "react-native" in spans and "react" in spans and spans["react"][0] > 10


def test_flag_on_base_parse_unchanged(ext_on):
    """Вакансии базовых направлений разбираются так же, как без флага."""
    from app.modules.matching.need_parser import parse_need

    texts = ["Python backend-разработчик (Middle)\nFastAPI, PostgreSQL, Redis, Docker",
             "Frontend-разработчик\nReact, TypeScript, адаптивная вёрстка",
             "QA-инженер\nТест-дизайн, pytest, тестирование API",
             "Специалист по информационной безопасности\nOWASP, SIEM, пентест"]
    on = [parse_need(t, use_llm=False) for t in texts]
    get_settings.cache_clear()
    import os
    os.environ["CATALOG_EXT_ENABLED"] = "0"
    get_settings.cache_clear()
    off = [parse_need(t, use_llm=False) for t in texts]
    os.environ["CATALOG_EXT_ENABLED"] = "1"
    get_settings.cache_clear()
    for a, b in zip(on, off):
        assert a["direction"] == b["direction"]
        assert [i["tag"] for i in a["stack_required"]] == [i["tag"] for i in b["stack_required"]]


def test_flag_on_onboarding_accepts_new_direction(client, ext_on):
    h = _login(client, "ext-on@example.com")
    r = client.put("/api/me/onboarding", json=_onboarding("devops", ["terraform", "linux", "ci-cd"]), headers=h)
    assert r.status_code == 200, r.text
    r = client.get("/api/me/onboarding", headers=h)
    assert r.json()["answers"]["direction"] == "devops"


def test_criteria_mentions_catalog_only_with_flag(monkeypatch):
    from app.modules.validation import criteria as C

    def see():
        items = [it for c in C.build()["criteria"] for it in c["items"] if it["tz"] == C.CATEGORIZATION_TZ]
        assert len(items) == 1
        return items[0]["see"]

    assert "Каталог" not in see()
    monkeypatch.setenv("CATALOG_EXT_ENABLED", "1")
    monkeypatch.setenv("CATALOG_EXT_FORCE_READY", "devops,mobile")
    get_settings.cache_clear()
    try:
        s = see()
        assert "Каталог: 7 направлений" in s and len(s) <= 170
    finally:
        monkeypatch.delenv("CATALOG_EXT_ENABLED")
        monkeypatch.delenv("CATALOG_EXT_FORCE_READY")
        get_settings.cache_clear()


def test_spa_inside_spark_only_fixed_with_flag(monkeypatch):
    """«spa» внутри «Spark» не голосует за Frontend — с флагом; без флага поведение прежнее (правка — под флагом)."""
    from app.modules.matching.need_parser import parse_need

    text = "Data Engineer (Middle)\nSpark, Airflow, SQL"
    assert parse_need(text, use_llm=False)["direction"] == "frontend"  # прежнее поведение без флага
    monkeypatch.setenv("CATALOG_EXT_ENABLED", "1")
    monkeypatch.setenv("CATALOG_EXT_MIN_FAMILIES", "100000")  # банк «не готов»: новых направлений нет
    get_settings.cache_clear()
    ext.reset_cache()
    try:
        assert parse_need(text, use_llm=False)["direction"] == "data_ml"
        r = parse_need("Frontend-разработчик SPA на React\nTypeScript", use_llm=False)
        assert r["direction"] == "frontend"
        from app.modules.catalog.dictionary import direction_keywords, find_keys

        assert find_keys("SPA на React, не Spark", direction_keywords()).get("frontend") == 1
    finally:
        monkeypatch.delenv("CATALOG_EXT_ENABLED")
        monkeypatch.delenv("CATALOG_EXT_MIN_FAMILIES")
        get_settings.cache_clear()
        ext.reset_cache()


def test_lead_principal_only_families_not_in_pool_without_flag(monkeypatch):
    """Без GRADES_EXT_ENABLED семейства только уровней Lead/Principal не выдаются и не считаются проверяемыми навыками
    (банк feat/bank-ext содержит такие семейства; тест 4 уровней остаётся прежним)."""
    only_top = SimpleNamespace(target_grades=["lead", "principal"])
    mixed = SimpleNamespace(target_grades=["senior", "lead"])
    base = SimpleNamespace(target_grades=["junior"])
    assert ext.in_active_pool(base) and ext.in_active_pool(mixed)
    assert not ext.in_active_pool(only_top)
    assert ext.active_specs([only_top, mixed, base]) == [mixed, base]
    monkeypatch.setattr(ext, "grades_ext_on", lambda: True)
    assert ext.in_active_pool(only_top)


def test_adaptive_pool_has_no_top_only_families():
    from assessment_bank import load_specs

    from app.modules.assessment.bank_engine import _pool

    specs = load_specs()
    top_only = {fid for fid, s in specs.items() if s.target_grades and not set(s.target_grades) & set(ext.GRADE_IDS)}
    in_pool = {pi.family_id for pi in _pool(1)}
    assert not (top_only & in_pool)
