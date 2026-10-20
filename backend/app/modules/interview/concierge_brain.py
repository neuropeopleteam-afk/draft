"""Мозг Елены: память разговора, стенограмма, ответ модели по базе знаний и фоновый наставник.

• Сессия разговора (по session_id от браузера): имя, роль, что уже показано, последние реплики, заметки наставника.
• Стенограмма каждой встречи — JSONL в <кэш>/transcripts/<дата>/<время>_<id>.jsonl (контакты маскируются,
  хранится 30 дней): реплики человека и Елены, шаги обзора, решения и время ответа.
• Ответ: сильная модель (по умолчанию Claude Sonnet) с базой знаний (RAG), «страховка» — быстрая модель, если основная
  задумалась. Постоянная часть подсказки помечена для кэша модели — длинная подсказка не замедляет ответ.
• Наставник: после хода человека в фоне ещё более сильная модель читает стенограмму и оставляет Елене подсказку на
  следующий ход (что человеку важно, что показать дальше, говорить ли проще).
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import shutil
import threading
import time
from contextlib import contextmanager
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.modules.interview import concierge_rag as rag

log = logging.getLogger("interview.concierge")

MSK = timezone(timedelta(hours=3))
# «провайдер=модель@усилие рассуждений». Замеры 20.10 на полной подсказке с историей: Claude Haiku 5.5 — 2,2–2,6 с,
# Gemini 2.5 Flash — 1,4–2,1 с (страховка, если основная задумалась дольше LLM_HEDGE_S); Sonnet 5.5 с историей
# разговора начинает рассуждать (5–7 с) — для живого разговора медленно, он не в цепочке. Опус — наставник в фоне.
LLM_MODELS = [m.strip() for m in os.environ.get(
    "CONCIERGE_BRAIN_MODELS",
    "openrouter=anthropic/claude-haiku-5.5@minimal|openrouter=google/gemini-2.5-flash").split("|") if m.strip()]
LLM_HEDGE_S = float(os.environ.get("CONCIERGE_LLM_HEDGE_S", "3.2"))
LLM_DEADLINE_S = float(os.environ.get("CONCIERGE_LLM_DEADLINE_S", "7.0"))
SUPERVISOR_MODEL = os.environ.get("CONCIERGE_SUPERVISOR_MODEL", "openrouter=anthropic/claude-opus-5.5@low").strip()
TRANSCRIPT_DAYS = int(os.environ.get("CONCIERGE_TRANSCRIPT_DAYS", "30"))
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="concierge-llm")
_SUP_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="concierge-sup")

STEP_TITLES: dict[str, str] = {
    "cand-overview": "кабинет кандидата и дорожная карта",
    "cand-assessment": "тест на грейд: выбор уровня и режима",
    "cand-category": "категория, шкала уровня и паспорт грейда с QR",
    "cand-defense": "паспорт честности и устная защита с ИИ-интервьюером",
    "cand-feedback": "карта навыков, маршрут роста и спрос рынка",
    "cand-invitations": "приглашения кандидату с вилкой и торг",
    "emp-home": "кабинет работодателя и тариф",
    "emp-needs": "потребность: текст вакансии, разбор требований, подборка",
    "emp-compare": "сравнение кандидатов и ИИ-советник руководителя",
    "emp-squad": "Командный Драфт: команда под проект и бюджет",
    "emp-invitations": "приглашения работодателя и передача в ATS",
    "emp-ats": "интеграция с ATS «Поток»",
    "fsp-cabinet": "кабинет Федерации: конвертер разряда, приглашения победителей",
    "fsp-effect": "аналитика ФСП: эффект соревнований",
    "warroom": "Боевой ИИ-Полигон: архитектура и атаки на оценщика",
    "val-arena": "проверка механики: числа точности и арена ранжирования",
}


# ------------------------------------------------------------------ стенограммы

def _transcripts_dir() -> Path:
    from app.modules.interview.concierge import _CACHE  # тот же каталог кэша голоса (смонтирован на хосте)

    p = _CACHE / "transcripts"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


_PHONE = re.compile(r"(?:\+7|8)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}|\+\d[\d\s\-()]{9,}\d")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_TG = re.compile(r"(?:t\.me/|@)[A-Za-z0-9_]{4,}")


def mask(text: str) -> str:
    t = _EMAIL.sub("[почта]", text or "")
    t = _PHONE.sub("[телефон]", t)
    return _TG.sub("[контакт]", t)


def _cleanup_old() -> None:
    try:  # состояния разговоров старше суток
        for f in _sessions_dir().iterdir():
            if f.suffix in (".json", ".lock", ".tmp") and time.time() - f.stat().st_mtime > 86400:
                f.unlink(missing_ok=True)
    except OSError:
        pass
    root = _transcripts_dir()
    cutoff = (datetime.now(MSK) - timedelta(days=TRANSCRIPT_DAYS)).strftime("%Y-%m-%d")
    try:
        for d in root.iterdir():
            if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name) and d.name < cutoff:
                shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


# ------------------------------------------------------------------ сессии
#
# API работает в нескольких процессах: состояние разговора — маленький JSON на общем диске (<кэш>/sessions/<id>.json),
# изменения — под файловой блокировкой (mutate), поэтому ход, событие браузера и наставник из разных процессов
# не затирают друг друга.

@dataclass
class Session:
    sid: str
    started: float = field(default_factory=time.time)
    touched: float = field(default_factory=time.time)
    name: str | None = None
    role: str | None = None
    shown: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    last_elena: str = ""
    notes: str = ""
    suggest: str | None = None
    tone: str = "normal"
    turns: int = 0
    sup_at: float = 0.0          # когда наставник взялся за разбор (0 — свободен)

    def remember(self, who: str, text: str) -> None:
        if not text:
            return
        self.history.append({"who": who, "text": text[:600]})
        if len(self.history) > 24:
            del self.history[: len(self.history) - 24]
        if who == "elena":
            self.last_elena = text

    @property
    def file(self) -> Path:
        dt = datetime.fromtimestamp(self.started, MSK)
        return _transcripts_dir() / dt.strftime("%Y-%m-%d") / f"{dt.strftime('%H%M%S')}_{self.sid[:12]}.jsonl"


_SID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_FIELDS = ("sid", "started", "touched", "name", "role", "shown", "history", "last_elena", "notes", "suggest", "tone",
           "turns", "sup_at")


def _sessions_dir() -> Path:
    from app.modules.interview.concierge import _CACHE

    p = _CACHE / "sessions"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def _load(sid: str) -> Session | None:
    try:
        d = json.loads((_sessions_dir() / f"{sid}.json").read_text(encoding="utf-8"))
        return Session(**{k: d[k] for k in _FIELDS if k in d})
    except (OSError, ValueError, TypeError):
        return None


def _save(s: Session) -> None:
    fp = _sessions_dir() / f"{s.sid}.json"
    tmp = fp.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps({k: getattr(s, k) for k in _FIELDS}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, fp)
    except OSError as e:
        log.warning("concierge session save: %s", e)


def session(sid: str | None) -> Session | None:
    """Снимок состояния разговора (только чтение; изменения — через mutate)."""
    if not sid or not _SID.match(sid):
        return None
    return _load(sid) or Session(sid=sid)


@contextmanager
def mutate(sid: str | None):
    """Изменить состояние разговора под блокировкой; без корректного id — None (ничего не пишется)."""
    if not sid or not _SID.match(sid):
        yield None
        return
    lock_fp = _sessions_dir() / f"{sid}.lock"
    fh = None
    try:
        fh = open(lock_fp, "a+")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except OSError:
        fh = None
    try:
        s = _load(sid)
        fresh = s is None
        if s is None:
            s = Session(sid=sid)
        yield s
        s.touched = time.time()
        _save(s)
        if fresh and int(s.started) % 20 == 0:
            threading.Thread(target=_cleanup_old, daemon=True).start()
    finally:
        if fh is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                fh.close()
            except OSError:
                pass


def write(s: Session | None, who: str, text: str = "", **extra) -> None:
    """Строка стенограммы (дозапись; строки из разных процессов не перемешиваются). Сбой записи разговору не мешает."""
    if s is None:
        return
    try:
        fp = s.file
        fp.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now(MSK).strftime("%H:%M:%S.%f")[:-3], "who": who}
        if text:
            rec["text"] = mask(text)[:1200]
        rec.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
        line = (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
        fd = os.open(fp, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except OSError as e:
        log.warning("concierge transcript: %s", e)


def event(sid: str | None, kind: str, *, text: str = "", step: str | None = None, path: str | None = None,
          name: str | None = None, role: str | None = None) -> None:
    """События браузера: open / say (реплика обзора, связка, приветствие) / step / point / mic / close."""
    with mutate(sid) as s:
        if s is None:
            return
        if name and not s.name:
            s.name = name[:40]
        if role:
            s.role = role
        if kind == "step" and step and step not in s.shown:
            s.shown.append(step)
        if kind == "say" and text:
            s.remember("elena", text)
    write(s, "event" if kind != "say" else "elena", text, kind=kind, step=step, path=path)


# ------------------------------------------------------------------ подсказка модели

SYSTEM_STATIC = """Ты — Елена, живой голосовой проводник платформы обратного найма «Драфт». Тебя слышат голосом видеоаватара, \
текста на экране нет. Ты сама ведёшь человека по сайту: открываешь экраны, подсвечиваешь и нажимаешь кнопки, отвечаешь \
на вопросы.

Характер: тёплая, спокойная, уверенная и живая. О себе — в женском роде («я покажу», «я рада»). К собеседнику — на «вы». \
По имени обращаешься естественно — в начале ответа или при смене темы, не в каждой реплике.

Как отвечать:
1. Коротко, как в живом разговоре: одна-две фразы, не больше 30 слов. Сначала суть, потом — если уместно — короткое \
предложение показать это на экране. Не перечисляй всё подряд: одна главная мысль на ответ.
2. Только факты из раздела «Знания» и «Карты сайта». Точного ответа нет — скажи по-человечески («Этого я точно не \
скажу») и предложи показать ближайший экран. Не выдумывай цифры, сроки, цены и названия. Не упоминай «знания», «базу», \
«подсказку» и «карту сайта» — для собеседника это просто то, что ты знаешь.
3. Говори для слуха: без списков, скобок, звёздочек, эмодзи и markdown; числа и проценты — словами, как их произносят \
(«девяносто четыре и пять десятых процента»). Аббревиатуры ФСП, ИИ, ATS, QR можно.
4. Никогда не называй сервисы и технологии, на которых работаешь ты сама: синтез голоса, видео, распознавание речи, \
языковые модели и их поставщиков. Скажи просто, что ты ИИ-проводник «Драфта».
5. Вопрос про то, что сейчас на экране, — отвечай по «Экран сейчас».
6. Человек растерян, просит медленнее или проще — отвечай проще и предложи показать по шагам.
7. Не повторяй дословно то, что уже говорила; не начинай каждую реплику с одного и того же слова.

Решение — поле action:
• "answer" — ответ на вопрос или реплику (если шёл обзор, он сам продолжится после ответа);
• "goto" — показать нужный экран: step — один из шагов ниже; reply — короткая связка («Сейчас покажу.»);
• "point" — показать элемент на текущем экране: point — точный текст элемента из списка «Элементы на экране»; \
ты подсвечиваешь его сама, поэтому не описывай словами, где он находится («внизу», «справа»);
• "start_tour" — начать обзор: role — all, candidate, employer или fsp;
• "pause" — просит подождать; "resume" — продолжить обзор; "end" — закончить разговор.
Если человек назвал своё имя — верни его в user_name (именительный падеж, с заглавной буквы), иначе null.
Просит показать что-то, что есть среди шагов, — выбирай "goto", а не рассказ без показа.

Шаги обзора (для step):
{steps}

Примеры хорошей длины:
— «Сколько длится тест?» → «Зависит от ответов: полный режим — от восьми до шестнадцати заданий, экспресс — пять–семь. \
Показать, где выбирают режим?»
— «А как работодатель поймёт, что я не списал?» → «Задания каждый раз генерируются заново, а у попытки есть паспорт \
честности и устная защита. Покажу, как это выглядит.» (action goto, step cand-defense)

Ответ — строго один JSON-объект без пояснений и без markdown:
{{"reply": "...", "action": "answer", "step": null, "point": null, "role": null, "user_name": null}}

Карта сайта — всё, о чём у тебя есть знания:
{site_map}"""


def _static_prompt() -> str:
    steps = "\n".join(f"- {k}: {v}" for k, v in STEP_TITLES.items())
    return SYSTEM_STATIC.format(steps=steps, site_map=rag.site_map())


def _dynamic(s: Session | None, *, message: str, name: str | None, role: str | None, path: str, step: str | None,
             touring: bool, paused: bool, screen: dict | None, numbers: dict | None) -> str:
    shown = [STEP_TITLES.get(x, x) for x in (s.shown if s else [])][-8:]
    tour = ("на паузе" if paused else f"идёт, сейчас шаг «{STEP_TITLES.get(step or '', step or '—')}»" if touring
            else "не идёт")
    said = [h["text"] for h in (s.history if s else []) if h.get("who") == "elena"][-3:]
    if name:
        recent = any(name.lower() in t.lower() for t in said)
        name_hint = (f"Имя звучало в последних репликах — в этом ответе к {name} по имени не обращайся." if recent
                     else f"Можно один раз обратиться по имени «{name}».")
    else:
        name_hint = "Имя пока неизвестно — не выдумывай его."
    lines = [
        f"Собеседник: {name or 'имя пока неизвестно'}; роль: {role or 'не выбрана'}; обзор: {tour}. {name_hint}",
        f"Уже показано: {', '.join(shown) if shown else 'пока ничего'}.",
    ]
    if screen:
        title = str(screen.get("title") or "").strip()[:120]
        items = [str(x).strip()[:60] for x in (screen.get("items") or []) if str(x).strip()][:28]
        lines.append(f"Экран сейчас: {path} — {title or 'без заголовка'}.")
        if items:
            lines.append("Элементы на экране: " + "; ".join(f"«{x}»" for x in items) + ".")
    else:
        lines.append(f"Экран сейчас: {path}.")
    if s and (s.notes or s.suggest):
        hint = s.notes
        if s.suggest and s.suggest in STEP_TITLES and s.suggest not in s.shown:
            hint += f" Стоит показать дальше: {s.suggest} ({STEP_TITLES[s.suggest]})."
        if s.tone in ("slower", "simpler"):
            hint += " Говори проще и короче."
        lines.append(f"Подсказка наставника (учитывай, но прежде всего отвечай на то, что человек сказал сейчас): {hint.strip()}")
    extra = str((screen or {}).get("title") or "")
    chunks = rag.retrieve(message, current_path=path, step=step, extra_text=extra)
    know = [f"[{c.id}] {c.body()}" for c in chunks]
    if numbers:
        know.append(f"[validation_numbers] {numbers.get('content', '')}")
    lines.append("Знания:\n" + "\n".join(know))
    return "\n".join(lines)


def _messages(s: Session | None, dyn: str, message: str, history: list[dict] | None) -> list[dict]:
    msgs: list[dict] = [
        {"role": "system", "content": [
            {"type": "text", "text": _static_prompt(), "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": dyn},
        ]},
    ]
    hist = (s.history if s and s.history else history) or []
    for h in hist[-12:]:
        who = "assistant" if h.get("who") == "elena" else "user"
        c = str(h.get("text") or "").strip()
        if c:
            if msgs[-1]["role"] == who and who != "system":
                msgs[-1]["content"] = f"{msgs[-1]['content']} {c[:400]}"
            else:
                msgs.append({"role": who, "content": c[:400]})
    if msgs[-1]["role"] == "user":
        msgs[-1]["content"] = f"{msgs[-1]['content']} {message.strip()[:600]}"
    else:
        msgs.append({"role": "user", "content": message.strip()[:600]})
    return msgs


def _flat(msgs: list[dict]) -> list[dict]:
    """Для моделей без кэша подсказки: системная часть — одной строкой."""
    out = []
    for m in msgs:
        c = m["content"]
        if isinstance(c, list):
            c = "\n\n".join(x.get("text", "") for x in c)
        out.append({"role": m["role"], "content": c})
    return out


_HTTP = None
_HTTP_LOCK = threading.Lock()


def _client():
    """Один клиент на процесс: соединение с ретранслятором переиспользуется (минус рукопожатие на каждом ходе)."""
    global _HTTP
    with _HTTP_LOCK:
        if _HTTP is None:
            import httpx

            from app.core.config import get_settings
            from app.modules.llm import client as llm

            _HTTP = httpx.Client(timeout=httpx.Timeout(20, connect=6), transport=llm._TRANSPORT,
                                 verify=llm._verify("openrouter", get_settings()),
                                 limits=httpx.Limits(max_connections=16, max_keepalive_connections=8))
        return _HTTP


TURN_SCHEMA = {"type": "json_schema", "json_schema": {"name": "elena_turn", "strict": True, "schema": {
    "type": "object", "additionalProperties": False,
    "required": ["reply", "action", "step", "point", "role", "user_name"],
    "properties": {
        "reply": {"type": "string"},
        "action": {"type": "string", "enum": ["answer", "goto", "point", "start_tour", "pause", "resume", "end"]},
        "step": {"type": ["string", "null"]}, "point": {"type": ["string", "null"]},
        "role": {"type": ["string", "null"]}, "user_name": {"type": ["string", "null"]},
    }}}}

_REPLY_RE = re.compile(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)')
_FIELD_RE = re.compile(r'"(action|step|point|role|user_name)"\s*:\s*"([^"]*)"')


def _salvage(text: str) -> dict | None:
    """Ответ оборвался или пришёл не чистым JSON — достаём reply и поля по отдельности."""
    m = _REPLY_RE.search(text or "")
    if not m:
        return None
    try:
        reply = json.loads('"' + m.group(1) + '"')
    except ValueError:
        reply = m.group(1)
    d: dict = {"reply": reply}
    for k, v in _FIELD_RE.findall(text):
        d[k] = v
    return d


def _ask(msgs: list[dict], spec: str, timeout: float, max_tokens: int = 420, schema: dict | None = None) -> dict | None:
    import httpx

    from app.core.config import get_settings
    from app.modules.llm import client as llm

    prov, _, rest = spec.partition("=")
    if not rest:
        prov, rest = "openrouter", spec
    model, _, effort = rest.partition("@")
    use = msgs if model.startswith("anthropic/") else _flat(msgs)
    t0 = time.monotonic()
    try:
        url, headers, extra = llm._endpoint(prov, get_settings())
        body = {"model": model, "messages": use, "temperature": 0.35, "max_tokens": max_tokens, **extra}
        if effort:
            body["reasoning"] = {"effort": effort}
        if schema:
            body["response_format"] = schema
        r = _client().post(url, headers=headers, json=body, timeout=httpx.Timeout(max(1.0, timeout), connect=5))
        ms = int((time.monotonic() - t0) * 1000)
        if r.status_code != 200:
            log.warning("concierge llm %s: HTTP %s за %d мс", model, r.status_code, ms)
            return None
        j = r.json()
        ch = (j.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        text = msg.get("content") or ""
        data = llm._extract_json(text) if text.strip() else None
        if not isinstance(data, dict):
            data = _salvage(text)
        if not isinstance(data, dict) and schema and text.strip() and "{" not in text and "<" not in text:
            data = {"reply": text.strip(), "action": "answer"}  # ответ простым текстом — тоже ответ
        if not isinstance(data, dict):
            log.warning("concierge llm %s: нет JSON за %d мс (finish=%s, out=%s): %r", model, ms, ch.get("finish_reason"),
                        (j.get("usage") or {}).get("completion_tokens"), text[:160])
            return None
        data["_model"] = model
        log.info("concierge llm %s: ответ за %d мс", model, ms)
        return data
    except Exception as e:  # noqa: BLE001 — сбой модели не роняет разговор, будет откат
        log.warning("concierge llm %s: %s за %d мс", model, type(e).__name__, int((time.monotonic() - t0) * 1000))
        return None


def answer(message: str, *, sid: str | None, name: str | None, role: str | None, path: str, step: str | None,
           touring: bool, paused: bool, screen: dict | None, history: list[dict] | None,
           numbers: dict | None = None) -> dict | None:
    """Ответ модели: первая годная из LLM_MODELS; «страховочный» запрос к следующей — если основная молчит LLM_HEDGE_S."""
    s = session(sid)
    dyn = _dynamic(s, message=message, name=name, role=role, path=path, step=step, touring=touring, paused=paused,
                   screen=screen, numbers=numbers)
    msgs = _messages(s, dyn, message, history)
    models = list(LLM_MODELS)
    if not models:
        return None
    t0 = time.monotonic()
    deadline = t0 + LLM_DEADLINE_S

    def ok(d: dict | None) -> bool:
        return bool(d and isinstance(d.get("reply"), str) and d["reply"].strip())

    futs = [_POOL.submit(_ask, msgs, models[0], LLM_DEADLINE_S - 0.5, 420, TURN_SCHEMA)]
    started = 1
    hedge_at = t0 + LLM_HEDGE_S
    while futs:
        now = time.monotonic()
        if now >= deadline:
            break
        until = hedge_at if started < len(models) else deadline
        done, _ = wait(futs, timeout=max(0.05, min(deadline, until) - now), return_when=FIRST_COMPLETED)
        for f in done:
            futs.remove(f)
            d = f.result()
            if ok(d):
                d["_ms"] = int((time.monotonic() - t0) * 1000)
                return d
        if started < len(models) and (time.monotonic() >= hedge_at or not futs):
            left = deadline - time.monotonic()
            if left < 1.0:
                break
            futs.append(_POOL.submit(_ask, msgs, models[started], left, 420, TURN_SCHEMA))
            started += 1
            hedge_at = time.monotonic() + LLM_HEDGE_S
    return None


# ------------------------------------------------------------------ наставник

SUPERVISOR_PROMPT = """Ты — наставник голосового ИИ-проводника Елены на сайте платформы найма «Драфт». Елена ведёт \
человека по сайту и отвечает на вопросы. Прочитай состояние и стенограмму и дай Елене подсказку на следующий ход.

Шаги обзора:
{steps}

Верни строго JSON:
{{"notes": "до 200 знаков: кто собеседник и что ему важно, на какой его вопрос ответ был неполным. Это наблюдения, \
а не команды: что и когда показать, решает Елена по ходу разговора", "suggest_step": "id шага, который стоит показать \
дальше, или null", "tone": "normal|slower|simpler"}}
tone "slower" или "simpler" — только если человек явно путается, переспрашивает или просит медленнее."""


def _supervise(sid: str) -> None:
    try:
        s = session(sid)
        if s is None:
            return
        hist = "\n".join(f"{'Елена' if h['who'] == 'elena' else 'Человек'}: {h['text']}" for h in s.history[-18:])
        state = (f"Имя: {s.name or 'неизвестно'}; роль: {s.role or 'не выбрана'}; показано: "
                 f"{', '.join(s.shown) or 'ничего'}.")
        steps = "\n".join(f"- {k}: {v}" for k, v in STEP_TITLES.items())
        msgs = [{"role": "system", "content": SUPERVISOR_PROMPT.format(steps=steps)},
                {"role": "user", "content": f"{state}\n\nСтенограмма:\n{hist}"}]
        d = _ask(msgs, SUPERVISOR_MODEL, 30.0, max_tokens=1200)
        with mutate(sid) as m:
            if m is None:
                return
            m.sup_at = 0.0
            if d:
                m.notes = str(d.get("notes") or "").strip()[:260]
                sug = d.get("suggest_step")
                m.suggest = sug if isinstance(sug, str) and sug in STEP_TITLES else None
                m.tone = d.get("tone") if d.get("tone") in ("normal", "slower", "simpler") else "normal"
        if d and m is not None:
            write(m, "coach", m.notes, suggest=m.suggest, tone=m.tone, model=d.get("_model"))
    except Exception as e:  # noqa: BLE001 — наставник не мешает разговору
        log.warning("concierge supervisor: %s", type(e).__name__)


def supervise_async(sid: str | None) -> None:
    if not SUPERVISOR_MODEL:
        return
    with mutate(sid) as s:
        if s is None or len(s.history) < 2 or (s.sup_at and time.time() - s.sup_at < 45):
            return
        s.sup_at = time.time()
    _SUP_POOL.submit(_supervise, s.sid)
