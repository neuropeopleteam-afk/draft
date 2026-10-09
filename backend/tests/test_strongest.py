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
