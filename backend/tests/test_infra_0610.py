"""Стабильность демо (06.10): песочницы жюри и сброс своей, «Красная кнопка» с входом и кэшем, лимиты SUS,
загрузка резюме вне цикла событий, /api/health без лишнего (аудит: С9, В2, Н5)."""
import inspect
import io
import threading
import time

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from tests.conftest import register_and_verify
from tests.test_day2_rules import H, _pdf_bytes


def _login(client, persona, scenario=None, **kw):
    body = {"persona": persona, **({"scenario": scenario} if scenario else {})}
    r = client.post("/api/jury/login", json=body, **kw)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- песочницы жюри
def test_jury_sandboxes_are_isolated(client):
    from app.modules.jury.scope import emails

    a = _login(client, "candidate", "new")
    b = _login(client, "candidate", "new")
    sa, sb = a["scenario"], b["scenario"]
    assert sa and sb and sa != sb and a["created"] and not a["shared"]
    assert client.get("/api/me", headers=H(a["access_token"])).json()["email"] == emails(sa)["candidate"]
    # смена персоны — внутри своей песочницы
    ea = _login(client, "employer", sa)
    assert ea["scenario"] == sa and not ea["created"]
    eb = _login(client, "employer", sb)
    own_a = {c["ref"] for c in client.get("/api/employer/candidates", params={"direction": "backend"},
                                          headers=H(ea["access_token"])).json()["items"]}
    own_b = {c["ref"] for c in client.get("/api/employer/candidates", params={"direction": "backend"},
                                          headers=H(eb["access_token"])).json()["items"]}
    # чужая песочница не видна: 4 демо-кандидата (трое с категорией и «Пройдите тест сами» со статусом «не подтверждён»)
    assert len(own_a) == 4 and len(own_b) == 4 and not own_a & own_b
    # подборка песочницы — только по её кандидатам
    # Ф2: условия потребности применяются сразу — берём удалённую потребность (персоны песочницы — удалённо, Москва;
    # в «Офис в Москве» они скрыты условиями)
    need = next(n for n in client.get("/api/employer/needs", headers=H(ea["access_token"])).json()
                if n["requirements"].get("direction") == "backend" and n["requirements"].get("grade") == "middle"
                and n["requirements"].get("work_format") == "remote")
    sel = client.get(f"/api/employer/needs/{need['id']}/selections/1", headers=H(ea["access_token"])).json()
    refs = {c["ref"] for c in sel["results"]}
    # подборка по умолчанию — категория потребности (backend.middle): два своих подтверждённых, затем ярус «грейд не
    # подтверждён» (И1): «Пройдите тест сами» и «Junior — нужен доп. этап» (персона с 21.10 вместо «Junior
    # (предварительно)»: по SPRT грейд не решён). Правило экспертов 20.10: без проверенного грейда кандидат идёт в
    # подборку отдельным ярусом только по направлению, заявленный грейд не фильтрует — поэтому он здесь (прежнее
    # ожидание 3 опиралось на фильтр по заявленному грейду). Чужая песочница по-прежнему не видна.
    assert len(refs) == 4 and refs == own_a and not refs & own_b, (refs, own_a)
    st = [r["grade_status"] for r in sel["results"]]
    assert st[:2] == ["confirmed", "confirmed"] and st[2:] == ["unconfirmed", "unconfirmed"], st
    assert sel["confirmed_matched"] == 2
    # обычный работодатель песочниц не видит
    real = register_and_verify(client, "hr@real.example.org", role="employer", company_name="Настоящая")
    seen = {c["ref"] for c in client.get("/api/employer/candidates", headers=H(real)).json()["items"]}
    assert not seen & (own_a | own_b)
    # эксперт песочницы видит только «свой» ответ на проверке
    xa = _login(client, "expert", sa)
    q = client.get("/api/expert/queue", headers=H(xa["access_token"])).json()
    assert q["counts"]["pending"] == 1 and {i["candidate_ref"] for i in q["items"]} <= own_a
    # сброс песочницы A: токены B продолжают работать, A получает новый токен
    r = client.post("/api/jury/reset", headers=H(ea["access_token"]))
    assert r.status_code == 200 and r.json()["scenario"] == sa and r.json()["persona"] == "employer"
    assert client.get("/api/me", headers=H(eb["access_token"])).status_code == 200
    assert client.get("/api/me", headers=H(b["access_token"])).status_code == 200
    assert client.get("/api/me", headers=H(ea["access_token"])).status_code == 401
    assert client.get("/api/me", headers=H(r.json()["access_token"])).status_code == 200
    # кулдаун сброса — у каждой песочницы свой
    assert client.post("/api/jury/reset", headers=H(r.json()["access_token"])).status_code == 429
    assert client.post("/api/jury/reset", headers=H(eb["access_token"])).status_code == 200


def test_jury_reset_only_for_jury_token(client):
    assert client.post("/api/jury/reset").status_code == 401
    t = register_and_verify(client, "cand@real.example.org")
    r = client.post("/api/jury/reset", headers=H(t))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "jury_only"
    assert client.post("/api/jury/login", json={"persona": "candidate", "scenario": "../etc"}).status_code == 422


def test_jury_sandbox_recreated_cap_and_rate_limit(client, monkeypatch):
    from app.core.config import get_settings
    from app.modules.jury import router as jr
    from app.modules.jury import seed

    first = _login(client, "employer", "new")["scenario"]
    with SessionLocal() as db:  # песочница удалена (по лимиту) — вход с тем же id создаёт её заново
        seed.delete_jury(db, first)
    again = _login(client, "employer", first)
    assert again["scenario"] == first and again["created"]
    monkeypatch.setattr(get_settings(), "jury_sandboxes_max", 2)
    second = _login(client, "employer", "new")["scenario"]
    third = _login(client, "employer", "new")["scenario"]
    with SessionLocal() as db:
        left = set(seed.sandboxes(db))
    assert left == {second, third}  # самая давняя удалена
    # лимит создания с адреса исчерпан — вход в один клик всё равно работает (общее демо)
    monkeypatch.setattr(get_settings(), "jury_new_sandboxes_per_ip_hour", 0)
    r = _login(client, "candidate", "new")
    assert r["shared"] and r["scenario"] is None and r["user"]["email"] == "candidate@jury.example.com"


def test_jury_spare_sandbox_instant_and_single_owner(client, monkeypatch):
    from app.core.config import get_settings
    from app.modules.jury import router as jr
    from app.modules.jury import seed

    monkeypatch.setattr(get_settings(), "jury_spare_sandboxes", 1)
    started = []
    monkeypatch.setattr(jr, "_refill", lambda: started.append(1))  # в тесте — синхронно, без фоновых потоков
    spare = jr.make_spare()
    assert spare and jr.make_spare() is None  # запас уже есть
    with SessionLocal() as db:
        assert seed.spares(db) == [spare]
        assert seed.claim(db, spare) and not seed.claim(db, spare)  # выдаётся ровно одному
        db.execute(seed.update(seed.User).where(seed.User.email == seed.scope.emails(spare)["candidate"])
                   .values(last_login_at=None))
        db.commit()
    t0 = time.time()
    r = _login(client, "employer", "new")
    assert r["scenario"] == spare and time.time() - t0 < 2 and started  # мгновенно + пополнение запаса
    with SessionLocal() as db:
        assert seed.spares(db) == []
    assert _login(client, "candidate", "new")["scenario"] != spare  # следующий эксперт — другая песочница
    # сброс выданной песочницы не делает её снова «запасной» — её не получит другой эксперт
    r = client.post("/api/jury/reset", headers=H(r["access_token"]))
    assert r.status_code == 200 and r.json()["scenario"] == spare
    with SessionLocal() as db:
        assert spare not in seed.spares(db)


# ---------------------------------------------------------------- «Красная кнопка»
def _seed_demo():
    from app.modules.demo.seed import seed

    with SessionLocal() as db:
        seed(db)
        db.commit()


def test_attacks_need_login_own_need_and_rate_limit(client, monkeypatch):
    from app.modules.validation import router as vr

    _seed_demo()
    assert client.post("/api/validation/attacks/rename", json={}).status_code == 401
    e1 = register_and_verify(client, "hr1@real.example.org", role="employer", company_name="Первая")
    e2 = register_and_verify(client, "hr2@real.example.org", role="employer", company_name="Вторая")
    text = "Backend-разработчик middle: Python, FastAPI, PostgreSQL. Удалённо, 250 000 ₽"
    n1 = client.post("/api/employer/needs", json={"text": text}, headers=H(e1))
    assert n1.status_code == 201, n1.text
    nid = n1.json().get("id") or n1.json()["need"]["id"]
    r = client.post("/api/validation/attacks/rename", json={"need_id": nid}, headers=H(e2))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "need_not_found"  # чужая потребность (IDOR)
    cand = register_and_verify(client, "c@real.example.org")
    assert client.post("/api/validation/attacks/rename", json={"need_id": nid}, headers=H(cand)).status_code == 404
    r = client.post("/api/validation/attacks/rename", json={"need_id": nid}, headers=H(e1))
    assert r.status_code == 200 and r.json()["need"] == text and r.json()["violated"] is False
    monkeypatch.setattr(vr._per_user, "limit", 2)
    fresh = register_and_verify(client, "c2@real.example.org")
    codes = [client.post("/api/validation/attacks/rename", json={}, headers=H(fresh)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    monkeypatch.setattr(vr._global, "limit", 0)
    r = client.post("/api/validation/attacks/rename", json={}, headers=H(e2))
    assert r.status_code == 429 and r.headers.get("retry-after")


def test_red_button_one_click_for_jury(client):
    """Режим жюри: вход в один клик (персона своей песочницы) — и атака сразу запускается."""
    _seed_demo()
    tok = _login(client, "employer", "new")["access_token"]
    r = client.post("/api/validation/attacks/inflate_keywords", json={}, headers=H(tok))
    assert r.status_code == 200 and r.json()["violated"] is False


def test_leak_bank_from_cache(client, monkeypatch, tmp_path):
    from app.modules.validation import attacks

    tok = register_and_verify(client)
    t0 = time.time()
    r = client.post("/api/validation/attacks/leak_bank", json={"leak_share": 0.3}, headers=H(tok))
    assert r.status_code == 200 and r.json()["cached"] and r.json()["violated"] is False
    assert time.time() - t0 < 2 and r.json()["computed_seconds"] > 1  # тяжёлый расчёт — заранее
    assert "," in r.json()["fact"] and "30 %" in r.json()["fact"]  # десятичная запятая, как в интерфейсе
    # доли нет в файле — считается один раз на процесс, повтор из памяти
    calls = []
    monkeypatch.setattr(attacks, "_leak", lambda p, seed=None: calls.append(p) or {"violated": False, "fact": "ok",
                                                                                   "details": {}})
    # межпроцессная блокировка симуляции (flock в каталоге временных файлов) — общая на машину: на сервере проверок её
    # держит настоящая симуляция соседнего прогона → 429 attack_busy не по вине кода (нестабильность 11.10). Поэтому в тесте
    # свой файл блокировки: проверяем кэш процесса и саму механику, а не соседей
    monkeypatch.setattr(attacks, "SIM_LOCK", tmp_path / "leak_sim.lock")
    attacks._leak_mem.pop("backend:0.7", None)
    for _ in range(2):
        r = client.post("/api/validation/attacks/leak_bank", json={"leak_share": 0.7}, headers=H(tok))
        assert r.status_code == 200 and r.json()["cached"], r.text
    assert len(calls) == 1
    attacks._leak_mem.pop("backend:0.7", None)
    # пока симуляция идёт в этом процессе — вторая такая же сразу получает 429, а не занимает воркер
    assert attacks._leak_mx.acquire(blocking=False)
    try:
        r = client.post("/api/validation/attacks/leak_bank", json={"leak_share": 0.7}, headers=H(tok))
        assert r.status_code == 429 and r.json()["detail"]["code"] == "attack_busy"
    finally:
        attacks._leak_mx.release()
    # …и если симуляция идёт в другом воркере контейнера (межпроцессная блокировка)
    held = attacks._sim_lock()
    assert held is not None  # свой файл блокировки — свободен
    try:
        r = client.post("/api/validation/attacks/leak_bank", json={"leak_share": 0.7}, headers=H(tok))
        assert r.status_code == 429 and r.json()["detail"]["code"] == "attack_busy"
    finally:
        held.close()
    r = client.post("/api/validation/attacks/leak_bank", json={"leak_share": 0.7}, headers=H(tok))
    assert r.status_code == 200 and len(calls) == 2


def test_attack_never_writes(client, monkeypatch):
    from app.modules.profiles.models import Company
    from app.modules.validation import attacks

    def evil(db, attack_id, req, text=None):
        db.add(Company(name="атака записала", is_demo=True))
        db.flush()
        return {"violated": False, "fact": "", "details": {}}

    monkeypatch.setattr(attacks, "_profile_attack", evil)
    with SessionLocal() as db:
        with pytest.raises(RuntimeError):
            attacks.run(db, "rename")
        db.commit()
        assert db.scalar(select(func.count()).select_from(Company).where(Company.name == "атака записала")) == 0


# ---------------------------------------------------------------- SUS
def test_sus_limits_and_anonymous_separate(client):
    ans = {"answers": [4, 2] * 5, "context": "other"}
    ip = lambda a: {"X-Forwarded-For": a}  # noqa: E731
    assert [client.post("/api/sus", json=ans, headers=ip("8.8.8.8")).status_code for _ in range(4)] == [201] * 3 + [429]
    # подделка X-Forwarded-For слева не помогает: учитывается адрес, который дописал наш nginx
    r = client.post("/api/sus", json=ans, headers=ip("1.2.3.4, 8.8.8.8, 172.18.0.1"))
    assert r.status_code == 429
    assert client.post("/api/sus", json=ans, headers=ip("9.9.9.9")).status_code == 201
    # после входа: повтор заменяет прежнюю анкету — накрутить одной учёткой нельзя
    t = register_and_verify(client)
    for a in ([5, 1] * 5, [3] * 10):
        assert client.post("/api/sus", json={"answers": a, "context": "jury"}, headers=H(t)).status_code == 201
    s = client.get("/api/sus/summary").json()
    assert s["n"] == 1 and s["mean"] == 50.0 and s["by_role"] == {"jury": s["by_role"]["jury"]}
    assert s["anonymous"]["n"] == 4 and s["all"]["n"] == 5 and s["scope"] == "authenticated"


def test_client_ip_rightmost_public():
    from starlette.requests import Request

    from app.core.ratelimit import client_ip

    def req(xff=None, real=None):
        h = [(b"x-forwarded-for", xff.encode())] if xff else []
        h += [(b"x-real-ip", real.encode())] if real else []
        return Request({"type": "http", "headers": h, "client": ("172.18.0.5", 1234)})

    assert client_ip(req("6.6.6.6, 5.5.5.5, 172.18.0.1")) == "5.5.5.5"
    assert client_ip(req("10.0.0.1, 127.0.0.1")) == "127.0.0.1"
    assert client_ip(req(None, None)) == "172.18.0.5"


# ---------------------------------------------------------------- резюме (аудит, В2)
def test_resume_handler_runs_in_threadpool(client, monkeypatch):
    from app.modules.profiles import candidate_router as cr
    from app.modules.resume import extract

    assert not inspect.iscoroutinefunction(cr.upload_resume)
    t = register_and_verify(client, "slowpdf@example.com")
    pdf = _pdf_bytes(["Python разработчик", "Опыт работы 3 года: Python, FastAPI, PostgreSQL."])
    real = extract.pdf_to_text_safe
    monkeypatch.setattr(extract, "pdf_to_text_safe", lambda *a, **k: (time.sleep(2.0), real(*a, **k))[1])
    out = {}
    th = threading.Thread(target=lambda: out.setdefault("r", client.post(
        "/api/me/resume", files={"file": ("cv.pdf", pdf, "application/pdf")}, headers=H(t))))
    th.start()
    time.sleep(0.3)
    t0 = time.time()
    assert client.get("/api/health").status_code == 200
    assert time.time() - t0 < 1.0  # пока резюме разбирается, API отвечает другим
    th.join(20)
    assert out["r"].status_code == 201, out["r"].text


def test_resume_pages_timeout_and_rate(client, monkeypatch):
    from pypdf import PdfWriter

    from app.core.config import get_settings

    t = register_and_verify(client, "limits@example.com")
    w = PdfWriter()
    for _ in range(25):
        w.add_blank_page(200, 200)
    buf = io.BytesIO()
    w.write(buf)
    up = lambda data: client.post("/api/me/resume", files={"file": ("cv.pdf", data, "application/pdf")},  # noqa: E731
                                  headers=H(t))
    r = up(buf.getvalue())
    assert r.status_code == 422 and r.json()["detail"]["code"] == "pdf_too_many_pages" and "25" in r.text
    pdf = _pdf_bytes(["Python разработчик", "Опыт работы 3 года: Python, FastAPI, PostgreSQL."])
    monkeypatch.setattr(get_settings(), "resume_parse_timeout_s", 0.01)
    r = up(pdf)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "pdf_timeout"
    monkeypatch.setattr(get_settings(), "resume_parse_timeout_s", 10.0)
    monkeypatch.setattr(get_settings(), "resume_uploads_per_hour", 1)
    assert up(pdf).status_code == 201
    r = up(pdf)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "resume_rate"


def test_pdf_worker_memory_limit():
    from app.modules.resume.extract import PdfError, pdf_to_text_safe

    pdf = _pdf_bytes(["Python разработчик", "Опыт работы 3 года: Python, FastAPI, PostgreSQL."])
    text, pages = pdf_to_text_safe(pdf)
    assert pages == 1 and "Python" in text
    with pytest.raises(PdfError):  # процесс разбора не может взять память сверх лимита — отказ, а не OOM воркера
        pdf_to_text_safe(pdf, memory_mb=16)


def test_health_has_only_status_and_db(client):
    assert client.get("/api/health").json() == {"status": "ok", "db": "ok"}
