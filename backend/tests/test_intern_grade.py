"""Грейд «Стажёр» (intern): справочник, решение по грейду на полной шкале, состав теста, разбор потребности."""
import pytest

from app.modules.assessment import engine as stub
from app.modules.assessment.grades import decide_grade, point_grade, probabilities
from app.modules.assessment.intern_pool import OPEN_FORMATS, intern_exclusions, intern_family_ids
from app.modules.assessment.rules import apply_result, check_can_start
from app.modules.catalog.seed_data import (GRADE_CUTS, GRADE_LEVEL, GRADE_ORDER, GRADES, category_title,
                                           grade_above, grade_below, grade_by_experience)
from app.modules.matching.need_parser import parse_rules
from datetime import datetime, timezone


def test_grade_order_and_cuts_consistent():
    assert GRADE_ORDER == ("intern", "junior", "middle", "senior")
    assert [GRADE_LEVEL[g] for g in GRADE_ORDER] == [0, 1, 2, 3]
    cuts = [GRADE_CUTS[g] for g in GRADE_ORDER]
    assert cuts == sorted(cuts) and cuts[0] == -1.75 and cuts[1] == -1.0
    assert GRADES["intern"] == "Стажёр" and category_title("qa.intern") == "QA · Стажёр"
    assert grade_above("intern") == "junior" and grade_below("intern") is None and grade_above("senior") is None


def test_grade_by_experience():
    assert grade_by_experience(0) == "intern" and grade_by_experience(0.4) == "intern"
    assert grade_by_experience(0.5) == "junior" and grade_by_experience(1.4) == "junior"
    assert grade_by_experience(2) == "middle" and grade_by_experience(5) == "senior"
    assert grade_by_experience(None) is None


def test_point_grade_and_probabilities_full_scale():
    assert point_grade(-2.5) == "none" and point_grade(-1.5) == "intern" and point_grade(-0.5) == "junior"
    p = probabilities(-1.4, 0.3)
    assert set(p) == {"none", "intern", "junior", "middle", "senior"}
    assert abs(sum(p.values()) - 1) < 1e-3 and p["intern"] > 0.7 and p["intern"] == max(p.values())


def test_decide_intern_same_rule_as_others():
    ok = decide_grade(-1.4, 0.3, "intern")
    assert ok.confirmed and ok.assigned == "intern" and not ok.upgrade_available
    up = decide_grade(-0.4, 0.3, "intern")  # уверенно выше порога Junior → можно идти на Junior
    assert up.confirmed and up.upgrade_available
    no = decide_grade(-2.3, 0.3, "intern")
    assert not no.confirmed and no.assigned == "none" and no.retake_lower is None  # ниже Стажёра грейда нет
    assert "не подтверждён" in no.explanation
    with pytest.raises(ValueError):
        decide_grade(0, 0.3, "lead")


def test_decide_junior_suggests_intern_as_lower():
    d = decide_grade(-1.4, 0.3, "junior")
    assert not d.confirmed and d.retake_lower == "intern" and d.point_grade == "intern"
    assert "intern" in d.explanation and d.probabilities["intern"] > 0.7
    # решения для прежних грейдов не меняются
    m = decide_grade(0.6, 0.3, "middle")
    assert m.confirmed and m.assigned == "middle"
    s = decide_grade(0.5, 0.3, "senior")
    assert not s.confirmed and s.retake_lower == "middle"


def test_stub_grade_decision_full_scale():
    d = stub.grade_decision(-1.4, 0.3, "intern")
    assert d["confirmed"] and d["point_grade"] == "intern"
    assert set(d["probabilities"]) == {"none", "intern", "junior", "middle", "senior"}
    assert abs(sum(d["probabilities"].values()) - 1) < 1e-2
    j = stub.grade_decision(-1.4, 0.3, "junior")
    assert not j["confirmed"] and j["retake_lower"] == "intern"
    assert "Стажёр" in stub._explain(j, -1.4, 0.3, "junior")


def test_rules_accept_intern():
    now = datetime.now(timezone.utc)
    assert check_can_start(None, None, "intern", now, False).allowed
    out = apply_result(None, "intern", True, now, False)
    assert out.changed and out.new_grade == "intern" and out.reason == "initial" and "Стажёр" in out.message
    up = apply_result("intern", "junior", True, now, True)
    assert up.changed and up.reason == "sandbox" and "Стажёр → Junior" in up.message
    down = apply_result("junior", "intern", True, now, False)
    assert down.reason == "retest_down"
    keep = apply_result("intern", "junior", False, now, False)
    assert not keep.changed and keep.new_grade == "intern"


def test_intern_pool_is_easy_closed_junior_families():
    from app.modules.assessment.bank_engine import _pool

    pool = _pool(2)
    for d in ("backend", "frontend", "data_ml", "qa", "security"):
        keep = intern_family_ids(pool, d)
        excl = set(intern_exclusions(pool, d))
        items = {i.family_id: i for i in pool}
        assert len(keep) >= 8, d
        assert keep.isdisjoint(excl)
        for fid in keep:
            it = items[fid]
            assert not it.canary and it.block in ("common", d)
            assert it.format not in OPEN_FORMATS
            assert "junior" in it.grades or "intern" in it.grades
        # всё остальное направления (кроме канареек) исключено, чужие направления не трогаем
        for i in pool:
            if i.canary or i.block not in ("common", d):
                assert i.family_id not in excl
            elif i.family_id not in keep:
                assert i.family_id in excl
        # семейства для Middle/Senior в тест Стажёра не попадают
        assert all("senior" not in items[f].grades for f in keep)


def test_bank_engine_intern_session_uses_only_intern_pool():
    from app.modules.assessment.bank_engine import BankEngine, _pool

    eng = BankEngine()
    st = eng.start(direction="qa", claimed_grade="intern", stack_tags=[], seed=4242)
    assert st["subpool"] is None  # без ротации субпулов
    keep = intern_family_ids(_pool(st["cfg"]["subpools"]), "qa")
    sess = eng._rebuild(st)
    assert sess.theta == pytest.approx(-1.25)  # стартовая θ Стажёра
    assert all(i.family_id in keep for i in sess.scored_pool)
    assert all(i.family_id in keep for i in sess.ext_pool)
    assert sess.cfg.cuts[0] == -1.75
    # ответы «всё верно» → тест заканчивается подтверждением Стажёра с предложением идти на Junior
    for _ in range(40):
        it = eng.next_item(st)
        if it is None:
            break
        if it.answer_kind == "option":
            ans = it.options[0]["id"]
        elif it.answer_kind == "line":
            ans = 1
        else:
            ans = "x"
        eng.answer(st, it.item_id, ans, step=it.step)
    res = eng.finish(st)
    assert res.claimed_grade == "intern"
    assert set(res.probabilities) == {"none", "intern", "junior", "middle", "senior"}
    assert "Стажёр" in res.explanation
    assert all(i["family_id"] in keep or i["canary"] for i in st["items"])


def test_need_parser_intern_keywords():
    for text in ("Ищем стажёра в backend-команду: Python, SQL. Без опыта, обучим.",
                 "Intern frontend developer: React, TypeScript, студент последних курсов",
                 "Стажировка QA без опыта: ручное тестирование, тест-дизайн"):
        r = parse_rules(text)
        assert r["grade"] == "intern", text
    assert parse_rules("Junior Python-разработчик, опыт от 1 года: Django, PostgreSQL")["grade"] == "junior"
    assert parse_rules("Наставник стажёров, senior backend: Go, Kafka")["grade"] == "senior"


def test_intern_cut_simulation_quick_and_report_block(client):
    from app.modules.validation import intern_cut

    res = intern_cut.run(quick=True, synthetic=True)
    assert res["chosen"]["cut"] in res["candidate_cuts"]
    assert res["chosen"]["basis"] == "with_easy_families"
    for s in res["by_cut"]:
        assert 0 <= (s["false_confirm"] or 0) <= 1 and 0 <= (s["false_reject"] or 0) <= 1
        assert s["n_sessions"] == len(res["theta_grid"]) * res["n_per_theta"] * len(res["directions"])
        assert set(s["stop_reasons"]) and len(s["by_theta"]) == len(res["theta_grid"])
    assert res["with_easy_families"]["pool"]["backend"][str(res["chosen"]["cut"])]["n_families"] > \
        res["pool"]["backend"][str(res["chosen"]["cut"])]["n_families"]
    assert res["families_used"] and all(not f.startswith("synthetic.") for f in res["families_used"])
    # сохранённые данные отдаются в отчёте валидации, выбранный порог совпадает с порогом платформы
    rep = client.get("/api/validation/report").json()
    blk = rep["intern_cut"]
    assert not blk.get("missing")
    assert blk["cut_in_use"] == GRADE_CUTS["intern"] == blk["chosen"]["cut"]
    assert blk["pool_now"]["qa"]["n_common"] + blk["pool_now"]["qa"]["n_direction"] >= 8
    assert all(k in blk for k in ("by_cut", "with_easy_families", "retest", "rule"))
