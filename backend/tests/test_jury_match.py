"""И18 «подбор»: разбор потребности (синонимы, отрицания, «будет плюсом» после перечня, вилки), честные объяснения
и «Что если» (Н1): какое требование отсекает больше всего подтверждённых и сколько появится без него."""
import time
import uuid

import pytest
from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.modules.matching import whatif
from app.modules.matching.coverage import coverage
from app.modules.matching.need_parser import parse_need
from app.modules.profiles.models import CandidateFact, EvidenceLevel, FactSource
from tests.test_day2_rules import H, candidate_with_category, employer


def _tags(r: dict, zone: str = "stack_required") -> list[str]:
    return [i["tag"] for i in r[zone]]


# ---------------------------------------------------------------- разбор потребности
def test_postfix_desired_applies_only_to_its_part():
    r = parse_need("Python/Django dev (middle+), DRF, Celery, Postgres, Docker, k8s будет плюсом; удалёнка", use_llm=False)
    assert _tags(r) == ["python", "django", "postgresql", "docker"] and _tags(r, "stack_desired") == ["kubernetes"]
    r = parse_need("Backend middle. Будет плюсом: Kafka, Redis.", use_llm=False)  # маркер-префикс — как раньше
    assert _tags(r, "stack_desired") == ["kafka", "redis"] and not r["stack_required"]
    r = parse_need("Нужен PHP (Laravel), MySQL, немного JS. Удалённо.", use_llm=False)
    assert _tags(r) == ["php", "sql"] and _tags(r, "stack_desired") == ["javascript"]


def test_negation_excludes_tag_with_quote():
    text = "Frontend middle: React, TypeScript. Опыт Angular не нужен."
    r = parse_need(text, use_llm=False)
    assert "angular" not in _tags(r) + _tags(r, "stack_desired")
    assert [x["tag"] for x in r["excluded"]] == ["angular"]
    ev = r["excluded"][0]["evidence"]
    assert text[ev["start"]:ev["end"]] == ev["quote"] and "не нужен" in ev["quote"]
    r = parse_need("Backend: Python без Django, PostgreSQL", use_llm=False)
    assert _tags(r) == ["python", "postgresql"] and [x["tag"] for x in r["excluded"]] == ["django"]
    assert parse_need("Опыт работы: не требуется. Python, SQL", use_llm=False)["excluded"] == []


def test_synonyms_city_experience():
    r = parse_need("Ищем мидла на джанго, постгря, редис, кубер, докер. hybrid Moscow", use_llm=False)
    assert set(_tags(r)) >= {"django", "postgresql", "redis", "kubernetes", "docker"}
    assert r["city"] == "Москва" and r["work_format"] == "hybrid"
    assert parse_need("QA: ручной тестировщик, баг-репорты. Офис в Питере", use_llm=False)["city"] == "Санкт-Петербург"
    assert "manual-testing" in _tags(parse_need("Нужен ручной тестировщик на мобильное приложение", use_llm=False))
    assert parse_need("Go-разработчик, 5+ лет опыта, Kafka", use_llm=False)["experience_years_min"] == 5
    assert parse_need("Python, от 3 лет опыта в разработке", use_llm=False)["experience_years_min"] == 3
    # Spring рядом с Kotlin — не Java; явная Java остаётся
    assert "java" not in _tags(parse_need("Kotlin-разработчик: Kotlin, Spring Boot, PostgreSQL", use_llm=False))
    assert "java" in _tags(parse_need("Нужны Java и Kotlin, Spring Boot", use_llm=False))


@pytest.mark.parametrize("text,lo,hi", [
    ("Python middle, 250-300 т.р.", 250_000, 300_000),
    ("Go senior, 350k+", 350_000, None),
    ("Vue, TypeScript. 200 000 - 250 000", 200_000, 250_000),
    ("1С программист, офис в Екатеринбурге. 150 000", 150_000, 150_000),
    ("Java senior, 2,4 млн в год", 200_000, 200_000),
])
def test_salary_forms(text, lo, hi):
    r = parse_need(text, use_llm=False)
    assert (r["salary_from"], r["salary_to"]) == (lo, hi), r["evidence"].get("salary")
    ev = r["evidence"]["salary"]
    assert text[ev["start"]:ev["end"]] == ev["quote"]


def test_foreign_currency_not_rubles_and_unknown_terms():
    r = parse_need("ML engineer (NLP), PyTorch. Remote, $4000-5000 gross", use_llm=False)
    assert r["salary_from"] is None and r["salary_to"] is None
    assert r["salary_note"]["code"] == "currency" and "$4000" in r["salary_note"]["evidence"]["quote"]
    r = parse_need("Senior systems engineer: Rust, eBPF, DPDK, Linux kernel", use_llm=False)
    assert [u["term"] for u in r["unknown_terms"]] == ["Rust", "eBPF", "DPDK"] and _tags(r) == ["linux"]
    assert parse_need("Python, Django, PostgreSQL", use_llm=False)["unknown_terms"] == []


def test_coverage_first_named_role():
    assert coverage("Бизнес-аналитик / аналитик 1С: BPMN, SQL")["role"] == "analytics"
    assert coverage("Программист 1С senior, SQL")["role"] == "1c"


# ---------------------------------------------------------------- «Что если» и объяснения
NEED = "Backend-разработчик middle: обязательно Python, PostgreSQL и Kafka. Удалённо."
SKILLS = [  # кандидат → навыки (доля верных); Kafka 0,33 — проверено тестом, но ниже порога подтверждения
    {"python": 1.0, "postgresql": 1.0, "kafka": 1.0},
    {"python": 1.0, "postgresql": 1.0},
    {"python": 1.0, "postgresql": 1.0, "kafka": 0.33},
    {"python": 1.0},
]


def _setup(client) -> tuple[str, str, list[str]]:
    refs = []
    for i, skills in enumerate(SKILLS):
        t = candidate_with_category(client, email=f"wi{i}@example.com")
        me = client.get("/api/me", headers=H(t)).json()
        uid = uuid.UUID(me["id"])
        refs.append(me["candidate"]["public_ref"])
        with SessionLocal() as db:
            db.execute(delete(CandidateFact).where(CandidateFact.user_id == uid, CandidateFact.kind == "skill"))
            for tag, sc in skills.items():
                total = 3
                db.add(CandidateFact(user_id=uid, kind="skill", key=tag, title=tag, evidence_level=EvidenceLevel.T1,
                                     source=FactSource.test, value={"direction": "backend", "score": sc,
                                                                    "correct": round(sc * total), "total": total}))
            db.commit()
    e = employer(client)
    n = client.post("/api/employer/needs", json={"text": NEED}, headers=H(e))
    assert n.status_code in (200, 201), n.text
    return e, n.json()["id"], refs


def test_what_if_counts_apply_and_explanations(client):
    e, nid, refs = _setup(client)
    whatif._CACHE.clear()
    r = client.get(f"/api/employer/needs/{nid}/selections/1/what-if", headers=H(e))
    assert r.status_code == 200, r.text
    w = r.json()
    assert w["strict"] == 1 and w["confirmed_in_categories"] == 4 and w["shown"] and not w["cached"]
    assert w["ms"] < 500 and w["provisional_full"] == 0  # «предварительно» — справочно, в приросты не входят
    assert w["cuts"][0] == {"kind": "skill", "key": "kafka", "title": "Kafka", "cut": 3}
    kafka = next(o for o in w["options"] if o["key"] == "kafka")
    assert kafka["gain"] == 2 and kafka["result"] == 3 and kafka["text"] == "Без Kafka — ещё 2 подтверждённых Middle"
    assert all(o["key"] != "postgresql" for o in w["options"])  # без PostgreSQL никто не добавляется
    assert w["salary"] is None  # вилки нет — и ожидания кандидатов в расчёт не входят никогда
    # кэш: повтор — из кэша и быстро
    t0 = time.perf_counter()
    w2 = client.get(f"/api/employer/needs/{nid}/selections/1/what-if", headers=H(e)).json()
    assert w2["cached"] and time.perf_counter() - t0 < 0.5 and w2["strict"] == 1
    # применение — новая версия, прежняя сохранена; прогноз совпадает с новой версией
    body = {"parent_version": 1, **kafka["apply"]}
    v2 = client.post(f"/api/employer/needs/{nid}/selections", json=body, headers=H(e))
    assert v2.status_code in (200, 201), v2.text
    v2 = v2.json()
    assert v2["version"] == 2 and v2["parent_version"] == 1 and v2["filters"]["relaxation"] == "Без Kafka"
    assert [i["tag"] for i in v2["requirements"]["stack_desired"]] == ["kafka"]
    w3 = client.get(f"/api/employer/needs/{nid}/selections/2/what-if", headers=H(e)).json()
    assert w3["strict"] == kafka["result"] == 3
    need = client.get(f"/api/employer/needs/{nid}", headers=H(e)).json()
    assert [x["version"] for x in need["versions"]] == [1, 2]
    # объяснения v1: проверено тестом ниже порога ≠ «нет данных»; не проверялось — честно и с подсказкой
    v1 = client.get(f"/api/employer/needs/{nid}/selections/1", headers=H(e)).json()
    by_ref = {x["ref"]: x for x in v1["results"]}
    k3 = next(x for x in by_ref[refs[2]]["reasons"] if x["requirement"].endswith("Kafka"))
    assert k3["status"] == "mismatch" and k3["level"] == "T1" and "1 из 3 — ниже порога" in k3["text"]
    k2 = next(x for x in by_ref[refs[1]]["reasons"] if x["requirement"].endswith("Kafka"))
    assert k2["status"] == "missing" and "можно проверить коротким заданием" in k2["text"] and "Нет данных" not in k2["text"]
    # порядок выдачи не меняется: полностью подходящий — первым, скор тот же, что считает ranking
    assert v1["results"][0]["ref"] == refs[0]


def test_what_if_cache_invalidated_by_new_fact_and_scoped(client):
    e, nid, _refs = _setup(client)
    whatif._CACHE.clear()
    url = f"/api/employer/needs/{nid}/selections/1/what-if"
    assert client.get(url, headers=H(e)).json()["strict"] == 1
    with SessionLocal() as db:  # второй кандидат подтвердил Kafka (новый тест) — отметка свежести меняется
        uid = db.scalar(select(CandidateFact.user_id).where(CandidateFact.key == "postgresql")
                        .order_by(CandidateFact.created_at).offset(1).limit(1))
        db.add(CandidateFact(user_id=uid, kind="skill", key="kafka", title="Kafka", evidence_level=EvidenceLevel.T1,
                             source=FactSource.test, value={"direction": "backend", "score": 1.0, "correct": 3, "total": 3}))
        db.commit()
    w = client.get(url, headers=H(e)).json()
    assert not w["cached"] and w["strict"] >= 1
    other = employer(client, email="hr2@corp.ru", company="ООО Лютик")
    assert client.get(url, headers=H(other)).status_code == 404  # чужая потребность
    assert client.get(f"/api/employer/needs/{nid}/selections/9/what-if", headers=H(e)).status_code == 404


def test_need_notes_recomputed_on_save(client):
    e = employer(client)
    text = "Senior systems engineer: Rust, eBPF, Linux. Опыт Kubernetes не нужен. Зарплата $5000"
    n = client.post("/api/employer/needs", json={"text": text}, headers=H(e)).json()
    req = n["requirements"]
    assert [u["term"] for u in req["unknown_terms"]] == ["Rust", "eBPF"]
    assert [x["tag"] for x in req["excluded"]] == ["kubernetes"] and req["salary_note"]["code"] == "currency"
    # работодатель вернул Kubernetes вручную — в «исключено» он больше не показывается
    req2 = {**req, "stack_required": req["stack_required"] + [{"tag": "kubernetes", "weight": 0.8, "status": "manual"}]}
    p = client.patch(f"/api/employer/needs/{n['id']}", json={"requirements": req2}, headers=H(e))
    assert p.status_code == 200, p.text
    assert p.json()["requirements"]["excluded"] == []
