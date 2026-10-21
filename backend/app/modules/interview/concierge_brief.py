"""Бриф работодателя голосом с Настей (решение владельца 21.10, по образцу брифа другое решение — подход перенесён, код свой).

Полудуплекс, как в устном тесте (voice/live/interview.ts): Настя задаёт короткий вопрос голосом, микрофон закрыт, пока
она говорит; ответ уходит сам после паузы или по «Я закончил». 4–6 вопросов: направление и грейд, обязательные навыки,
задачи, формат и город, вилка. Итог — текст вакансии: браузер вставляет его в поле потребности, дальше — обычный разбор
требований (цитаты, дискриминационные формулировки убираются), карточка и подборка.

Состояние брифа — в памяти процесса (30 мин). Модель — та же голова, что у Насти (concierge_brain.LLM_MODELS); модель
недоступна — вопросы по списку, вакансия — из ответов как есть.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
from pathlib import Path

log = logging.getLogger("interview.concierge")

TTL_S = 1800
MAX_Q = 6
_LOCK = threading.Lock()


def _dir() -> Path:
    """Состояние брифа — файлом в общем кэше: у api несколько процессов, запросы одного брифа попадают в разные."""
    from app.modules.interview import concierge as cg

    d = Path(cg._CACHE) / "briefs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(sid: str) -> Path | None:
    return _dir() / f"{sid}.json" if re.fullmatch(r"[A-Za-z0-9_-]{8,40}", sid or "") else None


def _load(sid: str) -> dict | None:
    p = _path(sid)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else None
    except (OSError, ValueError):
        return None


def _save(sid: str, s: dict) -> None:
    p = _path(sid)
    if not p:
        return
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)

FIRST = ("Здравствуйте, я Настя. Соберём вакансию голосом — пять коротких вопросов. Кого ищете: направление и уровень? "
         "Например, бэкенд-разработчик уровня Middle.")
FIXED = [
    "Какие навыки и технологии обязательны — без чего кандидат не подойдёт?",
    "Какие задачи будут в первые месяцы? Что было бы плюсом?",
    "Формат работы: офис, гибрид или удалёнка? И в каком городе?",
    "Какая зарплатная вилка — от и до?",
]
DONE_SAY = "Спасибо, бриф готов. Я вписала вакансию в поле — сейчас разберу требования, проверьте карточку."
MARK = "===ВАКАНСИЯ==="

SYSTEM = """Ты Настя, ИИ-проводник платформы «Драфт». Ведёшь короткий голосовой бриф с работодателем, чтобы составить \
потребность (вакансию) для подбора кандидатов с подтверждённым грейдом.
Выясни по порядку, пропуская то, что человек уже сказал: 1) направление и грейд (Стажёр, Junior, Middle, Senior, Lead); \
2) обязательные навыки и технологии; 3) задачи на первые месяцы и желательные навыки; 4) формат работы (офис, гибрид, \
удалёнка) и город; 5) зарплатная вилка от и до.
Правила: один короткий вопрос за раз, до 20 слов, разговорно, без списков и без markdown. Не повторяй вопрос, на который \
уже ответили; неясно — одно короткое уточнение. Требования к полу, возрасту, внешности, национальности, семейному \
положению не используются: если работодатель их называет — мягко скажи об этом одной фразой и не включай в вакансию. \
Не выдумывай фактов, которых не было в ответах. Вилку не предлагай сама — спроси.
Когда всего хватает или задано шесть вопросов — заканчивай.
Формат ответа: первая строка — JSON {"done": false} или {"done": true}. Со второй строки — то, что ты говоришь вслух \
(одна-две фразы). Если done — после слов вслух отдельной строкой ===ВАКАНСИЯ===, а за ней текст вакансии от лица \
компании: должность и грейд, задачи, обязательные навыки, желательные навыки, формат и город, зарплатная вилка — \
5–10 коротких строк, только из сказанного."""


def _gc() -> None:
    now = time.time()
    try:
        for f in _dir().glob("*.json"):
            if now - f.stat().st_mtime > TTL_S:
                f.unlink(missing_ok=True)
    except OSError:
        pass


def start(owner: str) -> dict:
    sid = secrets.token_urlsafe(12)
    with _LOCK:
        _gc()
        _save(sid, {"owner": owner, "at": time.time(), "history": [{"who": "nastya", "text": FIRST}],
                    "question": FIRST, "done": False, "vacancy": "", "n": 1, "live": False})
    return {"id": sid, "question": FIRST, "max_questions": MAX_Q}


def get(sid: str, owner: str) -> dict | None:
    s = _load(sid)
    return s if s and s.get("owner") == owner else None


def _fallback_vacancy(s: dict) -> str:
    asks = [h["text"] for h in s["history"] if h["who"] == "nastya"]
    ans = [h["text"] for h in s["history"] if h["who"] == "employer"]
    lines = []
    for i, a in enumerate(ans):
        q = asks[i] if i < len(asks) else ""
        topic = ("Должность и уровень" if i == 0 else "Обязательные навыки" if i == 1 else "Задачи и плюсы" if i == 2
                 else "Формат и город" if i == 3 else "Зарплатная вилка" if i == 4 else "Дополнительно")
        lines.append(f"{topic}: {a.strip().rstrip('.')}." if a.strip() else "")
        del q
    return "\n".join(x for x in lines if x)


def answer(sid: str, owner: str, text: str) -> dict:
    """Ответ работодателя → следующий вопрос Насти или итог (done + текст вакансии)."""
    s = get(sid, owner)
    if s is None:
        return {"error": "not_found"}
    if s["done"]:
        return {"question": s["question"], "done": True, "vacancy": s["vacancy"]}
    clean = re.sub(r"\s+", " ", text or "").strip()[:2000]
    s["history"].append({"who": "employer", "text": clean})
    s["at"] = time.time()
    t0 = time.monotonic()
    say, vacancy, done, model = _ask_model(s)
    if say is None:   # модель недоступна — вопросы по списку
        k = s["n"] - 1
        if k < len(FIXED):
            say, done = FIXED[k], False
        else:
            say, done, vacancy = DONE_SAY, True, _fallback_vacancy(s)
        model = "fixed"
        s["live"] = False
    else:
        s["live"] = True
    if not done and s["n"] >= MAX_Q:
        done = True
    if done:
        vacancy = vacancy or _fallback_vacancy(s)
        say = DONE_SAY   # одна и та же фраза: браузер сразу вписывает вакансию и разбирает требования
        s["vacancy"] = vacancy
    s["done"] = done
    s["question"] = say
    s["n"] += 1
    s["history"].append({"who": "nastya", "text": say})
    _save(sid, s)
    log.info("concierge brief %s: ход %d, %s, %d мс%s", sid[:6], s["n"] - 1, model, int((time.monotonic() - t0) * 1000),
             ", готово" if done else "")
    return {"question": say, "done": done, "vacancy": vacancy if done else "", "n": s["n"] - 1}


def _ask_model(s: dict) -> tuple[str | None, str, bool, str | None]:
    from app.modules.interview import concierge as cg
    from app.modules.interview import concierge_brain as brain
    from app.modules.interview import concierge_stream as cs

    if not brain.LLM_MODELS:
        return None, "", False, None
    msgs: list[dict] = [{"role": "system", "content": [{"type": "text", "text": SYSTEM,
                                                         "cache_control": {"type": "ephemeral"}}]},
                        {"role": "user", "content": "(служебно: работодатель открыл бриф голосом)"}]
    for h in s["history"]:
        role = "assistant" if h["who"] == "nastya" else "user"
        if msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n" + h["text"]
        else:
            msgs.append({"role": role, "content": h["text"]})
    note = f"(служебно: задано вопросов — {s['n']} из {MAX_Q}; первая строка ответа — JSON done)"
    if msgs[-1]["role"] == "user":
        msgs[-1]["content"] += "\n" + note
    else:
        msgs.append({"role": "user", "content": note})
    head, parts, model = None, [], None
    try:
        for ev in cs.brain_events(msgs, brain.LLM_MODELS, hedge_s=brain.STREAM_HEDGE_S, deadline_s=9.0):
            if ev[0] == "head":
                head, model = ev[1], ev[2]
            elif ev[0] == "text":
                parts.append(ev[1])
            elif ev[0] in ("done", "fail"):
                break
    except Exception as e:  # noqa: BLE001
        log.warning("concierge brief: %s", type(e).__name__)
    if head is None:
        return None, "", False, None
    full = "".join(parts)
    say_part, _, vac = full.partition(MARK)
    say = cg._clean_reply(say_part.strip()) if say_part.strip() else ""
    done = bool(head.get("done")) or bool(vac.strip())
    return say, vac.strip()[:3000], done, model
