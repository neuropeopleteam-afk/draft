"""И9: допуск модели-оценщика при модельной панели и контрольный ответ с инструкцией, заблокированный фильтром."""
from __future__ import annotations

from app.modules.experts import analysis as A

RUB = {"criteria": [{"id": "c1", "weight": 0.5}, {"id": "c2", "weight": 0.5}]}
TRUE = [0, 1, 2, 3, 3, 2, 1, 0, 2, 3, 1, 2]  # «истинный» балл 0–3 ответов пакета B


def _pack(noise_gpt=True):
    items, labels = {}, []
    for i, t in enumerate(TRUE):
        s = t / 3
        # стабильная (разброс 0), на трёх ответах из 12 — на балл выше консенсуса (как YandexGPT на стенде: MAE 0,083)
        y = [{"status": "scored", "score": min(1.0, s + (1 / 3 if i in (0, 6, 10) else 0)), "latency_ms": 1700}] * 3
        g = [{"status": "scored", "score": min(1.0, s + (0.34 if (noise_gpt and i % 3 == 0 and r == 0) else 0)),
              "latency_ms": 3400} for r in range(3)]
        items[f"b{i}"] = {"kind": "B", "payload": {"rubric": RUB}, "hidden": {"llm": {"yandexgpt/latest": y,
                                                                                     "gpt-oss-120b/latest": g}}}
        for coder in ("E1", "E2", "E3"):  # одна модель в трёх ролях: метки совпадают, κ между «экспертами» = 1
            labels.append({"coder": coder, "key": f"b{i}",
                           "value": {"holistic": t, "criteria": {"c1": s, "c2": s}, "flag": "none"}})
    blocked = [{"status": "pending", "score": None, "error": "prompt_injection_suspected", "latency_ms": 0}] * 3
    items["inj"] = {"kind": "B", "payload": {"rubric": RUB},
                    "hidden": {"control": "injection", "llm": {"yandexgpt/latest": blocked, "gpt-oss-120b/latest": blocked}}}
    for coder in ("E1", "E2", "E3"):
        labels.append({"coder": coder, "key": "inj", "value": {"holistic": 0, "criteria": {"c1": 0, "c2": 0},
                                                                "flag": "injection"}})
    return items, labels


def test_injection_blocked_by_filter_counts_as_ok():
    """Раньше: прогоны контрольного ответа «на проверке» отбрасывались → injection_ok = null."""
    items, labels = _pack()
    res = A.analyze(items, labels)
    by = {m["model"]: m for m in res["llm"]["models"]}
    for m in by.values():
        assert m["injection_ok"] is True and m["injection_mode"] == "blocked"
    assert res["agreement"]["B_controls"] == {"injection": {"n": 3, "flagged": 3}}  # эксперты контрольную распознали


def test_degenerate_panel_uses_absolute_criterion_and_picks_product_model():
    items, labels = _pack()
    res = A.analyze(items, labels)
    llm = res["llm"]
    assert res["agreement"]["B"]["kappa_mean"] == 1.0
    assert llm["criterion"] == "absolute" and "не независимая" in llm["caveat"]
    by = {m["model"]: m for m in llm["models"]}
    y, g = by["yandexgpt/latest"], by["gpt-oss-120b/latest"]
    assert y["substitution_gap"] < -0.1  # по старому критерию модель была бы недопустима
    assert y["admissible"] and y["kappa_consensus"] >= A.ABS_KAPPA and y["mae_weighted"] <= A.ABS_MAE
    assert y["product"] and not g["product"]
    assert llm["choice"] == "yandexgpt/latest"


def test_model_panel_kind_caveat_and_thresholds():
    items, labels = _pack()
    llm = A.analyze(items, labels, panel_kind="model")["llm"]
    assert llm["criterion"] == "absolute" and llm["panel_kind"] == "model" and "Панель модельная" in llm["caveat"]
    assert llm["thresholds"]["kappa"] == 0.70 and llm["thresholds"]["mae"] == 0.15


def test_absolute_criterion_rejects_weak_model():
    items, labels = _pack()
    for it in items.values():  # модель ставит всем ответам одно и то же — κ низкая
        if not it["hidden"].get("control"):
            it["hidden"]["llm"]["yandexgpt/latest"] = [{"status": "scored", "score": 0.67, "latency_ms": 1000}] * 3
    llm = A.analyze(items, labels, panel_kind="model")["llm"]
    by = {m["model"]: m for m in llm["models"]}
    assert by["yandexgpt/latest"]["admissible"] is False
    assert llm["choice"] is None  # gpt-oss допустима, но в продукте только российская модель


def test_human_panel_keeps_gap_criterion():
    items, labels = _pack()
    # люди расходятся: E3 сдвинут на балл на части ответов → межэкспертная κ < 0,98
    for lb in labels:
        if lb["coder"] == "E3" and lb["key"] in ("b1", "b4", "b7"):
            lb["value"] = {**lb["value"], "holistic": min(3, lb["value"]["holistic"] + 1)}
    llm = A.analyze(items, labels)["llm"]
    assert llm["criterion"] == "gap" and llm["caveat"] is None


def test_panel_kind_auto_by_profiles_and_setting(client, monkeypatch):
    from app.core.config import get_settings
    from app.core.db import SessionLocal
    from app.modules.experts import section

    k = section.kind_from_profiles
    assert k(["Модель YandexGPT в роли тимлида", "LLM: QA"]) == "model"
    assert k(["Модель YandexGPT в роли тимлида", "тимлид Backend"]) == "human"
    assert k([]) == "human" and k([None]) == "human" and k(["тимлид, модельер данных"]) == "human"
    with SessionLocal() as db:
        assert section.panel_kind(db) == "human"
        monkeypatch.setattr(get_settings(), "expert_panel_kind", "model")
        assert section.panel_kind(db) == "model"
