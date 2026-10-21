"""ЕВСК по официальным протоколам ФСП: нормы Приложения № 24 к приказу Минспорта № 450 и условия
Положения о ЕВСК (приказ № 173) на реальных соревнованиях из справок ФСП (evsk_data/events.json)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.fsp import evsk

ROOT = Path(__file__).resolve().parents[2]


def ev(event_id: str) -> dict:
    e = evsk.load_events()[event_id]
    return e


def check(event_id: str, place: int, birth: str | None = "2000-01-01") -> dict:
    return evsk.evsk_rank_for({"place": place, "event_id": event_id}, birth_date=birth)


def test_norm_files_are_the_same_in_backend_and_docs():
    for name in ("evsk_norms.json", "events.json"):
        a = json.loads((evsk.DATA_DIR / name).read_text(encoding="utf-8"))
        b = json.loads((ROOT / "docs/realdata/fsp_protocols" / name).read_text(encoding="utf-8"))
        assert a == b, name


def test_norms_table_has_all_rows_of_appendix_24():
    norms = evsk.load_norms()
    assert len(norms["rows"]) == 36
    pages = {r["page"] for r in norms["rows"]}
    assert pages == set(range(185, 196))  # стр. 185–195
    chr_row = next(r for r in norms["rows"] if r["status"] == "chr" and "МС" in r["places"])
    assert chr_row["places"] == {"МС": "1", "КМС": "2-4"}


def test_kr2025_final_second_place_is_kms_fulfilled():
    r = check("kr2025_prod_final", 2)
    assert r["rank"] == "КМС" and r["status"] == "fulfilled" and r["fulfilled"] is True
    assert r["basis"]["page"] == 187 and r["basis"]["places"] == "1-3"
    subj = next(c for c in r["conditions"] if c["code"] == "subjects")
    assert subj["value"] == 23 and subj["need"] == 23 and subj["ok"] is True
    judges = next(c for c in r["conditions"] if c["code"] == "judges")
    assert judges["ok"] is True


def test_kr2025_final_fifth_place_is_first_rank():
    r = check("kr2025_prod_final", 5)
    assert r["rank"] == "I" and r["fulfilled"]


def test_kr2025_algo_final_ninth_place_has_no_norm():
    assert check("kr2025_algo_final", 9)["status"] == "no_norm"


def test_chr2025_winner_ms_needs_second_result_and_kms():
    r = check("chr2025_prod", 1)
    assert r["rank"] == "МС"
    assert r["status"] == "needs_second_result"  # 10 субъектов из 89: п. 31
    assert "prior_rank" in r["pending"]          # п. 36 — нужен КМС
    assert not r["fulfilled"]
    j = next(c for c in r["conditions"] if c["code"] == "judges")
    assert j["ok"] is True  # 3 судьи ВК


def test_chr2025_third_place_kms_needs_second_result():
    r = check("chr2025_prod", 3)
    assert r["rank"] == "КМС" and r["status"] == "needs_second_result"


def test_kr2026_stage_counts_as_other_allrussian():
    r = check("kr2026_algo_stage", 1)
    assert r["rank"] == "КМС" and r["fulfilled"]  # п. 34.1, 24 субъекта
    assert r["basis"]["page"] == 188
    assert check("kr2026_algo_stage", 3)["rank"] == "I"
    assert check("kr2026_algo_stage", 5)["status"] == "no_norm"


def test_kr2026_prod_stage_18_subjects_needs_second_result():
    r = check("kr2026_prod_stage", 1)
    assert r["rank"] == "КМС" and r["status"] == "needs_second_result"


def test_kf2026_final_is_fizkult_event_second_rank():
    r = check("kf2026_sib_final", 1)
    assert r["rank"] == "II" and r["fulfilled"]  # 1К, 1К, 2К, 3К: 1 не ниже 1К и 2 не ниже 2К
    assert check("kf2026_sib_final", 5)["rank"] == "III"
    assert check("kf2026_sib_final", 7)["status"] == "no_norm"


def test_kf2026_qualifying_stage_has_no_norm():
    assert check("kf2026_sib_stage", 1)["status"] == "no_norm"


def test_fo_championship_without_half_of_district_subjects_is_not_met():
    r = check("fo2026_champ_pfo_prod", 1)
    assert r["rank"] == "I" and r["status"] == "conditions_not_met"
    subj = next(c for c in r["conditions"] if c["code"] == "subjects")
    assert subj["need"] == 7 and subj["value"] < 7


def test_participants_below_six_fail_p29():
    e = dict(ev("fo2026_perv_ufo_prod"))
    r = evsk.evsk_rank_for({"place": 1}, e, birth_date="2010-01-01")
    part = next(c for c in r["conditions"] if c["code"] == "participants")
    assert part["value"] < 6 and part["ok"] is False


def test_age_below_minimum_fails():
    r = check("kr2025_prod_final", 1, birth="2012-01-01")  # 13 лет на 18.05.2025, КМС с 15
    assert r["status"] == "conditions_not_met"


def test_unknown_birth_date_is_pending_not_fulfilled():
    r = check("kr2025_prod_final", 1, birth=None)
    assert r["status"] == "fulfilled" and "age" in r["pending"] and r["fulfilled"] is False


def test_judges_rule_kms_requires_vk():
    ok, _ = evsk._judges_ok("КМС", {"1К": 5})
    assert ok is False
    ok, _ = evsk._judges_ok("КМС", {"ВК": 2, "1К": 1})  # второй ВК засчитывается как «не ниже 1К»
    assert ok is True
    ok, _ = evsk._judges_ok("МС", {"ВК": 2, "1К": 3})
    assert ok is False


def test_kids_rows_only_for_algorithmic_and_robotics():
    e = {"evsk_status": "subject_perv", "age_group": "kids_u15", "discipline": "программирование продуктовое",
         "participants_total": 20, "subjects_total": None, "judges": {"2К": 2, "3К": 1}, "date_start": "2026-01-10"}
    assert evsk.evsk_rank_for({"place": 1}, e)["status"] == "no_norm"
    e["discipline"] = "программирование алгоритмическое"
    assert evsk.evsk_rank_for({"place": 1}, e, birth_date="2014-01-01")["rank"] == "III"


@pytest.mark.parametrize("event_id", ["kr2025_prod_final", "kr2026_sib_stage", "chr2025_prod", "kf2026_sib_final"])
def test_explain_mentions_official_basis(event_id):
    r = check(event_id, 1)
    assert "Приложение № 24" in r["explain"] and "орган власти" in r["explain"]


def test_page_map_excludes_certificates():
    # страницы справок о судьях и субъектах не дают записей спортсменов
    assert evsk.event_for_page("tb1vnqokiid4fiwdb40evznavplvmysg.pdf", 1) is None
    assert evsk.event_for_page("tb1vnqokiid4fiwdb40evznavplvmysg.pdf", 3) == "chr2025_prod"
    assert evsk.event_for_page("15a3exjee1npp1vux0sl5qborm4n6q3r.pdf", 72) == "kf2026_sib_final"
    assert evsk.event_for_page("15a3exjee1npp1vux0sl5qborm4n6q3r.pdf", 10) == "kf2026_sib_stage"


def test_best_result_prefers_fulfilled_higher_rank():
    recs = [{"place": 5, "event_id": "kr2025_prod_final", "date": "2025-05-18"},
            {"place": 2, "event_id": "kr2025_prod_final", "date": "2025-05-18"},
            {"place": 1, "event_id": "chr2025_prod", "date": "2025-11-20"}]
    best = evsk.best_evsk_for_athlete(recs, birth_date="2000-01-01")
    assert best["rank"] == "КМС" and best["status"] == "fulfilled"
