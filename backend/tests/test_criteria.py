"""Страница /criteria «Проверьте нас по критериям ТЗ» (К1): дословность ТЗ, один источник чисел, живые ссылки.

- подпункты — дословные куски раздела 6 ТЗ по порядку, между ними только разделители;
- каждое число страницы — то же поле JSON расчёта, что читает /validation, с подписью мира; нет расчёта — нет числа;
- каждая ссылка «что сделать» ведёт на существующий маршрут фронтенда, якорь есть в исходниках, персона — из режима жюри;
- docs/CRITERIA.md совпадает с выводом генератора (make criteria-doc).
"""
from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from app.modules.validation import criteria as C
from tests.conftest import register_and_verify

ROOT = Path(__file__).resolve().parents[2]
FRONT = ROOT / "frontend" / "src"
H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731

# Слова, которые в ТЗ стоят между подпунктами (вводная фраза критерия 6 и союз «и» в критерии 1)
GLUE = {"и", "Начисляется", "за", "реализацию", "необязательных", "для", "MVP", "возможностей:"}


def test_subpoints_are_verbatim_and_cover_criterion():
    assert [c["n"] for c in C.CRITERIA] == [1, 2, 3, 4, 5, 6]
    assert [c["weight"] for c in C.CRITERIA] == [35, 25, 10, 7, 6, 7] and C.PITCH["weight"] == 10
    assert C.build()["total_weight"] == 100
    for c in C.CRITERIA:
        rest, pos = c["tz"], 0
        for it in c["items"]:
            j = c["tz"].find(it["tz"], pos)
            assert j >= pos, f"{c['n']}: подпункт не дословен или не по порядку: {it['tz'][:60]}"
            pos = j + len(it["tz"])
            rest = rest.replace(it["tz"], " ", 1)
        left = set(re.sub(r"[;,.]", " ", rest).split())
        assert left <= GLUE, f"{c['n']}: часть текста ТЗ не попала в подпункты: {left - GLUE}"


def test_every_item_has_do_see_proof_limit_and_short_texts():
    for c in C.CRITERIA:
        for it in c["items"]:
            assert 1 <= len(it["do"]) <= 2, it["tz"]
            assert it["see"] and len(it["see"]) <= 170, it["see"]
            assert it["limit"] and len(it["limit"]) <= 100 and "\n" not in it["limit"], it["limit"]
            assert it["proof"]["kind"] in {"metric", "link", "doc", "sus"}
    assert len(C.UNIQUE) == 8 and all(len(u["text"]) <= 130 for u in C.UNIQUE)


def _routes() -> list[re.Pattern]:
    """Маршруты App.tsx (вложенные — с префиксом родителя) → регулярные выражения пути."""
    src = (FRONT / "App.tsx").read_text(encoding="utf-8")
    out, stack = [], []
    for line in src.splitlines():
        m = re.search(r'<Route\s+(?:path="([^"]*)"|index)', line)
        if m:
            p = m.group(1) or ""
            full = p if p.startswith("/") else "/".join([stack[-1] if stack else ""] + ([p] if p else []))
            out.append(re.compile("^" + re.sub(r":[a-z]+", "[^/]+", full.replace("*", ".*")) + "/?$"))
            if not line.rstrip().endswith("/>") and "</Route>" not in line:
                stack.append(full)
        elif "</Route>" in line and stack:
            stack.pop()
    return out


def _ids() -> set[str]:
    ids = set()
    for f in FRONT.rglob("*.tsx"):
        ids |= set(re.findall(r'\bid="([A-Za-z][\w-]*)"', f.read_text(encoding="utf-8")))
    return ids


def test_links_lead_to_existing_routes_and_anchors(client):
    routes, ids = _routes(), _ids()
    api = {getattr(r, "path", None) for r in client.app.routes}
    links = C.all_links()
    assert len(links) >= 40
    for g in links:
        to = g["to"]
        assert to.startswith("/") and not to.startswith("//"), to
        path, _, anchor = to.partition("#")
        path = path.split("?")[0]
        if path.startswith("/api/"):
            assert path in api, to
        else:
            assert any(r.match(path) for r in routes), f"нет маршрута фронтенда: {to}"
        if anchor:
            assert anchor in ids, f"нет якоря id=\"{anchor}\" в frontend/src: {to}"
        if g["as"]:
            assert g["as"] in C.PERSONAS, g
            assert not path.startswith("/validation") and not path.startswith("/api/"), g
        if g["need"]:
            assert g["as"] == "employer" and path == "/employer/needs", g
    # фрагмент названия демо-потребности — из демо-данных песочницы (иначе /jury/go откроет список потребностей)
    from app.modules.jury.seed import NEEDS
    for g in links:
        if g["need"]:
            assert any(g["need"] in n for n in NEEDS), g["need"]


def test_api_numbers_come_from_validation_json(client):
    r = client.get("/api/validation/criteria")
    assert r.status_code == 200
    d = r.json()
    assert len(d["criteria"]) == 6 and sum(len(c["items"]) for c in d["criteria"]) == 28 and len(d["unique"]) == 8
    ids = [it["id"] for c in d["criteria"] for it in c["items"]]
    assert len(ids) == len(set(ids)) and ids[0] == "c1-1"
    metrics = [it["proof"] for c in d["criteria"] for it in c["items"] if it["proof"]["kind"] == "metric"]
    assert len(metrics) >= 7
    for p in metrics:
        src = json.loads(C.SOURCES[p["src"]][0].read_text(encoding="utf-8"))
        assert p["value"] == C._get(src, p["path"]), p["path"]
        sig = p["signature"]
        assert sig["world"] and "commit" in sig, p["path"]
    p14 = d["criteria"][0]["items"][3]["proof"]
    bench = json.loads(C.SOURCES["bench"][0].read_text(encoding="utf-8"))
    assert p14["value"] == bench["metrics"]["platform"]["p@5"]["mean"]
    assert p14["ci"] == [bench["metrics"]["platform"]["p@5"]["lo"], bench["metrics"]["platform"]["p@5"]["hi"]]
    assert p14["signature"]["commit"] == bench["signature"]["commit"]
    # тот же расчёт, что у первого экрана /validation: κ повтора пути совпадает с карточкой «5 чисел»
    head = {i["id"]: i for i in client.get("/api/validation/headline").json()["items"]}
    p22 = d["criteria"][1]["items"][1]["proof"]
    assert p22["value"] == head["path_kappa"]["value"] and p22["signature"] == head["path_kappa"]["signature"]


def test_no_calculation_no_number(monkeypatch, tmp_path):
    monkeypatch.setitem(C.SOURCES, "bench", (tmp_path / "missing.json", "make bench"))
    C._cache.pop("bench", None)
    p = C.build()["criteria"][0]["items"][3]["proof"]
    assert p["kind"] == "link" and p["missing"] and "value" not in p and "make bench" in p["label"]
    C._cache.pop("bench", None)


def test_sus_proof_is_live_or_link(client):
    p = client.get("/api/validation/criteria").json()["criteria"][2]["items"][0]["proof"]
    assert p["kind"] == "link" and p["missing"]  # анкет нет — нет числа
    t = register_and_verify(client)
    client.post("/api/sus", json={"answers": [4, 2] * 5, "context": "e2e"}, headers=H(t))
    p = client.get("/api/validation/criteria").json()["criteria"][2]["items"][0]["proof"]
    assert p["kind"] == "metric" and p["value"] == 75.0 and p["signature"]["n"] == 1


def test_docs_match_generator():
    doc = ROOT / "docs" / "CRITERIA.md"
    assert doc.read_text(encoding="utf-8") == C.markdown(), \
        "docs/CRITERIA.md устарел: make criteria-doc (числа пересчитаны make bench / path-retest / validate)"
    text = doc.read_text(encoding="utf-8")
    for c in C.CRITERIA:
        assert f"## {c['n']}. {c['title']} — {c['weight']} %" in text
        for it in c["items"]:
            assert f"«{it['tz']}»" in text


@pytest.mark.parametrize("v,f,out", [(0.769, "pct1", "76,9\u00a0%"), (0.177, "signed3", "+0,177"),
                                     (-0.007, "signed3", "−0,007"), (0.841, "num3", "0,841"), (None, "num3", "—")])
def test_fmt_matches_ui(v, f, out):
    assert C.fmt(v, f) == out
