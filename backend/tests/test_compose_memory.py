"""Лимит памяти api в docker-compose.yml: 3072m с 10.10 (пик 1471 МиБ из 1536 при 100 пользователях); до того 1536m (08.10), 768m."""
from pathlib import Path
import re

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def test_api_memory_limit_3072m_with_reason():
    text = COMPOSE.read_text(encoding="utf-8")
    m = re.search(r"^  api:\n(?P<body>(?:    .*\n|\n)+)", text, re.M)
    assert m, "нет сервиса api"
    # 10.10: лимит переопределяется API_MEM_LIMIT в .env (больше воркеров — docs/LOAD.md, раздел 8), по умолчанию 3072m
    assert re.search(r"^    mem_limit: (?:3072m|\$\{API_MEM_LIMIT:-3072m\})$", m["body"], re.M)
    # причина записана рядом с лимитом и в шапке файла
    assert "было 768m" in m["body"] and "3072M" in text.split("name:")[0]
