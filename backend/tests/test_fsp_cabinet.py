"""Кабинет ФСП: доступ только роли «ФСП»/администратора, только агрегаты (K = 5), демо-данные и демо-кубки."""
import json

from sqlalchemy import select

from app.core.db import SessionLocal, utcnow
from tests.conftest import register_and_verify
from tests.test_day2_rules import INVITE, H, candidate_with_category, employer, my_ref


def analyst_token(client) -> str:
    """Учётка роли «ФСП» без режима жюри (вход жюри за ФСП проверяется ниже)."""
    from app.core.enums import UserRole
    from app.core.security import hash_password
    from app.modules.auth.service import issue_token
    from app.modules.demo.seed import _user

    with SessionLocal() as db:
        u = _user(db, "analyst@example.com", UserRole.fsp_analyst, hash_password("analyst-pass-123"))
        db.commit()
        return issue_token(u).access_token


def test_access_by_role(client):
    tc = register_and_verify(client, email="c@example.com")
    te = employer(client)
    for t in (tc, te):
        assert client.get("/api/fsp-cabinet/report", headers=H(t)).status_code == 403
    assert client.get("/api/fsp-cabinet/report").status_code == 401
    ta = analyst_token(client)
    assert client.get("/api/fsp-cabinet/report", headers=H(ta)).status_code == 200
    # «ФСП» не работодатель и не кандидат
    assert client.get("/api/employer/candidates", headers=H(ta)).status_code == 403
    assert client.get("/api/candidate/cups", headers=H(ta)).status_code == 403
    me = client.get("/api/me", headers=H(ta))
    assert me.status_code == 200


def test_small_groups_suppressed_and_no_pii(client):
    te = employer(client)
    refs = []
    for i in range(3):
        t = candidate_with_category(client, f"c{i}@example.com")
        refs.append(my_ref(client, t))
    for ref in refs[:2]:
        assert client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": ref},
                           headers=H(te)).status_code == 201
    ta = analyst_token(client)
    rep = client.get("/api/fsp-cabinet/report", headers=H(ta)).json()
    flat = json.dumps(rep, ensure_ascii=False)
    for secret in ("Иван", "Петров", "@example.com", "111-22-33", *refs):
        assert secret not in flat
    ov = rep["overview"]
    assert ov["candidates"] is None and ov["invited_candidates"] is None  # 3 и 2 человека — меньше 5
    row = next(r for r in rep["demand"]["categories"] if r["category_id"] == "backend.middle")
    assert row["invited_candidates"] is None and row["supply"] is None and row["invite_rate"] is None
    assert row["invitations"] == 2  # число приглашений-событий не идентифицирует человека
    sal = next(r for r in rep["salaries"]["categories"] if r["category_id"] == "backend.middle")
    assert sal["suppressed"] and "mid_median" not in sal
    empty = next(r for r in rep["demand"]["categories"] if r["category_id"] == "qa.senior")
    assert empty["supply"] == 0 and empty["invited_candidates"] == 0  # ноль раскрывать можно
    csv = client.get("/api/fsp-cabinet/export/demand.csv", headers=H(ta))
    assert csv.status_code == 200 and "<5" in csv.text and "@example.com" not in csv.text
    assert client.get("/api/fsp-cabinet/export/nope.csv", headers=H(ta)).status_code == 404


def test_k_rules_pure():
    from app.fsp_cabinet.analytics import K, kc, kr

    assert K == 5 and kc(0) == 0 and kc(4) is None and kc(5) == 5
    assert kr(3, 10) is None and kr(5, 10) == 0.5 and kr(0, 7) == 0.0 and kr(5, 4) is None


def _platform_demo():
    from app.modules.demo.seed import seed
    from app.modules.jury.seed import ensure_ideas

    with SessionLocal() as db:
        seed(db)
        db.commit()
        ensure_ideas(db)  # кубки демо-компаний и история приглашений — одни на платформу


def test_demo_report_and_cups(client):
    from app.cup.models import Cup, CupEntry
    from app.fsp_cabinet import demo

    _platform_demo()
    ta = analyst_token(client)
    with SessionLocal() as db:
        assert demo.has_demo_invitations(db)
        cups = db.scalars(select(Cup)).all()
        assert len(cups) == 6 and {c.status for c in cups} == {"finished", "active"}
        assert all(c.jury_scope is None for c in cups)
        placed = db.scalars(select(CupEntry).where(CupEntry.place.is_not(None))).all()
        assert placed and all(e.passport_status in ("written", "pending_link") for e in placed)
        assert any(e.passport_status == "written" for e in placed)
    rep = client.get("/api/fsp-cabinet/report", headers=H(ta)).json()
    flat = json.dumps(rep, ensure_ascii=False)
    assert "@demo.invalid" not in flat and "CND-" not in flat
    ov = rep["overview"]
    assert ov["candidates"] >= 150 and ov["invitations"] >= 100 and ov["cups"] == 6
    shown = [r for r in rep["salaries"]["categories"] if not r["suppressed"]]
    hidden = [r for r in rep["salaries"]["categories"] if r["suppressed"]]
    assert shown and hidden  # в части категорий офферов мало — вилки скрыты
    for r in shown:
        assert r["offers"] >= 5 and r["companies"] >= 2 and r["from_p25"] <= r["mid_median"] <= r["to_p75"]
    fe = rep["fsp_effect"]
    assert fe["groups"][0]["key"] == "no_fsp" and fe["groups"][0]["candidates"] >= 5
    for part in ("ranks", "results", "levels"):  # вторичное подавление: не бывает ровно одной скрытой группы
        assert sum(1 for g in fe[part] if g["candidates"] is None) != 1
    f = rep["funnel"]
    assert [s["key"] for s in f["cups"]] == ["joined", "placed", "invited", "accepted"]
    assert f["all"][0]["count"] >= 150 and f["all"][1]["conversion"] is not None
    assert len(rep["cups"]) == 6 and all("participants" in c for c in rep["cups"])
    assert all(s["count"] is not None for s in f["cups"])  # воронка кубков раскрыта целиком (каждый этап ≥ 5)
    with SessionLocal() as db:  # удаление демо — чистое
        from app.cup import demo as cup_demo

        assert cup_demo.delete_cups(db) == 6 and demo.delete_invitations(db) >= 100
        assert db.scalars(select(Cup)).all() == []


# ---------------------------------------------------------------- режим жюри: песочницы, персона «ФСП», сброс
def _login(client, persona, scenario=None):
    r = client.post("/api/jury/login", json={"persona": persona, **({"scenario": scenario} if scenario else {})})
    assert r.status_code == 200, r.text
    return r.json()


def _box(db, key):
    """Состояние копии демо жюри: её кубки, Мария (место, паспорт, приглашение), факты кубков."""
    from app.cup.models import Cup, CupEntry
    from app.modules.auth.models import User
    from app.modules.invitations.models import Invitation
    from app.modules.jury import scope

    cups = {c.title: c for c in db.scalars(select(Cup).where(Cup.jury_scope == key)).all()}
    maria = db.scalar(select(User).where(User.email == scope.emails("" if key == scope.SHARED else key)["candidate"]))
    me = db.scalars(select(CupEntry).where(CupEntry.candidate_user_id == maria.id)).all() if maria else []
    inv = [db.get(Invitation, e.invitation_id) for e in me if e.invitation_id]
    return {"cups": {t: c.id for t, c in cups.items()}, "maria": [(e.place, e.passport_status) for e in me],
            "maria_inv": [i.status.value for i in inv if i]}


def _orphans(db):
    from app.cup.models import Cup
    from app.modules.fsp.models import FspAchievement
    from app.modules.profiles.models import CandidateFact

    ids = {f"cup:{c}" for c in db.scalars(select(Cup.id)).all()}
    refs = db.scalars(select(CandidateFact.source_ref).where(CandidateFact.source_ref.like("cup:%"))).all()
    refs += db.scalars(select(FspAchievement.source_ref).where(FspAchievement.source_ref.like("cup:%"))).all()
    return set(refs) - ids


def _numbers(rep):
    ov = rep["overview"]
    return (ov["candidates"], ov["candidates_fsp"], ov["companies_active"], ov["needs"], ov["invitations"], ov["cups"],
            ov["cup_participants"], [s["count"] for s in rep["funnel"]["cups"]],
            [g["candidates"] for g in rep["fsp_effect"]["groups"]])


def test_jury_sandboxes_get_own_cups_and_shared_analytics(client, monkeypatch):
    """Две песочницы: у каждой свои кубки и своя Мария на 2-м месте; кубки чужой песочницы не видны; аналитика ФСП
    одна и та же при любом числе песочниц и после итогов кубка жюри; сброс пересоздаёт только свои кубки."""
    from app.fsp_cabinet import analytics
    from app.modules.jury import router as jr

    _platform_demo()
    with SessionLocal() as db:
        base = _numbers(analytics.report(db))
    st = client.get("/api/jury/status").json()
    assert any(p["id"] == "fsp" and p["role"] == "fsp_analyst" for p in st["personas"])
    a = _login(client, "candidate", "new")
    b = _login(client, "candidate", "new")
    sa, sb = a["scenario"], b["scenario"]
    assert sa and sb and sa != sb
    with SessionLocal() as db:
        box_a, box_b = _box(db, sa), _box(db, sb)
        assert not _orphans(db)
    for box in (box_a, box_b):  # Мария — 2-е место в «Платёжном шлюзе», запись в паспорте, приглашения от кубка нет:
        assert set(box["cups"]) == {"Платёжный шлюз", "Вебхуки без дублей"}  # её приглашает работодатель в сценарии
        assert box["maria"] == [(2, "written")] and box["maria_inv"] == []
    assert not set(box_a["cups"].values()) & set(box_b["cups"].values())
    # кандидат видит кубки своей песочницы и кубки платформы, но не чужие
    items = client.get("/api/candidate/cups", headers=H(a["access_token"])).json()["items"]
    mine = [c for c in items if c["title"] == "Платёжный шлюз"]
    assert len(mine) == 1 and mine[0]["id"] == str(box_a["cups"]["Платёжный шлюз"]) and mine[0]["my_place"] == 2
    assert {"Маршрутизация заказов", "Надёжные платежи"} <= {c["title"] for c in items}
    assert client.get(f"/api/candidate/cups/{box_b['cups']['Платёжный шлюз']}",
                      headers=H(a["access_token"])).status_code == 404
    pas = client.get("/api/candidate/cups/passport", headers=H(a["access_token"])).json()
    assert [(p["title"], p["place"], p["passport_status"], p["invited"]) for p in pas] == \
        [("Платёжный шлюз", 2, "written", False)]
    # ФСП песочницы A: та же аналитика, что без песочниц
    f = _login(client, "fsp", sa)
    assert f["landing"] == "/fsp" and f["user"]["role"] == "fsp_analyst" and f["scenario"] == sa
    rep = client.get("/api/fsp-cabinet/report", headers=H(f["access_token"])).json()
    assert _numbers(rep) == base
    # работодатель песочницы A: два кубка; оценил два решения — итоги и приглашения топ-3, без фактов «статистам»
    te = _login(client, "employer", sa)["access_token"]
    cups = {c["title"]: c for c in client.get("/api/employer/cups", headers=H(te)).json()}
    assert set(cups) == {"Платёжный шлюз", "Вебхуки без дублей"}
    assert cups["Платёжный шлюз"]["phase"] == "finished" and cups["Платёжный шлюз"]["summary"]["invited"] == 1
    rev = cups["Вебхуки без дублей"]
    assert rev["phase"] == "judging" and rev["to_review"] == 2
    # основной сценарий жюри не сломан: кубки не заняли приглашение Марии от этой компании (лимит 30 дней)
    r = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": my_ref(client, a["access_token"])},
                    headers=H(te))
    assert r.status_code == 201, r.text
    cup = client.get(f"/api/employer/cups/{rev['id']}", headers=H(te)).json()
    for sol in [x for x in cup["solutions"] if x["status"] == "submitted"]:
        r = client.post(f"/api/employer/cups/{rev['id']}/entries/{sol['entry_id']}/score",
                        json={"criteria": {"correctness": 1, "tradeoffs": 1, "clarity": 1}}, headers=H(te))
        assert r.status_code == 200, r.text
    res = r.json()
    assert res["phase"] == "finished" and res["summary"]["invited"] == 3
    assert all(not x.get("invite_note") for x in res["leaderboard"][:3])
    with SessionLocal() as db:
        from app.modules.profiles.models import CandidateFact

        assert db.scalars(select(CandidateFact).where(CandidateFact.source_ref == f"cup:{rev['id']}")).all() == []
        assert _numbers(analytics.report(db)) == base
    # сброс песочницы A: её кубки — заново, у B — те же, сирот нет
    monkeypatch.setitem(jr._state, sa, 0.0)
    r = client.post("/api/jury/reset", headers=H(te))
    assert r.status_code == 200 and r.json()["deleted_users"] == 7, r.text  # 7 персон песочницы
    assert set(r.json()["employer"]["cups"]) == {"Платёжный шлюз", "Вебхуки без дублей"}
    with SessionLocal() as db:
        new_a, again_b = _box(db, sa), _box(db, sb)
        assert again_b == box_b and not set(new_a["cups"].values()) & set(box_a["cups"].values())
        assert new_a["maria"] == [(2, "written")] and new_a["maria_inv"] == [] and not _orphans(db)
        assert _numbers(analytics.report(db)) == base
    te = r.json()["access_token"]
    assert {c["title"]: c["to_review"] for c in client.get("/api/employer/cups", headers=H(te)).json()} == \
        {"Платёжный шлюз": 0, "Вебхуки без дублей": 2}


def test_spare_sandbox_comes_with_cups(client, monkeypatch):
    from app.core.config import get_settings
    from app.modules.jury import router as jr

    _platform_demo()
    monkeypatch.setattr(get_settings(), "jury_spare_sandboxes", 1)
    monkeypatch.setattr(jr, "_refill", lambda: None)  # без фонового пополнения после выдачи
    spare = jr.make_spare()
    assert spare
    with SessionLocal() as db:
        box = _box(db, spare)
    assert set(box["cups"]) == {"Платёжный шлюз", "Вебхуки без дублей"} and box["maria"] == [(2, "written")]
    r = _login(client, "employer", "new")
    assert r["scenario"] == spare  # запасная выдана как есть — кубки уже на месте
    assert len(client.get("/api/employer/cups", headers=H(r["access_token"])).json()) == 2


def test_stale_demo_cups_reseeded_on_jury_login(client):
    from datetime import timedelta

    from app.cup import demo as cup_demo
    from app.cup.models import Cup

    _platform_demo()
    tc = _login(client, "candidate")["access_token"]  # общее демо: тоже свои кубки (jury_scope = shared)
    with SessionLocal() as db:
        assert not cup_demo.is_stale(db) and len(cup_demo._seeded(db)) == 6
        cup = db.scalar(select(Cup).where(Cup.title == "Маршрутизация заказов"))
        old = cup.id
        cup.ends_at = utcnow() + timedelta(hours=2)  # идущий кубок вот-вот закончится
        db.commit()
        assert cup_demo.is_stale(db)
        shared = _box(db, "shared")["cups"]
    # Мария записалась в идущий кубок платформы; пересев общего демо её запись снимает, кубки копий жюри не трогает
    assert client.post(f"/api/candidate/cups/{old}/join", headers=H(tc)).status_code == 200
    tc = _login(client, "candidate")["access_token"]
    with SessionLocal() as db:
        assert not cup_demo.is_stale(db)
        cup = db.scalar(select(Cup).where(Cup.title == "Маршрутизация заказов"))
        assert cup.id != old and len(cup_demo._seeded(db)) == 6 and _box(db, "shared")["cups"] == shared
        assert not _orphans(db)
    items = client.get("/api/candidate/cups", headers=H(tc)).json()["items"]
    titles = {c["title"]: c for c in items}
    assert titles["Маршрутизация заказов"]["phase"] == "active" and titles["Маршрутизация заказов"]["my_status"] is None
    assert titles["Платёжный шлюз"]["my_place"] == 2


def test_report_single_load_cache_60s_invalidation_and_byte_for_byte_equivalence(client, monkeypatch):
    """2б-1 (21.10): /api/fsp-cabinet/report вызывает an.load ровно 1 раз (передаёт Data в build_regions_map и benefit),
    кэш 60 с по ключу (days, include_demo, jury_key) не смешивает песочницы и сбрасывается при записи в БД,
    а ответы report / regions / benefit совпадают байт-в-байт с прямым расчётом без кэша."""
    from app.core.config import get_settings
    from app.cup import tournament
    from app.fsp_cabinet import analytics as an
    from app.fsp_cabinet import benefit as benefit_mod
    from app.fsp_cabinet.regions import build_regions_map

    monkeypatch.setattr(get_settings(), "tariffs_enabled", True)
    _platform_demo()
    ta = analyst_token(client)
    an.invalidate_cache()

    load_calls = 0
    orig_load = an.load

    def spy_load(db, days=None, include_demo=True):
        nonlocal load_calls
        load_calls += 1
        return orig_load(db, days, include_demo=include_demo)

    monkeypatch.setattr(an, "load", spy_load)

    # 1. Первый вызов /report делает ровно ОДИН вызов an.load (а не два — для an.report и build_regions_map)
    r1 = client.get("/api/fsp-cabinet/report", headers=H(ta))
    assert r1.status_code == 200, r1.text
    assert load_calls == 1
    rep_cached = r1.json()

    # 2. Повторный вызов /report и /benefit с теми же параметрами берут данные из кэша (0 новых вызовов an.load)
    r2 = client.get("/api/fsp-cabinet/report", headers=H(ta))
    assert r2.status_code == 200
    assert load_calls == 1
    r_ben = client.get("/api/fsp-cabinet/benefit", headers=H(ta))
    assert r_ben.status_code == 200
    assert load_calls == 1
    ben_cached = r_ben.json()

    # 3. Байт-в-байт совпадение с прямым расчётом без кэша на тех же данных (кроме метки generated_at)
    with SessionLocal() as db:
        d_fresh = orig_load(db, None, include_demo=True)
        expected_rep = {
            **an.report(db, None, include_demo=True, d=d_fresh),
            "regions_map": build_regions_map(db, None, d=d_fresh, include_demo=True),
            "tournaments": tournament.cabinet_list(db, None, include_demo=True),
        }
        expected_ben = benefit_mod.compute(db, None, d=d_fresh, include_demo=True)

    rep_cmp = {**rep_cached, "generated_at": expected_rep["generated_at"]}
    assert json.dumps(rep_cmp, sort_keys=True, ensure_ascii=False) == json.dumps(
        expected_rep, sort_keys=True, ensure_ascii=False
    )
    assert json.dumps(ben_cached, sort_keys=True, ensure_ascii=False) == json.dumps(
        expected_ben, sort_keys=True, ensure_ascii=False
    )

    # 4. Песочницы жюри не смешиваются по ключу кэша
    f_a = _login(client, "fsp", "new")
    an.invalidate_cache()
    load_calls = 0
    assert client.get("/api/fsp-cabinet/report", headers=H(f_a["access_token"])).status_code == 200
    assert load_calls == 1
    # Запрос от аналитика вне песочницы имеет другой jury_key -> отдельный ключ кэша
    assert client.get("/api/fsp-cabinet/report", headers=H(ta)).status_code == 200
    assert load_calls == 2

    # 5. Вход пользователя (обновление last_login_at, создание RefreshSession / AuditEvent / вход жюри) НЕ сбрасывает кэш
    calls_before_login = load_calls
    f_shared = _login(client, "candidate", None)
    assert f_shared.get("access_token")
    r_after_login = client.get("/api/fsp-cabinet/report", headers=H(ta))
    assert r_after_login.status_code == 200
    assert load_calls == calls_before_login

    # 6. Запись в таблицы, от которых зависит отчёт (приглашения, кандидаты, потребности), автоматически сбрасывает кэш
    te = employer(client)
    tc = candidate_with_category(client, "cache-bust@example.com")
    assert client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": my_ref(client, tc)}, headers=H(te)).status_code == 201
    calls_before = load_calls
    r_after = client.get("/api/fsp-cabinet/report", headers=H(ta))
    assert r_after.status_code == 200
    assert load_calls == calls_before + 1


def test_demand_skills_deterministic_order_and_unspecified_city(client):
    """А12/владелец (21.10):
    1) demand.skills сортируется детерминированно по (-w, -invited_sk, tag) — порядок хвоста не зависит от порядка обхода set;
    2) кандидаты и потребности без города (или с неизвестным городом) не раскидываются по округам по кругу,
       а выносятся в строку «Город не указан» (в итогах учтены, на карте и в разрыве округов не учитываются)."""
    import uuid
    from app.core.db import SessionLocal
    from app.fsp_cabinet import analytics as an
    from app.fsp_cabinet.regions import CITY_UNSPECIFIED_TITLE, build_regions_map, resolve_geo
    from app.modules.catalog.models import Category

    # 1. Детерминированный порядок навыков при равных весах и числе приглашённых
    d1 = an.Data(
        cands={
            uuid.uuid4(): an.Cand(
                user_id=uuid.uuid4(),
                category="backend.middle",
                direction="backend",
                skills={"zzzz_tag", "aaaa_tag", "mmmm_tag"},
                invitations=[object()],
            )
        },
        invs=[],
        needs=[],
        categories={},
        cups=[],
        entries=[],
        period_days=None,
    )
    dem = an.demand(d1)
    skill_tags = [s["tag"] for s in dem["skills"]]
    assert skill_tags == ["aaaa_tag", "mmmm_tag", "zzzz_tag"]

    # 2. resolve_geo без города или с неизвестным городом возвращает (None, 'Город не указан') независимо от fallback_idx
    for idx in range(12):
        assert resolve_geo(None, idx) == (None, CITY_UNSPECIFIED_TITLE)
        assert resolve_geo("", idx) == (None, CITY_UNSPECIFIED_TITLE)
        assert resolve_geo("Неизвестный Город XYZ", idx) == (None, CITY_UNSPECIFIED_TITLE)
    assert resolve_geo("Москва", 5) == ("cfo", "Москва и МО")

    # 3. В build_regions_map профили без города попадают в city_unspecified и total_confirmed, но НЕ в округа карты и НЕ в gap округов
    cands_map = {}
    for i in range(6):
        uid = uuid.uuid4()
        cands_map[uid] = an.Cand(user_id=uid, category="backend.middle", direction="backend", city="Москва", is_synthetic=False)
    for i in range(5):
        uid = uuid.uuid4()
        cands_map[uid] = an.Cand(user_id=uid, category="backend.middle", direction="backend", city=None if i < 3 else "Неизвестныйград", is_synthetic=False)

    d_geo = an.Data(
        cands=cands_map,
        invs=[],
        needs=[],
        categories={},
        cups=[],
        entries=[],
        period_days=None,
    )
    with SessionLocal() as db:
        rm = build_regions_map(db, None, d=d_geo, include_demo=False)
    assert rm["total_confirmed"] == 11
    assert rm["mapped_confirmed"] == 6
    assert rm["city_unspecified"]["title"] == "Город не указан"
    assert rm["city_unspecified"]["confirmed"] == 5
    assert rm["city_unspecified"]["real_confirmed"] == 5
    assert rm["city_unspecified"]["gap"] is None
    assert "Город не указан" in rm["synthetic_note"]
    cfo = next(x for x in rm["districts"] if x["id"] == "cfo")
    assert cfo["confirmed"] == 6
    for other in rm["districts"]:
        if other["id"] != "cfo":
            assert other["confirmed"] == 0


