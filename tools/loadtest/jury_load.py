"""Нагрузка 100–200 одновременных пользователей по сценариям жюри (Я7, 09.10; docs/LOAD.md).

Без временных учёток на сервере: все виртуальные пользователи входят в ОДНУ отдельную песочницу жюри
(POST /api/jury/login, scenario = её id) — как эксперт по кнопке «Войти» на главной. Песочницу создаёт
tools/loadtest/run_load.py prepare (один вызов scenario=new), удаляет — run_load.py cleanup (DELETE /api/jury/sandbox)
или администратор стенда. Страницы сайта — с cookie личной ссылки эксперта (/x/<токен>, без базовой авторизации; токен — из файла
LT_XLINK_FILE, в журналы и CSV не попадает: у запросов фиксированные имена, тексты ошибок без адреса).

Роли (веса — для числа пользователей сверх тестирующих):
  CandidateTester (фиксированное число LT_TESTERS, по умолчанию 4 — по персоне-кандидату песочницы на каждого):
      вход → статус → экспресс-тест (mode=express: 5–7 автопроверяемых заданий, без open_answer и open_book_3step,
      то есть без LLM-оценки) → ответы → finish → итог → обратная связь → две попытки рядом; не больше
      LT_MAX_STARTS стартов на персону за прогон (лимит продукта — 30 в сутки на демо-учётку).
      У одной учётки одна активная сессия, поэтому параллельных тестов не больше числа учёток; LT_TOKENS (файл
      tools/loadtest/lt_accounts.py setup) добавляет свои учётки — по одному тестирующему на учётку.
  CandidateViewer (3): вход за кандидата → кабинет: статус категории, приглашения, зонды, обратная связь, попытки,
      вакансии, непрочитанные.
  Employer (3): вход за работодателя → разбор потребности (mode=fast: правила сразу; модель — в фоне, один раз на
      текст, дальше кэш; LT_PARSE=0 — без разбора) → создание потребности с готовыми требованиями (без LLM; не больше
      LT_MAX_NEEDS за прогон) → подборка → «что если» → сравнение 2–3 кандидатов → карточка → приглашение (не больше
      LT_MAX_INVITES за прогон; повтор кандидату — 409 invitation_cooldown, это правило продукта, не ошибка).
  PublicVisitor (2): главная и /criteria — HTML и статика один раз (как браузер с кэшем), дальше API страниц.
  ValidationVisitor (2): /validation — все запросы страницы (отчёт, первый экран, бенчмарк, retest, …).
  RedButton (фиксированное число LT_REDBUTTON, по умолчанию 2): /validation → «Красная кнопка» — атака из списка
      (переименование, накрутка слов, демография, поддельный/снятый паспорт ФСП, утечка банка) раз в 6–10 с;
      429 (12 атак в минуту на учётку) — лимит продукта, не ошибка.
  ResumeUploader (LT_RESUME, по умолчанию 1): загрузка резюме DOCX модельного кандидата (модель, не человек) раз в
      40–70 с, не больше LT_MAX_RESUME за прогон (лимит продукта — 5 в час на учётку).
  Тяжёлые действия с LLM на стенде (подписаны в CSV, у каждого потолок за прогон): каждый 2-й старт персоны
  candidate — полный тест с открытым ответом и оценкой (LT_MAX_OPEN, 4); новый текст потребности — модель уточняет
  разбор в фоне, опрос до готовности, время — событие «потребность: модель уточнила разбор (фон)» (LT_MAX_LLM_TEXT, 6).
  Всплеск холодного входа N экспертов (новые песочницы) — run_load.py run --burst-at <с> --burst-n 5.
Пауза между действиями — 1–4 с (человек), между страницами /validation — 5–15 с.

Переменные: LT_SCENARIO (id песочницы, обязательно), LT_XLINK_FILE (файл с JURY_LINK_1=…; пусто — страницы без
cookie, для локального стенда), LT_WEB (адрес страниц, по умолчанию --host), LT_TESTERS, LT_MAX_STARTS (10),
LT_MAX_NEEDS (20), LT_MAX_INVITES (12), LT_PARSE (1), LT_MAX_OPEN (4), LT_MAX_LLM_TEXT (6), LT_MAX_RESUME (6),
LT_REDBUTTON (2), LT_RESUME (1), LT_TOKENS (необязательно).
"""
from __future__ import annotations

import itertools
import json
import os
import random
import re
import sys
import threading
import time

from locust import HttpUser, between, events, task

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flows import (ATTACKS, CAND_PERSONAS, GRADE_FOR, NEED_TEXTS, OPEN_ANSWER, answer_for, attack_body,  # noqa: E402
                   invitation_body, is_llm_item, need_requirements, need_text_variant, resume_docx)

SCENARIO = os.environ.get("LT_SCENARIO", "")
WEB = os.environ.get("LT_WEB", "")
MAX_STARTS = int(os.environ.get("LT_MAX_STARTS", "10"))
MAX_NEEDS = int(os.environ.get("LT_MAX_NEEDS", "20"))
MAX_INVITES = int(os.environ.get("LT_MAX_INVITES", "12"))
PARSE = os.environ.get("LT_PARSE", "1") != "0"
# Тяжёлые действия (09.10: всплески памяти api и время ответа под LLM) — с LLM на стенде, поэтому с потолком за прогон:
MAX_OPEN = int(os.environ.get("LT_MAX_OPEN", "4"))          # открытых ответов с оценкой LLM (полный тест персоны candidate)
MAX_LLM_TEXT = int(os.environ.get("LT_MAX_LLM_TEXT", "6"))  # новых текстов потребности (модель уточняет в фоне)
MAX_RESUME = int(os.environ.get("LT_MAX_RESUME", "6"))      # загрузок резюме DOCX (лимит продукта — 5 в час на учётку)
REDBUTTON = int(os.environ.get("LT_REDBUTTON", "2"))        # пользователей «Красной кнопки» (12 атак в минуту на учётку)
RESUME_USERS = int(os.environ.get("LT_RESUME", "1"))        # пользователей с загрузкой резюме
# Подпись запросов в журнале nginx стенда: run_load.py nginx сверяет число запросов Locust с тем, что дошло до сервера
UA = f"spectrek-load/{os.environ.get('LT_TAG', 'run')}"
# 429 на страницах — limit_req nginx хоста (10 запросов/с с адреса): у генератора один адрес, это защита, не отказ
NGINX_429 = "429 лимит nginx для одного адреса (страницы)"


def _xlink() -> str:
    """Токен личной ссылки эксперта из файла (JURY_LINK_1=<токен или адрес …/x/<токен>>). Не печатается."""
    path = os.environ.get("LT_XLINK_FILE", "")
    if not path:
        return ""
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*JURY_LINK_\d+\s*=\s*(\S+)", line)
        if m:
            v = m.group(1).strip().strip("'\"")
            return v.split("/x/", 1)[1].strip("/") if "/x/" in v else v
    return ""


XLINK = _xlink()
_lock = threading.Lock()
_counters = {"starts": {}, "needs": 0, "invites": 0, "invited": set(), "llm_texts": set(), "open": 0, "llm_text": 0,
             "resume": 0, "attacks": 0, "full": 0}
_tokens = json.load(open(os.environ["LT_TOKENS"])) if os.environ.get("LT_TOKENS") else {}
_extra = [c["token"] for c in _tokens.get("candidates", [])]
_tester_slots = itertools.cycle([("persona", p) for p in CAND_PERSONAS] + [("token", t) for t in _extra])
TESTERS = int(os.environ.get("LT_TESTERS", str(len(CAND_PERSONAS) + len(_extra))))


def _take(key: str, cap: int) -> bool:
    with _lock:
        if _counters[key] >= cap:
            return False
        _counters[key] += 1
        return True


@events.test_start.add_listener
def _check(environment, **_kw):
    if not SCENARIO:
        raise SystemExit("LT_SCENARIO не задан: сначала tools/loadtest/run_load.py prepare")


@events.quitting.add_listener
def _report(environment, **_kw):
    print(f"[jury_load] стартов теста по персонам: {dict(_counters['starts'])}; потребностей создано: "
          f"{_counters['needs']}; приглашений отправлено: {_counters['invites']}; "
          f"текстов на разбор (модель в фоне — не больше одного раза на текст): {len(_counters['llm_texts'])}; "
          f"новых текстов для модели: {_counters['llm_text']}; полных тестов: {_counters['full']}; открытых ответов "
          f"с оценкой: {_counters['open']}; резюме: {_counters['resume']}; атак «Красной кнопки»: {_counters['attacks']}")


def _fire(name: str, t0: float, exc: Exception | None = None, kind: str = "LLM") -> None:
    """Своё событие в статистику Locust: время фоновой работы (модель уточнила разбор) — p50/p95 в той же таблице."""
    events.request.fire(request_type=kind, name=name, response_time=(time.time() - t0) * 1000, response_length=0,
                        exception=exc, context={})


class JuryUser(HttpUser):
    abstract = True
    wait_time = between(1, 4)
    persona = "candidate"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client.headers["User-Agent"] = UA

    def login(self, persona: str | None = None) -> bool:
        persona = persona or self.persona
        with self.client.post("/api/jury/login", json={"persona": persona, "scenario": SCENARIO},
                              name="вход жюри (песочница)", catch_response=True) as r:
            if r.status_code == 200 and r.json().get("access_token"):
                self.client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
                r.success()
                return True
            r.failure(f"{r.status_code} {r.text[:120]}")
            return False

    def page_once(self, path: str, label: str) -> None:
        """HTML страницы и её статика (JS, CSS) — как первый заход браузера; дальше браузер берёт из кэша."""
        base = WEB or self.host
        if XLINK and not getattr(self, "_xcookie", False):
            with self.client.get(f"{base}/x/{XLINK}", name="страница: вход по личной ссылке", allow_redirects=False,
                                 catch_response=True) as r:
                if r.status_code in (200, 302, 303) and "fsp_x" in r.cookies.keys() | self.client.cookies.keys():
                    r.success()
                    self._xcookie = True
                elif r.status_code == 429:
                    r.failure(NGINX_429)
                else:
                    r.failure(f"{r.status_code} (личная ссылка)")
        with self.client.get(f"{base}{path}", name=f"страница: {label} (HTML)", catch_response=True) as r:
            if r.status_code == 429:
                return r.failure(NGINX_429)
            if r.status_code != 200 or '<div id="root">' not in r.text:
                return r.failure(f"{r.status_code} нет SPA")
            assets = re.findall(r'(?:src|href)="(/assets/[^"]+\.(?:js|css))"', r.text)
            r.success()
        for a in assets:
            self.client.get(f"{base}{a}", name="страница: статика /assets/")


class CandidateTester(JuryUser):
    """Полный путь кандидата: вход → экспресс-тест → ответы → итог. Учётка — своя у каждого тестирующего."""
    fixed_count = TESTERS
    wait_time = between(2, 5)

    def on_start(self):
        kind, val = next(_tester_slots)
        self.slot = val if kind == "persona" else f"учётка {_extra.index(val) + 1}"
        if kind == "persona":
            self.persona = val
            self.ok = self.login(val)
        else:
            self.persona, self.ok = "candidate", True
            self.client.headers["Authorization"] = f"Bearer {val}"
        self.done = False

    @task
    def full_path(self):
        if not self.ok or self.done:
            return self.view()
        with _lock:
            n = _counters["starts"].get(self.slot, 0)
            if n >= MAX_STARTS:
                self.done = True
                return
            _counters["starts"][self.slot] = n + 1
        self.client.get("/api/assessment/status", name="тест: статус категории")
        self.client.get("/api/assessment/grade-hint", name="тест: подсказка грейда")
        full = self.persona == "candidate" and n % 2 == 1 and _counters["open"] < MAX_OPEN
        mode = "full" if full else "express"
        if full:
            with _lock:
                _counters["full"] += 1
        body = {"claimed_grade": GRADE_FOR.get(self.persona, "middle"), "mode": mode, "integrity_ack": True}
        with self.client.post("/api/assessment/sessions", json=body,
                              name="тест: начать (полный)" if full else "тест: начать (экспресс)",
                              catch_response=True) as r:
            if r.status_code in (200, 201):
                s = r.json()
                r.success()
            elif r.status_code == 429:  # лимит стартов демо-учётки за сутки — правило продукта
                r.success()
                self.done = True
                return
            else:
                return r.failure(f"{r.status_code} {r.text[:120]}")
        sid, item, guard = s["session_id"], s.get("item"), 0
        while item and guard < 30:
            guard += 1
            time.sleep(random.uniform(2, 5))  # «читает задание»
            name = "тест: ответ"
            if is_llm_item(item):  # оценивает LLM по рубрике (в экспресс-тесте таких заданий нет)
                if not _take("open", MAX_OPEN):
                    return  # потолок открытых ответов за прогон: сессию бросаем, следующий старт её закроет
                a, name = {"item_id": item["item_id"], "answer": OPEN_ANSWER, "time_spent_ms": 60_000}, \
                    "тест: открытый ответ (оценка LLM)"
                if item.get("step"):
                    a["step"] = item["step"]
            else:
                a = answer_for(item)
            with self.client.post(f"/api/assessment/sessions/{sid}/answers", json=a, name=name,
                                  catch_response=True) as r:
                if r.status_code == 200:
                    item = r.json().get("item")
                    r.success()
                elif r.status_code == 409:  # время сессии вышло — тест закрыт сервером
                    r.success()
                    break
                else:
                    r.failure(f"{r.status_code} {r.text[:120]}")
                    g = self.client.get(f"/api/assessment/sessions/{sid}", name="тест: получить задание")
                    item = g.json().get("item") if g.status_code == 200 else None
        with self.client.post(f"/api/assessment/sessions/{sid}/finish", name="тест: завершить (итог)",
                              catch_response=True) as r:
            if r.status_code == 200 or (r.status_code == 409 and "session_closed" in r.text):
                r.success()
            else:
                return r.failure(f"{r.status_code} {r.text[:120]}")
        self.client.get(f"/api/assessment/sessions/{sid}/result", name="тест: итог")
        self.client.get("/api/assessment/feedback", params={"session_id": sid}, name="тест: обратная связь")
        self.client.get("/api/assessment/attempts", name="тест: две попытки рядом")
        time.sleep(random.uniform(5, 10))

    def view(self):
        time.sleep(random.uniform(2, 5))
        self.client.get("/api/assessment/status", name="тест: статус категории")


class CandidateViewer(JuryUser):
    weight = 3

    def on_start(self):
        self.persona = random.choice(CAND_PERSONAS)
        self.ok = self.login()

    @task(3)
    def category(self):
        self.client.get("/api/assessment/status", name="кандидат: статус категории")

    @task(2)
    def inbox(self):
        self.client.get("/api/candidate/invitations", name="кандидат: приглашения")
        self.client.get("/api/candidate/probes", name="кандидат: зонды")
        self.client.get("/api/messages/unread", name="кабинет: непрочитанные")

    @task(2)
    def feedback(self):
        with self.client.get("/api/assessment/feedback", name="кандидат: обратная связь", catch_response=True) as r:
            r.success() if r.status_code in (200, 404, 409) else r.failure(str(r.status_code))  # нет теста — 409

    @task(1)
    def attempts(self):
        self.client.get("/api/assessment/attempts", name="кандидат: две попытки рядом")

    @task(1)
    def vacancies(self):
        self.client.get("/api/vacancies", name="кандидат: вакансии")


class Employer(JuryUser):
    weight = 3
    persona = "employer"

    def on_start(self):
        self.ok = self.login()
        self.need, self.version, self.refs = None, 1, []
        if self.ok:
            self.pick_need()

    def pick_need(self):
        r = self.client.get("/api/employer/needs", name="работодатель: потребности")
        needs = [n for n in (r.json() if r.status_code == 200 else []) if n.get("versions")]
        if needs:
            n = random.choice(needs[:8])
            self.need, self.version = n["id"], n["versions"][-1]["version"]

    @task(1)
    def new_need(self):
        """Жюри вводит свою потребность: разбор (правила сразу) → сохранение с готовыми требованиями → подборка."""
        if not PARSE:
            return
        with _lock:
            fresh = _counters["llm_text"] < MAX_LLM_TEXT and random.random() < 0.5
            if fresh:
                _counters["llm_text"] += 1
            text = need_text_variant(_counters["llm_text"] - 1) if fresh else random.choice(NEED_TEXTS)
            _counters["llm_texts"].add(text)
        t0 = time.time()
        r = self.client.post("/api/employer/needs/parse", json={"text": text, "mode": "fast"},
                             name="потребность: разбор (правила, модель в фоне)")
        if r.status_code == 200 and fresh:
            self.wait_llm(r.json(), t0)
        if r.status_code != 200 or not _take("needs", MAX_NEEDS):
            return
        req = need_requirements(r.json())
        with self.client.post("/api/employer/needs", json={"text": text, "requirements": req},
                              name="потребность: создать + подборка v1", catch_response=True) as c:
            if c.status_code == 201:
                d = c.json()
                self.need, self.version = d["id"], (d.get("versions") or [{"version": 1}])[-1]["version"]
                c.success()
            else:
                c.failure(f"{c.status_code} {c.text[:120]}")

    def wait_llm(self, parsed: dict, t0: float) -> None:
        """Новый текст: модель уточняет разбор в фоне — опрашиваем, как интерфейс, и пишем время до готовности."""
        job = (parsed.get("parse_job") or {}).get("id")
        if not job or not (parsed.get("llm") or {}).get("pending"):
            return  # модель не настроена (локальный стенд) или ответ из кэша
        for _ in range(40):
            time.sleep(1.5)
            g = self.client.get(f"/api/employer/needs/parse/{job}", name="потребность: опрос фонового разбора")
            st = g.json().get("status") if g.status_code == 200 else "failed"
            if st in ("done", "failed"):
                return _fire("потребность: модель уточнила разбор (фон)", t0,
                             None if st == "done" else RuntimeError("модель не ответила — остался разбор словарём"))
        _fire("потребность: модель уточнила разбор (фон)", t0, TimeoutError("нет ответа модели за 60 с"))

    @task(4)
    def selection(self):
        if not self.need:
            return self.pick_need()
        r = self.client.get(f"/api/employer/needs/{self.need}/selections/{self.version}", name="подборка: версия")
        if r.status_code == 200:
            self.refs = [x.get("ref") or (x.get("card") or {}).get("ref") for x in r.json().get("results", [])][:10]
            self.refs = [x for x in self.refs if x]

    @task(1)
    def what_if(self):
        if self.need:
            self.client.get(f"/api/employer/needs/{self.need}/selections/{self.version}/what-if",
                            name="подборка: что если")

    @task(2)
    def compare(self):
        if not self.need:
            return
        with self.client.get(f"/api/employer/needs/{self.need}/compare", params={"version": self.version},
                             name="подборка: сравнение 2–3", catch_response=True) as r:
            r.success() if r.status_code in (200, 422) else r.failure(str(r.status_code))  # <2 кандидатов — 422

    @task(2)
    def card(self):
        if self.refs:
            self.client.get(f"/api/employer/candidates/{random.choice(self.refs)}", name="подборка: карточка кандидата")

    @task(1)
    def invite(self):
        if not (self.need and self.refs):
            return
        ref = random.choice(self.refs[:5])
        with _lock:
            if _counters["invites"] >= MAX_INVITES or ref in _counters["invited"]:
                return
            _counters["invites"] += 1
            _counters["invited"].add(ref)
        body = invitation_body(ref, self.need)
        with self.client.post("/api/employer/invitations", json=body, name="приглашение: отправить",
                              catch_response=True) as r:
            r.success() if r.status_code in (201, 409) else r.failure(f"{r.status_code} {r.text[:120]}")

    @task(1)
    def lists(self):
        self.client.get("/api/employer/invitations", name="работодатель: приглашения")
        self.client.get("/api/employer/categories", name="работодатель: категории с рынком")


class PublicVisitor(JuryUser):
    weight = 2
    wait_time = between(3, 8)

    def on_start(self):
        self.page_once("/", "главная")

    @task(3)
    def landing(self):
        self.client.get("/api/meta", name="главная: /api/meta")
        self.client.get("/api/jury/status", name="главная: персоны жюри")

    @task(2)
    def criteria(self):
        self.client.get("/api/validation/criteria", name="/criteria: критерии ТЗ")

    @task(1)
    def docs(self):
        self.client.get("/api/catalog", name="публичное: каталог категорий")
        self.client.get("/api/study/summary", name="публичное: живые пользователи")

    @task(1)
    def reload(self):  # прямой заход по ссылке (новая вкладка): только HTML, статика уже в кэше браузера
        base = WEB or self.host
        with self.client.get(f"{base}/criteria", name="страница: /criteria (HTML)", catch_response=True) as r:
            r.success() if r.status_code == 200 else r.failure(f"{r.status_code}")


VALIDATION_API = ["/api/validation/report", "/api/validation/headline", "/api/validation/matching-bench",
                  "/api/validation/path-retest", "/api/validation/fsp-rating", "/api/validation/junior-stability",
                  "/api/validation/grader-check", "/api/validation/llm-models", "/api/validation/attempts-repeat",
                  "/api/study/summary", "/api/meta"]


class ValidationVisitor(JuryUser):
    weight = 2
    wait_time = between(5, 15)

    def on_start(self):
        self.page_once("/validation", "/validation")

    @task
    def open_page(self):
        for p in VALIDATION_API:
            self.client.get(p, name=f"/validation: {p.rsplit('/', 1)[-1]}")


class RedButton(JuryUser):
    """«Красная кнопка» /validation: атаки на подбор (симуляция вне кэша — всплеск памяти api). Своя учётка у каждого
    пользователя (лимит продукта — 12 атак в минуту на учётку, 90 в минуту на воркер); 429 — правило, не сбой."""
    fixed_count = REDBUTTON
    wait_time = between(6, 10)
    _personas = itertools.cycle(["expert", "fsp", "candidate_nofsp", "employer"])

    def on_start(self):
        self.ok = self.login(next(self._personas))

    @task
    def attack(self):
        if not self.ok:
            return
        aid = random.choice(ATTACKS)
        with self.client.post(f"/api/validation/attacks/{aid}", json=attack_body(aid),
                              name=f"/validation: красная кнопка ({aid})", catch_response=True) as r:
            if r.status_code == 200:
                r.success()
                with _lock:
                    _counters["attacks"] += 1
            elif r.status_code == 429:
                r.success()  # лимит продукта
            else:
                r.failure(f"{r.status_code} {r.text[:120]}")


class ResumeUploader(JuryUser):
    """Загрузка резюме DOCX (разбор в отдельном процессе, ПДн вырезаются; на стенде поля уточняет LLM)."""
    fixed_count = RESUME_USERS
    wait_time = between(40, 70)
    _personas = itertools.cycle(["candidate_nofsp", "candidate_junior"])

    def on_start(self):
        self.ok = self.login(next(self._personas))
        self.i = 0

    @task
    def upload(self):
        if not self.ok or not _take("resume", MAX_RESUME):
            return
        self.i += 1
        files = {"file": ("resume.docx", resume_docx(self.i),
                          "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        with self.client.post("/api/me/resume", files=files, name="кандидат: резюме DOCX (разбор)",
                              catch_response=True) as r:
            r.success() if r.status_code in (201, 429) else r.failure(f"{r.status_code} {r.text[:120]}")
        self.client.get("/api/me/resume", name="кандидат: последнее резюме")
