"""Статистика протоколов ФСП без ПДн: k-анонимность, нормализация субъектов, снимок aggregates.json."""
from __future__ import annotations

import json
from pathlib import Path

from app.modules.fsp import protocol_stats as ps

ROOT = Path(__file__).resolve().parents[2]


def _rec(i: int, region: str, disc: str = "программирование продуктовое", place: int = 5, rank=None, status="no_norm"):
    return {"person": True, "fio_hash": f"h{i}", "fio_norm": f"фамилия{i} имя отчество", "birth_date": "2003-01-01",
            "region": region, "discipline": disc, "place": place, "event_id": "e1", "date": "2026-04-17",
            "evsk_rank": rank, "evsk_status": status, "event_status": "allrus_other_sport_ekp"}


def test_small_groups_are_suppressed():
    recs = [_rec(i, "г. Москва") for i in range(5)] + [_rec(10 + i, "Томская область") for i in range(2)]
    out = ps.protocol_stats(("region",), records=recs)
    regions = {g["key"]["region"]: g["athletes"] for g in out["groups"]}
    assert regions == {"г. Москва": 5}
    assert out["suppressed_groups"] == 1


def test_output_has_no_personal_fields():
    recs = [_rec(i, "Воронежская область", place=1 + i % 3, rank="КМС", status="fulfilled") for i in range(6)]
    agg = ps.aggregates(records=recs)
    txt = json.dumps(agg, ensure_ascii=False)
    for r in recs:
        assert r["fio_norm"] not in txt and r["fio_hash"] not in txt
    assert "2003-01-01" not in txt
    assert agg["totals"]["athletes_with_evsk_norm"] == 6
    assert agg["regions"][0]["kms_plus"] == 6 and agg["regions"][0]["podiums"] == 6


def test_region_normalization_handles_protocol_spellings():
    n = lambda s: ps.normalize_region(s)[0]  # noqa: E731
    assert n("г. Санкт Петербург") == "г. Санкт-Петербург"
    assert n("Московская область, г. Пушкино") == "Московская область"
    assert n("Томская область") == "Томская область"  # не «Омская»
    assert n("Сахалинская область") == "Сахалинская область"  # не «Саха»
    assert n("Республика Татарстан г. Иннополис") == "Республика Татарстан"
    assert n("РФ (отборочный этап)") is None
    assert ps.normalize_region("Донецкая Народная Республика г. Донецк")[1] == "ЮФО"
    assert len(ps.SUBJECTS) == 89


def test_snapshot_in_docs_is_anonymous_and_k3():
    agg = json.loads((ROOT / "docs/realdata/fsp_protocols/aggregates.json").read_text(encoding="utf-8"))
    assert agg["k_min"] == 3
    for section in ("by_discipline", "by_year_discipline", "by_event_status", "by_fo"):
        for g in agg[section]:
            assert g["athletes"] >= 3
    for r in agg["regions"]:
        assert r["athletes"] >= 3
        assert all(v >= 3 for v in r["by_discipline"].values())
    banned = {"fio", "fio_norm", "fio_hash", "key_hash", "birth_date", "team"}
    def walk(o):
        if isinstance(o, dict):
            assert not (set(o) & banned), set(o) & banned
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(agg)
    stats = json.loads((ROOT / "docs/realdata/fsp_protocols/index_stats.json").read_text(encoding="utf-8"))
    for k in ("documents", "results", "years", "generated_at", "recompute"):
        assert stats.get(k), k
    assert stats["athletes"] == agg["totals"]["athletes"]
