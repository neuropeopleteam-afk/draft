"""День 3А: контроль частоты и ротация субпулов, лимит форматов, достоверность результата (античит),
экспертная проверка, режим жюри, разбор зарплаты, атаки «Красной кнопки», метрики подбора."""
import pytest

from app.core.db import SessionLocal
from app.modules.assessment import bank_engine as be
from app.modules.assessment import integrity
from app.modules.assessment.bank_engine import BankEngine
from app.modules.assessment.exposure import choose_subpool, exposure_control, exposure_table, parse_quarantine
from app.modules.assessment.grader import GradeOutcome
from app.modules.matching.need_parser import parse_need, parse_salary
from app.modules.validation.matching_eval import dcg, ndcg, precision
from tests.test_bank_engine import oracle, run_session
from tests.test_day2_rules import H


@pytest.fixture
def bank(monkeypatch):
    def fake_grade(*, stem, code, step_prompt, rubric, answer, use_llm=True):
        return GradeOutcome(status="scored", score=0.9 if len(answer) > 40 else 0.0, method="llm", model="test")
    monkeypatch.setattr(be, "grade_open", fake_grade)
    return BankEngine()


# ---------------------------------------------------------------- тест: состав, частота показа, субпулы
@pytest.mark.parametrize("direction", ["backend", "frontend", "common_heavy"])
def test_format_limits_and_length(bank, direction):
    d = "backend" if direction == "common_heavy" else direction
    for seed_policy in ("good", "edge"):
        st, res, _ = run_session(bank, "middle", d, seed_policy)
        scored = [i for i in st["items"] if not i["canary"]]
        assert sum(1 for i in scored if i["format"] == "open_book_3step") <= 2
        assert sum(1 for i in scored if i["format"] == "open_answer") <= 1
        ext = res.details.get("extension")
        assert len(scored) <= 16 + (ext["items"] if ext else 0)
        assert res.details["formats"] and res.details["subpool"] in (0, 1)


def test_sympson_hetter_enabled_and_subpool_respected(bank):
    t = exposure_table()
    assert t and t["r_max"] == 0.3 and set(t["k"]) == {"backend", "frontend", "data_ml", "qa", "security"}
    ctrl = exposure_control("backend")
    assert ctrl is not None and ctrl.k and all(0 < v <= 1 for v in ctrl.k.values())
    st, res, _ = run_session(bank, "middle", "backend", "good")
    assert st["cfg"]["exposure"] == "sympson_hetter"
    sp = st["subpool"]
    pool = {p.family_id: p for p in be._pool(2)}
    main = [i for i in st["items"] if not i["canary"] and not i["ext"]]
    assert main and all(pool[i["family_id"]].subpool == sp for i in main)


def test_subpool_rotation_on_retake():
    assert choose_subpool(1, 5) is None
    assert choose_subpool(2, 4) == 0 and choose_subpool(2, 5) == 1
    assert choose_subpool(2, 4, previous=[0]) == 1 and choose_subpool(2, 5, previous=[1]) == 0
    assert choose_subpool(2, 4, quarantined={0}) == 1 and choose_subpool(2, 5, previous=[1], quarantined={0}) == 1
    assert choose_subpool(2, 4, quarantined={0, 1}) is None
    assert parse_quarantine("0, 2,x") == {0, 2}


def test_retake_gets_other_subpool(bank):
    a = bank.start(direction="qa", claimed_grade="junior", stack_tags=[], seed=10)
    b = bank.start(direction="qa", claimed_grade="junior", stack_tags=[], seed=10, previous_subpools=[a["subpool"]])
    assert a["subpool"] != b["subpool"]


# ---------------------------------------------------------------- достоверность результата
def _items(n=12, t=120.0, limit=300, score=1.0, signals=None, canary_fast=0):
    out = [{"format": "mcq_concept", "canary": False, "time_s": t, "time_limit_s": limit, "score": score,
            "signals": dict(signals) if signals is not None else {"focus_lost": 0, "hidden_ms": 0, "paste": 0,
                                                                     "paste_chars": 0}} for _ in range(n)]
    for _ in range(canary_fast):
        out.append({"format": "mcq_concept", "canary": True, "time_s": 3, "time_limit_s": limit, "score": 1.0,
                    "signals": {"focus_lost": 0}})
    return out


def test_integrity_levels():
    assert integrity.assess(_items())["level"] == "high"
    # потеря фокуса в 2 заданиях → средняя; в 5 → низкой нет, но 2 балла → средняя; + вставка → низкая
    it = _items()
    for i in it[:2]:
        i["signals"]["focus_lost"] = 1
    assert integrity.assess(it)["level"] == "medium"
    for i in it[:5]:
        i["signals"]["focus_lost"] = 2
    r = integrity.assess(it)
    assert r["level"] == "medium" and r["points"] == 2 and "вкладки" in r["reasons"][0]
    it[0]["signals"].update(paste=1, paste_chars=400)
    it[1]["signals"].update(paste=1, paste_chars=120)
    r = integrity.assess(it)
    assert r["level"] == "low" and any("Вставка" in x for x in r["reasons"])
    # детектор предзнания → низкая
    assert integrity.assess(_items(), {"flagged": True, "combined": 3.1, "excluded_answers": 2})["level"] == "low"
    # аномально быстрые верные: 4 из 12 (≥ 25 %) → 2 балла
    it = _items()
    for i in it[:4]:
        i["time_s"] = 4
    r = integrity.assess(it)
    assert r["signals"]["fast_correct"] == 4 and r["points"] >= 2
    # быстрые неверные — угадывание, не предзнание
    it = _items(score=0.0)
    for i in it[:5]:
        i["time_s"] = 3
    r = integrity.assess(it)
    assert r["signals"]["fast_wrong"] == 5 and r["signals"]["fast_correct"] == 0
    # ответы в обход интерфейса (нет сигналов)
    it = _items()
    for i in it:
        i["signals"] = None
    assert integrity.assess(it)["level"] == "medium"


def test_integrity_signals_are_sanitized():
    assert integrity.clean_signals({"focus_lost": "3", "paste": -5, "hidden_ms": 10**12, "evil": 1}) == {
        "focus_lost": 3, "hidden_ms": 3_600_000, "paste": 0, "paste_chars": 0, "copy": 0}
    assert integrity.clean_signals("x") is None


def test_engine_records_signals_and_integrity(bank):
    st = bank.start(direction="backend", claimed_grade="middle", stack_tags=[], seed=99)
    n = 0
    while n < 60:
        item = bank.next_item(st)
        if item is None:
            break
        it = next(i for i in st["items"] if i["token"] == item.item_id)
        sig = {"focus_lost": 1, "hidden_ms": 20_000, "paste": 0, "paste_chars": 0}
        bank.answer(st, item.item_id, oracle(it, item.step or 1, True), 1000, step=item.step, signals=sig)
        n += 1
    res = bank.finish(st)
    integ = res.details["integrity"]
    assert integ["level"] in ("medium", "low") and integ["signals"]["focus_lost_items"] >= 2
    assert any("вкладки" in r for r in integ["reasons"])


# ---------------------------------------------------------------- экспертная проверка
def test_expert_review_applies_to_pending(bank, monkeypatch):
    monkeypatch.setattr(be, "grade_open", lambda **kw: GradeOutcome(status="pending", score=None, method="none",
                                                                      error="LLM недоступен"))
    st, res, _ = run_session(bank, "middle", "backend", "good")
    items = bank.review_items(st)
    pend = [i for i in items if i["status"] == "pending"]
    assert pend and res.details["pending_review"] == len(pend)
    it = pend[0]
    crit = {c["id"]: 1.0 for c in it["rubric"]["criteria"]}
    assert bank.apply_review(st, it["token"], it["part"], {"x": 1.0}, None, "e@x") is None  # не все критерии
    rec = bank.apply_review(st, it["token"], it["part"], crit, "верно", "e@x")
    assert rec["applied"] and rec["score"] == 1.0
    res2 = bank.finish(st)
    assert res2.details["pending_review"] == len(pend) - 1


# ---------------------------------------------------------------- разбор зарплаты
@pytest.mark.parametrize("text,expected", [
    ("Зарплата 260 000 ₽ на руки", (260000, 260000)),
    ("Гибрид, от 200 до 250 тыс.", (200000, 250000)),
    ("260 тыс. рублей", (260000, 260000)),
    ("Оклад 180к", (180000, 180000)),
    ("до 300 000 рублей", (None, 300000)),
    ("от 150к", (150000, None)),
    ("Удалённо, 220–300 тыс.", (220000, 300000)),
    ("вилка 180 000 - 220 000", (180000, 220000)),
    ("Зарплата: 250000", (250000, 250000)),
    ("Senior Go: от 5 лет опыта, команда 12 человек", (None, None)),
])
def test_parse_salary(text, expected):
    assert parse_salary(text) == expected


@pytest.mark.parametrize("text,req,des", [
    ("Python, FastAPI, PostgreSQL обязательно, Kafka будет плюсом.", ["python", "fastapi", "postgresql"], ["kafka"]),
    ("Обязательно Python, FastAPI, желательно Kafka, Redis.", ["python", "fastapi"], ["kafka", "redis"]),
    ("Опыт работы с Go и Kafka, хорошо, если знаете Redis.", ["go", "kafka"], ["redis"]),
])
def test_need_mixed_required_desired(text, req, des):
    r = parse_need(text, use_llm=False)
    assert [x["tag"] for x in r["stack_required"]] == req and [x["tag"] for x in r["stack_desired"]] == des


def test_need_salary_net_and_one_sided():
    r = parse_need("Backend middle: Python, FastAPI. Зарплата 260 000 ₽ на руки.", use_llm=False)
    assert (r["salary_from"], r["salary_to"], r["salary_net"]) == (260000, 260000, True)
    r = parse_need("Frontend middle: React. До 300 000 рублей.", use_llm=False)
    assert (r["salary_from"], r["salary_to"]) == (None, 300000)


# ---------------------------------------------------------------- метрики подбора
def test_ranking_metrics():
    assert precision([3, 2, 1, 0, 2], 5) == 0.6
    assert ndcg([3, 2, 1], [1, 2, 3], 3) == pytest.approx(1.0)
    assert ndcg([0, 0, 3], [3, 0, 0], 3) == pytest.approx(dcg([0, 0, 3], 3) / dcg([3, 0, 0], 3))
    assert ndcg([0, 0], [0, 0], 2) == 0.0


# ---------------------------------------------------------------- режим жюри и атаки (API)
def test_jury_login_reset_and_expert(client, monkeypatch):
    from app.core.config import get_settings
    from app.modules.jury import router as jr

    r = client.get("/api/jury/status")
    assert r.status_code == 200 and len(r.json()["personas"]) == 4
    r = client.post("/api/jury/login", json={"persona": "candidate"})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    me = client.get("/api/me", headers=H(tok)).json()
    assert me["email"] == "candidate@jury.example.com" and me["candidate"]["current_category_id"] == "backend.middle"
    # тест пройден настоящим движком банка, сигналы интерфейса есть → достоверность высокая; правило 90 дней снято
    with SessionLocal() as db:
        from sqlalchemy import select

        from app.modules.assessment.models import TestSession
        from app.modules.profiles.models import CandidateProfile

        import uuid

        uid = uuid.UUID(me["id"])
        ts = db.scalars(select(TestSession).where(TestSession.user_id == uid)).all()
        assert ts and ts[0].result["engine"].startswith("bank")
        assert ts[0].result["engine_result"]["details"]["integrity"]["level"] == "high"
        assert db.get(CandidateProfile, uid).jury_mode
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "senior"}, headers=H(tok))
    assert r.status_code in (200, 201), r.text  # повторный тест без ожидания 90 дней
    # работодатель: потребности и подборки, у кандидата без ФСП — входящее приглашение
    e = client.post("/api/jury/login", json={"persona": "employer"}).json()["access_token"]
    needs = client.get("/api/employer/needs", headers=H(e)).json()
    assert len(needs if isinstance(needs, list) else needs.get("items", [])) == 3
    assert sum(1 for n in needs if n["requirements"].get("bias")) == 1  # потребность для показа фильтра ст. 64 ТК РФ
    # эксперт: в очереди есть ответ «на проверке»
    x = client.post("/api/jury/login", json={"persona": "expert"}).json()["access_token"]
    q = client.get("/api/expert/queue", headers=H(x)).json()
    assert q["counts"]["pending"] >= 1
    it = q["items"][0]
    crit = {c["id"]: 0.5 for c in it["rubric"]["criteria"]}
    r = client.post("/api/expert/review", headers=H(x), json={"session_id": it["session_id"], "token": it["token"],
                                                              "part": it["part"], "criteria": crit})
    assert r.status_code == 200, r.text
    assert r.json()["review"]["applied"] and r.json()["recomputed"]
    assert client.get("/api/expert/queue", headers=H(tok)).status_code == 403  # кандидат — не эксперт
    # сброс: пересоздаёт только учётки жюри; повтор сразу — 429
    monkeypatch.setitem(jr._state, "last_reset", 0.0)
    r = client.post("/api/jury/reset")
    assert r.status_code == 200 and r.json()["deleted_users"] == 4
    with SessionLocal() as db:  # у кандидата без ФСП два ухода со вкладки → достоверность средняя
        from app.modules.jury.seed import EMAILS
        from app.modules.auth.models import User

        u = db.scalar(select(User).where(User.email == EMAILS["candidate_nofsp"]))
        t = db.scalars(select(TestSession).where(TestSession.user_id == u.id)).all()
        assert t[0].result["engine_result"]["details"]["integrity"]["level"] == "medium"
    assert client.post("/api/jury/reset").status_code == 429
    assert client.get("/api/me", headers=H(tok)).status_code == 401  # старый токен удалённой учётки
    assert get_settings().jury_mode_available


def test_red_button_attacks(client):
    from app.modules.demo.seed import seed

    with SessionLocal() as db:
        seed(db)
        db.commit()
    for aid in ("inflate_keywords", "rename", "demographics", "fake_fsp", "remove_fsp"):
        r = client.post(f"/api/validation/attacks/{aid}", json={})
        assert r.status_code == 200, r.text
        assert r.json()["violated"] is False, r.json()
    rep = client.get("/api/validation/report").json()
    assert len(rep["attacks"]) == 6 and "live" in rep
    # атаки ничего не записали
    with SessionLocal() as db:
        from sqlalchemy import func, select

        from app.modules.fsp.models import FspAchievement

        assert db.scalar(select(func.count()).select_from(FspAchievement).where(FspAchievement.verified.is_(False))) == 0


def test_bm25_baseline():
    from app.modules.validation.matching_eval import BM25

    bm = BM25({"a": "Python FastAPI PostgreSQL разработчик", "b": "React TypeScript фронтенд", "c": "Python Django"})
    q = "Нужен разработчик: Python, FastAPI"
    assert bm.score("a", q) > bm.score("c", q) > bm.score("b", q) == 0.0


def test_fixed_form_is_same_for_everyone():
    import numpy as np
    from assessment_bank.simulation import make_population, make_truth

    from app.modules.validation import sim

    rng = np.random.default_rng(1)
    pool = sim.make_pool(1)
    truth = make_truth(pool, rng, misspec=0.5)
    cfg = sim.AppConfig()
    forms = sim.fixed_forms(pool, truth, "qa", cfg, rng)
    assert all(8 <= len(f) <= 16 for f in forms.values())
    people = [p for p in make_population(40, rng) if p.claimed == "middle"][:2]
    seen = []
    for p in people:
        s = sim.FixedFormSession(pool, "qa", cfg.cat(), forms["middle"], "middle", rng)
        while (it := s.next_item()) is not None:
            s.record(it, [1.0] * len(it.b), None)
        seen.append([a.family_id for a in s.administered])
    assert seen[0] == seen[1] == [i.family_id for i in forms["middle"]]
