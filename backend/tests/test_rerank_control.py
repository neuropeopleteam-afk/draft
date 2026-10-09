"""Я1, пункт 6: контроль признака «ядро роли» на разметке v1 и v2 (experts.rerank_control) — тот же A.matching_by_pack,
что /validation. Здесь — на синтетической разметке тестового мира (не на настоящей v2: она только на сервере).
Главная проверка: пересчёт мест текущим кодом при выключенном признаке воспроизводит замороженные места v2."""
import json

from app.core.db import SessionLocal
from tests.test_experts2 import _label_v1_synthetic, _seed_v1


def _label_v2_by_rules(db):
    from app.modules.experts import pack2
    from app.modules.experts.models import ExpertItem
    from sqlalchemy import select

    hidden = {str(i.id): i.hidden for i in db.scalars(select(ExpertItem).where(ExpertItem.pack == pack2.PACK2))}
    for code in ("E1", "E2", "E3"):
        rows = pack2.export_rows(db, code)
        lines = [json.dumps({"item_id": x["item_id"], "relevance": int(hidden[x["item_id"]]["rule_label"])}) for x in rows]
        pack2.import_labels(db, code, lines)


def test_rerank_control_reproduces_frozen_v2_and_prints_numbers(client, monkeypatch):
    from app.modules.experts import analysis as A
    from app.modules.experts import pack as P
    from app.modules.experts import pack2, rerank_control as R
    from app.modules.experts.section import load

    monkeypatch.delenv("RANK_CORE_SKILL", raising=False)
    _seed_v1()
    with SessionLocal() as db:
        _label_v1_synthetic(db)
        assert pack2.build(db)["created"]
        _label_v2_by_rules(db)
        items2, labels2 = load(db, pack2.PACK2)
        demo = pack2._demo_pool(db)
        st: dict = {}
        off = R.rerank(db, items2, demo, core_on=False, rank_key="rank_match", stats=st)
        # выкл.: места те же, что в пакете (тот же код подборки, тот же мир)
        assert all(off[k]["hidden"]["rank_match"] == items2[k]["hidden"]["rank_match"] for k in items2
                   if items2[k]["kind"] == "A")
        assert sum(s.get("map_ref", 0) for s in st.values()) == sum(1 for i in items2.values() if i["kind"] == "A")
        on = R.rerank(db, items2, demo, core_on=True, rank_key="rank_match", stats=st)
        assert set(on) == set(items2)  # из пакета никто не выпал
        items1, labels1 = load(db)
        frozen = A.matching_by_pack({P.PACK: (items1, labels1), pack2.PACK2: (items2, labels2)}, base=P.PACK)
        again = A.matching_by_pack({P.PACK: (items1, labels1), pack2.PACK2: (off, labels2)}, base=P.PACK)
        assert again["packs"]["v2"]["summary"] == frozen["packs"]["v2"]["summary"]
        lines = R.run(db)
    text = "\n".join(lines)
    print(text)
    assert "заморожено в пакетах" in text and "RANK_CORE_SKILL=0" in text and "RANK_CORE_SKILL=1" in text
    assert "вкл. − выкл." in text and "v2 p@5:" in text and "не найдено 0" in text
    # печатаются только числа и коды: ни ref кандидатов, ни текстов потребностей
    for it in items2.values():
        assert it["hidden"]["ref"] not in text
    assert all(nd["text"][:30] not in text for nd in pack2.needs2())
