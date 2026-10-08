"""Исправления 07.10 (И5): демо-данные на чистом стеке, темы карты навыков, место в кубке без повтора, индекс доверия
после жалобы, адрес демо-ATS, данные песочницы жюри, честная подпись источника экспертной разметки."""
from pathlib import Path
import re
import tempfile
import uuid

from alembic import command
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa
from sqlalchemy import select

from app.core.db import SessionLocal, utcnow
from app.core.enums import UserRole
from tests.conftest import alembic_config
from tests.test_day2_rules import H


def jury(client, persona: str) -> str:
    r = client.post("/api/jury/login", json={"persona": persona})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def demo_companies(n: int = 2) -> None:
    """Демо-компании платформы без 150 кандидатов (для демо-вакансий) — как в test_integrations."""
    from app.modules.demo.seed import COMPANIES
    from app.modules.profiles.models import Company

    with SessionLocal() as db:
        for name, industry, city in COMPANIES[:n]:
            db.add(Company(name=name, industry=industry, city=city, is_demo=True))
        db.commit()


# ------------------------------------------------------------------ 7. демо-данные на чистом стеке
def test_demo_pool_ignores_jury_and_drops_jury_built_on_empty_pool(client):
    from app.modules.demo.seed import _user, demo_pool_size, drop_jury_built_on_empty_pool
    from app.modules.jury import seed as jury_seed
    from app.modules.profiles.models import Company

    jury(client, "candidate")  # api создаёт демо жюри раньше основных демо-данных
    with SessionLocal() as db:
        assert demo_pool_size(db) == 0  # учётки @jury.example.com — не основные демо-данные
        assert db.scalar(select(Company.id).where(Company.name == jury_seed.COMPANY2)) is not None
        assert "" in drop_jury_built_on_empty_pool(db)
        assert db.scalar(select(Company.id).where(Company.name.in_([jury_seed.COMPANY, jury_seed.COMPANY2]))) is None
        _user(db, "demo-cand-1@demo.example.com", UserRole.candidate, "Демо")
        db.commit()
        assert demo_pool_size(db) == 1


# ------------------------------------------------------------------ 2. карта навыков: темы по-русски
def test_skill_map_topics_have_russian_titles():
    from app.modules.assessment import feedback as fb
    from app.modules.assessment.bank_engine import load_specs
    from app.modules.assessment.skill_map import to_stack_tags

    assert fb._title("other") == "Прочие темы"
    assert fb._title("system-performance") == "Производительность систем"
    # каждое семейство банка без стек-тега попадает в тему с названием, «other» не остаётся
    for fid, s in load_specs().items():
        if not to_stack_tags(s.direction, s.skills):
            tag = next((t for keys, t, _ in fb._EXTRA_TOPICS if keys & set(s.skills)), "other")
            assert tag != "other", fid


# ------------------------------------------------------------------ 3. место в кубке: миграция fx01
def test_fx01_strips_place_from_cup_fact_titles():
    url = f"sqlite:///{Path(tempfile.mkdtemp()) / 'fx01.db'}"
    cfg = alembic_config(url)
    # ревизия перед fx01 — из самой миграции: после слияния fx01 встанет в конец цепочки, тест не меняется
    down = ScriptDirectory.from_config(cfg).get_revision("fx01").down_revision
    command.upgrade(cfg, down)
    eng = sa.create_engine(url)
    fid, other = uuid.uuid4().hex, uuid.uuid4().hex
    row = {"user_id": uuid.uuid4().hex, "kind": "probe", "key": "cup:x", "value": "{}", "evidence_level": "T1",
           "source": "probe", "weight": 1.0, "created_at": utcnow().isoformat()}
    with eng.begin() as c:
        ins = sa.text("INSERT INTO candidate_facts (id, user_id, kind, key, title, value, evidence_level, source, "
                      "source_ref, weight, created_at) VALUES (:id, :user_id, :kind, :key, :title, :value, "
                      ":evidence_level, :source, :source_ref, :weight, :created_at)")
        c.execute(ins, {**row, "id": fid, "title": "Кубок «Платёжный шлюз»: 2 место из 5", "source_ref": "cup:1"})
        c.execute(ins, {**row, "id": other, "title": "Зонд: 2 место из 5", "source_ref": "probe:1"})
    command.upgrade(cfg, "fx01")
    with eng.connect() as c:
        titles = dict(c.execute(sa.text("SELECT id, title FROM candidate_facts")).all())
        cols = {x["name"] for x in sa.inspect(c).get_columns("expert_panelists")}
    assert titles[fid] == "Кубок «Платёжный шлюз»"  # место — только в вердикте
    assert titles[other] == "Зонд: 2 место из 5"  # не кубок — не трогаем
    assert {"source", "source_model"} <= cols
    command.downgrade(cfg, down)
    with eng.connect() as c:
        assert not {"source", "source_model"} & {x["name"] for x in sa.inspect(c).get_columns("expert_panelists")}
    eng.dispose()


# ------------------------------------------------------------------ 6. индекс доверия после жалобы
def test_complaint_lowers_trust_by_five_even_on_third_response(client):
    """Раньше жалоба не меняла индекс: отклонение с жалобой было третьим ответом, доля принятых из «мало ответов»
    (5 баллов) становилась посчитанной (10) — и съедала штраф −5."""
    from app.modules.demo.seed import _user
    from app.modules.invitations.models import Invitation
    from app.modules.profiles.models import CandidateProfile

    t = jury(client, "candidate_nofsp")
    inv = client.get("/api/candidate/invitations", headers=H(t)).json()
    mine = next(i for i in inv if i["position_title"] == "Backend-разработчик (платежи)")
    with SessionLocal() as db:  # ещё два принятых приглашения той же компании
        base = db.get(Invitation, uuid.UUID(mine["id"]))
        for k in range(2):
            u = _user(db, f"accepted-{k}@example.com", UserRole.candidate, "x")
            db.add(CandidateProfile(user_id=u.id))
            db.flush()
            db.add(Invitation(company_id=base.company_id, employer_user_id=base.employer_user_id,
                              candidate_user_id=u.id, position_title="Принято", offer_description="x",
                              salary_from=base.salary_from, salary_to=base.salary_to, contact_method="почта",
                              evidence={}, status="accepted",
                              expires_at=base.expires_at))
        db.commit()
    url = f"/api/candidate/invitations/{mine['id']}/trust"
    before = client.get(url, headers=H(t)).json()
    acc = next(f for f in before["factors"] if f["id"] == "acceptance")
    r = client.post(f"/api/candidate/invitations/{mine['id']}/complaint", headers=H(t), json={"reason": "role"})
    assert r.status_code == 201, r.text
    after = client.get(url, headers=H(t)).json()
    assert after["score"] == max(0, before["score"] - 5), (before["score"], after["score"])
    assert next(f for f in after["factors"] if f["id"] == "acceptance")["points"] == acc["points"]
    assert next(f for f in after["factors"] if f["id"] == "complaints")["points"] == -5


def test_trust_score_floor_is_zero(client, monkeypatch):
    from app.integrations.egrul import trust
    from app.modules.profiles.models import Company

    monkeypatch.setattr(trust, "complaints_factor",
                        lambda db, c: trust._factor("complaints", "Жалобы кандидатов", "bad", -100, 0, "много жалоб"))
    with SessionLocal() as db:
        c = Company(name="Пол индекса", is_demo=False)
        db.add(c)
        db.commit()
        assert trust.compute(db, c)["score"] == 0


# ------------------------------------------------------------------ 8. адрес демо-ATS внутри контейнера
def test_ats_stub_public_url_is_called_via_internal_base(monkeypatch):
    from app.integrations.ats import clients, providers
    from app.integrations.settings import get_isettings

    s = get_isettings()
    monkeypatch.setattr(s, "public_base_url", "https://site.example")
    monkeypatch.setattr(s, "ats_stub_base_url", "http://127.0.0.1:8000")
    assert providers.demo_base("talantix") == "https://site.example/api/ats-stub/talantix"  # хранится и видно
    assert clients.check_url("https://site.example/api/ats-stub/talantix/v1") == \
        "http://127.0.0.1:8000/api/ats-stub/talantix/v1"  # вызывается напрямую
    inner = "http://127.0.0.1:8000/api/ats-stub/webhook/k"
    assert clients.check_url(inner) == inner
    with pytest.raises(clients.AtsError):
        clients.check_url("http://127.0.0.1:8000/api/health")  # не заглушка — внутренняя сеть запрещена


# ------------------------------------------------------------------ 13. песочница жюри: приглашение и вакансии
def test_jury_maria_has_invitation_and_vacancies(client):
    from app.modules.jury import seed as jury_seed

    demo_companies()
    t = jury(client, "candidate")
    inv = client.get("/api/candidate/invitations", headers=H(t)).json()
    # без 150 демо-кандидатов Мария ещё и выигрывает кубок — на стенде приглашение одно
    route = [i for i in inv if i["position_title"] == "Python-разработчик (сервис маршрутов)"]
    assert len(route) == 1 and route[0]["company"]["name"] == jury_seed.COMPANY2, inv
    vac = client.get("/api/vacancies", headers=H(t)).json()
    assert (vac.get("items") if isinstance(vac, dict) else vac), vac
    # работодатель песочницы по-прежнему может пригласить Марию сам (лимит 30 дней — по компании). Приглашение
    # за кубок, выигранный в пустой базе, убираем — на стенде с демо-кандидатами Мария кубок не выигрывает.
    from app.modules.invitations.models import Invitation
    from app.modules.profiles.models import Company

    with SessionLocal() as db:
        cid = db.scalar(select(Company.id).where(Company.name == jury_seed.COMPANY))
        for i in db.scalars(select(Invitation).where(Invitation.company_id == cid)):
            if "Кубка" in i.offer_description:
                db.delete(i)
        db.commit()
    e = jury(client, "employer")
    me = client.get("/api/me", headers=H(t)).json()
    r = client.post("/api/employer/invitations", headers=H(e), json={
        "candidate_ref": me["candidate"]["public_ref"], "position_title": "Сценарий жюри",
        "offer_description": "Команда платежей, FastAPI и PostgreSQL", "salary_from": 240000, "salary_to": 280000,
        "contact_method": "почта"})
    assert r.status_code == 201, r.text


# ------------------------------------------------------------------ 4. θ в серверных текстах — с запятой
def test_theta_in_server_texts_uses_decimal_comma(client):
    from app.core.fmt import quoted, ru_num, theta_se
    from app.integrations.ats.profile import test_line
    from app.modules.assessment.engine import _explain

    assert theta_se(1.274, 0.488) == "+1,27 ± 0,49" and theta_se(-0.1) == "−0,10" and ru_num(None) == "—"
    # название факта кубка уже в кавычках — объяснение зонда без «Кубок «…»»
    assert quoted("Кубок «Платёжный шлюз»") == "Кубок «Платёжный шлюз»" and quoted("Ревью кода") == "«Ревью кода»"
    dec = {"confirmed": True, "upgrade_available": False, "retake_lower": None}
    assert "(θ = +0,73 ± 0,31)" in _explain(dec, 0.734, 0.31, "middle")
    assert "θ = −0,42 ± 0,30" in test_line({"test": {"correct": 7, "answered": 12, "theta": -0.42, "se": 0.3}})
    # доказательства приглашения Марии и объяснения подборки работодателя песочницы — без «θ = +1.65»
    demo_companies()
    t = jury(client, "candidate")
    texts = [e["text"] for i in client.get("/api/candidate/invitations", headers=H(t)).json() for e in i["evidence"]]
    from app.modules.matching.ranking import score_candidate
    from app.modules.profiles.facts import load_bundles

    with SessionLocal() as db:
        uid = uuid.UUID(client.get("/api/me", headers=H(t)).json()["id"])
        texts += [r["text"] for r in score_candidate(load_bundles(db, [uid])[uid], {})[2]]
    theta = [x for x in texts if "θ = " in x]
    assert theta, texts
    assert all(re.search(r"θ = [+−]\d+,\d\d ± \d+,\d\d", x) for x in theta), theta


# ------------------------------------------------------------------ 16. подпись источника экспертной разметки
CAPTION = ("Разметка выполнена моделью Claude Fable 5.1 в трёх независимых прогонах с разными ролями (тимлид Backend, "
           "Data/ML, QA/ИБ), без доступа к коду ранжирования и друг к другу; это проверка конвейера и методики, а не "
           "замена экспертной панели — реальных экспертов подключаем на этапе доработки.")


def _panel(db, codes=("E1", "E2", "E3")):
    from app.modules.demo.seed import _user
    from app.modules.experts import pack as P
    from app.modules.experts.models import ExpertPanelist

    for code in codes:
        u = _user(db, f"{code.lower()}@expert.example.com", UserRole.expert, code)
        db.add(ExpertPanelist(code=code, slot=code, user_id=u.id, pack=P.PACK, assignment={}))
    db.commit()


def test_expert_source_caption_depends_on_model_panel(client):
    from app.modules.experts.service import panel_status, set_source, source_summary

    with SessionLocal() as db:
        _panel(db)
        s = source_summary(panel_status(db))
        assert s["kind"] == "people" and s["title"] == "люди" and not s["model_panel"] and s["caption"] is None
        set_source(db, ["E1", "E2", "E3"], "model", "Claude Fable 5.1", ["тимлид Backend", "Data/ML", "QA/ИБ"])
        s = source_summary(panel_status(db))
        assert s["model_panel"] and s["title"] == "модель Claude Fable 5.1 в трёх ролях"
        assert s["caption"] == CAPTION
    ex = client.get("/api/validation/report").json()["experts"]
    assert ex["model_panel"] is True and ex["source"]["caption"] == CAPTION
    assert "тимлид" not in ex["status"]["text"]
    with SessionLocal() as db:  # в панели появился человек — модельная подпись исчезает
        set_source(db, ["E1"], "people")
        s = source_summary(panel_status(db))
        assert not s["model_panel"] and s["caption"] is None
        assert s["title"] == "люди (E1) и модель Claude Fable 5.1 в двух ролях (E2, E3)"
    ex = client.get("/api/validation/report").json()["experts"]
    assert ex["model_panel"] is False and ex["source"]["caption"] is None
    with SessionLocal() as db:
        with pytest.raises(Exception):
            set_source(db, ["E2"], "model", None)  # модель без названия — нельзя


def test_model_panel_view_neutral_verdicts_and_reference_angoff():
    from app.modules.experts import analysis as A
    from app.modules.experts.section import MODEL_AGREEMENT, MODEL_CAVEAT, model_panel_view

    cuts = dict(A.CURRENT_CUTS)
    res = {"agreement": {"A": {"alpha": 0.955, "alpha_verdict": "надёжно"},
                         "C": {"alpha": 0.95, "alpha_verdict": "надёжно"},
                         "B_controls": {"injection": {"n": 2, "flagged": 2}}},
           "llm": {"models": [], "choice": None},
           "angoff": {"boundaries": [{"boundary": "junior_middle", "angoff": 0.53, "replace_suggested": True}]}}
    out = model_panel_view(res)
    assert {out["agreement"][k]["alpha_verdict"] for k in ("A", "C")} == {MODEL_AGREEMENT}
    assert "надёжно" not in str(out["agreement"]) and out["agreement_caveat"] == MODEL_CAVEAT
    assert out["llm"]["reference"] == "консенсус модельной панели"
    assert out["angoff"]["reference_only"] and out["angoff"]["note"] == "справочно, модельная панель"
    assert A.CURRENT_CUTS == cuts  # текущие пороги не меняются
