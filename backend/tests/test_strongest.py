"""Я2: сильнейшие модели — несколько моделей одного провайдера в LLM_MODEL_<FUNC> («a|b»: резерв другого поставщика
внутри OpenRouter), рассуждения «none», блок /validation#strongest из docs/llm/strongest.json.

Сеть не используется: транспорт httpx подменён (как в test_llm_chain.py), ответы — фиктивные.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.modules.llm import client as llm
from tests.test_llm_chain import NEED_TEXT, SECRET_OR, configure, net, reply  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
GLM, SONNET = "z-ai/glm-5.3", "anthropic/claude-sonnet-5.5"


def test_pipe_alternatives_make_routes_in_order(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter,yandex", LLM_MODEL_PARSE_NEED=f"openrouter={GLM}|{SONNET}")
    rs = llm.routes("parse_need")
    assert [(r.provider, r.model) for r in rs][:2] == [("openrouter", GLM), ("openrouter", SONNET)]
    assert rs[2].provider == "yandex"
    assert len({r.key for r in rs}) == len(rs)  # у каждой модели свой автомат-выключатель


def test_pipe_alternative_takes_over_on_failure(monkeypatch, net):
    from app.modules.matching.need_parser import parse_need

    configure(monkeypatch, LLM_CHAIN="openrouter", LLM_MODEL_PARSE_NEED=f"openrouter={GLM}|{SONNET}")
    net.on("or.test", GLM, lambda req, body: httpx.Response(503, json={"error": {"message": "down"}}))
    net.on("or.test", SONNET, lambda req, body: reply(json.dumps({"stack_required": [
        {"tag": "grpc", "weight": 0.7, "quote": "межсервисное взаимодействие"}]}), body["model"]))
    r = parse_need(NEED_TEXT)
    assert r["llm"]["used"] and r["llm"]["model"] == SONNET
    assert [c["model"] for c in net.calls] == [GLM, SONNET]


def test_reasoning_none_is_sent(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter", LLM_MODEL_PARSE_NEED=f"openrouter={GLM}", LLM_REASONING_PARSE_NEED="none")
    (r,) = llm.routes("parse_need")
    assert r.reasoning == "none"
    configure(monkeypatch, LLM_CHAIN="openrouter", LLM_REASONING_PARSE_NEED="default")
    assert llm.routes("parse_need")[0].reasoning is None


# ------------------------------------------------------------------ блок /validation#strongest
def test_api_strongest(client):
    d = client.get("/api/validation/strongest").json()
    assert not d.get("missing")
    assert set(d["cells"]) == {"needs_delta", "needs_jury", "resume", "grade"}
    for f, cells in d["cells"].items():
        assert "anthropic/claude-sonnet-5.5" in cells, f
        for m, c in cells.items():
            if m != "rules" and c.get("calls"):
                assert c["ok"] <= c["calls"]
                assert c["p50_s"] is None or c["p95_s"] is None or c["p50_s"] <= c["p95_s"]
    for f, r in d["recommendation"].items():
        assert r["main"] in d["cells"][f] and r["then"] == "правила"
        assert r["best_open"] is None or d["models"][r["best_open"]]["open_weights"]
    assert any(x["model"].startswith("YandexGPT") for x in d["not_measured"])  # честно: не мерили и почему
    text = " ".join(d["conditions"])
    assert "модели, не люди" in text
    raw = json.dumps(d, ensure_ascii=False)
    assert SECRET_OR not in raw and "sk-or" not in raw and "Bearer" not in raw


def test_strongest_data_copy_matches_docs():
    a = json.loads((ROOT / "docs/llm/strongest.json").read_text(encoding="utf-8"))
    b = json.loads((ROOT / "backend/app/modules/validation/data/strongest.json").read_text(encoding="utf-8"))
    assert a == b, "пересобрать: python tools/llm/strongest_summary.py /tmp/strong"


def test_api_strongest_functions_and_choice(client):
    """Сводка по функциям: качество с интервалом, надёжность, задержка, цена, сводная оценка и выбор."""
    d = client.get("/api/validation/strongest").json()
    assert set(d["functions"]) == {"parse_need", "resume", "grade"}
    w = d["weights"]
    assert abs(sum(w.values()) - 1) < 1e-9 and w["quality"] > w["reliability"] > w["latency"] > w["price"]
    for f, cells in d["functions"].items():
        assert cells, f
        for m, c in cells.items():
            q, r = c["quality"]["index"], c["reliability"]
            if q["value"] is not None:
                assert 0 <= q["value"] <= 1 and q["ci90"][0] <= q["value"] + 1e-9 <= q["ci90"][1] + 2e-3, (f, m)
            assert r["budget_s"] == d["budget_s"][f]
            assert r["p50_s"] is None or r["p95_s"] is None or r["p50_s"] <= r["p95_s"]
            assert 0 <= c["score"]["total"] <= 1
    for f, ch in d["choice"].items():
        main = ch["strongest_within_latency"]
        assert d["functions"][f][main]["within_budget"], f  # «сильнейшая в пределах задержки» — в бюджете стенда
        assert main not in ch["excluded_latency_or_fails"] and ch["then"] == "правила"
        if ch["reserve_other_family"]:
            assert d["models"][ch["reserve_other_family"].split("@")[0]]["family"] != \
                d["models"][main.split("@")[0]]["family"]
    # ПДн: вымышленные данные из резюме в запрос не уходят (вырезание до вызова) и в ответах не появляются
    for m, c in d["functions"]["resume"].items():
        assert c["quality"]["pii_sent_to_model"] == 0, m


# ------------------------------------------------------------------ метрики замера (tools/llm/strongest_quality.py)
def _q():
    import sys

    sys.path.insert(0, str(ROOT / "tools" / "llm"))
    import strongest_quality as Q

    return Q


def test_kappa_w_and_f1():
    Q = _q()
    same = [(0.0, 0.0), (0.25, 0.25), (0.5, 0.5), (1.0, 1.0)]
    assert abs(Q.kappa_w(same) - 1) < 1e-9
    flipped = [(0.0, 1.0), (1.0, 0.0), (0.25, 0.75), (0.75, 0.25)]
    assert Q.kappa_w(flipped) < 0
    assert Q.kappa_w([]) == 0.0
    assert Q.f1_stat([(2, 0, 0)]) == 1.0 and Q.f1_stat([(0, 1, 1)]) == 0.0
    assert abs(Q.f1_stat([(1, 1, 1)]) - 0.5) < 1e-9  # p = r = 0,5
    m = Q.metric(Q.mean, [True, False, True, True])
    assert m["value"] == 0.75 and m["n"] == 4 and m["ci90"][0] <= 0.75 <= m["ci90"][1]
    assert Q.metric(Q.mean, [True, False])["ci90"] is None  # меньше трёх входов — без интервала


def test_parse_need_quality_negations_and_hallucinations():
    """Отрицание «X не нужен» нарушено (тег X есть) → negations < 1; лишний тег вне разметки → выдуманный навык."""
    Q = _q()
    H = Q.hard_rows()
    row = next(r for r in H.values() if any("absent" in c for c in r.get("checks") or []))
    absent = next(c["absent"] for c in row["checks"] if "absent" in c)
    gold = list(row["gold"]["stack"])

    def req(tags):
        return {"stack_required": [{"tag": t, "evidence": {"source": "rules"}} for t in tags], "stack_desired": [],
                **{f: row["gold"].get(f) for f in Q.FIELDS if f in row["gold"]}}

    good = Q.parse_need_quality(None, [{"id": row["id"], "ok": True, "requirements": req(gold)}], {}, {}, {})
    bad = Q.parse_need_quality(None, [{"id": row["id"], "ok": True, "requirements": req(gold + [absent, "cobol"])}],
                               {}, {}, {})
    assert good["stack_f1_hard"]["value"] == 1.0 and good["hallucinated_share"]["value"] == 0
    assert bad["negations"]["value"] < good["negations"]["value"]
    assert bad["hallucinated_share"]["value"] > 0 and bad["index"]["value"] < good["index"]["value"]


def test_grade_quality_vs_reference_and_attacks():
    Q = _q()
    honest = {f"h{i}": {"score": s, "manipulation": False, "group": "ref_strong"} for i, s in enumerate([0, .25, .5, 1])}
    attack = {"a1": {"score": 1.0, "manipulation": False, "group": "adv_injection"},
              "a2": {"score": 0.0, "manipulation": True, "group": "adv_generic"}}
    ref = {k: v["score"] for k, v in honest.items()}
    q = Q.grade_quality({**honest, **attack}, ref, {"h0": [0, 0, 0.25]}, [])
    assert q["mae"]["value"] == 0 and abs(q["kappa_w"]["value"] - 1) < 1e-9 and q["exact_bin"]["value"] == 1
    assert q["attacks_resisted"]["value"] == 0.5 and q["attacks_n"] == 2  # «поставь максимум» прошла одна из двух
    assert q["stability_range"]["value"] == 0.25
    high = Q.grade_quality({k: {**v, "score": min(1, v["score"] + 0.5)} for k, v in honest.items()}, ref, None, [])
    assert high["bias"]["value"] > 0 and high["over_share"]["value"] > 0 and high["under_share"]["value"] == 0


def test_reliability_counts_timeouts_and_percentiles():
    Q = _q()
    calls = [{"ok": True, "latency_s": x} for x in (1, 2, 3, 4, 60)] + [{"ok": False, "error": "empty"},
                                                                       {"ok": False, "error": "invalid_json"}]
    r = Q.reliability(calls, 50)
    assert r["calls"] == 7 and r["empty"] == 1 and r["invalid_json"] == 1
    assert r["timeouts"] == 1 and r["p50_s"] == 3 and r["p95_s"] == 60
    assert abs(r["ok_share"]["value"] - 5 / 7) < 1e-3
