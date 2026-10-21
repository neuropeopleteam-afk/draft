"""Пакет экспертной разметки v2 (Р33): сборка (детерминированность, без дублей с v1, слепота экспорта), импорт
(валидация, идемпотентность, источник), метрики по пакетам (ДИ сходится к известному ответу), метрики v1 — по снимку
пакета (не зависят от пересоздания демо-данных)."""
import json
import random

import numpy as np
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.modules.experts import analysis as A
from app.modules.experts import stats as S


def _seed_v1():
    from app.modules.demo.seed import seed
    from app.modules.experts.pack import ensure_pack

    with SessionLocal() as db:
        seed(db)
        db.commit()
        assert ensure_pack(db)


def _label_v1_synthetic(db):
    """Синтетические оценки v1 тремя ролями (как в test_experts) — чтобы было, что заимствовать и считать."""
    from app.modules.experts import section, synth
    from app.modules.experts.models import ExpertItem, ExpertLabel, ExpertPanelist
    from app.modules.experts.service import create_invite

    for code in ("E1", "E2", "E3"):
        create_invite(db, code)
    items, _ = section.load(db)
    pans = {p.slot: p for p in db.scalars(select(ExpertPanelist).where(ExpertPanelist.pack == "v1"))}
    ids = {i.key: i.id for i in db.scalars(select(ExpertItem).where(ExpertItem.pack == "v1"))}
    for lb in synth.make(items):
        if items[lb["key"]]["kind"] == "A":
            db.add(ExpertLabel(panelist_id=pans["E" + lb["coder"][1:]].id, item_id=ids[lb["key"]], value=lb["value"]))
    db.commit()


def _plan_view(pl):
    return [(it["key"], json.dumps(it["hidden"], sort_keys=True, ensure_ascii=False),
             json.dumps(it["payload"], sort_keys=True, ensure_ascii=False)) for it in pl["items"]], pl["assignment"]


# ------------------------------------------------------------------ сборка, слепота экспорта, импорт
def test_pack2_build_export_import(client, monkeypatch):
    # пакет v2 размечен по порядку match-v1.2 — сверяем с продуктом без добора ступенью выше (Я12б, test_grade_above)
    monkeypatch.setenv("MATCH_GRADE_ABOVE", "0")
    monkeypatch.setenv("MATCH_V2", "0")  # пакет v2 экспертов — порядок match-v1.2 (pack2.match_order), сверка с v1-путём
    from app.modules.experts import pack2
    from app.modules.experts.models import ExpertItem, ExpertLabel, ExpertPanelist
    from app.modules.matching import ranking
    from app.modules.matching.need_parser import parse_need

    _seed_v1()
    with SessionLocal() as db:
        _label_v1_synthetic(db)
        # match-v1 в пакете — тот же порядок, что подборка продукта (без недемо-кандидатов)
        demo = pack2._demo_pool(db)
        refs = {db.get(__import__("app.modules.profiles.models", fromlist=["CandidateProfile"]).CandidateProfile, u)
                .public_ref for u in demo}
        for nd in pack2.needs2()[:3]:
            req = parse_need(nd["text"], use_llm=False)
            prod = [r["ref"] for r in ranking.build_selection(db, req, {}, limit=10_000)["results"] if r["ref"] in refs]
            assert [b.profile.public_ref for _, b in pack2.match_order(db, req, demo)] == prod
        # детерминированность: два плана по одному миру совпадают полностью
        p1, p2 = pack2.plan(db), pack2.plan(db)
        assert _plan_view(p1) == _plan_view(p2)
        r = pack2.build(db)
    assert r["created"] and 150 <= r["new_pairs"] <= pack2.PAIRS_MAX, r
    assert set(r["needs"]) >= {f"N{i:02d}" for i in range(17)}
    assert all(v <= pack2.ROLE_MAX for v in r["per_role"].values()) and sum(r["per_role"].values()) == 2 * r["new_pairs"]
    with SessionLocal() as db:
        n_items = db.scalar(select(func.count()).select_from(ExpertItem).where(ExpertItem.pack == "v2"))
        again = pack2.build(db)  # повторный запуск ничего не дублирует
        assert not again["created"] and again["exists"] and again["new_pairs"] == r["new_pairs"]
        assert db.scalar(select(func.count()).select_from(ExpertItem).where(ExpertItem.pack == "v2")) == n_items
        assert db.scalar(select(func.count()).select_from(ExpertPanelist).where(ExpertPanelist.pack == "v2")) == 3
        v1 = {(i.grp, pack2.fingerprint(i.payload["card"], i.hidden.get("category"))): i.key
              for i in db.scalars(select(ExpertItem).where(ExpertItem.pack == "v1", ExpertItem.kind == "A"))}
        v1_refs = {(i.grp, i.hidden["ref"]) for i in db.scalars(select(ExpertItem).where(ExpertItem.pack == "v1",
                                                                                          ExpertItem.kind == "A"))}
        v2 = db.scalars(select(ExpertItem).where(ExpertItem.pack == "v2")).all()
        assert {i.kind for i in v2} == {"A"}  # блоки B и C в v2 не входят
        new = [i for i in v2 if not i.hidden.get("borrowed_from")]
        borrowed = [i for i in v2 if i.hidden.get("borrowed_from")]
        # без дублей с v1: ни по ref (тот же мир), ни по снимку карточки; совпавшие — ссылкой на ключ v1, без ролей
        assert borrowed and all(i.hidden["borrowed_from"] in v1.values() and i.hidden["roles"] == [] for i in borrowed)
        for i in new:
            assert (i.grp, i.hidden["ref"]) not in v1_refs
            assert (i.grp, i.hidden["fingerprint"]) not in v1
            assert len(i.hidden["roles"]) == 2 and set(i.hidden["roles"]) <= {"E1", "E2", "E3"}
        by_need: dict = {}
        for i in v2:
            by_need.setdefault(i.grp, []).append(i.hidden)
        for nid, hs in by_need.items():
            n_sel = hs[0]["n_selection"]
            assert sum(h["stratum"] == "top" for h in hs) == min(pack2.TOP, n_sel), nid
            assert sum(h["stratum"] == "mid" for h in hs) == min(pack2.MID_N, max(0, min(n_sel, 30) - 8)), nid
            assert sum(h["stratum"] == "hard" for h in hs) == pack2.HARD_N, nid
            assert all(h["rank_match"] is None or h["rank_match"] > 30 for h in hs if h["stratum"] == "hard"), nid
            assert all(9 <= h["rank_match"] <= 30 for h in hs if h["stratum"] == "mid"), nid
        rows = {c: pack2.export_rows(db, c) for c in ("E1", "E2", "E3")}
        hidden = {str(i.id): i.hidden for i in v2}
        refs_all = {i.hidden["ref"] for i in v2}
    # экспорт вслепую: только item_id, текст и поля карточки, шкала; ни мест, ни баллов, ни метода, ни ref
    for code, rr in rows.items():
        assert len(rr) == r["per_role"][code] and len({x["item_id"] for x in rr}) == len(rr)
        assert set(rr[0]) == {"item_id", "n", "total", "need_id", "need_text", "card_text", "card", "question", "scale",
                              "rules", "answer_format"}
        blob = json.dumps(rr, ensure_ascii=False)
        for bad in ("rank", "score_match", "score_bm25", "bm25", "BM25", "match-v1", "stratum", "rule_label",
                    "borrowed", "hidden", "fingerprint", "demo_idx", "platform", "sources"):
            assert bad not in blob, (code, bad)
        assert not any(ref in blob for ref in refs_all)
        assert rr[0]["scale"]["3"] and "θ" in rr[0]["card_text"]
    # порядок перемешан: внутри потребности не по месту в подборке, и у ролей разный
    shuffled = 0
    for code, rr in rows.items():
        seq: dict = {}
        for x in rr:
            seq.setdefault(x["need_id"], []).append(hidden[x["item_id"]]["rank_match"] or 10 ** 6)
        shuffled += sum(1 for v in seq.values() if v != sorted(v))
    assert shuffled >= 10
    assert [x["item_id"] for x in rows["E1"]] != [x["item_id"] for x in rows["E2"]]

    # ---- импорт: проверки save_label, всё или ничего, повтор не дублирует, источник честно
    e1 = rows["E1"]
    lines = [json.dumps({"item_id": x["item_id"], "relevance": k % 4, "comment": "ок"}) for k, x in enumerate(e1[:12])]
    with SessionLocal() as db:
        def imp(ls, **kw):
            return pack2.import_labels(db, "E1", ls, **kw)

        def count():
            return db.scalar(select(func.count()).select_from(ExpertLabel).join(
                ExpertPanelist, ExpertPanelist.id == ExpertLabel.panelist_id).where(ExpertPanelist.pack == "v2"))

        try:
            imp(lines, source="model")
            raise AssertionError("модель без названия")
        except Exception as e:  # noqa: BLE001
            assert getattr(e, "status_code", None) == 422
        bad = lines + [json.dumps({"item_id": e1[12]["item_id"], "relevance": 5})]
        r1 = imp(bad, source="model", model="Claude Fable 5.1")
        assert not r1["ok"] and "0 до 3" in r1["errors"][0] and count() == 0  # одна ошибка — не записано ничего
        foreign = next(x for x in rows["E2"] if x["item_id"] not in {y["item_id"] for y in e1})
        r1 = imp(lines + [json.dumps({"item_id": foreign["item_id"], "relevance": 1})], source="model", model="M")
        assert not r1["ok"] and "назначении" in r1["errors"][0]
        assert not imp(lines + lines[:1], source="model", model="M")["ok"]  # повтор объекта в файле
        assert not imp(lines + ["{не json"], source="model", model="M")["ok"]
        assert not imp([json.dumps({"item_id": e1[0]["item_id"], "relevance": True})], source="model", model="M")["ok"]
        ok = imp(lines, source="model", model="Claude Fable 5.1", role="тимлид Backend")
        assert ok["ok"] and ok["added"] == 12 and ok["labeled"] == 12 and count() == 12
        again = imp(lines, source="model", model="Claude Fable 5.1")
        assert again["ok"] and again["added"] == 0 and again["unchanged"] == 12 and count() == 12
        # формат строк v1 (kind, n, group, item_id, value, comment) — тоже принимается; правка перезаписывает
        v1fmt = [json.dumps({"kind": "A", "n": 1, "group": "N00", "item_id": e1[0]["item_id"],
                             "value": {"relevance": 3, "must_have_missing": "Kafka"}, "comment": "сильный"})]
        upd = imp(v1fmt, source="model", model="Claude Fable 5.1")
        assert upd["updated"] == 1 and count() == 12
        # смешать источники под одним кодом нельзя
        for kw in ({"source": "people"}, {"source": "model", "model": "Другая модель"}):
            try:
                imp(lines, **kw)
                raise AssertionError(kw)
            except Exception as e:  # noqa: BLE001
                assert getattr(e, "status_code", None) == 409, kw
        pan = db.scalar(select(ExpertPanelist).where(ExpertPanelist.pack == "v2", ExpertPanelist.code == "E1"))
        assert pan.source == "model" and pan.source_model == "Claude Fable 5.1" and pan.profile == "тимлид Backend"
        lb = db.scalar(select(ExpertLabel).where(ExpertLabel.panelist_id == pan.id,
                                                 ExpertLabel.item_id == __import__("uuid").UUID(e1[0]["item_id"])))
        assert lb.value == {"relevance": 3, "must_have_missing": "Kafka"} and lb.comment == "сильный"
        # приглашение и источник v1 не задевают роли v2
        from app.modules.experts.service import panel_status, set_source

        assert [p["code"] for p in panel_status(db)] == ["E1", "E2", "E3"]
        assert set_source(db, ["E1"], "people") == ["E1"]
        db.refresh(pan)
        assert pan.source == "model"
    # /validation: пакеты v1, v2 и вместе; честная подпись источника
    ex = client.get("/api/validation/report").json()["experts"]
    pk = ex["packs"]
    assert pk["v2_labeled"] and pk["pack2"]["A_pairs_new"] == r["new_pairs"] and set(pk["packs"]) == {"v1", "v2", "all"}
    assert "не люди" in pk["caption"] and "Claude Fable 5.1" in pk["caption"]
    assert pk["packs"]["v1"]["summary"]["p@5"]["platform"]["mean"] == ex["matching"]["summary"]["p@5"]["platform"]["mean"]
    assert pk["packs"]["v1"]["summary"]["p@5"]["bm25"]["mean"] == ex["matching"]["summary"]["p@5"]["bm25"]["mean"]
    assert pk["packs"]["v2"]["labels"] == 12 and ex["pack"]["version"] == "v1"
    assert [p["code"] for p in ex["panel"]] == ["E1", "E2", "E3"]  # панель v1 — как раньше


def test_validation_without_v2_labels_shows_v1_as_before(client, capsys, monkeypatch):
    import io

    from app.modules.experts import pack2
    from app.modules.experts.__main__ import main

    _seed_v1()
    ex = client.get("/api/validation/report").json()["experts"]
    assert ex["packs"] is None and ex["pack"]["A_needs"] == 10
    assert main(["pack2", "build", "--dry-run"]) == 0
    with SessionLocal() as db:
        assert not pack2.exists(db)  # пробный расчёт ничего не пишет
        assert pack2.build(db)["created"]
    ex = client.get("/api/validation/report").json()["experts"]
    assert ex["packs"]["v2_labeled"] is False and ex["pack"]["A_needs"] == 10 and ex["labels"] == 0
    # CLI через docker compose exec -T: экспорт в stdout (только JSONL), импорт из stdin
    capsys.readouterr()
    assert main(["pack2", "export", "--code", "E2", "--out", "-"]) == 0
    rows = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert rows and all(set(r) >= {"item_id", "card_text", "scale"} for r in rows)
    good = "\n".join(json.dumps({"item_id": r["item_id"], "relevance": 2}) for r in rows[:3])
    monkeypatch.setattr("sys.stdin", io.StringIO(good + "\n" + json.dumps({"item_id": rows[3]["item_id"], "relevance": 9})))
    assert main(["pack2", "import", "--code", "E2", "--file", "-", "--source", "model", "--model", "M"]) == 2
    monkeypatch.setattr("sys.stdin", io.StringIO(good))
    assert main(["pack2", "import", "--code", "E2", "--file", "-", "--source", "model", "--model", "M"]) == 0
    assert "добавлено 3" in capsys.readouterr().out
    assert client.get("/api/validation/report").json()["experts"]["packs"]["v2_labeled"] is True


# ------------------------------------------------------------------ v1 по снимку после demo.seed --reset
def test_v1_metrics_by_snapshot_survive_demo_reset_and_v2_dedupes_by_card(client):
    from app.modules.demo.seed import delete_demo, seed
    from app.modules.experts import pack2, section
    from app.modules.experts.models import ExpertItem

    _seed_v1()
    with SessionLocal() as db:
        _label_v1_synthetic(db)
        before = section.section(db)["matching"]
        v1_refs = {i.hidden["ref"] for i in db.scalars(select(ExpertItem).where(ExpertItem.pack == "v1",
                                                                                 ExpertItem.kind == "A"))}
        delete_demo(db)  # как demo.seed --reset: id и ref кандидатов меняются
        seed(db)
        db.commit()
        section._cache.clear()
        after = section.section(db)["matching"]
        assert after["summary"] == before["summary"] and after["per_need"] == before["per_need"]
        pl = pack2.plan(db)
    hs = [it["hidden"] for it in pl["items"]]
    assert not ({h["ref"] for h in hs} & v1_refs)  # мир пересоздан
    borrowed = [h for h in hs if h.get("borrowed_from")]
    assert borrowed, "совпадения с v1 должны находиться по снимку карточки, а не по ref"
    assert all(h["roles"] == [] for h in borrowed) and all(len(h["roles"]) == 2 for h in hs if not h.get("borrowed_from"))


# ------------------------------------------------------------------ метрики по пакетам
def _item(nid, text, rank_m, rank_b, borrowed=None):
    h = {"rank_match": rank_m, "rank_bm25": rank_b}
    if borrowed:
        h["borrowed_from"] = borrowed
    return {"kind": "A", "grp": nid, "payload": {"need_text": text}, "hidden": h}


def test_cluster_bootstrap_matches_plain_bootstrap_for_single_units():
    v = [0.2, 0.4, 0.4, 0.8, 1.0, 0.6]
    a, b = S.boot_ci(v), S.cluster_boot_ci([[x] for x in v])
    assert (a["mean"], a["lo"], a["hi"]) == (b["mean"], b["lo"], b["hi"]) and b["clusters"] == 6
    c = S.cluster_boot_ci([[0.5, 0.5], [0.5]])
    assert c["mean"] == 0.5 and c["lo"] == c["hi"] == 0.5 and c["n"] == 3 and c["clusters"] == 2


def test_pack_metrics_exact_answer_and_borrowed_gold():
    """Известный ответ: в каждой потребности топ-5 match-v1 — 4 релевантных, сжатый топ-5 BM25 — 2 → P@5 0,8 и 0,4,
    разность 0,4 с ДИ нулевой ширины; пара v2, совпавшая с v1, берёт эталон из оценок v1."""
    items1, labels1, items2, labels2 = {}, [], {}, []
    gold_pattern = [3, 3, 2, 2, 0, 1, 0, 3, 0, 0, 2, 0, 1]  # места match-v1 1..13
    bm_order = [5, 6, 7, 8, 9, 10, 11, 12, 13, 1, 2, 3, 4]  # места BM25 для тех же пар
    for pack, items, labels in (("v1", items1, labels1), ("v2", items2, labels2)):
        for n in range(6):
            nid, text = f"N{n:02d}", f"потребность {n}"
            for j, g in enumerate(gold_pattern):
                key = f"A:{nid}:{pack}:{j}"
                rank_b = bm_order[j]
                if pack == "v1":
                    items[key] = {"kind": "A", "grp": nid, "payload": {"need_text": text},
                                  "hidden": {"rank_platform": j + 1, "rank_bm25": rank_b}}
                else:
                    items[key] = _item(nid, text, j + 1, rank_b, borrowed=f"A:{nid}:v1:{j}" if j == 0 else None)
                if pack == "v1" or j:  # пара 0 в v2 не размечается — эталон из v1
                    for coder in ("E1", "E2"):
                        labels.append({"coder": coder, "key": key, "value": {"relevance": g}})
    res = A.matching_by_pack({"v1": (items1, labels1), "v2": (items2, labels2)})
    for pack in ("v1", "v2", "all"):
        r = res["packs"][pack]
        s = r["summary"]["p@5"]
        assert r["needs_complete"] == (12 if pack == "all" else 6) and r["clusters"] == 6
        assert s["platform"]["mean"] == 0.8 and s["bm25"]["mean"] == 0.4  # BM25: места 1–4 и 5 → золото 2,0,1,0 и 3
        assert s["diff"]["mean"] == 0.4 and s["diff"]["lo"] == s["diff"]["hi"] == 0.4
        assert r["agreement"]["kappa_mean"] == 1.0
    assert res["packs"]["v2"]["borrowed"] == 6 and res["packs"]["v2"]["labels"] == 6 * 12 * 2


def test_pack_metrics_ci_covers_known_difference():
    """Синтетика с известной истиной: релевантных в топ-5 match-v1 ~ Bin(5; 0,8), в сжатом топ-5 BM25 ~ Bin(5; 0,5) —
    ожидаемая разность P@5 = 0,3. 95 % ДИ бутстрепа по потребностям накрывает её примерно в 95 % наборов и сужается
    с ростом числа потребностей."""
    def dataset(rng, n_needs):
        items, gold = {}, {}
        for n in range(n_needs):
            nid = f"N{n:03d}"
            top = [int(rng.random() < 0.8) for _ in range(5)]
            bm = [int(rng.random() < 0.5) for _ in range(5)]
            for j in range(10):  # места 1–5 — топ match-v1, 6–10 — топ BM25 (разные кандидаты)
                k = f"{nid}:{j}"
                items[k] = _item(nid, nid, j + 1, j - 4 if j >= 5 else 20 + j)
                gold[k] = 3.0 * (top[j] if j < 5 else bm[j - 5])
        return A.summarize_units(A.need_units(items, gold, "v2"))

    rng = random.Random(20261008)
    cover, widths = 0, {15: [], 60: []}
    reps = 120
    for i in range(reps):
        s = dataset(rng, 30)["summary"]["p@5"]["diff"]
        cover += s["lo"] <= 0.3 <= s["hi"]
    for n in widths:
        for _ in range(20):
            d = dataset(rng, n)["summary"]["p@5"]["diff"]
            widths[n].append(d["hi"] - d["lo"])
    assert 0.88 <= cover / reps <= 0.995, cover / reps
    assert np.mean(widths[60]) < 0.6 * np.mean(widths[15])
    big = dataset(random.Random(1), 400)["summary"]["p@5"]["diff"]
    assert abs(big["mean"] - 0.3) < 0.03 and big["lo"] < 0.3 < big["hi"]
