"""Подбор: цитаты из текста потребности, фильтр ст. 64 ТК РФ, сравнение кандидатов, атака «пол, возраст, имя»."""
import json

import pytest

from app.core.db import SessionLocal
from app.modules.matching import bias
from app.modules.matching.need_parser import parse_need
from tests.test_day2_rules import H, candidate_with_category, employer

NEED = ("Ищем бэкенд-разработчика уровня middle: обязательно Python, FastAPI и PostgreSQL, опыт с Redis. "
        "Будет плюсом Kafka. Удалённо, 220–300 тыс.")
BIASED = ("Python-разработчик middle в отдел интеграций: только мужчины до 35 лет, славянской внешности, без детей, "
          "в молодой коллектив. Нужны Python, Django и PostgreSQL, желательно Docker. Офис в Москве, 180–240 тыс.")


def _all_evidence(r: dict) -> list[dict]:
    items = [i["evidence"] for i in r["stack_required"] + r["stack_desired"]]
    return items + list(r["evidence"].values())


# ---------------------------------------------------------------- цитаты (путь без LLM)
def test_every_requirement_has_quote_from_text():
    r = parse_need(NEED, use_llm=False)
    assert r["method"] == "rules"
    assert set(r["evidence"]) == {"direction", "grade", "work_format", "salary"}
    for ev in _all_evidence(r):
        assert ev and NEED[ev["start"]:ev["end"]] == ev["quote"] and ev["source"] == "rules"
        assert ev["quote"] in ev["context"] and ev["context"] in NEED
    q = {i["tag"]: i["evidence"]["quote"] for i in r["stack_required"] + r["stack_desired"]}
    assert q == {"python": "Python", "fastapi": "FastAPI", "postgresql": "PostgreSQL", "redis": "Redis", "kafka": "Kafka"}
    assert r["evidence"]["salary"]["quote"] == "220–300 тыс." and r["evidence"]["grade"]["quote"] == "middle"
    assert r["stack_desired"][0]["evidence"]["basis"] == "desired"
    assert all(i["status"] == "extracted" for i in r["stack_required"])
    # грейд по опыту — цитата опыта
    r = parse_need("Нужен Go-разработчик, опыт от 5 лет, Kafka", use_llm=False)
    assert r["grade"] == "senior" and r["evidence"]["grade"]["basis"] == "experience"
    assert "5 лет" in r["evidence"]["grade"]["quote"] and r["evidence"]["experience_years_min"]


def test_llm_path_quotes_verified(monkeypatch):
    """LLM: новый тег с цитатой из текста добавляется (source=llm), без найденной цитаты — отбрасывается."""
    from app.modules.llm.client import LLMResult
    from app.modules.matching import need_parser

    text = "Backend-разработчик: Python и брокеры сообщений (Kafka), межсервисное взаимодействие. Гибрид."
    data = {"direction": "backend", "grade": "middle",
            "stack_required": [{"tag": "python", "weight": 1.0, "quote": "Python"},
                               {"tag": "grpc", "weight": 0.7, "quote": "межсервисное  взаимодействие"},
                               {"tag": "redis", "weight": 0.8, "quote": "кэш на Redis"}],  # такого в тексте нет
            "stack_desired": [{"tag": "kafka", "weight": 0.3}],  # без цитаты
            "quotes": {"direction": "Backend-разработчик", "grade": "уровень middle"}}  # грейда в тексте нет
    monkeypatch.setattr(need_parser, "chat_json", lambda *a, **k: LLMResult(ok=True, data=data, latency_ms=5))
    r = parse_need(text)
    assert r["method"] == "llm+rules" and r["llm"]["dropped_without_quote"] == 3
    tags = {i["tag"]: i for i in r["stack_required"] + r["stack_desired"]}
    assert "redis" not in tags and tags["grpc"]["evidence"]["source"] == "llm"
    assert text[tags["grpc"]["evidence"]["start"]:tags["grpc"]["evidence"]["end"]] == "межсервисное взаимодействие"
    assert tags["python"]["evidence"]["source"] == "rules"  # тег из словаря сохраняет цитату правил
    assert tags["kafka"]["evidence"]["source"] == "rules"  # Kafka найдена словарём — не потерялась
    assert r["grade"] is None  # грейд LLM без цитаты из текста не принят
    for ev in _all_evidence(r):
        assert text[ev["start"]:ev["end"]] == ev["quote"]


def test_llm_does_not_get_discriminatory_fragments(monkeypatch):
    from app.modules.llm.client import LLMResult
    from app.modules.matching import need_parser

    seen = {}

    def fake(system, user, **kw):
        seen["user"] = user
        return LLMResult(ok=True, data={"stack_required": [{"tag": "python", "quote": "мужчины до 35"}]}, latency_ms=1)

    monkeypatch.setattr(need_parser, "chat_json", fake)
    r = parse_need("Нужен Python-разработчик, только мужчины до 35 лет.")
    assert "мужчин" not in seen["user"] and "35" not in seen["user"]
    assert r["stack_required"][0]["evidence"]["source"] == "rules" and len(r["bias"]) == 2


# ---------------------------------------------------------------- фильтр ст. 64 ТК РФ
@pytest.mark.parametrize("text,cat", [
    ("Кандидат до 35 лет", "age"), ("возраст 25–35 лет", "age"), ("не старше 40", "age"),
    ("в молодой коллектив", "age"), ("молодую и дружную команду", "age"), ("от 20 до 30 лет", "age"),
    ("только мужчины", "gender"), ("Ищем девушку на позицию QA", "gender"), ("мужской коллектив", "gender"),
    ("без детей", "family"), ("не планирующая декрет", "family"), ("не замужем", "family"),
    ("славянской внешности", "appearance"), ("без акцента", "appearance"), ("национальность любая", "appearance"),
    ("православный", "religion"), ("с московской пропиской", "residence"),
    ("регистрация по месту жительства", "residence"), ("без вредных привычек", "other"),
])
def test_bias_found(text, cat):
    f = bias.find_bias(text)
    assert f and f[0]["category"] == cat and text[f[0]["start"]:f[0]["end"]] == f[0]["quote"], f


@pytest.mark.parametrize("text", [
    "Senior Go: от 5 лет опыта, команда 12 человек.", "Опыт от 3 до 5 лет, Python.",
    "Опыт работы 25-30 лет не нужен.", "Компания 20 лет на рынке, сервис регистрации пользователей на FastAPI.",
    NEED, "Junior frontend: JavaScript, HTML/CSS, React. Гибрид, 120–160 тыс. ₽",
    "Стаж до 10 лет в банковской сфере", "Middle QA: тест-дизайн, API-тестирование, pytest.",
])
def test_bias_no_false_positives(text):
    assert bias.find_bias(text) == []


def test_bias_masked_and_rewritten():
    # раньше «не старше 35 лет» давало грейд senior (ключ «старш»), «младше» — junior
    r = parse_need("Python-разработчик не старше 35 лет, младше 30. Django.", use_llm=False)
    assert r["grade"] is None and [b["category"] for b in r["bias"]] == ["age", "age"]
    r = parse_need(BIASED, use_llm=False)
    assert {b["category"] for b in r["bias"]} == {"gender", "age", "appearance", "family"} and len(r["bias"]) == 5
    assert all(b["suggestion"] and "ст. 64 ТК РФ" in b["law"] for b in r["bias"])
    clean = BIASED.replace(" только мужчины до 35 лет, славянской внешности, без детей, в молодой коллектив", "")
    rc = parse_need(clean, use_llm=False)
    keys = ("direction", "grade", "stack_required", "stack_desired", "work_format", "salary_from", "salary_to")
    strip = (lambda x: json.dumps({k: [(i["tag"], i["weight"]) for i in x[k]] if k.startswith("stack") else x[k]
                                   for k in keys}))
    assert strip(r) == strip(rc)  # те же требования, что и без дискриминационных фраз
    s = r["suggested_text"]
    for bad in ("мужчин", "35", "славянск", "детей", "молод"):
        assert bad not in s.lower(), s
    assert "Python, Django" in s and "навыкам" in s
    assert bias.find_bias(s) == [] and parse_need(s, use_llm=False)["bias"] == []
    assert parse_need(NEED, use_llm=False)["suggested_text"] is None


# ---------------------------------------------------------------- API: разбор, подтверждение, правка, удаление
def test_need_review_flow_api(client):
    te = employer(client)
    r = client.post("/api/employer/needs/parse", json={"text": BIASED}, headers=H(te))
    assert r.status_code == 200, r.text
    req = r.json()
    assert len(req["bias"]) == 5 and req["suggested_text"]
    # работодатель подтверждает Python, удаляет Docker, меняет вес Django, добавляет Redis вручную
    req["stack_required"][0]["status"] = "confirmed"
    req["stack_desired"] = [i for i in req["stack_desired"] if i["tag"] != "docker"]
    for i in req["stack_required"]:
        if i["tag"] == "django":
            i.update(weight=0.5, status="edited")
    req["stack_desired"].append({"tag": "redis", "weight": 0.3, "status": "manual"})
    req["review"] = {"grade": "confirmed", "salary": "edited"}
    req["bias"] = []  # клиент не может «стереть» находки фильтра — они считаются на сервере по тексту
    body = {k: v for k, v in req.items() if k not in ("method", "bias", "suggested_text", "salary_net", "llm")}
    n = client.post("/api/employer/needs", json={"text": BIASED, "requirements": body}, headers=H(te))
    assert n.status_code == 201, n.text
    saved = n.json()["requirements"]
    st = {i["tag"]: i["status"] for i in saved["stack_required"] + saved["stack_desired"]}
    assert st["python"] == "confirmed" and st["django"] == "edited" and st["redis"] == "manual" and "docker" not in st
    assert saved["review"] == {"grade": "confirmed", "salary": "edited"}
    assert len(saved["bias"]) == 5 and saved["evidence"]["salary"]["quote"] == "180–240 тыс."
    assert next(i for i in saved["stack_required"] if i["tag"] == "python")["evidence"]["quote"] == "Python"
    # подборка версии 1 хранит те же требования; дискриминационные фразы в ранжирование не попали
    v1 = client.get(f"/api/employer/needs/{n.json()['id']}/selections/1", headers=H(te)).json()
    assert v1["requirements"]["bias"] and not any(
        "мужчин" in json.dumps(x["reasons"], ensure_ascii=False) for x in v1["results"])
    # PATCH требований пересчитывает находки по исходному тексту
    p = client.patch(f"/api/employer/needs/{n.json()['id']}", json={"requirements": {"direction": "backend"}},
                     headers=H(te))
    assert p.status_code == 200 and len(p.json()["requirements"]["bias"]) == 5
    # недопустимый статус и чужие поля цитаты отклоняются
    bad = client.post("/api/employer/needs", json={"text": NEED, "requirements": {
        "stack_required": [{"tag": "python", "status": "hacked"}]}}, headers=H(te))
    assert bad.status_code == 422


# ---------------------------------------------------------------- сравнение кандидатов
def _seeded_need(client, te, text=NEED) -> dict:
    from app.modules.demo.seed import seed

    with SessionLocal() as db:
        seed(db)
        db.commit()
    n = client.post("/api/employer/needs", json={"text": text}, headers=H(te))
    assert n.status_code == 201, n.text
    return n.json()


def test_compare_candidates(client):
    te = employer(client)
    need = _seeded_need(client, te)
    v1 = client.get(f"/api/employer/needs/{need['id']}/selections/1", headers=H(te)).json()
    refs = [r["ref"] for r in v1["results"][:3]]
    r = client.get(f"/api/employer/needs/{need['id']}/compare", params={"refs": refs, "version": 1}, headers=H(te))
    assert r.status_code == 200, r.text
    c = r.json()
    assert [x["ref"] for x in c["candidates"]] == refs and c["need"]["version"] == 1
    keys = [row["key"] for row in c["rows"]]
    for k in ("score", "category", "theta", "integrity", "stack:python", "stack:kafka", "work_format", "fsp", "probe",
              "market"):
        assert k in keys, k
    assert next(row for row in c["rows"] if row["key"] == "stack:python")["quote"] == "Python"
    assert next(row for row in c["rows"] if row["key"] == "market")["quote"] == "220–300 тыс."
    for cand in c["candidates"]:
        assert set(cand["cells"]) == set(keys)
        assert cand["rank_in_selection"] == refs.index(cand["ref"]) + 1
        assert abs(cand["score"] - v1["results"][refs.index(cand["ref"])]["score"]) < 1e-9  # тот же скор, что в подборке
        assert all(cell["level"] in ("T0", "T1", "T2", "none", "market") for cell in cand["cells"].values())
        assert "±" in cand["cells"]["theta"]["text"] and "95 %" in cand["cells"]["theta"]["text"]
        assert "Рынок Backend · Middle" in cand["cells"]["market"]["text"]
        for k, cell in cand["cells"].items():  # заявленное (T0) никогда не «подтверждено»
            if cell["level"] == "T0":
                assert cell["status"] != "confirmed", (k, cell)
        assert cand["can_invite"] is True and cand["probe_active"] is False
    assert sum(1 for x in c["candidates"] if x["cells"]["score"].get("best")) >= 1
    # обезличено: ни ФИО, ни почты, ни скрытого минимума зарплаты
    from sqlalchemy import select

    from app.modules.auth.models import User
    from app.modules.profiles.models import CandidateProfile

    with SessionLocal() as db:
        ps = db.scalars(select(CandidateProfile).where(CandidateProfile.public_ref.in_(refs))).all()
        secrets_ = [p.full_name for p in ps] + [db.get(User, p.user_id).email for p in ps]
        mins = [p.salary_min_hidden for p in ps if p.salary_min_hidden]
    raw = r.text
    assert not any(s and s in raw for s in secrets_)
    assert not any(f'"salary_min_hidden"' in raw or f": {m}," in raw for m in mins)
    # без refs — первые три из последней версии; 1 или 4 кандидата — 422; скрытый кандидат — 404
    d = client.get(f"/api/employer/needs/{need['id']}/compare", headers=H(te)).json()
    assert [x["ref"] for x in d["candidates"]] == refs
    assert client.get(f"/api/employer/needs/{need['id']}/compare", params={"refs": refs[:1]},
                      headers=H(te)).status_code == 422
    four = [x["ref"] for x in v1["results"][:4]]
    assert client.get(f"/api/employer/needs/{need['id']}/compare", params={"refs": four},
                      headers=H(te)).status_code == 422
    assert client.get(f"/api/employer/needs/{need['id']}/compare", params={"refs": [refs[0], "K-NOPE00"]},
                      headers=H(te)).status_code == 404
    assert client.get(f"/api/employer/needs/{need['id']}/compare", params={"refs": refs, "version": 9},
                      headers=H(te)).status_code == 404
    # чужая компания не видит сравнение по чужой потребности
    te2 = employer(client, email="hr2@corp.ru", company="ООО Лютик")
    assert client.get(f"/api/employer/needs/{need['id']}/compare", params={"refs": refs},
                      headers=H(te2)).status_code == 404


def test_compare_then_probe_and_invite(client):
    """Из сравнения — сразу зонд и приглашение: статусы в сравнении обновляются."""
    tc = candidate_with_category(client)
    te = employer(client)
    need = _seeded_need(client, te)
    me = client.get("/api/me", headers=H(tc)).json()["candidate"]["public_ref"]
    v1 = client.get(f"/api/employer/needs/{need['id']}/selections/1", headers=H(te)).json()
    other = next(r["ref"] for r in v1["results"] if r["ref"] != me)
    refs = [me, other]
    pr = client.post("/api/employer/probes", headers=H(te), json={
        "candidate_refs": refs, "need_id": need["id"], "title": "Медленный запрос",
        "task_text": "Запрос с JOIN выполняется 8 секунд. Опишите план диагностики.", "salary_from": 220000,
        "salary_to": 300000})
    assert pr.status_code in (200, 201), pr.text
    inv = client.post("/api/employer/invitations", headers=H(te), json={
        "candidate_ref": me, "need_id": need["id"], "position_title": "Python-разработчик",
        "offer_description": "Разработка API платёжного сервиса, команда 6 человек.", "salary_from": 220000,
        "salary_to": 300000, "contact_method": "Telegram @hr_corp"})
    assert inv.status_code == 201, inv.text
    c = client.get(f"/api/employer/needs/{need['id']}/compare", params={"refs": refs}, headers=H(te)).json()
    by = {x["ref"]: x for x in c["candidates"]}
    assert by[me]["probe_active"] and by[other]["probe_active"]
    assert by[me]["can_invite"] is False and by[me]["last_invitation_status"] == "sent"
    assert by[other]["can_invite"] is True and by[other]["last_invitation_status"] is None
    assert "Иван Петров" not in json.dumps(c, ensure_ascii=False)


# ---------------------------------------------------------------- объяснения и ранжирование
def test_selection_explanations_only_t1_t2_confirmed(client):
    te = employer(client)
    need = _seeded_need(client, te)
    v1 = client.get(f"/api/employer/needs/{need['id']}/selections/1", headers=H(te)).json()
    assert v1["results"]
    for res in v1["results"]:
        for reason in res["reasons"]:
            if reason["status"] == "confirmed":
                assert reason["level"] in ("T1", "T2"), reason


def test_discriminatory_text_does_not_change_ranking(client):
    te = employer(client)
    a = _seeded_need(client, te, text=NEED)
    b = client.post("/api/employer/needs", json={"text": NEED + " Только мужчины до 35 лет, без детей."},
                    headers=H(te)).json()
    assert len(b["requirements"]["bias"]) == 3 and not a["requirements"]["bias"]
    ra = client.get(f"/api/employer/needs/{a['id']}/selections/1", headers=H(te)).json()["results"]
    rb = client.get(f"/api/employer/needs/{b['id']}/selections/1", headers=H(te)).json()["results"]
    assert [(x["ref"], x["score"]) for x in ra] == [(x["ref"], x["score"]) for x in rb]


def test_red_button_demographics_attack(client):
    from sqlalchemy import select

    from app.modules.demo.seed import seed
    from app.modules.profiles.models import CandidateProfile

    with SessionLocal() as db:
        seed(db)
        db.commit()
        names = {p.public_ref: (p.full_name, p.about) for p in db.scalars(select(CandidateProfile)).all()}
    from tests.conftest import register_and_verify

    tok = register_and_verify(client, "demographics-attack@example.com", role="employer")  # атаки — только после входа (аудит, С9)
    r = client.post("/api/validation/attacks/demographics", json={}, headers=H(tok))
    assert r.status_code == 200, r.text
    x = r.json()
    assert x["violated"] is False, x
    d = x["details"]
    assert d["order_same"] and d["requirements_same"] and d["max_score_diff"] == 0 and not d["card_leaks"]
    assert d["pool"] >= 20 and len(d["bias_found"]) == 5
    assert "тот же" in x["fact"] and "5 фрагментов" in x["fact"]
    with SessionLocal() as db:  # ничего не записано
        assert {p.public_ref: (p.full_name, p.about) for p in db.scalars(select(CandidateProfile)).all()} == names
    rep = client.get("/api/validation/report").json()
    assert any(a["id"] == "demographics" for a in rep["attacks"])


def test_demographics_attack_detects_violation(monkeypatch):
    """Контрольный эксперимент: если бы ранжирование учитывало пол/возраст, атака это показала бы."""
    from app.modules.demo.seed import seed
    from app.modules.matching import ranking
    from app.modules.validation import attacks

    real = ranking.score_candidate

    def biased(b, req):
        s, comps, reasons = real(b, req)
        return s + (0.01 if "мужчина" in (b.profile.about or "") else 0.0), comps, reasons

    monkeypatch.setattr(attacks, "score_candidate", biased)
    with SessionLocal() as db:
        seed(db)
        db.commit()
        out = attacks.run(db, "demographics")
    assert out["violated"] is True


# ---------------------------------------------------------------- «почему A выше B»
def test_compare_why_pairs(client):
    te = employer(client)
    need = _seeded_need(client, te)
    c = client.get(f"/api/employer/needs/{need['id']}/compare", headers=H(te)).json()
    by = {x["ref"]: x for x in c["candidates"]}
    assert len(c["why"]) == len(c["candidates"]) - 1
    for w in c["why"]:
        a, b = by[w["higher"]], by[w["lower"]]
        assert a["score"] >= b["score"] and abs(w["diff"] - (a["score"] - b["score"]) * 100) < 0.01
        # разложение точное: сумма вкладов = разница скоров (до округления компонент)
        assert abs(sum(f["points"] for f in w["factors"]) - w["diff"]) < 0.3, w
        assert all(f["level"] in ("T1", "T2") for f in w["factors"])  # только подтверждённое
        assert all(f["points"] > 0 for f in w["pro"]) and all(f["points"] < 0 for f in w["con"])
        assert w["text"].startswith(f"{a['ref']} ") and "против" in w["text"]
        assert "мужчин" not in w["text"] and "лет" not in w["text"].replace("лет опыта", "")


def test_why_pairs_unit():
    from app.modules.matching.compare import why_pairs

    req = {"stack_required": [{"tag": "python", "weight": 1.0}, {"tag": "kafka", "weight": 1.0}], "stack_desired": []}
    base = {"theta": 1.0, "se": 0.3, "comps": {"test": 0.8, "stack_required": 0.0, "stack_desired": 0.0, "fsp": 0.0,
                                                "probe": 0.0}}
    a = {**base, "ref": "C-A", "tags": {"python": 1.0, "kafka": 0.0}}
    b = {**base, "ref": "C-B", "tags": {"python": 0.0, "kafka": 0.0}, "comps": {**base["comps"], "fsp": 0.5}}
    a["comps"] = {**base["comps"], "stack_required": 0.5}
    a["score"] = 0.45 * 0.8 + 0.35 * 0.5
    b["score"] = 0.45 * 0.8 + 0.10 * 0.5
    [w] = why_pairs([b, a], req)
    assert w["higher"] == "C-A" and w["diff"] == pytest.approx(12.5)
    assert w["pro"][0]["text"] == "обязательно Python: 100 % против не подтверждено" and w["pro"][0]["points"] == 17.5
    assert w["con"][0]["level"] == "T2" and w["con"][0]["points"] == -5.0
    assert w["con"][0]["text"] == "ФСП: сила паспорта 0,50 против нет подтверждённых"
    assert w["summary"] == "C-A выше C-B на 12,5 балла из 100"


# ---------------------------------------------------------------- ширина вилки
def test_salary_range_width_limit(client):
    tc = candidate_with_category(client)
    te = employer(client)
    ref = client.get("/api/me", headers=H(tc)).json()["candidate"]["public_ref"]
    base = {"candidate_ref": ref, "position_title": "Python-разработчик", "contact_method": "Telegram @hr_corp",
            "offer_description": "Разработка API платёжного сервиса, команда 6 человек."}
    r = client.post("/api/employer/invitations", headers=H(te), json={**base, "salary_from": 100000, "salary_to": 300000})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "salary_range_too_wide"
    assert "1,5 раза" in r.json()["detail"]["message"] and "150\u00a0000" in r.json()["detail"]["message"]
    probe = {"candidate_refs": [ref], "title": "Медленный запрос", "salary_from": 100000, "salary_to": 200000,
             "task_text": "Запрос с JOIN выполняется 8 секунд. Опишите план диагностики."}
    r = client.post("/api/employer/probes", headers=H(te), json=probe)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "salary_range_too_wide"
    assert client.post("/api/employer/probes", headers=H(te), json={**probe, "salary_to": 150000}).status_code == 201
    ok = client.post("/api/employer/invitations", headers=H(te), json={**base, "salary_from": 200000, "salary_to": 300000})
    assert ok.status_code == 201, ok.text


# ---------------------------------------------------------------- жалоба на приглашение и индекс доверия
def _invite(client, te, ref, **kw):
    body = {"candidate_ref": ref, "position_title": "Python-разработчик", "contact_method": "Telegram @hr_corp",
            "offer_description": "Разработка API платёжного сервиса, команда 6 человек.", "salary_from": 220000,
            "salary_to": 300000, **kw}
    r = client.post("/api/employer/invitations", headers=H(te), json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_invitation_complaint_lowers_trust(client):
    te = employer(client)
    t0 = client.get("/api/employer/company/trust", headers=H(te)).json()
    f0 = {f["id"]: f for f in t0["factors"]}
    assert f0["complaints"]["status"] == "ok" and f0["complaints"]["points"] == 0 and f0["complaints"]["max"] == 0
    cands = [candidate_with_category(client, email=f"c{i}@example.com") for i in range(3)]
    refs = [client.get("/api/me", headers=H(t)).json()["candidate"]["public_ref"] for t in cands]
    invs = [_invite(client, te, r) for r in refs]
    tc = cands[0]
    # чужое приглашение — 404; неизвестная причина — 422
    assert client.post(f"/api/candidate/invitations/{invs[1]}/complaint", json={"reason": "spam"},
                       headers=H(tc)).status_code == 404
    assert client.post(f"/api/candidate/invitations/{invs[0]}/complaint", json={"reason": "rude"},
                       headers=H(tc)).status_code == 422
    r = client.post(f"/api/candidate/invitations/{invs[0]}/complaint",
                    json={"reason": "salary", "comment": "Назвали сумму вдвое ниже"}, headers=H(tc))
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["status"] == "declined" and out["complaint"]["reason_title"] == "Нереальная вилка"
    assert out["complaint"]["comment"] == "Назвали сумму вдвое ниже"
    assert client.post(f"/api/candidate/invitations/{invs[0]}/complaint", json={"reason": "spam"},
                       headers=H(tc)).status_code == 409
    emp = {i["id"]: i for i in client.get("/api/employer/invitations", headers=H(te)).json()}
    assert emp[invs[0]]["complaint"]["reason"] == "salary" and "comment" not in emp[invs[0]]["complaint"]
    t1 = client.get("/api/employer/company/trust", headers=H(te)).json()
    f1 = {f["id"]: f for f in t1["factors"]}
    assert f1["complaints"]["status"] == "warn" and f1["complaints"]["points"] == -5
    assert "нереальная вилка — 1" in f1["complaints"]["text"]
    assert t1["score"] == max(0, round(sum(f["points"] for f in t1["factors"])))  # штраф входит в индекс
    # ещё две жалобы от разных кандидатов (в т. ч. на принятое приглашение) — «плохо», штраф 15
    assert client.post(f"/api/candidate/invitations/{invs[1]}/accept", headers=H(cands[1])).status_code == 200
    for t, i, why in ((cands[1], invs[1], "role"), (cands[2], invs[2], "spam")):
        assert client.post(f"/api/candidate/invitations/{i}/complaint", json={"reason": why}, headers=H(t)).status_code == 201
    accepted = client.get(f"/api/candidate/invitations/{invs[1]}", headers=H(cands[1])).json()
    assert accepted["status"] == "accepted" and accepted["complaint"]["reason"] == "role"  # статус не меняется
    t3 = client.get("/api/employer/company/trust", headers=H(te)).json()
    f3 = {f["id"]: f for f in t3["factors"]}
    assert f3["complaints"]["status"] == "bad" and f3["complaints"]["points"] == -15
    without = round(sum(f["points"] for f in t3["factors"] if f["id"] != "complaints"))
    assert t3["score"] == max(0, without - 15) and t3["summary"]
    # кандидат видит тот же пониженный индекс в своём приглашении
    tr = client.get("/api/candidate/invitations-trust", headers=H(cands[2])).json()
    assert tr[invs[2]]["score"] == t3["score"]
