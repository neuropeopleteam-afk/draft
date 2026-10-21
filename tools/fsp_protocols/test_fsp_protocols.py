"""Тесты модуля нормализации, обезличивания и поиска по протоколам ФСП России (`tools.fsp_protocols`)."""

from __future__ import annotations

import json
from pathlib import Path

from tools.fsp_protocols.lookup import verify_candidate_fsp
from tools.fsp_protocols.normalize import (
    compute_fio_hash,
    compute_key_hash,
    extract_birth_date,
    normalize_fio,
    normalize_rank,
)
from tools.fsp_protocols.sources import SOURCES


def test_normalize_fio_and_hashes() -> None:
    f1 = normalize_fio("  Иванов   Пётр Сергеевич ")
    f2 = normalize_fio("иванов петр сергеевич")
    assert f1 == "иванов петр сергеевич"
    assert f1 == f2
    assert compute_fio_hash(f1) == compute_fio_hash(f2)
    bdate, byear = extract_birth_date("М 01.01.2000")
    assert bdate == "2000-01-01"
    assert byear == "2000"
    h_with_year = compute_key_hash(f1, byear)
    h_no_year = compute_key_hash(f1, None)
    assert h_with_year != h_no_year
    assert len(h_with_year) == 64


def test_normalize_rank() -> None:
    assert normalize_rank("КМС") == "КМС"
    assert normalize_rank("Мастер спорта") == "МС"
    assert normalize_rank("1 разряд") == "I"
    assert normalize_rank("ВК") == "ВК"


def test_sources_catalog_complete() -> None:
    assert len(SOURCES) == 19
    urls = {s.pdf_url for s in SOURCES}
    assert len(urls) == 19
    assert all(u.startswith("https://fsp-russia.ru/upload/iblock/") for u in urls)


def test_sample_anonymized_has_no_personal_data() -> None:
    sample_path = Path(__file__).resolve().parents[2] / "docs/realdata/fsp_protocols/sample_anonymized.json"
    assert sample_path.exists()
    data = json.loads(sample_path.read_text(encoding="utf-8"))
    assert data["stats"]["documents_count"] == 19
    assert data["stats"]["total_records"] >= 3000
    assert len(data["sample_records"]) == 3
    for row in data["sample_records"]:
        assert "152-ФЗ" in (row.get("fio_norm") or "")
        assert row.get("birth_date") is None or "152-ФЗ" in str(row.get("birth_date"))
        # с e31b107c хэши в индексе — HMAC с секретом сервера; в образце в git хэша нет вовсе (заглушка)
        assert row.get("key_hash") == "<hmac-sha256>" and row.get("fio_hash") == "<hmac-sha256>"
        assert row.get("pdf_url", "").startswith("https://fsp-russia.ru/")


def test_verify_candidate_lookup_roundtrip(tmp_path: Path) -> None:
    fio = normalize_fio("Тестов Тест Тестович")
    idx_file = tmp_path / "index.json"
    idx_file.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "key_hash": compute_key_hash(fio, "2003"),
                        "fio_hash": compute_fio_hash(fio),
                        "fio_norm": fio,
                        "birth_date": "2003-05-10",
                        "discipline": "программирование продуктовое",
                        "event_title": "Чемпионат России 2025",
                        "ekp_no": "2101590019043742",
                        "date": "2025-11-23",
                        "place": 1,
                        "rank": "КМС",
                        "team": "Тест-Команда",
                        "region": "Москва",
                        "pdf_url": "https://fsp-russia.ru/upload/iblock/138/tb1vnqokiid4fiwdb40evznavplvmysg.pdf",
                        "page": 3,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    res1 = verify_candidate_fsp(fio="Тестов Тест Тестович", birth_date="10.05.2003", index_path=idx_file)
    assert res1["verified"] is True
    assert res1["match_type"] == "exact_key_hash"
    assert res1["highest_rank"] == "КМС"
    assert res1["achievements"][0]["ekp_no"] == "2101590019043742"
    assert "fio_norm" not in res1["achievements"][0]

    res2 = verify_candidate_fsp(fio="Тестов Тест Тестович", index_path=idx_file)
    assert res2["verified"] is True
    assert res2["match_type"] == "fio_hash"
