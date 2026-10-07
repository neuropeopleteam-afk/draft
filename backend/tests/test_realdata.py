import json
from pathlib import Path
import random

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.auth.models import User
from app.modules.catalog.dictionary import find_stack
from app.modules.demo.seed import _candidate, extend_candidates, DIRECTIONS, GRADES
from app.modules.matching.coverage import coverage
from app.modules.matching.need_parser import parse_need
from app.modules.matching.ranking import apply_filters, condition_filters, requirement_priority, score_candidate
from app.modules.profiles.models import CandidateFact, CandidateProfile
from app.modules.validation.closed_set import Dataset, TEMPLATE, Upload, bundle, decode, evaluate, safe_cell
from tests.test_day2_rules import H, employer

CORPUS = Path(__file__).resolve().parents[2] / "docs/realdata/vacancies_50.json"


@pytest.mark.parametrize("text,direction,role", [
    ("DevOps middle: Docker, Kubernetes, Linux", "backend", "devops"),
    ("Android developer senior, Kotlin", "frontend", "mobile"),
    ("Аналитик данных middle, SQL, статистика", "data_ml", "analytics"),
    ("Программист 1С senior, SQL", "backend", "1c"),
    ("Unity developer junior, C#", "frontend", "gamedev"),
])
def test_unsupported_coverage_and_quote(text, direction, role):
    req = parse_need(text, use_llm=False)
    cov = req["coverage"]
    assert req["direction"] == direction and cov["role"] == role
    assert cov["tested"] and cov["not_tested"] and cov["supported"] is False
    ev = cov["evidence"]
    assert text[ev["start"]:ev["end"]] == ev["quote"]


def test_distinct_tags_no_false_equivalences():
    assert set(find_stack("Kotlin Kubernetes PHP C#")) == {"kotlin", "kubernetes", "php", "csharp"}
    assert coverage("QA automation Java для Android") is None


@pytest.mark.parametrize("text,direction", [
    ("ML-инженер senior: PyTorch, Python. Желательно Spark.", "data_ml"),
    ("Senior frontend: TypeScript, React, доступность и тестирование фронтенда.", "frontend"),
    ("QA automation engineer: Java, Android, API.", "qa"),
])
def test_profession_not_incidental_stack(text, direction):
    assert parse_need(text, use_llm=False)["direction"] == direction


def test_closed_metrics_denominator_and_missing_labels():
    dataset = Dataset.model_validate(TEMPLATE)
    result = evaluate(dataset, 5)
    assert result["evaluated_needs"] == 1
    assert result["summary"]["p@5"] == 0.2  # 1 relevant / 5, not / returned 2
    assert result["summary"]["ndcg@5"] == 1
    assert result["per_need"][0]["results"][0]["candidate_id"] == "candidate-1"
    assert "не проверены платформой" in result["per_need"][0]["results"][0]["reasons"][0]["text"]
    dataset.labels.pop()
    assert evaluate(dataset)["summary"] is None
    assert evaluate(dataset)["per_need"][0]["label_coverage"] == 0.5


def test_closed_declared_stack_not_scored():
    dataset = Dataset.model_validate(TEMPLATE)
    before = evaluate(dataset)["per_need"][0]["results"]
    dataset.candidates[1].declared_stack = ["python", "java", "postgresql", "docker", "kotlin"]
    after = evaluate(dataset)["per_need"][0]["results"]
    assert [r["score"] for r in before] == [r["score"] for r in after]
    dataset.candidates[1].theta = None
    assert evaluate(dataset)["per_need"][0]["returned"] == 1


@pytest.mark.parametrize("mutate", [
    lambda d: d["candidates"].append(d["candidates"][0]),
    lambda d: d["labels"].append(d["labels"][0]),
    lambda d: d["labels"][0].update(candidate_id="unknown"),
    lambda d: d["candidates"][0].update(theta=float("nan")),
    lambda d: d["candidates"][0].update(email="private@example.com"),
    lambda d: d["candidates"][0]["skills"][0].update(correct=6, total=5),
])
def test_closed_invalid_input(mutate):
    data = json.loads(json.dumps(TEMPLATE))
    mutate(data)
    with pytest.raises(Exception):
        decode(Upload(content=json.dumps(data)))


def test_templates_api_export_isolated(client):
    anon = client.post("/api/validation/closed-set/evaluate",
                       json={"content": json.dumps(TEMPLATE)})
    assert anon.status_code == 401
    normal = employer(client, "ordinary@example.com")
    assert client.post("/api/validation/closed-set/evaluate", json={"content": json.dumps(TEMPLATE)},
                       headers=H(normal)).status_code == 403
    # Isolated test personas, no expensive bank demo generation.
    tokens = []
    for sid in ("aaaaaaaaaa", "bbbbbbbbbb"):
        token = employer(client, f"employer+{sid}@jury.example.com")
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == f"employer+{sid}@jury.example.com"))
            user.is_demo = True
            db.commit()
        tokens.append(token)
    with SessionLocal() as db:
        before = len(list(db.scalars(select(CandidateProfile))))
    json_template = client.get("/api/validation/closed-set/template/json")
    assert json_template.status_code == 200
    csv_template = client.get("/api/validation/closed-set/template/csv")
    a = client.post("/api/validation/closed-set/evaluate",
                    json={"content": json_template.text}, headers=H(tokens[0]))
    b = client.post("/api/validation/closed-set/evaluate",
                    json={"content": csv_template.text, "format": "csv"}, headers=H(tokens[1]))
    assert a.status_code == b.status_code == 200, (a.text, b.text)
    assert a.json()["summary"] == b.json()["summary"]
    export = client.post("/api/validation/closed-set/export",
                         json={"content": json_template.text}, headers=H(tokens[0]))
    assert export.status_code == 200 and "explanations" in export.text
    with SessionLocal() as db:
        assert len(list(db.scalars(select(CandidateProfile)))) == before
    assert client.get("/api/validation/closed-set/results").status_code == 404  # no stored result API


def test_csv_formula_injection():
    for text in ("=SUM(1,2)", " @cmd", "+cmd", "-cmd"):
        assert safe_cell(text).startswith("'")
    assert safe_cell("ordinary") == "ordinary"


def test_upload_limit_is_bytes_not_unicode_characters():
    with pytest.raises(Exception):
        Upload(content="я" * 1_100_000)


def test_mandatory_gaps_only_use_confirmed_skill():
    dataset = Dataset.model_validate(TEMPLATE)
    req = parse_need("Backend middle: обязательно Python и PostgreSQL", use_llm=False)
    a, b = [bundle(c) for c in dataset.candidates]
    assert requirement_priority(a, req) == 0
    gaps = requirement_priority(b, req)
    dataset.candidates[1].declared_stack = ["python", "postgresql"]
    assert requirement_priority(bundle(dataset.candidates[1]), req) == gaps
    assert gaps > 0


def test_explicit_city_format_filters_are_t0_not_score():
    dataset = Dataset.model_validate(TEMPLATE)
    c = dataset.candidates[0]
    req = parse_need("Junior аналитик данных, Python и SQL. Офис в Москве или гибрид.", use_llm=False)
    assert req["city"] == "Москва" and req["work_formats"] == ["office", "hybrid"]
    c.work_format, c.city, c.relocation = "office", "Томск", False
    b = bundle(c)
    before = score_candidate(b, req)[0]
    assert apply_filters([b], condition_filters(req, {})) == []
    c.relocation = True
    assert len(apply_filters([bundle(c)], condition_filters(req, {}))) == 1
    assert score_candidate(bundle(c), req)[0] == before
    ev = req["evidence"]["city"]
    text = "Junior аналитик данных, Python и SQL. Офис в Москве или гибрид."
    assert text[ev["start"]:ev["end"]] == ev["quote"]


def test_append_preserves_original_150(engine):
    from app.core.security import hash_password
    rnd = random.Random(20261006)
    pwd = hash_password("Never-used-demo-password")
    with SessionLocal() as db:
        idx = 0
        for d in DIRECTIONS:
            for g in GRADES:
                for _ in range(10):
                    idx += 1
                    _candidate(db, rnd, idx, d, g, pwd, idx % 4 == 0)
        db.commit()
        from app.models import metadata
        def all_rows():
            return {table.name: {json.dumps(dict(row._mapping), sort_keys=True, default=str)
                                for row in db.execute(table.select())}
                    for table in metadata.sorted_tables}
        original_rows = all_rows()
        originals = {str(p.user_id): (p.public_ref, p.current_category_id, p.full_name,
                                     p.rating_score, p.about, p.privacy)
                     for p in db.scalars(select(CandidateProfile))}
        result = extend_candidates(db)
        assert result["added"] == 350 and result["total"] == 500
        db.commit()
        db.expire_all()
        profiles = list(db.scalars(select(CandidateProfile)))
        assert len(profiles) == 500
        appended_rows = all_rows()
        assert all(rows <= appended_rows[table] for table, rows in original_rows.items())
        for p in profiles:
            if str(p.user_id) in originals:
                assert originals[str(p.user_id)] == (p.public_ref, p.current_category_id, p.full_name,
                                                     p.rating_score, p.about, p.privacy)
        assert extend_candidates(db)["added"] == 0
        assert all(result["audiences_added"][a] > 0 for a in ("school", "student", "professional"))
        assert not list(db.scalars(select(CandidateFact).where(
            CandidateFact.kind == "skill", CandidateFact.key.in_(["kotlin", "csharp", "php", "kubernetes"]))))


@pytest.mark.parametrize("row", json.loads(CORPUS.read_text())["vacancies"], ids=lambda r: r["id"])
def test_public_corpus_no_crash_and_all_quotes_grounded(row):
    text = row["text"]
    req = parse_need(text, use_llm=False)
    assert req["direction"] in ("backend", "frontend", "data_ml", "qa", "security", None)
    assert req["grade"] in ("intern", "junior", "middle", "senior", None)  # «Стажёр» — грейд платформы (И13)
    evs = list(req["evidence"].values()) + [i["evidence"] for i in req["stack_required"] + req["stack_desired"]]
    for ev in evs:
        assert text[ev["start"]:ev["end"]] == ev["quote"], row["id"]
    assert row["source_url"].startswith("https://") and len(row["text_sha256"]) == 64
    # Silver annotations were frozen independently of parser predictions. Known ambiguity is explicit.
    for field, expected in row["expected"].items():
        if field == "grade" and expected is None:
            continue  # grade inferred from experience is not an explicit textual grade
        if row["id"] == "vac-037" and field == "work_format":
            assert req[field] == "remote"  # known training-vs-job ambiguity, not hidden as success
        else:
            acceptable = row.get("acceptable", {}).get(field, [expected])
            if field == "grade" and "junior" in acceptable:
                # разметка корпуса заморожена до появления грейда «Стажёр» (И13): стажировки там размечены как junior
                acceptable = [*acceptable, "intern"]
            assert req.get(field) in acceptable, (row["id"], field)
    # Exact deterministic stack snapshot catches regressions; it is not expert gold.
    predictions = json.loads((CORPUS.parent / "rules_predictions.json").read_text())
    snapshot = predictions[int(row["id"].split("-")[1]) - 1]
    assert [i["tag"] for i in req["stack_required"]] == [i["tag"] for i in snapshot["stack_required"]]
    assert [i["tag"] for i in req["stack_desired"]] == [i["tag"] for i in snapshot["stack_desired"]]
