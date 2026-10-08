"""Задание C (Ангофф) эксперта берётся из сохранённого пакета, а не из пересчёта по текущему банку (Ф1, С-3)."""
from sqlalchemy import select

from app.core.db import SessionLocal
from tests.test_day2_rules import H
from tests.test_jury_live import _login


def test_demo_expert_c_tasks_come_from_saved_pack_not_current_bank(client, monkeypatch):
    from app.modules.demo.seed import seed
    from app.modules.experts import pack as P
    from app.modules.experts.models import ExpertPanelist

    with SessionLocal() as db:
        seed(db)
        db.commit()
        assert P.ensure_pack(db)
        before = {s: P.assignment(db, s) for s in ("DEMO", "E1", "E2", "E3")}
    assert len(before["DEMO"]["C"]) == 6 and all(len(before[s]["C"]) == 30 for s in ("E1", "E2", "E3"))
    # банк изменился после сборки пакета: пересчитанный план — по другим семействам, с ключами пакета не пересекается
    monkeypatch.setattr(P, "c_plan", lambda: {"core": ["zz_core_1", "zz_core_2"], "E1": ["zz_a"], "E2": ["zz_b"],
                                              "E3": ["zz_c"]})
    with SessionLocal() as db:
        after = {s: P.assignment(db, s) for s in ("DEMO", "E1", "E2", "E3")}
    assert after == before
    # у слотов разные блоки, ядро общее для всех
    core = {k for k in before["E1"]["C"]} & {k for k in before["E2"]["C"]} & {k for k in before["E3"]["C"]}
    assert len(core) == P.C_CORE_N
    # демо-эксперт жюри (новый и созданный до правки — с пустым C) видит ≥ 4 заданий C
    tok = _login(client, "expert")["access_token"]
    me = client.get("/api/expert-panel/me", headers=H(tok)).json()
    assert me["is_demo"] and me["progress"]["C"]["total"] >= 4 and me["progress"]["C"]["done"] == 0
    with SessionLocal() as db:
        pan = db.scalar(select(ExpertPanelist).where(ExpertPanelist.is_demo.is_(True)))
        pan.assignment = {**pan.assignment, "C": []}  # как на стенде: «0 из 0»
        db.commit()
    again = client.get("/api/expert-panel/me", headers=H(tok)).json()
    assert again["progress"]["C"]["total"] >= 4
    items = client.get("/api/expert-panel/items/C", headers=H(tok)).json()["items"]
    assert len(items) == again["progress"]["C"]["total"]
