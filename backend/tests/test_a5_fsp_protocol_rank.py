"""Протоколы ФСП в подборе (fsp-v3): подтверждено ФСП > найдено в протоколе (ждёт ФСП) > заявлено (0);
судьи — не достижение; нет ФСП — штраф 0; объяснение цитирует протокол; фильтр fsp_protocol_only."""
from datetime import date
from types import SimpleNamespace

from app.modules.matching import fsp_factor as ff
from app.modules.matching import ranking
from app.modules.profiles.facts import Bundle

TODAY = date(2026, 10, 21)


def ach(**kw):
    base = dict(event_name="Кубок России по спортивному программированию", event_date=date(2025, 11, 20),
                discipline="product", place=2, team_size=None, role_in_team=None, verified=False,
                result_title=None, sport_rank=None, source_ref="profile", event_id=None, team_result=None,
                level=None, evsk_rank=None)
    base.update(kw)
    return SimpleNamespace(**base)


PROTO = dict(source_ref="protocol:kr_2025_product:17", event_id="2008650020027577",
             team_result={"ekp_no": "2008650020027577", "page": 3, "pdf_url": "https://fsp-russia.ru/x.pdf"})


def test_status_order_and_weights():
    v = ach(**PROTO, protocol_status="verified")
    p = ach(**PROTO, protocol_status="pending_fsp")
    legacy = ach(**PROTO, verified=True)          # самоподтверждение до миграции А2 — это «ждёт ФСП»
    reg = ach(verified=True, source_ref="registry:demo")
    dec = ach()
    assert [ff.status(x) for x in (v, p, legacy, reg, dec)] == ["verified", "pending_fsp", "pending_fsp",
                                                               "verified", "declared"]
    sv = ff.details([v], today=TODAY, relevance=False)["strength"]
    sp = ff.details([p], today=TODAY, relevance=False)["strength"]
    sd = ff.details([dec], today=TODAY, relevance=False)["strength"]
    assert sv > sp > sd == 0.0 and abs(sp - sv / 2) < 1e-3


def test_judges_and_protocol_rows_without_event_are_not_achievements():
    for j in ("ВК", "1К", "3 К", "спортивный судья"):
        assert ff.status(ach(**PROTO, protocol_status="verified", sport_rank=j)) == "excluded"
    no_event = ach(source_ref="protocol:kr_2025_sk_otbor:4", protocol_status="pending_fsp")
    assert ff.status(no_event) == "excluded"
    assert ff.details([no_event], today=TODAY, relevance=False)["strength"] == 0.0


def test_same_as_fsp_v2_for_verified_registry():
    from app.modules.fsp.rating import details as v2

    a = [ach(verified=True, source_ref="registry:demo", place=1),
         ach(verified=True, source_ref="registry:demo", event_name="Хакатон ФСП", place=5)]
    assert ff.details(a, today=TODAY, relevance=False)["strength"] == v2(a, today=TODAY)["strength"]


def test_citation_and_reason():
    a = ach(**PROTO, protocol_status="pending_fsp", evsk_rank="КМС")
    c = ff.protocol_citation(a)
    assert "Кубок России" in c and "2 место" in c and "ЕКП № 2008650020027577" in c and "стр. 3" in c and "КМС" in c
    p = SimpleNamespace(current_direction_id="backend", current_grade_id="middle", current_category_id="backend.middle",
                        grade_provisional=False, work_format=None, privacy={}, rating_score=None, public_ref="K-1",
                        city=None, relocation=False, salary_min=None)
    b = Bundle(profile=p)
    b.achievements = [a]
    _, comp, reasons = ranking.score_candidate(b, {"direction": "backend", "grade": "middle", "stack_required": []})
    r = next(x for x in reasons if x["requirement"] == "Достижения ФСП")
    assert r["fsp_status"] == "pending_fsp" and r["protocol"]["url"].endswith(".pdf")
    assert "ждёт подтверждения ФСП" in r["text"] and comp["fsp"] > 0


def test_no_fsp_penalty_zero_and_filter():
    p = SimpleNamespace(current_direction_id="backend", current_grade_id="middle", current_category_id="backend.middle",
                        grade_provisional=False, work_format=None, privacy={}, rating_score=None, public_ref="K-2",
                        city=None, relocation=False, salary_min=None)
    b0 = Bundle(profile=p)
    s0, c0, _ = ranking.score_candidate(b0, {"direction": "backend", "grade": "middle", "stack_required": []})
    assert c0["fsp"] == 0
    b1 = Bundle(profile=p)
    b1.achievements = [ach()]  # заявлено без документа — тоже 0, как без ФСП
    s1, c1, _ = ranking.score_candidate(b1, {"direction": "backend", "grade": "middle", "stack_required": []})
    assert s1 == s0 and c1["fsp"] == 0
    assert not ff.has_protocol(b1.achievements)
    assert ff.has_protocol([ach(**PROTO, protocol_status="pending_fsp")])
    assert not ff.has_protocol([ach(**PROTO, protocol_status="pending_fsp", sport_rank="ВК")])
