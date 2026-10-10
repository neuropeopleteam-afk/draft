"""Движок ИИ-интервьюера (backend/app/modules/interview/engine): чистые функции, заглушка, сверка цитат, таблица
вердикта, адаптеры поставщиков с подменённым HTTP. Моделей и сети тесты не требуют."""
import importlib
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.modules.interview import engine as e
ev = importlib.import_module("app.modules.interview.engine.evaluate")  # функция evaluate затеняет подмодуль
from app.modules.interview.engine.providers import avatar as av
from app.modules.interview.engine.providers import relay, stt, tts
from app.modules.interview.engine.rules import plural
from app.modules.interview.engine.textnorm import contains, normalize, overlap

LONG = ("Я добавил индекс по колонке user_id, потому что все запросы фильтруют по ней, а план показывал полный просмотр. "
        "Проверял через EXPLAIN ANALYZE до и после: время упало с 800 мс до 5 мс. Альтернатива — денормализация, но она "
        "усложнила бы запись.")


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    monkeypatch.setenv("INTERVIEW_STUB", "1")
    e.reset_interview_settings()
    yield
    e.reset_interview_settings()


def defense_spec(**kw) -> e.SessionSpec:
    tasks = kw.pop("tasks", None) or [
        e.TaskContext(id="t1", title="Индексы", topics=["индексы", "план запроса"], answer=LONG, integrity_flags=["paste"]),
        e.TaskContext(id="t2", title="Кэш", answer="слишком коротко"),
        e.TaskContext(id="t3", title="Очереди", answer="Очередь нужна, чтобы развязать производителя и потребителя; при пике "
                      "сообщения копятся, а обработчик разгребает их в своём темпе. Проверял нагрузочным тестом на 10 тысяч сообщений."),
    ]
    return e.SessionSpec(mode="defense", candidate_name=kw.pop("name", "Иван"),
                         context=e.DefenseContext(role="backend", grade="middle", tasks=tasks), **kw)


def interview_spec(**kw) -> e.SessionSpec:
    return e.SessionSpec(mode="interview", candidate_name="Анна", context=e.InterviewContext(
        need_title="Аналитик данных", unconfirmed_skills=[e.SkillContext(name="SQL"), e.SkillContext(name="Переговоры")]), **kw)


# --- нормализация и план -------------------------------------------------------------------------------------------

def test_normalize_defaults_and_jury_cap():
    s = e.normalize_spec(defense_spec())
    assert (s.duration_min, s.max_questions) == (4, 3)
    assert [t.id for t in s.context.tasks] == ["t1", "t3"]  # короткий ответ отброшен
    j = e.normalize_spec(interview_spec(duration_min=15, max_questions=20, jury=True))
    assert j.duration_min == 5 and j.max_questions == 8
    assert e.normalize_spec(interview_spec(duration_min=1)).duration_min == 5


def test_normalize_errors():
    with pytest.raises(e.EngineError) as ei:
        e.normalize_spec(defense_spec(tasks=[e.TaskContext(id="a", title="x", answer="мало")]))
    assert ei.value.code == "insufficient_context" and ei.value.status == 422
    with pytest.raises(e.EngineError) as ei:
        e.normalize_spec(e.SessionSpec(mode="interview", candidate_name="А", context=e.InterviewContext(need_title="x", unconfirmed_skills=[])))
    assert ei.value.code == "insufficient_context"
    with pytest.raises(e.EngineError) as ei:
        e.normalize_spec(e.SessionSpec(mode="defense", candidate_name="А", context=e.InterviewContext(need_title="x", unconfirmed_skills=[e.SkillContext(name="s")])))
    assert ei.value.code == "bad_request"


def test_plan_flags_first_then_rotates_angles():
    s = e.normalize_spec(defense_spec(max_questions=4))
    p = e.plan(s)
    assert [x.task_id for x in p] == ["t1", "t3", "t1", "t3"]  # задание с признаком — первым
    assert p[0].angle != p[2].angle and p[0].k == 1 and p[3].k == 4
    pi = e.plan(e.normalize_spec(interview_spec(max_questions=3)))
    assert [x.skill for x in pi] == ["SQL", "Переговоры", "SQL"]


def test_plural():
    assert plural(1, "вопрос", "вопроса", "вопросов") == "1 вопрос"
    assert plural(3, "вопрос", "вопроса", "вопросов") == "3 вопроса"
    assert plural(5, "вопрос", "вопроса", "вопросов") == "5 вопросов"
    assert plural(11, "вопрос", "вопроса", "вопросов") == "11 вопросов"


# --- ход разговора (заглушка) ------------------------------------------------------------------------------------------

def run_dialog(spec, replies, step_s=40):
    now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    out = e.next_turn(e.TurnInput(spec=spec, transcript=e.Transcript(), now=now))
    assert out.kind == "opening" and out.k == 1 and not out.finished and out.started_at is None
    for i, r in enumerate(replies):
        out = e.next_turn(e.TurnInput(spec=spec, transcript=out.transcript, candidate_text=r, now=now + timedelta(seconds=step_s * (i + 1))))
        spec = spec.model_copy(update={"started_at": out.started_at})
    return spec, out


def test_turn_loop_stub_defense():
    spec = e.normalize_spec(defense_spec())
    spec, out = run_dialog(spec, ["Поставил индекс по user_id, потому что фильтруем по этой колонке.",
                                  "Очередь развязывает производителя и потребителя, пик копится в очереди.",
                                  "Альтернатива — денормализация, но запись усложнится."])
    assert out.kind == "closing" and out.finished and out.source == "stub"
    assert "Иван" in out.text and "не меняется" in out.text
    assert out.transcript.questions_asked() == 3 and len(out.transcript.candidate_items()) == 3
    assert [u.n for u in out.transcript.candidate_items()] == [1, 2, 3]
    with pytest.raises(e.EngineError) as ei:
        e.next_turn(e.TurnInput(spec=spec, transcript=out.transcript, candidate_text="ещё"))
    assert ei.value.code == "finished" and ei.value.status == 409


def test_turn_time_limit_closes_early():
    spec = e.normalize_spec(defense_spec(max_questions=4))
    now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    out = e.next_turn(e.TurnInput(spec=spec, transcript=e.Transcript(), now=now))
    out = e.next_turn(e.TurnInput(spec=spec, transcript=out.transcript, candidate_text="ответ раз", now=now))
    spec = spec.model_copy(update={"started_at": out.started_at})
    out = e.next_turn(e.TurnInput(spec=spec, transcript=out.transcript, candidate_text="ответ два", now=now + timedelta(minutes=4, seconds=1)))
    assert out.kind == "closing"


def test_turn_repeat_and_validation():
    spec = e.normalize_spec(defense_spec())
    out = e.next_turn(e.TurnInput(spec=spec, transcript=e.Transcript()))
    rep = e.next_turn(e.TurnInput(spec=spec, transcript=out.transcript, repeat=True))
    assert rep.kind == "repeat" and rep.transcript.questions_asked() == 1 and rep.text.startswith("Повторю")
    with pytest.raises(e.EngineError) as ei:
        e.next_turn(e.TurnInput(spec=spec, transcript=out.transcript, candidate_text=""))
    assert ei.value.code == "bad_request"
    with pytest.raises(e.EngineError):
        e.next_turn(e.TurnInput(spec=spec, transcript=out.transcript, candidate_text="x" * 6001))


def test_turn_interview_opening_mentions_skill_and_time():
    spec = e.normalize_spec(interview_spec(max_questions=3, duration_min=5))
    out = e.next_turn(e.TurnInput(spec=spec, transcript=e.Transcript()))
    assert "Анна" in out.text and "SQL" in out.text and "3 коротких вопроса" in out.text and "5 минут" in out.text


# --- сверка цитат и вердикт ----------------------------------------------------------------------------------------------

def test_textnorm():
    assert normalize("Ёж, EXPLAIN  ANALYZE!") == "еж explain analyze"
    assert contains("Я поставил индекс по user_id, потому что фильтруем.", "индекс по user_id")
    assert not contains("Я поставил индекс.", "кэш")
    assert overlap("индекс запрос план", "план запроса показывал индекс") > 0.5


def test_verify_quotes_drops_unknown_and_relinks():
    tr = e.Transcript(items=[
        e.Utterance(who="candidate", text="Поставил индекс по user_id, потому что фильтруем по колонке.", at=datetime.now(timezone.utc), n=1),
        e.Utterance(who="candidate", text="Очередь развязывает производителя и потребителя.", at=datetime.now(timezone.utc), n=2),
    ])
    kept, removed = e.verify_quotes([{"n": 1, "text": "индекс по user_id"}, {"n": 1, "text": "развязывает производителя"},
                                     {"n": 2, "text": "этого не говорил"}, {"n": 9, "text": "кор"}, "мусор",
                                     {"n": 1, "text": "индекс по user_id"}], tr)
    assert [(q.n, q.text) for q in kept] == [(1, "индекс по user_id"), (2, "развязывает производителя")]
    assert removed == 3


@pytest.mark.parametrize("mode,levels,answers,chars,expected", [
    ("defense", ["confirmed", "confirmed", "partial"], 3, 500, ("confirmed", 87)),
    ("defense", ["confirmed", "discrepancy", "confirmed"], 3, 500, ("discrepancies", 70)),
    ("defense", ["partial", "partial", "no_data"], 3, 500, ("insufficient", None)),
    ("defense", ["confirmed", "confirmed"], 1, 500, ("insufficient", None)),
    ("defense", ["confirmed", "confirmed"], 2, 100, ("insufficient", None)),
    ("defense", ["no_data", "no_data"], 2, 500, ("insufficient", None)),
    ("defense", ["partial", "partial", "partial"], 3, 500, ("insufficient", None)),
    ("defense", ["partial", "discrepancy"], 2, 500, ("discrepancies", 35)),
    ("interview", ["strong", "medium", "strong"], 3, 500, ("strong", 87)),
    ("interview", ["medium", "medium", "weak"], 3, 500, ("medium", 48)),
    ("interview", ["weak", "weak", "no_data"], 3, 500, ("weak", 25)),
])
def test_verdict_table(mode, levels, answers, chars, expected):
    v, score, label = e.verdict_from_levels(mode, levels, answers, chars)
    assert (v, score) == expected and label


def test_evaluate_stub_defense_confirmed_and_lowering():
    spec = e.normalize_spec(defense_spec())
    spec, out = run_dialog(spec, [
        "Запросы всегда фильтруют по user_id, а план показывал seq scan — поэтому поставил btree-индекс именно на эту колонку. Сравнивал через EXPLAIN ANALYZE: было около 800 мс, стало единицы миллисекунд.",
        "Очередь буферизует пик: производитель кладёт сообщения и не ждёт, а обработчик забирает их со своей скоростью. Гонял нагрузочный тест на десяти тысячах сообщений, задержка была стабильной.",
        "Денормализацию отбросил, потому что при каждой записи пришлось бы обновлять копии данных — это усложняет запись и даёт шанс рассинхронизации; индекс дешевле.",
    ])
    v = e.evaluate(spec, out.transcript)
    assert v.verdict == "confirmed" and v.verdict_label == "подтверждено устно" and v.score and v.score >= 70
    assert v.source == "stub" and v.coverage == 100 and all(q.quotes for q in v.questions)
    assert v.questions[0].question.startswith("Здравствуйте") and v.questions[0].answer_excerpt.startswith("Запросы всегда")


def test_rules_verbatim_and_vague_are_partial():
    spec = e.normalize_spec(defense_spec())
    spec, out = run_dialog(spec, [LONG[:150], "В целом главное, чтобы очередь работала быстро, наверное, так и сделал бы, подробно не скажу.",
                                  "Я добавил индекс по колонке user_id, потому что все запросы фильтруют по ней, а план показывал полный просмотр."])
    v = e.evaluate(spec, out.transcript)
    assert [q.level for q in v.questions] == ["partial", "partial", "partial"] and v.verdict == "insufficient"
    assert "дословный" in v.questions[0].reasoning and "Общие слова" in v.questions[1].reasoning


def test_evaluate_short_dialog_insufficient():
    spec = e.normalize_spec(defense_spec())
    spec, out = run_dialog(spec, ["не помню", "не знаю", "ну"])
    v = e.evaluate(spec, out.transcript)
    assert v.verdict == "insufficient" and v.score is None and v.flags


def test_build_lowers_level_without_quotes_and_skeptic_merge():
    spec = e.normalize_spec(defense_spec())
    spec, out = run_dialog(spec, ["Поставил индекс по user_id, потому что фильтруем по этой колонке, план показывал полный просмотр." * 2,
                                  "Очередь развязывает производителя и потребителя, пик копится в очереди и разбирается потом." * 2,
                                  "Денормализация усложнила бы запись, поэтому индекс." * 3])
    raw = {"questions": [{"k": 1, "level": "confirmed", "quotes": [{"n": 1, "text": "такого не было"}], "reasoning": "ок"},
                         {"k": 2, "level": "discrepancy", "quotes": [], "reasoning": "путается"},
                         {"k": 3, "level": "confirmed", "quotes": [{"n": 3, "text": "усложнила бы запись"}]}],
           "flags": ["  "], "summary": "Итого."}
    v = ev._build(spec, out.transcript, raw, "llm", None, 0.0, None)
    assert v.questions[0].level == "no_data" and v.questions[0].lowered
    assert v.questions[1].level == "partial" and v.questions[1].lowered  # расхождение без цитаты → частично
    assert v.questions[2].level == "confirmed" and not v.questions[2].lowered
    assert v.removed_quotes == 1 and v.flags == [] and v.summary == "Итого."
    merged = ev._apply_remarks(
        {"questions": [{"k": 1, "level": "confirmed", "quotes": []}, {"k": 2, "level": "weak_typo", "quotes": []}]},
        {"remarks": [{"k": 1, "issue": "пересказ наизусть", "level": "partial"},
                     {"k": 2, "issue": "ответ по теме есть", "level": "confirmed", "quote": {"n": 2, "text": "очередь развязывает"}},
                     {"k": 3, "level": "confirmed"}, {"k": "x"}, "мусор"]}, "defense")
    assert merged["questions"][0]["level"] == "partial" and "Скептик" in merged["questions"][0]["reasoning"]
    assert merged["questions"][1]["level"] == "confirmed" and merged["questions"][1]["quotes"] == [{"n": 2, "text": "очередь развязывает"}]
    # повышение без цитаты не принимается
    m2 = ev._apply_remarks({"questions": [{"k": 1, "level": "partial", "quotes": []}]}, {"remarks": [{"k": 1, "level": "confirmed"}]}, "defense")
    assert m2["questions"][0]["level"] == "partial"


# --- лимиты и стоимость -------------------------------------------------------------------------------------------------

def test_limits():
    now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    e.check_limits(False, [{"created_at": now, "active": True}], 0.0, now)  # не жюри — без ограничения
    e.check_limits(True, [], 0.0, now)
    with pytest.raises(e.EngineError) as ei:
        e.check_limits(True, [{"created_at": now - timedelta(minutes=10), "active": False}], 0.0, now)
    assert ei.value.code == "jury_limit" and ei.value.status == 429 and 2990 <= ei.value.retry_after <= 3000
    with pytest.raises(e.EngineError) as ei:
        e.check_limits(False, None, 15.0, now)
    assert ei.value.code == "daily_cap" and ei.value.to_dict()["retry_after"] == 3600


def test_cost_estimates():
    assert e.estimate_cost("tts", 1000) == pytest.approx(0.15)
    assert e.estimate_cost("stt", 60) == pytest.approx(0.0077)
    assert e.estimate_cost("avatar", 300) == pytest.approx(0.75)
    assert e.estimate_cost("tts", 0) == 0.0 and e.estimate_cost("other", 10) == 0.0


def test_status_has_no_secrets(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "secret-value-xyz")
    e.reset_interview_settings()
    st = e.status()
    assert st["stub"] is True and st["label"] == "модель, не люди"
    assert "secret-value-xyz" not in repr(st)


# --- адаптеры поставщиков (HTTP подменён) -------------------------------------------------------------------------------

def test_stub_providers():
    a = e.tts("Проверка связи", "pcm_24000")
    assert a.stub and a.sample_rate == 16000 and len(a.data) > 0 and a.cost_usd == 0
    assert e.tts("x", "mp3").stub
    with pytest.raises(e.EngineError):
        e.tts("", "mp3")
    t = e.stt(b"\0" * 32000, stub_text="привет")
    assert t.stub and t.text == "привет" and t.seconds == 2.0
    with pytest.raises(e.EngineError) as ei:
        e.avatar_token()
    assert ei.value.code == "avatar_unavailable" and ei.value.status == 503


def _live(monkeypatch, **env):
    monkeypatch.setenv("INTERVIEW_STUB", "0")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    e.reset_interview_settings()


def test_relay_route(monkeypatch):
    _live(monkeypatch, INTERVIEW_RELAY_URL="https://relay.example:18743", INTERVIEW_RELAY_TOKEN="rt")
    r = relay.route("api.deepgram.com", "/v1/listen?model=nova-3", {"Authorization": "Token k"})
    assert r.url == "https://relay.example:18743/v1/listen?model=nova-3"
    assert r.headers["X-Relay-Host"] == "api.deepgram.com" and r.headers["X-Relay-Token"] == "rt" and r.headers["Authorization"] == "Token k"
    monkeypatch.delenv("INTERVIEW_RELAY_URL")
    monkeypatch.delenv("INTERVIEW_RELAY_TOKEN")
    monkeypatch.setattr(relay, "get_settings", lambda: type("S", (), {"llm_relay_url": "https://relay.example:18743/api/v1", "llm_relay_token": "lt",
                                                                    "llm_relay_ca_file": None, "llm_relay_ca_pem_b64": None})())
    e.reset_interview_settings()
    r2 = relay.route("api.anam.ai", "/v1/auth/session-token")  # общий LLM_RELAY_URL: хвост /api/v1 отрезается
    assert r2.url == "https://relay.example:18743/v1/auth/session-token" and r2.headers["X-Relay-Token"] == "lt" and r2.verify is True
    monkeypatch.setattr(relay, "get_settings", lambda: type("S", (), {"llm_relay_url": None, "llm_relay_token": None,
                                                                    "llm_relay_ca_file": None, "llm_relay_ca_pem_b64": None})())
    assert relay.route("api.anam.ai", "/v1/auth/session-token").url == "https://api.anam.ai/v1/auth/session-token"
    assert relay.relay_root("https://r:1/api/v1/") == "https://r:1" and relay.relay_root("https://r:1") == "https://r:1"


def _fake_request(monkeypatch, handler):
    calls = []

    def fake(method, host, path, *, headers=None, json=None, content=None, timeout_s=30.0):
        calls.append({"method": method, "host": host, "path": path, "headers": headers, "json": json, "content": content})
        return handler(calls[-1])

    monkeypatch.setattr(relay, "request", fake)
    return calls


def test_tts_live(monkeypatch):
    _live(monkeypatch, ELEVENLABS_API_KEY="k", ELEVENLABS_VOICE_ID="v1")
    calls = _fake_request(monkeypatch, lambda c: httpx.Response(200, content=b"\x01\x02" * 100))
    a = e.tts("Здравствуйте", "pcm_24000")
    assert not a.stub and a.data == b"\x01\x02" * 100 and a.cost_usd == pytest.approx(0.15 * 12 / 1000)
    assert calls[0]["host"] == "api.elevenlabs.io" and "/v1/text-to-speech/v1?output_format=pcm_16000" == calls[0]["path"]
    assert calls[0]["headers"]["xi-api-key"] == "k" and calls[0]["json"]["text"] == "Здравствуйте"
    _fake_request(monkeypatch, lambda c: httpx.Response(401))
    with pytest.raises(e.EngineError) as ei:
        e.tts("Здравствуйте", "mp3")
    assert ei.value.status == 503


def test_stt_live(monkeypatch):
    _live(monkeypatch, DEEPGRAM_API_KEY="k")
    body = {"metadata": {"duration": 7.5}, "results": {"channels": [{"alternatives": [{"transcript": "  Я поставил индекс. "}]}]}}
    calls = _fake_request(monkeypatch, lambda c: httpx.Response(200, json=body))
    t = e.stt(b"abc", "audio/webm")
    assert t.text == "Я поставил индекс." and t.seconds == 7.5 and t.cost_usd == pytest.approx(0.0077 * 7.5 / 60, abs=1e-6)
    assert calls[0]["content"] == b"abc" and calls[0]["headers"]["Authorization"] == "Token k" and "language=ru" in calls[0]["path"]
    _fake_request(monkeypatch, lambda c: httpx.Response(200, json={"oops": 1}))
    with pytest.raises(e.EngineError) as ei:
        e.stt(b"abc")
    assert ei.value.code == "stt_unavailable"
    with pytest.raises(e.EngineError):
        e.stt(b"x" * (stt.MAX_BYTES + 1))


def test_avatar_live(monkeypatch):
    _live(monkeypatch, ANAM_API_KEY="k", ANAM_AVATAR_ID="av-1", INTERVIEW_TURN_URLS="stun:1.2.3.4:3478,turn:1.2.3.4:3478?transport=udp",
          INTERVIEW_TURN_SECRET="s3", INTERVIEW_TURN_ONLY="1", INTERVIEWER_NAME="Интервьюер")
    calls = _fake_request(monkeypatch, lambda c: httpx.Response(200, json={"sessionToken": "tok"}))
    t = e.avatar_token()
    assert t.session_token == "tok" and t.relay_only and t.persona_name == "Интервьюер" and t.max_seconds == 600
    pc = calls[0]["json"]["personaConfig"]
    assert pc["avatarId"] == "av-1" and pc["enableAudioPassthrough"] is True and pc["name"] == "Интервьюер" and "voiceId" not in pc
    assert calls[0]["json"]["sessionOptions"]["showAIAvatarDisclosure"] is True
    assert calls[0]["headers"]["Authorization"] == "Bearer k"
    assert t.ice_servers[0] == {"urls": ["stun:1.2.3.4:3478"]}
    turn = t.ice_servers[1]
    assert turn["urls"] == ["turn:1.2.3.4:3478?transport=udp"] and ":" in turn["username"] and turn["credential"]
    _fake_request(monkeypatch, lambda c: httpx.Response(500))
    with pytest.raises(e.EngineError) as ei:
        e.avatar_token()
    assert ei.value.code == "avatar_unavailable"


def test_turn_credentials_deterministic(monkeypatch):
    monkeypatch.setattr(av.time, "time", lambda: 1_000_000)
    u, p = av.turn_credentials("secret", ttl_s=60, label="x")
    assert u == "1000060:x" and len(p) == 28  # base64 от 20 байт SHA-1
    assert av.turn_credentials("secret", ttl_s=60, label="x") == (u, p)
