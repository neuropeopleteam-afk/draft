"""А5, 21.10 вечер: второй отложенный набор hh.ru (проверка dir-v2) — набор не пересекается с прежними, хэш до прогона,
на экран — одна цифра направления из второго набора, первый набор и разработка — только история."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RD = ROOT / "docs/realdata"
H2 = RD / "hh_holdout2_corpus.json"


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _need(p: Path) -> dict:
    if not p.exists():
        pytest.skip(f"{p.name} ещё не собран")
    return _load(p)


def test_holdout2_disjoint_from_dev_and_holdout1():
    h2 = _need(H2)
    prev = _load(RD / "hh_match_corpus.json")["items"] + _load(RD / "hh_holdout_corpus.json")["items"]
    ids, shas = {it["id"] for it in prev}, {it["text_sha256"] for it in prev}
    for it in h2["items"]:
        assert it["id"] not in ids and it["text_sha256"] not in shas, it["id"]
    assert len({it["text_sha256"] for it in h2["items"]}) == len(h2["items"])
    assert set(h2["excluded_sets"]) == {"docs/realdata/hh_match_corpus.json", "docs/realdata/hh_holdout_corpus.json"}


def test_holdout2_freeze_hash_matches_and_run_after_freeze():
    h2 = _need(H2)
    fz = _load(RD / "hh_holdout2_FREEZE.json")
    rows = sorted(f"{it['id']}\t{it['text_sha256']}\t{it['bucket']}" for it in h2["items"])
    assert hashlib.sha256("\n".join(rows).encode()).hexdigest() == fz["manifest_sha256"]
    assert hashlib.sha256((RD / "hh_holdout2_PROTOCOL.md").read_bytes()).hexdigest() == fz["protocol_sha256"]
    run = RD / "hh_holdout2_RUN.json"
    if run.exists():
        r = _load(run)
        assert r["manifest_sha256"] == fz["manifest_sha256"] and r["run_started_at"] > fz["frozen_at"]


def test_numbers_site_figure_is_holdout2_and_history_kept():
    res = ROOT / "backend/app/modules/validation/data/hh_match_holdout2.json"
    if not res.exists():
        pytest.skip("прогона на втором наборе ещё нет")
    hm = _load(RD / "numbers_matching.json")["hh_match"]
    r = _load(res)
    assert hm["manifest_sha256"] == r["holdout"]["freeze"]["manifest_sha256"]
    assert hm["site"]["direction_ok"]["k"] == r["overall"]["direction_ok"]["k"]
    assert hm["site"]["direction_ok"]["n"] == r["overall"]["direction_ok"]["n"]
    assert "--tag 2" in hm["site"]["recompute"]
    assert "holdout1" in hm["history"] and "dir-v2" in hm["history"]["holdout1"]["note"]
    assert hm["direction_control"]["flag"] == "NEED_TITLE_ROLE=0"


def test_hh_match_endpoint_serves_holdout2(client):
    res = ROOT / "backend/app/modules/validation/data/hh_match_holdout2.json"
    if not res.exists():
        pytest.skip("прогона на втором наборе ещё нет")
    d = client.get("/api/validation/hh-match").json()
    assert d["set"] == "holdout2" and "отложенный набор" in d["set_ru"]
    assert d["overall"]["direction_ok"] == _load(res)["overall"]["direction_ok"]
    assert "disputed" not in d and "disputed" not in (d.get("direction_control") or {})
