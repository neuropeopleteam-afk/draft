"""Оператор платформы без реквизитов юрлица (решение владельца 21.10 22:28/22:40: «Драфт» — конкурсный прототип, юрлица
нет нигде). Оператор — «команда Neuropeople (конкурсный прототип)», контакт — форма обратной связи на сайте. Ни ИНН, ни ОГРН,
ни адреса, ни «ООО», ни почты на <сайт оператора> — ни в коде, ни в ответах API, ни в текстах согласий."""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.core import legal
from app.modules.proctor import service as proctor

FORBIDDEN = re.compile(r"Neuropeople|ООО|<реквизит>|<реквизит>|770101001|neuropeople\.shop|<адрес>|<реквизит>|ИНН|ОГРН",
                       re.I)
EXPECTED_FIELDS = {"full_name", "short_name", "email", "storage"}
ROOT = Path(__file__).resolve().parents[2]


def test_operator_is_team_stub():
    o = legal.OPERATOR
    assert set(o) == EXPECTED_FIELDS
    assert o["full_name"] == "команда Neuropeople (конкурсный прототип)"
    assert "форма обратной связи" in o["email"] and "@" not in o["email"]
    assert not FORBIDDEN.search(json.dumps(o, ensure_ascii=False))


def test_api_has_no_requisites(client):
    meta = client.get("/api/meta").json()["operator"]
    assert set(meta) == EXPECTED_FIELDS and not FORBIDDEN.search(json.dumps(meta, ensure_ascii=False))
    for kind in ("processing", "publication"):
        c = client.get(f"/api/legal/consents/{kind}").json()
        assert c["version"] == legal.CONSENT_VERSION
        assert "Оператор платформы — команда Neuropeople (конкурсный прототип)" in c["text"], kind
        assert not FORBIDDEN.search(json.dumps(c, ensure_ascii=False)), kind
    sup = client.get("/api/support").json()
    assert sup["support_email"] == "" and sup["legal_email"] == "" and "форма обратной связи" in sup["contact"]
    assert not FORBIDDEN.search(json.dumps(sup, ensure_ascii=False))


def test_proctoring_consent_operator_stub():
    cam = proctor.consent_text()["operator"]
    assert cam.startswith("Оператор платформы — команда Neuropeople (конкурсный прототип)") and not FORBIDDEN.search(cam)
    assert proctor.CONSENT_VERSION == legal.CONSENT_VERSION  # обе редакции пересмотрены 21.10 вместе


def test_backend_sources_and_legal_docs_have_no_requisites():
    """Код бэкенда, примеры API, OpenAPI и юридические документы — без реквизитов юрлица."""
    paths = [*ROOT.joinpath("backend/app").rglob("*.py"), ROOT / "backend/app/core/api_examples.json",
             ROOT / "docs/api/openapi.json", *ROOT.joinpath("docs/legal").glob("*.md")]
    rx = re.compile(r"Neuropeople|<реквизит>|<реквизит>|neuropeople\.shop|<адрес>|<реквизит>", re.I)
    bad = [str(p.relative_to(ROOT)) for p in paths if p.exists() and rx.search(p.read_text(encoding="utf-8"))]
    assert not bad, bad
