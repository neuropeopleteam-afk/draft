"""Лимит памяти api в docker-compose.yml (Ф1, п. 5): 1536m — на сервере 7,9 ГБ; 768m на стенде уже занято на 77 %."""
from pathlib import Path
import re

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def test_api_memory_limit_1536m_with_reason():
    text = COMPOSE.read_text(encoding="utf-8")
    m = re.search(r"^  api:\n(?P<body>(?:    .*\n|\n)+)", text, re.M)
    assert m, "нет сервиса api"
    # 10.10: лимит переопределяется API_MEM_LIMIT в .env (больше воркеров — docs/LOAD.md, раздел 8), по умолчанию 1536m
    assert re.search(r"^    mem_limit: (?:1536m|\$\{API_MEM_LIMIT:-1536m\})$", m["body"], re.M)
    # причина записана рядом с лимитом и в шапке файла
    assert "было 768m" in m["body"] and "1536M" in text.split("name:")[0]
