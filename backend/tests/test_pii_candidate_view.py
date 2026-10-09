"""П1 п. 5 (дыра 7): сырой текст потребности (`employer_needs.raw_text`, в нём бывают контакты рекрутёра и адрес офиса)
не уходит кандидату — ни в приглашение, ни в «почему выбрали», ни в уведомления; кандидату видны только название
потребности и требования. Данные синтетические.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from tests.test_day2_rules import H, INVITE, candidate_with_category, employer, my_ref

NEED = ("Нужен middle Python-разработчик в платёжный сервис: FastAPI, PostgreSQL, интеграции с банками. "
        "Удалённо, зарплата 240 000 – 300 000 ₽. Офис: Москва, ул. Секретная, д. 13, оф. 666. "
        "Рекрутер — Ольга Сидорова-Тестовая, +7 999 765-43-21, olga.secret@acme-corp.ru, t.me/olga_secret_hr. "
        "Пишите Ольге в tg. Внутренний код вакансии ZX-SECRET-42.")
SECRETS = ("Ольга", "Ольге", "Сидорова", "765-43-21", "olga.secret", "acme-corp", "olga_secret_hr", "Секретная", "оф. 666",
           "ZX-SECRET-42", "интеграции с банками")


def test_candidate_never_sees_raw_need_text(client):
    t1 = candidate_with_category(client, "pii-c1@example.com")
    te = employer(client)
    r = client.post("/api/employer/needs", json={"text": NEED}, headers=H(te))
    assert r.status_code == 201, r.text
    nid = r.json()["id"]
    inv = client.post("/api/employer/invitations", headers=H(te),
                      json={**INVITE, "candidate_ref": my_ref(client, t1), "need_id": nid})
    assert inv.status_code == 201, inv.text
    iid = inv.json()["id"]
    seen = []
    for url in ("/api/candidate/invitations", f"/api/candidate/invitations/{iid}", f"/api/candidate/invitations/{iid}/why",
                "/api/notifications", "/api/candidate/assignments", "/api/me/profile"):
        resp = client.get(url, headers=H(t1))
        if resp.status_code == 404 and url == "/api/me/profile":
            continue
        assert resp.status_code == 200, (url, resp.status_code, resp.text[:300])
        seen.append((url, json.dumps(resp.json(), ensure_ascii=False)))
    for url, body in seen:
        for s in SECRETS:
            assert s not in body, (url, s)
    why = json.loads(dict(seen)[f"/api/candidate/invitations/{iid}/why"])
    assert why["need"]["title"] and "raw_text" not in why["need"]  # кандидату — только название и требования


# Где в коде читается raw_text: только сторона работодателя (своя компания), сиды и разбор — не ответы кандидату.
# Новый модуль, читающий raw_text, должен попасть в этот список осознанно (и не отдавать текст кандидату).
RAW_TEXT_ALLOWED = {
    "app/modules/matching/models.py", "app/modules/matching/router.py", "app/modules/matching/compare.py",
    "app/modules/mutual/service.py",  # только detect_tasks (тип задач + слово-цитата) и индикатор условий
    "app/modules/demo/seed.py", "app/modules/jury/seed.py", "app/jury_live/service.py",
    "app/modules/validation/attacks.py",
}


def test_raw_text_readers_are_known():
    root = Path(__file__).resolve().parents[1]
    readers = {str(p.relative_to(root)) for p in (root / "app").rglob("*.py")
               if re.search(r"\braw_text\b", p.read_text(encoding="utf-8"))}
    assert readers <= RAW_TEXT_ALLOWED, sorted(readers - RAW_TEXT_ALLOWED)
