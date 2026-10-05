"""Нагрузочный тест «спокойного режима»: 50 одновременных пользователей по основным операциям.

Запуск (учётки — временные, создаются tools/loadtest/lt_accounts.py внутри контейнера api):
    LT_TOKENS=/tmp/lt_tokens.json locust -f tools/loadtest/locustfile.py --host https://fsp.neuropeople.pro \
        --headless -u 50 -r 5 -t 4m --csv docs/loadtest/run

30 работодателей: подборка (версия подборки потребности), карточка кандидата, поиск по базе, категории.
20 кандидатов: тест — начать сессию, получить задание, ответить (только задания с выбором варианта или строки:
открытые ответы не отправляются, чтобы не нагружать LLM-оценку), статус категории.
Пауза между действиями 1–3 с — поведение человека, не стресс-тест.
"""
from __future__ import annotations

import itertools
import json
import os
import random

from locust import HttpUser, between, task

DATA = json.load(open(os.environ.get("LT_TOKENS", "/tmp/lt_tokens.json")))
_cand = itertools.cycle(DATA["candidates"])
_emp = itertools.cycle(DATA["employers"])
REFS = DATA["refs"]
DIRS = ["backend", "frontend", "data_ml", "qa", "security"]
GRADES = ["junior", "middle", "senior"]
STACK = {"backend": ["python", "postgresql"], "frontend": ["typescript", "react"], "data_ml": ["python", "pandas"],
         "qa": ["pytest"], "security": ["owasp"]}


class Employer(HttpUser):
    weight = 3
    wait_time = between(1, 3)

    def on_start(self):
        e = next(_emp)
        self.client.headers["Authorization"] = f"Bearer {e['token']}"
        self.needs = e["needs"]

    @task(3)
    def selection(self):
        if not self.needs:
            return
        need_id, version = random.choice(self.needs)
        self.client.get(f"/api/employer/needs/{need_id}/selections/{version}", name="подборка: версия подборки")

    @task(3)
    def card(self):
        self.client.get(f"/api/employer/candidates/{random.choice(REFS)}", name="профиль: карточка кандидата")

    @task(3)
    def search(self):
        d = random.choice(DIRS)
        params = {"direction": d, "limit": 30}
        r = random.random()
        if r < 0.4:
            params["grade"] = random.choice(GRADES)
        elif r < 0.7:
            params["stack"] = random.choice(STACK[d])
        elif r < 0.85:
            params["fsp"] = "true"
        self.client.get("/api/employer/candidates", params=params, name="поиск по базе")

    @task(1)
    def categories(self):
        self.client.get("/api/employer/categories", name="категории с рынком")


class Candidate(HttpUser):
    weight = 2
    wait_time = between(1, 3)

    def on_start(self):
        self.client.headers["Authorization"] = f"Bearer {next(_cand)['token']}"
        self.sid = None
        self.item = None
        self.begin()

    def begin(self):
        with self.client.post("/api/assessment/sessions", json={"claimed_grade": "middle"},
                              name="тест: начать сессию", catch_response=True) as r:
            if r.status_code in (200, 201):
                d = r.json()
                self.sid, self.item = d["session_id"], d.get("item")
                r.success()
            else:
                r.failure(f"{r.status_code} {r.text[:120]}")

    @task(2)
    def get_session(self):
        if not self.sid:
            return self.begin()
        r = self.client.get(f"/api/assessment/sessions/{self.sid}", name="тест: получить задание")
        if r.status_code == 200:
            self.item = r.json().get("item")

    @task(3)
    def answer(self):
        it = self.item
        if not self.sid or not it:
            return self.get_session()
        kind = it.get("answer_kind", "option")
        if kind == "text":  # открытый ответ — не отправляем (LLM-оценка), только просмотр
            return self.get_session()
        ans = random.choice([o["id"] for o in it.get("options") or [{"id": "A"}]]) if kind == "option" else 1
        body = {"item_id": it["item_id"], "answer": ans, "time_spent_ms": random.randint(20_000, 90_000)}
        if it.get("step"):
            body["step"] = it["step"]
        with self.client.post(f"/api/assessment/sessions/{self.sid}/answers", json=body,
                              name="тест: ответ на задание", catch_response=True) as r:
            if r.status_code == 200:
                self.item = r.json().get("item")
                r.success()
            elif r.status_code == 409:  # сессия закрыта или время истекло — начнём новую
                r.success()
                self.sid, self.item = None, None
            else:
                r.failure(f"{r.status_code}")

    @task(1)
    def status(self):
        self.client.get("/api/assessment/status", name="тест: статус категории")
