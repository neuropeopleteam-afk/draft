"""Блок «Какая модель где» (/validation#experts): API отдаёт сводку прогонов, файл совпадает с docs/llm/*.json."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_api_llm_models(client):
    r = client.get("/api/validation/llm-models")
    assert r.status_code == 200
    d = r.json()
    assert not d.get("missing") and d["how"] == "make llm-local"
    models = [x["model"] for x in d["rows"]]
    # на экран — роли, без названий моделей и поставщиков (решение штаба 21.10; имена — в data/llm_models.json и docs/)
    assert models[0] == "Правила и словари" and any(m.startswith("открытая модель") for m in models)
    assert "модель стенда" in models and "российская модель" in models
    for x in d["rows"]:
        n = x["needs"]
        assert 0 < n["p"] <= 1 and 0 < n["r"] <= 1 and n["date"]
        assert x["grader"] or x.get("grader_none")
    qwen = next(x for x in d["rows"] if x["model"].startswith("открытая модель"))
    assert "облако" in qwen["needs"]["note"]  # время облачного прогона не выдаётся за время на CPU
    assert d["cpu"]["median_s"] > 10 and d["cpu"]["ram_gib"] > 5
    assert "не эксперты" in d["caveat"] and "модель" in d["caveat"]


def test_llm_models_file_is_fresh():
    r = subprocess.run([sys.executable, str(ROOT / "tools/llm/llm_models_table.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
