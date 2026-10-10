"""Я15: устная защита развёрнутых ответов теста и ИИ-интервью этапом найма (заглушка продукта и порт движка)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.assessment.models import TestSession
from app.modules.interview import port as pt
from app.modules.interview import service as svc
from app.modules.interview.models import InterviewSession
from tests.test_day2_rules import H, INVITE, candidate_with_category, employer, my_ref

WRITTEN = ("Я бы сначала нормализовал телефоны и почты, затем сравнивал клиентов по ключам сопоставления: телефон, "
           "почта, ФИО с датой рождения. Дубликаты сливал бы транзакционно, сохраняя историю заказов, а спорные пары "
           "отправлял на ручную проверку. Мой контакт ivan.petrov@example.com, телефон +7 900 111-22-33.")
WRITTEN2 = ("Индекс по полю created_at ускорит выборку за период, но замедлит вставки; для отчёта по дням лучше "
            "составной индекс по статусу и дате, а старые партиции архивировать, чтобы не раздувать таблицу заказов.")


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(get_settings(), "interview_enabled", True)
    monkeypatch.setattr(get_settings(), "interview_engine", "stub")
    return get_settings()


def _open_item(pos: int, text: str, fmt: str = "open_answer") -> dict:
    it = {"position": pos, "format": fmt, "done": True, "canary": False, "skills": ["postgresql"],
          "public": {"stem": f"Задание {pos}. Опишите, как бы вы решили задачу. Подробно.", "code": None},
          "answers": {"1": {"value": text}}, "x": [0.8], "signals": {"paste_chars": 0}}
    if fmt == "open_book_3step":
        it["public"]["steps"] = [{"prompt": "шаг 1"}, {"prompt": "шаг 2"}, {"prompt": "Обоснуйте выбор"}]
        it["answers"] = {"1": {"value": 1}, "2": {"value": 2}, "3": {"value": text}}
        it["x"] = [1, 1, 0.7]
    return it


def _with_open_answers(client, t, texts=(WRITTEN, WRITTEN2), email="cand@example.com") -> str:
    from app.modules.auth.models import User

    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == email))
        ts = db.scalars(select(TestSession).where(TestSession.user_id == uid)
                        .order_by(TestSession.started_at.desc())).first()
        items = ts.result["state"].setdefault("items", [])
        items.append(_open_item(90, texts[0]))
        if len(texts) > 1:
            items.append(_open_item(91, texts[1], "open_book_3step"))
        items.append(_open_item(92, "коротко"))  # короче порога — не защищается
        flag_modified(ts, "result")
        db.commit()
        return str(ts.id)


def _talk(client, t, sid, answers):
    r = client.post(f"/api/interview/sessions/{sid}/begin", json={"channel": "text"}, headers=H(t))
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["status"] == "in_progress" and s["conversation"]["question"]
    for a in answers:
        if s["status"] != "in_progress":
            break
        txt = s["conversation"]["hint"] if a == "hint" else a
        s = client.post(f"/api/interview/sessions/{sid}/answer", json={"text": txt, "channel": "text"},
                        headers=H(t)).json()
    return s


def test_flag_off_hides_everything(client):
    t = candidate_with_category(client)
    ts = _with_open_answers(client, t)
    assert client.get("/api/meta").json()["interview"]["enabled"] is False
    st = client.get(f"/api/interview/defense/{ts}", headers=H(t)).json()
    assert st["enabled"] is False and st["can_start"] is False
    r = client.post(f"/api/interview/defense/{ts}", json={"name": "Иван", "consent": True}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "interview_disabled"
    te = employer(client)
    card = client.get(f"/api/employer/candidates/{my_ref(client, t)}", headers=H(te)).json()
    assert card["test"]["defense"] is None  # флаг выключен — значка нет


def test_defense_stub_flow_badge_and_pii(client, on):
    t = candidate_with_category(client)
    ts = _with_open_answers(client, t)
    st = client.get(f"/api/interview/defense/{ts}", headers=H(t)).json()
    assert st["enabled"] and st["eligible"] and st["can_start"] and st["answers_n"] == 2 and st["stub"]
    assert st["name_hint"] == "Иван" and st["minutes"] == 3 and "Грейд по тесту не меняется" in " ".join(st["consent"]["items"])
    assert client.post(f"/api/interview/defense/{ts}", json={"name": "Иван", "consent": False},
                       headers=H(t)).status_code == 422
    r = client.post(f"/api/interview/defense/{ts}", json={"name": "Иван Петров", "consent": True}, headers=H(t))
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    with SessionLocal() as db:
        row = db.get(InterviewSession, uuid.UUID(sid))
        ctx = row.state["ctx"]
        dumped = str(ctx)
        # в движок — только свои ответы и темы, без контактов; короткий ответ не защищается
        assert "ivan.petrov@example.com" not in dumped and "111-22-33" not in dumped and "[почта]" in dumped
        assert [x["id"] for x in ctx["tasks"]] == ["t90", "t91"] and ctx["grade"] == "middle"
        assert "rubric" not in dumped and "Петров" not in row.state.get("name", "")
    # повторный старт при активной сессии — та же сессия
    assert client.post(f"/api/interview/defense/{ts}", json={"name": "Иван", "consent": True},
                       headers=H(t)).json()["id"] == sid
    s = _talk(client, t, sid, ["hint", "Меня зовут Иван Петров. " + WRITTEN2, "hint", "hint"])
    assert s["status"] == "completed", s
    assert s["verdict"] == "confirmed" and s["verdict_title"] == "Ответ подтверждён устно" and s["stub"]
    assert s["conversation"] is None and s["transcript"] is None  # кандидату расшифровка не отдаётся
    # значок на карточке и подробности у работодателя
    te = employer(client)
    ref = my_ref(client, t)
    card = client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()
    assert card["test"]["defense"]["verdict"] == "confirmed" and card["test"]["defense"]["title"] == "Ответ подтверждён устно"
    d = client.get(f"/api/interview/candidates/{ref}", headers=H(te)).json()
    assert d["enabled"] and d["defense"]["verdict"] == "confirmed" and d["defense"]["questions"]
    said = " ".join(x["text"] for x in d["defense"]["transcript"] if x["who"] == "candidate")
    assert "Петров" not in said and "Иван" not in said  # имя из профиля вычищено до отправки в модели
    for q in d["defense"]["questions"]:
        for c in q["quotes"]:
            assert c["text"] in said  # цитаты только из расшифровки
    # вторая защита той же попытки — нельзя (кроме жюри)
    r = client.post(f"/api/interview/defense/{ts}", json={"name": "Иван", "consent": True}, headers=H(t))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "defense_done"
    # удаление записи — значок снова «не проходил»
    assert client.delete(f"/api/interview/sessions/{sid}", headers=H(t)).json() == {"deleted": True}
    card = client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()
    assert card["test"]["defense"]["verdict"] is None and card["test"]["defense"]["title"] == "Устную защиту не проходил"


def test_defense_discrepancies_and_not_eligible(client, on):
    t = candidate_with_category(client)
    ts = _with_open_answers(client, t)
    sid = client.post(f"/api/interview/defense/{ts}", json={"name": "Иван", "consent": True}, headers=H(t)).json()["id"]
    off = "Честно, не помню, что там писал, наверное взял готовое решение и оно как-то заработало само по себе."
    s = _talk(client, t, sid, [off, off, off])
    assert s["status"] == "completed" and s["verdict"] == "discrepancies", s
    t2 = candidate_with_category(client, email="c2@example.com")
    ts2 = _with_open_answers(client, t2, texts=("короткий ответ",), email="c2@example.com")
    st = client.get(f"/api/interview/defense/{ts2}", headers=H(t2)).json()
    assert not st["eligible"] and "120" in st["reason"]
    r = client.post(f"/api/interview/defense/{ts2}", json={"name": "Анна", "consent": True}, headers=H(t2))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "insufficient_context"
    # чужая попытка — 404
    assert client.get(f"/api/interview/defense/{ts}", headers=H(t2)).status_code == 404


def test_early_finish_and_cancel(client, on):
    t = candidate_with_category(client)
    ts = _with_open_answers(client, t)
    sid = client.post(f"/api/interview/defense/{ts}", json={"name": "Иван", "consent": True}, headers=H(t)).json()["id"]
    assert client.post(f"/api/interview/sessions/{sid}/finish", headers=H(t)).json()["status"] == "cancelled"
    # отменённая без ответов — можно ещё раз (попыток 2)
    st = client.get(f"/api/interview/defense/{ts}", headers=H(t)).json()
    assert st["can_start"] and st["attempts_left"] == 1


def test_jury_limit_one_live_per_hour(client, on, monkeypatch):
    t = candidate_with_category(client)
    ts = _with_open_answers(client, t)
    monkeypatch.setattr(svc, "jury_key", lambda user: "sbxtest01")
    st = client.get(f"/api/interview/defense/{ts}", headers=H(t)).json()
    assert st["jury"] == {"live_per_hour": 1, "max_minutes": 5} and st["attempts_left"] is None
    sid = client.post(f"/api/interview/defense/{ts}", json={"name": "Мария", "consent": True}, headers=H(t)).json()["id"]
    _talk(client, t, sid, ["hint", "hint", "hint"])
    r = client.post(f"/api/interview/defense/{ts}", json={"name": "Мария", "consent": True}, headers=H(t))
    assert r.status_code == 429 and r.json()["detail"]["code"] == "jury_limit"


def test_example_seed_label_and_badge(client, on):
    t = candidate_with_category(client)
    _with_open_answers(client, t)
    from app.modules.interview.demo import seed_jury_defense
    from app.modules.profiles.models import CandidateProfile

    with SessionLocal() as db:
        p = db.scalars(select(CandidateProfile)).first()
        seed_jury_defense(db, p)
        db.commit()
    tsid = None
    with SessionLocal() as db:
        row = db.scalars(select(InterviewSession).where(InterviewSession.is_example.is_(True))).one()
        assert row.status == "completed" and row.verdict == "confirmed" and row.engine == "example"
        tsid = str(row.test_session_id)
    st = client.get(f"/api/interview/defense/{tsid}", headers=H(t)).json()
    assert st["session"] is None and st["example"]["example_label"] == "пример, модельный кандидат"
    te = employer(client)
    card = client.get(f"/api/employer/candidates/{my_ref(client, t)}", headers=H(te)).json()
    assert card["test"]["defense"]["example"] is True and card["test"]["defense"]["verdict"] == "confirmed"
    cell = svc.compare_cell(card["test"]["defense"])
    assert cell["status"] == "confirmed" and "пример, модельный кандидат" in cell["text"]
    assert svc.compare_cell(None)["text"] == "Устную защиту не проходил"


def test_hiring_ai_interview_stage(client, on):
    tc = candidate_with_category(client)
    te = employer(client)
    inv = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": my_ref(client, tc)},
                      headers=H(te)).json()
    st = client.get(f"/api/employer/invitations/{inv['id']}/ai-interview", headers=H(te)).json()
    assert not st["can_invite"] and st["reason"]  # до принятия — нельзя
    assert client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc)).status_code == 200
    r = client.post(f"/api/employer/invitations/{inv['id']}/ai-interview", json={}, headers=H(te))
    assert r.status_code == 422  # потребности нет — навыки вручную
    r = client.post(f"/api/employer/invitations/{inv['id']}/ai-interview",
                    json={"skills": ["Kafka", "Код-ревью"], "note": "10 минут, без подготовки"}, headers=H(te))
    assert r.status_code == 201, r.text
    assert r.json()["session"]["status"] == "invited" and r.json()["session"]["skills"] == ["Kafka", "Код-ревью"]
    assert client.post(f"/api/employer/invitations/{inv['id']}/ai-interview", json={"skills": ["Kafka"]},
                       headers=H(te)).status_code == 409
    cs = client.get(f"/api/candidate/invitations/{inv['id']}/ai-interview", headers=H(tc)).json()
    assert cs["session"]["status"] == "invited" and cs["consent"]["items"] and cs["session"]["note"] is None
    r = client.post(f"/api/candidate/invitations/{inv['id']}/ai-interview", json={"name": "Иван", "consent": True},
                    headers=H(tc))
    assert r.status_code == 201, r.text
    long = "В прошлом проекте я настраивал консьюмеров Kafka с ручным коммитом смещений, разбирал задержки и " * 3
    s = _talk(client, tc, r.json()["id"], [long, "Делал ревью каждый день, договаривались о правилах в команде."])
    # кандидату — только статус: итог ИИ-интервью видит пригласившая компания
    assert s["status"] == "completed" and s["result_hidden"] and s["verdict"] is None and not s["questions"], s
    st = client.get(f"/api/employer/invitations/{inv['id']}/ai-interview", headers=H(te)).json()
    assert st["session"]["status"] == "completed" and st["session"]["transcript"] and st["session"]["note"]
    assert st["session"]["verdict"] in ("strong", "medium") and not st["session"]["result_hidden"]
    d = client.get(f"/api/interview/candidates/{my_ref(client, tc)}", headers=H(te)).json()
    assert d["interviews"] and d["interviews"][0]["mode"] == "interview"
    # другая компания результата не видит
    te2 = employer(client, email="hr2@corp.ru", company="ООО Василёк")
    assert client.get(f"/api/employer/invitations/{inv['id']}/ai-interview", headers=H(te2)).status_code == 404
    assert client.get(f"/api/interview/candidates/{my_ref(client, tc)}", headers=H(te2)).json()["interviews"] == []


def _fake_engine():
    """Дублёр движка по engine/CONTRACT.md v1.0 (Я14): те же имена и формы, без моделей."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from pydantic import BaseModel

    class Transcript(BaseModel):
        items: list[dict] = []

    class Ctx(BaseModel):
        model_config = {"extra": "allow"}

    class SessionSpec(BaseModel):
        mode: str
        candidate_name: str
        duration_min: int
        max_questions: int
        jury: bool = False
        context: Ctx
        started_at: datetime | None = None

    class TurnInput(BaseModel):
        spec: SessionSpec
        transcript: Transcript
        candidate_text: str | None = None
        channel: str = "text"

    def next_turn(ti):
        items = list(ti.transcript.items)
        if ti.candidate_text:
            items.append({"who": "candidate", "text": ti.candidate_text, "n": sum(i["who"] == "candidate" for i in items) + 1})
        asked = sum(i["who"] == "interviewer" and i.get("kind") == "question" for i in items)
        fin = asked >= 2
        text = "Спасибо, всё." if fin else ("Почему так?" if asked == 0 else "А что если строже?")
        items.append({"who": "interviewer", "text": text, "kind": "closing" if fin else "question", "k": asked + 1})
        return SimpleNamespace(text=text, finished=fin, transcript=Transcript(items=items), source="llm", cost_usd=0.01,
                               started_at=datetime.now(timezone.utc) if ti.candidate_text else None)

    def evaluate(spec, tr):
        said = [i["text"] for i in tr.items if i["who"] == "candidate"]
        q = SimpleNamespace(k=1, task_id="t90", skill=None, question="Почему так?", answer_excerpt=said[0][:400],
                            level="confirmed", reasoning="совпадает", lowered=False,
                            quotes=[SimpleNamespace(n=1, text=said[0][:30]), SimpleNamespace(n=1, text="этого не говорил")])
        return SimpleNamespace(verdict="confirmed", verdict_label="подтверждено устно", score=81, summary="Уверенно.",
                               questions=[q], flags=[], coverage=100, removed_quotes=2, source="llm", cost_usd=0.1)

    def stt(audio, mime):
        return SimpleNamespace(text="распознанный ответ про индексы", seconds=3.0, cost_usd=0.002, stub=False)

    def tts(text, fmt="mp3"):
        return SimpleNamespace(data=b"ID3fake", mime="audio/mpeg", cost_usd=0.003, stub=False)

    def avatar_token():
        return SimpleNamespace(session_token="tok-test", ice_servers=[{"urls": "turn:example"}], max_seconds=420,
                               relay_only=False, persona_name="Интервьюер")

    limits = {"calls": []}

    def check_limits(jury, last_hour, spent):
        limits["calls"].append((jury, last_hour, spent))

    return SimpleNamespace(
        Transcript=Transcript, SessionSpec=SessionSpec, TurnInput=TurnInput, DefenseContext=Ctx, InterviewContext=Ctx,
        normalize_spec=lambda spec: spec, next_turn=next_turn, evaluate=evaluate, stt=stt, tts=tts,
        avatar_token=avatar_token, check_limits=check_limits, is_stub=lambda: False, limits=limits,
        status=lambda: {"stub": False, "channels": {"text": True, "voice": True, "stt": True, "avatar": True}},
        plan=lambda spec: [])


def test_engine_port_channels_and_quote_check(client, on, monkeypatch):
    eng = _fake_engine()
    monkeypatch.setattr(pt, "get_port", lambda: pt.EnginePort(eng))
    t = candidate_with_category(client)
    ts = _with_open_answers(client, t)
    sid = client.post(f"/api/interview/defense/{ts}", json={"name": "Иван", "consent": True}, headers=H(t)).json()["id"]
    a = client.post(f"/api/interview/sessions/{sid}/avatar", headers=H(t)).json()
    assert a["session_token"] == "tok-test" and "sdk_url" not in a  # SDK — из бандла, не с CDN
    s = client.post(f"/api/interview/sessions/{sid}/begin", json={"channel": "avatar"}, headers=H(t)).json()
    assert s["conversation"]["channels"] == {"avatar": True, "voice": True, "text": True} and s["conversation"]["hint"] is None
    sp = client.get(f"/api/interview/sessions/{sid}/speech", headers=H(t))
    assert sp.status_code == 200 and sp.headers["content-type"] == "audio/mpeg"
    tr = client.post(f"/api/interview/sessions/{sid}/transcribe", content=b"\x1a\x45\xdf\xa3",
                     headers={**H(t), "Content-Type": "audio/webm"})
    assert tr.json() == {"text": "распознанный ответ про индексы"}
    client.post(f"/api/interview/sessions/{sid}/channel", json={"channel": "voice"}, headers=H(t))
    client.post(f"/api/interview/sessions/{sid}/answer", json={"text": "Потому что индекс по дате ускоряет отчёт",
                                                               "channel": "voice"}, headers=H(t))
    s = client.post(f"/api/interview/sessions/{sid}/answer", json={"text": "Добавил бы партиции", "channel": "text"},
                    headers=H(t)).json()
    s = client.get(f"/api/interview/sessions/{sid}", headers=H(t)).json()  # оценка — в фоне (TestClient дождался)
    assert s["status"] == "completed" and s["verdict"] == "confirmed" and not s["stub"]
    q = s["questions"][0]
    assert [c["text"] for c in q["quotes"]] == ["Потому что индекс по дате уско"]  # выдуманная цитата отброшена
    assert eng.limits["calls"] == [(False, 0, 0.0)]  # лимиты движка спрошены при создании
    with SessionLocal() as db:
        row = db.get(InterviewSession, uuid.UUID(sid))
        assert row.result["quotes_dropped"] == 1 and row.result["channels"] == ["avatar", "voice", "text"]
        assert row.result["quotes_removed_by_engine"] == 2 and row.result["source"] == "llm"
        # модель: 3 хода по 0,01 + оценка 0,1; распознавание 0,002 и голос 0,003 — посчитаны продуктом
        assert row.state == {} and row.cost["usd"] == pytest.approx(0.135) and row.cost["stt_usd"] == 0.002


def test_stub_channels_unavailable(client, on):
    t = candidate_with_category(client)
    ts = _with_open_answers(client, t)
    sid = client.post(f"/api/interview/defense/{ts}", json={"name": "Иван", "consent": True}, headers=H(t)).json()["id"]
    assert client.post(f"/api/interview/sessions/{sid}/avatar", headers=H(t)).status_code == 503
    client.post(f"/api/interview/sessions/{sid}/begin", json={"channel": "text"}, headers=H(t))
    assert client.get(f"/api/interview/sessions/{sid}/speech", headers=H(t)).status_code == 503
    r = client.post(f"/api/interview/sessions/{sid}/transcribe", content=b"x", headers={**H(t), "Content-Type": "audio/webm"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "stt_unavailable"


def test_openapi_has_interview_models(client):
    sch = client.get("/api/openapi.json").json()
    op = sch["paths"]["/api/interview/defense/{test_session_id}"]["post"]
    assert op["tags"] == ["interview"] and "$ref" in str(op["responses"]["201"])
    assert any(t["name"] == "interview" for t in sch["tags"])


def test_criteria_link_only_with_flag(on, monkeypatch):
    from app.modules.validation import criteria as C

    assert C.INTERVIEW_GO in C.build()["criteria"][1]["items"][0]["do"]
    monkeypatch.setattr(get_settings(), "interview_enabled", False)
    assert C.INTERVIEW_GO not in C.build()["criteria"][1]["items"][0]["do"]
    assert "docs/INTERVIEW.md" in C.markdown()  # строка документа — всегда, от флага не зависит


def test_auto_picks_engine_when_present(monkeypatch):
    """INTERVIEW_ENGINE=auto: есть пакет engine/ (Я14) — порт движка, а не заглушка продукта; нет — заглушка."""
    import sys

    import app.modules.interview as pkg
    from app.modules.interview import port as pt

    monkeypatch.setattr(get_settings(), "interview_engine", "auto")
    eng = _fake_engine()
    monkeypatch.setattr(pkg, "engine", eng, raising=False)
    monkeypatch.setitem(sys.modules, "app.modules.interview.engine", eng)
    p = pt.get_port()
    assert isinstance(p, pt.EnginePort) and p.name == "engine" and not pt.is_stub()
    monkeypatch.setattr(get_settings(), "interview_engine", "stub")
    assert isinstance(pt.get_port(), pt.StubPort)  # явная заглушка — всегда своя
    monkeypatch.setattr(get_settings(), "interview_engine", "auto")
    monkeypatch.delattr(pkg, "engine")
    monkeypatch.setitem(sys.modules, "app.modules.interview.engine", None)  # пакета нет → ImportError
    assert isinstance(pt.get_port(), pt.StubPort) and pt.is_stub()
