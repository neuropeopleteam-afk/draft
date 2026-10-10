#!/usr/bin/env python3
"""Проверка свежего развёртывания по README (Я7, 09.10; docs/LOAD.md, раздел «Развёртывание с нуля»).

  python3 tools/ci/fresh_check.py --base http://127.0.0.1:8140 [--expect-candidates]

Только стандартная библиотека (запускается на сервере рядом со стеком). Проверяет путь эксперта жюри:
сайт и API живы → вход в один клик (своя песочница) → экспресс-тест до итога → потребность из текста (разбор правилами)
→ подборка с кандидатами → сравнение. Печатает время каждого шага; код выхода 1 — если шаг не прошёл.
Песочницу проверки удаляет за собой (DELETE /api/jury/sandbox).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "loadtest"))
import flows  # noqa: E402

STEPS: list[tuple[str, bool, float, str]] = []


def call(base: str, method: str, path: str, body: dict | None = None, token: str | None = None, raw: bool = False):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json",
                                          **({"authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read().decode()
            return r.status, (data if raw else json.loads(data or "null"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def step(name: str, fn):
    t0 = time.time()
    try:
        note = fn() or ""
        STEPS.append((name, True, time.time() - t0, str(note)))
        return True
    except Exception as e:  # noqa: BLE001
        STEPS.append((name, False, time.time() - t0, f"{type(e).__name__}: {str(e)[:200]}"))
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8140")
    ap.add_argument("--web", default="", help="адрес страниц, если сайт отдельно от API (локальная разработка)")
    ap.add_argument("--expect-candidates", action="store_true", help="демо-данные загружены — подборка не пуста")
    a = ap.parse_args()
    b, st = a.base.rstrip("/"), {}

    def health():
        c, d = call(b, "GET", "/api/health")
        assert c == 200 and d.get("status") == "ok", (c, d)

    def site():
        for p in ("/", "/validation", "/criteria"):
            c, d = call(a.web.rstrip("/") or b, "GET", p, raw=True)
            assert c == 200 and '<div id="root">' in d, (p, c)

    def meta():
        c, d = call(b, "GET", "/api/meta")
        assert c == 200, c
        return f"llm.configured={d['llm']['configured']}"

    def login():
        c, d = call(b, "POST", "/api/jury/login", {"persona": "employer", "scenario": "new"})
        assert c == 200 and d.get("access_token"), (c, d)
        st["sid"], st["emp"] = d.get("scenario"), d["access_token"]
        return "своя песочница" if d.get("scenario") else "общее демо (лимит песочниц)"

    def test():
        c, d = call(b, "POST", "/api/jury/login", {"persona": "candidate_new", "scenario": st.get("sid")})
        assert c == 200, (c, d)
        tok, rnd = d["access_token"], random.Random(1)
        c, s = call(b, "POST", "/api/assessment/sessions", {"claimed_grade": "junior", "mode": "express",
                                                            "integrity_ack": True}, tok)
        assert c == 201, (c, s)
        item, n = s["item"], 0
        while item and n < 30:
            assert not flows.is_llm_item(item), item.get("format")
            c, r = call(b, "POST", f"/api/assessment/sessions/{s['session_id']}/answers", flows.answer_for(item, rnd), tok)
            assert c == 200, (c, r)
            item, n = r["item"], n + 1
        c, f = call(b, "POST", f"/api/assessment/sessions/{s['session_id']}/finish", None, tok)
        assert c == 200, (c, f)
        return f"{n} заданий, итог: {f.get('decision') or f.get('status') or 'есть'}"

    def selection():
        text = flows.NEED_TEXTS[0]
        c, p = call(b, "POST", "/api/employer/needs/parse", {"text": text, "mode": "fast"}, st["emp"])
        assert c == 200, (c, p)
        c, n = call(b, "POST", "/api/employer/needs", {"text": text, "requirements": flows.need_requirements(p)}, st["emp"])
        assert c == 201, (c, n)
        c, v = call(b, "GET", f"/api/employer/needs/{n['id']}/selections/{n['versions'][-1]['version']}", None, st["emp"])
        assert c == 200, (c, v)
        if a.expect_candidates:
            assert v["total"] > 0, "подборка пуста"
        c, cmp_ = call(b, "GET", f"/api/employer/needs/{n['id']}/compare", None, st["emp"])
        assert c in (200, 422), (c, cmp_)
        return f"разбор {p.get('method', '?')}, в подборке {v['total']}, сравнение {c}"

    ok = step("health", health) and step("страницы /, /validation, /criteria", site)
    ok = step("/api/meta", meta) and ok
    if ok and step("вход жюри в один клик", login):
        step("экспресс-тест до итога", test)
        step("потребность → подборка → сравнение", selection)
        if st.get("sid"):
            step("удалить песочницу проверки", lambda: call(b, "DELETE", "/api/jury/sandbox", None, st["emp"])[0])
    for name, good, sec, note in STEPS:
        print(f"{'OK ' if good else 'ERR'} {sec:6.2f} с  {name}{'  — ' + note if note else ''}")
    return 0 if all(g for _, g, _, _ in STEPS) else 1


if __name__ == "__main__":
    sys.exit(main())
