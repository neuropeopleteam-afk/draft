"""Тесты apply_audit_fixes.py на синтетических записях (без ПДн)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("FSP_INDEX_HMAC_KEY", "00" * 32)
import apply_audit_fixes as aaf  # noqa: E402
import normalize as norm  # noqa: E402


def _rec(fio, page, file="a.pdf", person=True, bd="2005-01-02"):
    return {"pdf_url": "https://x/" + file, "page": page, "event_id": "e1", "person": person, "fio_norm": fio,
            "birth_date": bd, "fio_hash": norm.compute_fio_hash(fio), "key_hash": norm.compute_key_hash(fio, bd[:4]),
            "evsk_status": "no_norm", "place_status": "placed"}


def _idx():
    return {"stats": {"documents_count": 1}, "sources": [{"filename": "a.pdf"}],
            "records": [_rec("иванов иван иванович", 1), _rec("петров петр петрович", 1), _rec("тренер т т", 3), _rec("специалист с с", 3)]}


def test_fix_fio_rehashes_and_drop_page():
    idx = _idx()
    kh = idx["records"][0]["key_hash"]
    out, s = aaf.apply(idx, [{"file": "a.pdf", "page": 1, "key_hash": kh, "set": {"fio_norm": "иванов иван ильич"}},
                             {"file": "a.pdf", "page": 3, "drop": True}])
    assert s["records_out"] == 2 and s["matched"] == {"0": 1, "1": 2}
    r = out["records"][0]
    assert r["fio_norm"] == "иванов иван ильич" and r["key_hash"] == norm.compute_key_hash("иванов иван ильич", "2005")
    assert r["fio_hash"] != idx["records"][1]["fio_hash"]
    assert out["stats"]["person_records"] == 2 and out["sources"][0]["records_count"] == 2


def test_unmatched_rule_fails():
    with pytest.raises(SystemExit):
        aaf.apply(_idx(), [{"file": "a.pdf", "page": 9, "drop": True}])
