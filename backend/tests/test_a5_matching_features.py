"""Тесты новых возможностей подбора и объяснимости (А5):
- Режим «Принесите свой набор» (/api/employer/benchmark/sample и /api/employer/benchmark/upload, JSON/CSV, метки 0..3 и 0/1)
- Объяснимость: explain, why_above_next («Почему №1 выше №2»), строгое разделение T1/T2 (t0_in_score = False)
- Честность цифр (P0-3): калибровка вилки при 0 кандидатов = 0; прогноз принятия без истории = insufficient_data (pct=None);
  индекс ответственности при < 5 событиях = insufficient_data (score=None); ЕГРЮЛ без реестра = unverified (не failed по регулярке);
  без вилки не пишем «вилка соответствует рынку»
- Фильтр real_only=true в API подбора и поиска
- Правило справедливости 4/5 (matching.bias.fairness_four_fifths), team_factor (fsp.rating) и protocol_highlight (fsp.relevance)
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.modules.catalog.dictionary import find_stack
from app.modules.fsp import rating as fsp_rating, relevance as fsp_rel
from app.modules.matching import bench_upload, bias, explain, need_parser, vacancy_guard
from tests.test_day2_rules import H, candidate_with_category, employer


def _jury_employer_headers(client) -> dict[str, str]:
    r = client.post("/api/jury/login", json={"persona": "employer"})
    assert r.status_code == 200, r.text
    return H(r.json()["access_token"])


def test_benchmark_sample_and_upload_json_and_csv_end_to_end(client):
    # 1. Скачивание образца JSON и CSV (публичный маршрут)
    r_json = client.get("/api/employer/benchmark/sample?format=json")
    assert r_json.status_code == 200
    r_csv = client.get("/api/employer/benchmark/sample?format=csv")
    assert r_csv.status_code == 200
    assert "vac-backend-py" in r_csv.text

    headers = _jury_employer_headers(client)

    # 2. Оценка JSON-набора в демо-песочнице жюри
    up_json = client.post(
        "/api/employer/benchmark/upload",
        json={"content": r_json.text, "format": "json", "k": 5},
        headers=headers,
    )
    assert up_json.status_code == 200, up_json.text
    data = up_json.json()
    assert data["n_needs"] == 2 and data["n_candidates"] == 5
    assert data["summary"]["p@5"] > 0 and data["summary"]["ndcg@10"] > 0 and data["summary"]["mrr"] == 1.0
    assert data["summary"]["p@5"] >= data["baseline_t0"]["p@5"]
    assert data["fairness"]["rule"] == "four_fifths" and data["fairness"]["penalty_without_fsp"] == 0.0
    assert "need_id,need_title,rank,candidate_id" in data["csv_export"]

    first_need = data["per_need"][0]
    assert len(first_need["results"]) >= 2
    r0 = first_need["results"][0]
    assert r0["explain"]["t0_in_score"] is False
    assert r0["why_above_next"] is not None
    assert "Выше следующего кандидата" in r0["why_above_next"]["headline"]

    # 3. Оценка CSV-набора
    up_csv = client.post(
        "/api/employer/benchmark/upload",
        json={"content": r_csv.text, "format": "csv", "k": 5},
        headers=headers,
    )
    assert up_csv.status_code == 200, up_csv.text
    assert up_csv.json()["summary"]["mrr"] == 1.0

    # 4. Поддержка бинарных меток релевантности 0/1 (P0-2)
    binary_ds = bench_upload. evaluate_uploaded_dataset(
        content='{"needs":[{"id":"n1","text":"Backend middle: Python, FastAPI, PostgreSQL"}],"candidates":[{"id":"c1","direction":"backend","grade":"middle","theta":0.9,"skills":["python","fastapi","postgresql"]},{"id":"c2","direction":"backend","grade":"middle","theta":-0.2,"skills":[]}],"labels":[{"need_id":"n1","candidate_id":"c1","relevance":1},{"need_id":"n1","candidate_id":"c2","relevance":0}]}',
        fmt="json",
        k=5,
    )
    assert binary_ds["summary"]["p@5"] > 0 and binary_ds["summary"]["mrr"] == 1.0


def test_honest_numbers_no_fabricated_defaults():
    # 1. Калибровка вилки при 0 подтверждённых кандидатов -> additional_candidates == 0
    req_low = {"salary_from": 80_000, "salary_to": 100_000, "salary_net": True}
    market = {"from": 160_000, "median": 210_000, "to": 260_000}
    cal_zero = explain.compute_salary_calibration(0, req_low, market)
    assert cal_zero is not None
    assert cal_zero["additional_candidates"] == 0
    assert cal_zero["confirmed_in_pool"] == 0
    assert "0 подтверждённых кандидатов" in cal_zero["text"]

    # При реальных 3 кандидатах в пуле ниже рынка — ровно 3
    cal_three = explain.compute_salary_calibration(3, req_low, market)
    assert cal_three["additional_candidates"] == 3

    # 2. Прогноз принятия приглашения без статистики реальных принятий -> pct is None, status = insufficient_data
    fc = explain.compute_offer_forecast(
        {"market_range": market, "work_format": "remote"},
        {"salary_to": 240_000, "salary_net": True, "work_format": "remote"},
        {},
        3,
        3,
    )
    assert fc["status"] == "insufficient_data"
    assert fc["probability"] is None and fc["pct"] is None
    assert fc["factors"]

    # При наличии >= 5 реальных приглашений считает фактическую долю
    fc_real = explain.compute_offer_forecast(
        {"market_range": market, "work_format": "remote"},
        {"salary_to": 240_000, "salary_net": True, "work_format": "remote"},
        {},
        3,
        3,
        accepted_count=4,
        invited_count=5,
    )
    assert fc_real["status"] == "measured" and fc_real["pct"] == 80

    # 3. Индекс ответственности без событий или при < 5 событиях -> score is None, status = insufficient_data
    resp_empty = vacancy_guard.compute_responsibility_index()
    assert resp_empty["status"] == "insufficient_data" and resp_empty["score"] is None
    resp_few = vacancy_guard.compute_responsibility_index(total_events=3, response_rate=0.9, median_response_hours=12)
    assert resp_few["status"] == "insufficient_data" and resp_few["score"] is None
    resp_real = vacancy_guard.compute_responsibility_index(
        total_events=8, response_rate=0.875, median_response_hours=16.0, realistic_salary_share=1.0, cancelled_share=0.0
    )
    assert resp_real["status"] == "measured" and resp_real["score"] >= 85

    # 4. ЕГРЮЛ: никогда не возвращает failed по регулярке названия без реестра; извлекает ИНН из текста
    eg_no_reg = vacancy_guard.verify_egrul_summary(inn=None, company_name="ООО Быстрый заработок")
    assert eg_no_reg["status"] == "unverified"
    parsed_with_inn = need_parser.parse_need(
        "ООО Ромашка, ИНН 7707083893. Ищем Backend-разработчика middle: Python, FastAPI, PostgreSQL.",
        use_llm=False,
    )
    assert parsed_with_inn["vacancy_guard"]["egrul"]["inn"] == "7707083893"
    assert parsed_with_inn["vacancy_guard"]["egrul"]["status"] == "unverified"
    assert "не указана" in parsed_with_inn["vacancy_guard"]["summary"]


def test_selection_explain_why_above_next_and_real_only(client):
    tc1 = candidate_with_category(client, email="a5_c1@example.com")
    tc2 = candidate_with_category(client, email="a5_c2@example.com")
    assert tc1 and tc2
    te = employer(client)
    n = client.post(
        "/api/employer/needs",
        json={"text": "Backend-разработчик middle: обязательно Python, FastAPI и PostgreSQL. Удалённо, 200–260 тыс. на руки."},
        headers=H(te),
    )
    assert n.status_code == 201, n.text
    nid = n.json()["id"]

    v1 = client.get(f"/api/employer/needs/{nid}/selections/1", headers=H(te)).json()
    assert v1["t0_in_score"] is False
    assert v1["salary_calibration"] is not None
    assert len(v1["results"]) >= 2
    assert v1["results"][0]["explain"]["headline"]
    assert v1["results"][0]["why_above_next"]["headline"].startswith("Выше следующего кандидата")

    # Фильтр real_only=true в поиске и в новой версии подборки
    sr = client.get("/api/employer/candidates?direction=backend&real_only=true", headers=H(te))
    assert sr.status_code == 200
    v2 = client.post(
        f"/api/employer/needs/{nid}/selections",
        json={"filters": {"real_only": True}},
        headers=H(te),
    )
    assert v2.status_code == 201, v2.text


def test_synonyms_fsp_team_and_protocol_highlight():
    # Словарь синонимов
    tags = set(find_stack("Ищем разработчика: Postgres, K8s, JS, C#, .NET Core, Spring Boot, Apache Kafka, MS SQL, функциональное тестирование"))
    assert {"postgresql", "kubernetes", "javascript", "csharp", "java", "kafka", "sql", "test-design"} <= tags

    # Командный коэффициент ФСП по полю team из индекса протоколов
    today = date(2026, 10, 20)
    personal = SimpleNamespace(verified=True, event_name="ЧР", event_date=today, place=1, discipline="algorithmic", result_title="победитель", team=None)
    team_ach = SimpleNamespace(verified=True, event_name="ЧР", event_date=today, place=1, discipline="algorithmic", result_title="победитель", team="Сборная-1")
    assert fsp_rating.details([personal], today=today)["strength"] > fsp_rating.details([team_ach], today=today)["strength"]

    # Подсветка профильных навыков протокола ФСП
    hl = fsp_rel.protocol_highlight("security", "security")
    assert hl["coef"] == 1.0 and "owasp" in hl["tags"]

    # Правило 4/5
    f45 = bias.fairness_four_fifths(0.84, 0.92, n_without_fsp=120, n_with_fsp=60)
    assert f45["passed"] is True and f45["disparate_impact_ratio"] >= 0.80
