"""Тесты восстановления мест (place_recover.py): разбор ячейки «Место», шапка в геометрии, места по порядку.

Строки — как напечатаны в официальных протоколах ФСП (разбор глазами 21.10, переезд 16):
«б/м» (КФ-2026 итог, стр. 60–70), «14-24» (КР-2026 робототехника, стр. 5–6), «9-10» (ЧР-2025 продуктовое, стр. 5),
«1.» (ЦФО-2026), «DSQ» в баллах (ПФО-2026, стр. 11)."""
from __future__ import annotations

import json
from pathlib import Path

from tools.fsp_protocols.place_recover import fit_geometry, infer_sequence, norm_pt, parse_place


def test_parse_place_cell_texts() -> None:
    assert parse_place("7") == {"place": 7, "place_range": None, "place_status": "placed"}
    assert parse_place("1.")["place"] == 1
    assert parse_place("9-10") == {"place": None, "place_range": [9, 10], "place_status": "shared_range"}
    assert parse_place("14 – 24")["place_range"] == [14, 24]
    assert parse_place("б/м")["place_status"] == "no_place"
    assert parse_place("Б\\М")["place_status"] == "no_place"
    assert parse_place("DSQ")["place_status"] == "disqualified"
    assert parse_place("н/я")["place_status"] == "did_not_start"
    assert parse_place("")["place_status"] == "empty"
    assert parse_place("24-14")["place_status"] == "unparsed"  # обратный диапазон — не место
    assert norm_pt(" 12. ") == "12"


def test_fit_geometry_strips_header_only_when_sum_requires() -> None:
    # КР-2026 продуктовое, стр. 1: линия над шапкой (0), шапка (1), лишний блок (1), команды 5/6/1
    assert fit_geometry([0, 1, 1, 5, 6, 1], 12) == [5, 6, 1]
    # КФ-2026, стр. 60: шапка 1 + продолжение команды с прошлой страницы (1 строка) — продолжение остаётся
    assert fit_geometry([1, 1, 3, 3, 2, 1, 2, 3, 2, 2], 19) == [1, 3, 3, 2, 1, 2, 3, 2, 2]
    assert fit_geometry([1, 5, 7, 1], 12) is None  # суммы не сходятся — геометрии не верим


def _row(team: str, text: str, uncertain: bool) -> dict:
    p = parse_place(text)
    return {"team": team, "place_text": text, "place": p["place"], "place_range": p["place_range"],
            "place_status": p["place_status"], "place_uncertain": uncertain, "place_check": None if uncertain else "x"}


def test_infer_sequence_between_confirmed_neighbours(tmp_path: Path) -> None:
    # ЧР-2025 продуктовое, стр. 4–5: место команды под печатью не читается; до неё 7, после «9-10» → 8
    d = tmp_path / "doc" / "pages_json"
    d.mkdir(parents=True)
    (d / "page_004.json").write_text(json.dumps({"rows": [_row("A", "7", False), _row("B", "", True)]}), encoding="utf-8")
    (d / "page_005.json").write_text(json.dumps({"rows": [_row("B", "", True), _row("C", "9-10", False)]}), encoding="utf-8")
    infer_sequence(tmp_path)
    p4 = json.loads((d / "page_004.json").read_text(encoding="utf-8"))["rows"]
    p5 = json.loads((d / "page_005.json").read_text(encoding="utf-8"))["rows"]
    assert p4[1]["place"] == 8 and p4[1]["place_check"] == "sequence" and not p4[1]["place_uncertain"]
    assert p5[0]["place"] == 8


def test_infer_sequence_refuses_ambiguous_gap(tmp_path: Path) -> None:
    d = tmp_path / "doc" / "pages_json"
    d.mkdir(parents=True)
    rows = [_row("A", "7", False), _row("B", "", True), _row("C", "10", False)]  # между 7 и 10 — два места
    (d / "page_001.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    infer_sequence(tmp_path)
    out = json.loads((d / "page_001.json").read_text(encoding="utf-8"))["rows"]
    assert out[1]["place"] is None and out[1]["place_uncertain"]
