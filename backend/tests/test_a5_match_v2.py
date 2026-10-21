"""match-v2 (21.10, вечер): каскад фильтра стека, признаки «сильнее запроса» и «риск ниже запрошенного», веса — только
с миров разработки, дозапрос (короткие задания работодателя) не понижает подтвердившего навык.

Правило экспертов (20.10): категория и фильтр грейда — только по тесту; стек — фильтр; самооценка в балл не входит.
Проверяем на пакетах мира бенчмарка (bench_world.build_bundle: в пакете только наблюдаемое, истины нет).
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from app.modules.matching import ltr, ranking
from app.modules.matching.need_parser import parse_need
from app.modules.profiles.facts import merge_skill
from app.modules.validation import bench_world as bw

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _v2(monkeypatch):
    monkeypatch.setenv("MATCH_V2", "1")  # продукт включает match-v2, когда есть ltr_weights.json; тест — явно


@pytest.fixture(scope="module")
def world():
    w = bw.generate(bw.BenchConfig(seed=20261006, n_needs=6, n_candidates=400))
    bundles = [bw.build_bundle(c.obs, "platform") for c in w.candidates]
    for b in bundles:  # в мире бенчмарка города нет; условия потребности «Гибрид, Москва» — как у продукта
        b.profile.city, b.profile.relocation = "Москва", False
    return w, bundles


def _pool(bundles, req):
    cat = f"{req['direction']}.{req['grade']}"
    return [b for b in bundles if b.profile.current_category_id == cat]


def test_cascade_hides_nobody_and_full_stack_goes_first(world):
    w, bundles = world
    checked = 0
    for n in w.needs:
        req = parse_need(n.text, use_llm=False)
        pool = _pool(bundles, req)
        if not pool or not ltr.required_tags(req):
            continue
        scored, info = ranking.order_bundles(pool, req, {})
        # каскад никого не прячет: после условий потребности (формат) — все кандидаты пула в выдаче
        assert len(scored) == info["after_conditions"]
        sf = info["stack_filter"]
        assert sf["on"] and sf["cascade"] and sf["hidden"] == 0 and "steps" not in sf
        tags = ltr.required_tags(req)
        steps = [ltr.stack_step(ltr.stack_coverage(x[1], tags)) for x in scored if ranking.tier(x[1]) == 0]
        assert steps == sorted(steps), "сначала — все обязательные навыки, затем часть"
        assert ltr.threshold_text(sf).startswith("Сначала — кандидаты, у которых все обязательные навыки")
        checked += 1
    assert checked >= 3


def test_declared_stack_and_claimed_grade_never_change_score(world):
    w, bundles = world
    req = parse_need(w.needs[0].text, use_llm=False)
    for c in w.candidates[:60]:
        o = c.obs
        b0 = bw.build_bundle(o, "platform")
        extra = [t for t in bw.POPULARITY[o.direction_declared] if t not in o.stack_declared][:4]
        o2 = replace(o, stack_declared=tuple(o.stack_declared) + tuple(extra),
                     grade_declared="senior" if o.grade_declared != "senior" else "junior")
        b1 = bw.build_bundle(o2, "platform")
        s0, c0, _ = ranking.score_candidate(b0, req)
        s1, c1, _ = ranking.score_candidate(b1, req)
        assert s0 == s1 and c0.get("contrib") == c1.get("contrib")


def test_band_and_level_features():
    assert ltr.in_band_of(1.6, 1.0) < 0.3 and ltr.in_band_of(0.2, 1.0) > 0.75 and ltr.in_band_of(None, 1.0) == 0.0
    assert ltr.in_band_of(1.2, None) == 1.0  # у Senior следующего грейда нет — «сильнее запроса» не бывает
    assert ltr.level_ok_of(-0.3, 0.4, 0.0) < 0.3 and ltr.level_ok_of(0.6, 0.4, 0.0) > 0.9
    assert abs(ltr.level_ok_of(0.0, 0.4, 0.0) - 0.5) < 1e-6 and ltr.level_ok_of(None, 0.4, 0.0) == 0.0
    assert "in_band" in ltr.FREE and "level_ok" in ltr.POSITIVE and set(ltr.NEGATIVE) == {"failed", "provisional"}


def test_weights_file_trained_on_dev_only_with_sign_constraints():
    f = ltr.WEIGHTS_FILE
    if not f.exists():
        pytest.skip("ltr_weights.json ещё нет — продукт на запасных весах")
    d = json.loads(f.read_text(encoding="utf-8"))
    w, meta = d["weights"], d["meta"]
    assert all(w.get(k, 0) >= 0 for k in ltr.POSITIVE) and all(w.get(k, 0) <= 0 for k in ltr.NEGATIVE)
    assert abs(sum(v for k, v in w.items() if v > 0 and k not in ltr.NEGATIVE) - 1.0) < 1e-3
    dev = {int(s) for ss in meta["dev_seeds"].values() for s in ss}
    hold = {int(s) for s in meta["holdout_seeds_not_used"]}
    assert dev and not (dev & hold)
    fr = ROOT / "docs/realdata/bench_holdout2_FREEZE.json"
    if fr.exists():
        frozen = {int(s) for ss in json.loads(fr.read_text(encoding="utf-8"))["worlds"].values() for s in ss}
        assert not (dev & frozen), "веса не видели отложенных миров"


def test_successful_short_tasks_never_lower_place(world):
    """Дозапрос: кандидат решил задания по обязательным навыкам — балл не ниже (вес «задания» и навыков ≥ 0)."""
    w, bundles = world
    req = parse_need(w.needs[1].text, use_llm=False)
    tags = ltr.required_tags(req)
    pool = _pool(bundles, req)
    assert pool and tags
    for b in pool[:15]:
        s0, _, _ = ranking.score_candidate(b, req)
        saved = (b.skills_t1, b.probes_t1)
        try:
            sk = dict(b.skills_t1)
            for t in tags:
                f = bw._fact(b.profile.user_id, "skill", t, {"correct": 3, "total": 3, "score": 1.0, "origin": "assignment"},
                             bw.EvidenceLevel.T1, bw.FactSource.probe, False)
                sk[t] = merge_skill(sk.get(t), f)
            b.skills_t1 = sk
            b.probes_t1 = list(b.probes_t1) + [bw._fact(b.profile.user_id, "probe", "probe.t", {"score": 1.0, "origin": "assignment"},
                                                        bw.EvidenceLevel.T1, bw.FactSource.probe, False)]
            s1, c1, _ = ranking.score_candidate(b, req)
        finally:
            b.skills_t1, b.probes_t1 = saved
        assert s1 >= s0 - 1e-9
