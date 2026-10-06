"""Экспертная разметка: статистика, пакет, вход по ссылке, вслепую, сохранение по ходу, расчёт на /validation."""
import math

from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.experts import analysis as A
from app.modules.experts import stats as S


def H(t):
    return {"Authorization": f"Bearer {t}"}


# ------------------------------------------------------------------ статистика
def test_krippendorff_alpha_reference_values():
    """Пример из Krippendorff (2011), «Computing Krippendorff's Alpha-Reliability»: 4 оценщика, 12 объектов."""
    n = None
    rows = [[1, 2, 3, 3, 2, 1, 4, 1, 2, n, n, n], [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, n, 3],
            [n, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, n], [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, n]]
    units = {i: [r[i] for r in rows if r[i] is not None] for i in range(12)}
    assert S.krippendorff_alpha(units, "interval") == 0.849
    assert S.krippendorff_alpha(units, "ordinal") == 0.815


def test_weighted_kappa_and_bootstrap():
    assert S.weighted_kappa([0, 1, 2, 3, 3], [0, 1, 2, 3, 3]) == 1.0
    assert S.weighted_kappa([0, 1, 2, 3], [3, 2, 1, 0]) == -1.0
    k = S.weighted_kappa([0, 1, 2, 3, 2, 1], [0, 1, 3, 3, 2, 0])
    assert 0.6 < k < 1.0
    ci = S.boot_ci([0.8, 0.9, 1.0, 0.6, 0.7])
    assert ci["lo"] <= ci["mean"] <= ci["hi"] and ci["n"] == 5


def test_angoff_theta_inverts_expected_share():
    params = [([1.2], [0.0]), ([0.8, 0.8], [0.5, 1.0]), ([1.5], [-0.5])]
    for th in (-1.0, 0.3, 1.4):
        target = sum(S.expected_share(th, a, b) for a, b in params)
        assert math.isclose(S.solve_theta(target, params), th, abs_tol=1e-6)


def test_matching_metrics_and_random_estimator():
    """Топ-5 платформы и BM25 по рангам, «случайный порядок» — стратифицированная оценка по всей базе."""
    items = {}
    gold = {"p1": 3, "p2": 3, "p3": 2, "p4": 2, "p5": 1, "b1": 1, "b2": 0, "b3": 0, "b4": 2, "r1": 0, "r2": 2}
    rp = {"p1": 1, "p2": 2, "p3": 3, "p4": 4, "p5": 5, "b1": 9, "b2": 20, "b3": 30, "b4": 6, "r1": 50, "r2": 40}
    rb = {"b1": 1, "b2": 2, "b3": 3, "b4": 4, "p5": 5, "p1": 7, "p2": 8, "p3": 9, "p4": 10, "r1": 60, "r2": 70}
    for k in gold:
        src = ["random"] if k.startswith("r") else (["platform"] if rp[k] <= 5 else []) + (["bm25"] if rb[k] <= 5 else [])
        items[k] = {"kind": "A", "grp": "N00", "payload": {"need_text": "x"},
                    "hidden": {"rank_platform": rp[k], "rank_bm25": rb[k], "sources": src, "n_population": 100,
                               "rule_label": gold[k]}}
    labels = [{"coder": "E1", "key": k, "value": {"relevance": v}} for k, v in gold.items()]
    m = A.matching(items, labels)
    row = m["per_need"][0]
    assert row["complete"] and row["platform"]["p@5"] == 0.8 and row["bm25"]["p@5"] == 0.2
    # база 100: объединение топов (9 карточек, 5 релевантных) целиком + 91 × доля релевантных в выборке (1 из 2)
    assert math.isclose(row["random"]["p@5"], (5 + 91 * 0.5) / 100, abs_tol=1e-3)
    assert row["platform"]["ndcg@5"] > row["bm25"]["ndcg@5"]
    assert m["vs_rules"]["kappa"] == 1.0


# ------------------------------------------------------------------ пакет, ссылки, разметка
def _seed_and_pack():
    from app.modules.demo.seed import seed
    from app.modules.experts.pack import ensure_pack

    with SessionLocal() as db:
        seed(db)
        db.commit()
        assert ensure_pack(db)


def test_invite_link_blind_items_and_saving(client):
    from app.modules.experts.models import ExpertItem
    from app.modules.experts.service import create_invite

    _seed_and_pack()
    with SessionLocal() as db:
        inv = create_invite(db, "E1", name="Тест", profile="тимлид Backend")
        assert inv["url"].endswith(f"/expert-invite/{inv['token']}") and inv["assigned"]["A"] > 50
        n_items = {k: db.query(ExpertItem).filter(ExpertItem.kind == k).count() for k in "ABC"}
    assert n_items["B"] == 24 and n_items["C"] >= 60 and n_items["A"] >= 90
    assert client.post("/api/expert-panel/enter", json={"token": "x" * 32}).status_code == 404
    r = client.post("/api/expert-panel/enter", json={"token": inv["token"]})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    me = client.get("/api/expert-panel/me", headers=H(tok)).json()
    assert me["in_panel"] and me["code"] == "E1" and not me["is_demo"]
    assert me["progress"]["A"]["done"] == 0 and me["progress"]["B"]["total"] == 24
    a = client.get("/api/expert-panel/items/A", headers=H(tok)).json()["items"]
    # вслепую: ни ранга, ни скора, ни источника пула, ни метки по правилам, ни ref кандидата
    blob = str(a)
    for bad in ("rank", "score_platform", "bm25", "sources", "rule_label", "ref", "rating"):
        assert bad not in blob, bad
    assert a[0]["need_text"] and a[0]["card"]["category"]
    # сохранение по ходу, правка перезаписывает
    ok = client.post("/api/expert-panel/labels", headers=H(tok),
                     json={"item_id": a[0]["id"], "value": {"relevance": 2, "must_have_missing": "Redis"}, "seconds": 30})
    assert ok.status_code == 200 and ok.json()["progress"]["done"] == 1
    ok = client.post("/api/expert-panel/labels", headers=H(tok), json={"item_id": a[0]["id"], "value": {"relevance": 3}})
    assert ok.json()["progress"]["done"] == 1
    again = client.get("/api/expert-panel/items/A", headers=H(tok)).json()["items"][0]
    assert again["label"]["relevance"] == 3
    assert client.post("/api/expert-panel/labels", headers=H(tok),
                       json={"item_id": a[1]["id"], "value": {"relevance": 5}}).status_code == 422
    # B: все критерии рубрики, 0 / 0,5 / 1, общая 0–3, флаг
    b = client.get("/api/expert-panel/items/B", headers=H(tok)).json()["items"]
    assert all(not ({"intended", "control", "hidden", "llm", "family_id"} & set(x)) for x in b)
    crit = {c["id"]: 0.5 for c in b[0]["rubric"]["criteria"]}
    assert client.post("/api/expert-panel/labels", headers=H(tok),
                       json={"item_id": b[0]["id"], "value": {"criteria": crit, "holistic": 2, "flag": "none"}}).status_code == 200
    bad = dict(crit, **{next(iter(crit)): 0.7})
    assert client.post("/api/expert-panel/labels", headers=H(tok),
                       json={"item_id": b[1]["id"], "value": {"criteria": bad, "holistic": 2}}).status_code == 422
    # C: шаг 5, Senior не ниже Middle, для MCQ из 4 вариантов — не ниже 25
    c = client.get("/api/expert-panel/items/C", headers=H(tok)).json()["items"]
    assert all(not ({"a", "b", "hidden", "target_grades"} & set(x)) for x in c)
    it = c[0]
    lo = max(25, it["floor"])
    assert client.post("/api/expert-panel/labels", headers=H(tok),
                       json={"item_id": it["id"], "value": {"junior_middle": lo + 20, "middle_senior": lo, "confidence": 2}}).status_code == 422
    assert client.post("/api/expert-panel/labels", headers=H(tok),
                       json={"item_id": it["id"], "value": {"junior_middle": 33, "middle_senior": 60, "confidence": 2}}).status_code == 422
    assert client.post("/api/expert-panel/labels", headers=H(tok),
                       json={"item_id": it["id"], "value": {"junior_middle": lo, "middle_senior": lo + 30, "confidence": 3}}).status_code == 200
    mcq = next((x for x in c if x["floor"] == 25), None)
    if mcq:
        assert client.post("/api/expert-panel/labels", headers=H(tok),
                           json={"item_id": mcq["id"], "value": {"junior_middle": 20, "middle_senior": 40, "confidence": 1}}).status_code == 422
    # объект вне назначения недоступен
    with SessionLocal() as db:
        from app.modules.experts.models import ExpertPanelist

        pan = db.scalar(select(ExpertPanelist).where(ExpertPanelist.code == "E1"))
        foreign = db.scalar(select(ExpertItem).where(ExpertItem.kind == "A", ExpertItem.key.not_in(pan.assignment["A"])))
    assert client.post("/api/expert-panel/labels", headers=H(tok),
                       json={"item_id": str(foreign.id), "value": {"relevance": 1}}).status_code == 404
    # перевыпуск ссылки: старая не работает, разметка сохраняется
    with SessionLocal() as db:
        new = create_invite(db, "E1", rotate=True)
    assert client.post("/api/expert-panel/enter", json={"token": inv["token"]}).status_code == 404
    t2 = client.post("/api/expert-panel/enter", json={"token": new["token"]}).json()["access_token"]
    assert client.get("/api/expert-panel/me", headers=H(t2)).json()["progress"]["A"]["done"] == 1
    # /validation: блок экспертов — разметка идёт, проверка расчёта на синтетике проходит
    ex = client.get("/api/validation/report").json()["experts"]
    assert ex["status"]["state"] == "partial" and ex["panel"][0]["code"] == "E1"
    assert ex["synthetic_check"]["ok"] is True
    assert "Тест" not in str(ex["panel"])  # имена экспертов наружу не уходят


def test_validation_waiting_and_demo_expert_excluded(client):
    _seed_and_pack()
    ex = client.get("/api/validation/report").json()["experts"]
    assert ex["status"]["state"] == "waiting" and ex["pack"]["A_needs"] == 10 and ex["labels"] == 0
    assert ex["synthetic_check"]["ok"] is True
    assert {c["what"] for c in ex["synthetic_check"]["checks"]} >= {"Порог Middle → Senior восстановлен"}
    from app.modules.auth.models import User
    from app.modules.demo.seed import _user
    from app.core.enums import UserRole
    from app.core.security import create_access_token

    with SessionLocal() as db:  # демо-эксперт (как у жюри): демо-назначение, оценки в метрики не входят
        u = _user(db, "expert@jury.example.com", UserRole.expert, "x")
        db.commit()
        tok, _ = create_access_token(u.id, u.role.value, u.token_version)
    me = client.get("/api/expert-panel/me", headers=H(tok)).json()
    assert me["in_panel"] and me["is_demo"] and me["progress"]["A"]["total"] < 30
    a = client.get("/api/expert-panel/items/A", headers=H(tok)).json()["items"]
    assert client.post("/api/expert-panel/labels", headers=H(tok),
                       json={"item_id": a[0]["id"], "value": {"relevance": 1}}).status_code == 200
    ex = client.get("/api/validation/report").json()["experts"]
    assert ex["labels"] == 0 and ex["status"]["state"] == "waiting"
    # кандидату панель недоступна
    with SessionLocal() as db:
        c = db.scalar(select(User).where(User.role == UserRole.candidate))
        ct, _ = create_access_token(c.id, c.role.value, c.token_version)
    assert client.get("/api/expert-panel/me", headers=H(ct)).status_code == 403


def test_full_labeling_by_three_experts_gives_metrics(client):
    """Три эксперта размечают всё назначенное (синтетически) → метрики подбора, согласие, Ангофф на /validation."""
    from app.modules.experts import section, synth
    from app.modules.experts.models import ExpertItem, ExpertLabel, ExpertPanelist
    from app.modules.experts.service import create_invite

    _seed_and_pack()
    with SessionLocal() as db:
        for code in ("E1", "E2", "E3"):
            create_invite(db, code)
        items, _ = section.load(db)
        fake = synth.make(items)
        pans = {p.slot: p for p in db.scalars(select(ExpertPanelist))}
        ids = {i.key: i.id for i in db.scalars(select(ExpertItem))}
        for lb in fake:
            db.add(ExpertLabel(panelist_id=pans["E" + lb["coder"][1:]].id, item_id=ids[lb["key"]], value=lb["value"]))
        db.commit()
    ex = client.get("/api/validation/report").json()["experts"]
    assert ex["status"]["state"] == "ready", ex["status"]
    m = ex["matching"]["summary"]
    assert m["p@5"]["platform"]["mean"] > m["p@5"]["bm25"]["mean"] > m["p@5"]["random"]["mean"]
    assert m["p@5"]["diff_platform_bm25"]["lo"] is not None
    assert ex["agreement"]["A"]["alpha"] is not None and len(ex["agreement"]["A"]["pairwise"]) == 3
    cuts = {b["boundary"]: b for b in ex["angoff"]["boundaries"]}
    assert abs(cuts["middle_senior"]["angoff"] - synth.PLANTED_CUTS["middle_senior"]) < 0.3
    assert cuts["junior_middle"]["current"] == 0.0 and cuts["junior_middle"]["se"] is not None
    assert ex["llm"] is None  # оценок модели нет — LLM в тестах выключен
