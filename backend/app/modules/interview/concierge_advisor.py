"""Живой разговор с Настей о кандидатах на сравнении (решение владельца 21.10, «смысл как у другое решение»).

Не зачитка доклада: Настя коротко, в двух-трёх фразах, говорит главное (кого позвать первым и почему, чем отличается
второй, главный риск) и спрашивает, что важно руководителю; дальше — живой вопрос-ответ голосом. Полудуплекс, как бриф
(voice/live/interview.ts): пока Настя говорит, микрофон закрыт; вопрос уходит сам после паузы.

Факты — только из сравнения (matching.compare + правила matching.advisor, те же, что в таблице ниже): балл, навыки,
подтверждённые тестом и нет, достоверность, ФСП, рынок категории и вилка. Своих чисел и обещаний трудоустройства нет,
поставщиков моделей Настя не называет. Модель недоступна — ответ правилами matching.advisor (как было).
Состояние — файлом в общем кэше (у api несколько процессов), 30 мин. Данные кандидатов в журнал не пишутся.
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
MAX_TURNS = 30
_LOCK = threading.Lock()

SYSTEM = """Ты Настя, ИИ-советник руководителя на платформе «Драфт». Ты разговариваешь голосом с руководителем, который \
сравнивает кандидатов на свою вакансию. Это живой разговор, как по видеосвязи, а не доклад.
Как говорить: коротко и по-человечески — одна-две фразы, до 35 слов; без списков, без markdown, без скобок и кодов. \
Кандидатов называй по номеру на экране: «первый», «второй», «третий» (номер — порядок в списке ниже); коды вида C-XXXX \
вслух не произноси. Числа — как в фактах. Отвечай на сам вопрос, не пересказывай всё подряд. Когда уместно — заканчивай \
коротким встречным вопросом или предложением («Подсказать вопросы для созвона с ним?»), но не каждый раз.
Факты — только из блока ФАКТЫ ниже. Чего там нет — честно скажи, что в сравнении этого нет, и предложи, как проверить \
(устная защита, короткое задание с вилкой, вопрос на созвоне). Не придумывай опыт, компании, проекты, зарплаты кандидатов. \
Скрытый минимум зарплаты кандидата ты не видишь. Трудоустройство не обещай; решение принимает руководитель. Не называй, \
на какой модели или у какого поставщика ты работаешь. Не оценивай людей по полу, возрасту, внешности, национальности.
Первая реплика (служебно «начало»): поздоровайся одним словом и скажи главное в двух-трёх фразах — кого позвать первым и \
почему, чем отличается второй, главный риск; закончи вопросом, что для руководителя важнее. До 55 слов."""


def _dir() -> Path:
    from app.modules.interview import concierge as cg

    d = Path(cg._CACHE) / "advisors"
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
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def _gc() -> None:
    now = time.time()
    try:
        for f in _dir().glob("*.json"):
            if now - f.stat().st_mtime > TTL_S:
                f.unlink(missing_ok=True)
    except OSError:
        pass


def _rub(v) -> str:
    try:
        return f"{round(float(v) / 1000):d} тыс. ₽"
    except (TypeError, ValueError):
        return "—"


def build_facts(db, company, need, refs: list[str], version: int | None) -> tuple[str, list[dict], list[str]]:
    """Факты сравнения для модели (текст), карточки кандидатов (как у советника правилами) и устный доклад правилами."""
    from app.modules.matching import advisor as adv
    from app.modules.matching import compare as compare_mod

    data = compare_mod.compare(db, company, need, refs, version)
    req = data["need"]["requirements"] or {}
    fs = [adv._facts(c, data["rows"], req) for c in data["candidates"]]
    fs.sort(key=lambda x: -x["score"])
    why = data.get("why") or []
    lead = adv._leader(fs)
    out = [f"Вакансия: {data['need']['title']}."]
    vilka, _ = adv._need_salary(req)
    if vilka:
        out.append(f"Вилка руководителя: {vilka}.")
    for i, f in enumerate(fs, 1):
        conf = ", ".join(x["title"] for x in f["confirmed"][:8]) or "нет"
        decl = ", ".join(x["title"] for x in f["declared"][:6]) or "нет"
        weak = ", ".join(x["title"] for x in f["weak"][:6]) or "нет"
        miss = ", ".join(x["title"] for x in f["missing"] if x["required"]) or "нет"
        mk = f["market"] or {}
        parts = [
            f"Кандидат {i}{' (лидер)' if f['ref'] == lead['ref'] else ''}, код на экране {f['ref']}: балл соответствия "
            f"{f['score100']} из 100",
            f"грейд по тесту: {f['category_title'] or 'нет данных'}" + (", пока не окончательный" if f["provisional"] else "")
            if f["has_test"] else "теста нет — уровень не подтверждён",
            f"обязательные навыки подтверждены тестом: {f['required_confirmed']} из {f['required_total']}",
            f"подтверждено тестом: {conf}", f"заявлено без проверки тестом: {decl}", f"слабо по тесту: {weak}",
            f"обязательное без подтверждения: {miss}",
            f"достоверность теста: {adv._integrity_word(f['integrity']) or 'нет данных'}",
            f"ФСП: {f['fsp']}" if f["fsp"] else "достижений ФСП в реестре нет",
            f"рынок его категории на руки: {_rub(mk.get('from'))}–{_rub(mk.get('to'))}" if mk.get("from") else "",
            f"устная защита: {f['defense']}" if f.get("defense") else "",
            "риски: " + "; ".join(f["risks"]) if f["risks"] else "рисков по данным нет",
        ]
        out.append("; ".join(p for p in parts if p) + ".")
    for title, lines in (("Кого позвать первым (правила сравнения)", adv._first(fs, why)),
                         ("Деньги", adv._salary(fs, req)),
                         ("Вопросы на созвон", adv._questions(fs, data["need"]["title"])),
                         ("ФСП", adv._fsp(fs)), ("Риски", adv._risks(fs))):
        if lines:
            out.append(f"{title}: " + " ".join(lines[:6]))
    refmap = {f["ref"]: i for i, f in enumerate(fs, 1)}
    txt = "\n".join(out)
    cards = [{"ref": f["ref"], "n": refmap[f["ref"]], "score": f["score100"], "category_title": f["category_title"],
              "required_confirmed": f["required_confirmed"], "required_total": f["required_total"],
              "fsp": bool(f["fsp"]), "integrity": f["integrity"], "leader": f["ref"] == lead["ref"],
              "unverified": [x["title"] for x in f["declared"]][:3], "risk": (f["risks"] or [None])[0]} for f in fs]
    brief = adv._briefing(fs, why, req)
    return txt, cards, brief


def _refs_to_numbers(text: str, refs: list[str]) -> str:
    """Коды кандидатов вслух не читаются: «C-XCRD6V» → «первый кандидат» (если модель всё же написала код)."""
    words = ["первый", "второй", "третий"]
    for i, r in enumerate(refs[:3]):
        text = re.sub(rf"(?:кандидат[а-я]*\s+)?\(?{re.escape(r)}\)?", f"{words[i]} кандидат", text)
    return text


def start(owner: str, facts: str, cards: list[dict], brief: list[str], ctx: dict | None = None) -> dict:
    sid = secrets.token_urlsafe(12)
    refs = [c["ref"] for c in cards]
    s = {"owner": owner, "at": time.time(), "facts": facts, "refs": refs, "brief": brief, "history": [], "say": "",
         "live": False, "n": 0, "ctx": ctx or {}}
    say, model = _ask_model(s, "(служебно: начало — руководитель открыл разговор; скажи главное и спроси)")
    if say is None:
        from app.modules.matching import advisor as adv

        say, model = adv.spoken(brief, 3), "rules"
    s["live"] = model != "rules"
    s["say"] = say
    s["history"].append({"who": "nastya", "text": say})
    with _LOCK:
        _gc()
        _save(sid, s)
    log.info("concierge advisor %s: начало, %s", sid[:6], model)
    return {"id": sid, "say": say, "cards": cards, "live": s["live"]}


def get(sid: str, owner: str) -> dict | None:
    s = _load(sid)
    return s if s and s.get("owner") == owner else None


def answer(sid: str, owner: str, text: str, rules_answer=None) -> dict:
    s = get(sid, owner)
    if s is None:
        return {"error": "not_found"}
    clean = re.sub(r"\s+", " ", text or "").strip()[:1000]
    if not clean:
        return {"say": s["say"]}
    t0 = time.monotonic()
    s["history"].append({"who": "employer", "text": clean})
    s["at"] = time.time()
    say, model = (None, None) if s["n"] >= MAX_TURNS else _ask_model(s, None)
    if say is None and rules_answer is not None:
        try:
            say, model = rules_answer(clean), "rules"
        except Exception as e:  # noqa: BLE001
            log.warning("concierge advisor rules: %s", type(e).__name__)
    if not say:
        say, model = "Не расслышала — повторите, пожалуйста, вопрос.", "none"
    s["live"] = model not in ("rules", "none")
    s["say"] = say
    s["n"] += 1
    s["history"].append({"who": "nastya", "text": say})
    _save(sid, s)
    log.info("concierge advisor %s: ход %d, %s, %d мс", sid[:6], s["n"], model, int((time.monotonic() - t0) * 1000))
    return {"say": say, "n": s["n"]}


def _ask_model(s: dict, service: str | None) -> tuple[str | None, str | None]:
    from app.modules.interview import concierge as cg
    from app.modules.interview import concierge_brain as brain
    from app.modules.interview import concierge_stream as cs

    if not brain.LLM_MODELS:
        return None, None
    system = SYSTEM + "\nФормат: первая строка — {} (пустой JSON), со второй — то, что ты говоришь вслух.\n\nФАКТЫ\n" + s["facts"]
    msgs: list[dict] = [{"role": "system", "content": [{"type": "text", "text": system,
                                                         "cache_control": {"type": "ephemeral"}}]}]
    if service:
        msgs.append({"role": "user", "content": service})
    else:
        msgs.append({"role": "user", "content": "(служебно: начало)"})
        for h in s["history"][-16:]:
            role = "assistant" if h["who"] == "nastya" else "user"
            if msgs[-1]["role"] == role:
                msgs[-1]["content"] += "\n" + h["text"]
            else:
                msgs.append({"role": role, "content": h["text"]})
    head, parts, model = None, [], None
    try:
        for ev in cs.brain_events(msgs, brain.LLM_MODELS, hedge_s=brain.STREAM_HEDGE_S, deadline_s=12.0):
            if ev[0] == "head":
                head, model = ev[1], ev[2]
            elif ev[0] == "text":
                parts.append(ev[1])
            elif ev[0] in ("done", "fail"):
                break
    except Exception as e:  # noqa: BLE001
        log.warning("concierge advisor: %s", type(e).__name__)
    full = "".join(parts).strip()
    if head is None and not full:
        return None, None
    say = cg._clean_reply(_refs_to_numbers(full, s["refs"])) if full else ""
    return (_spoken(say) or None), model


def _spoken(text: str) -> str:
    """Фразы со сбоем модели (английское числительное посреди русской речи) — не в голос; самопоправка — срезается."""
    from app.modules.interview import concierge as cg

    out = []
    for x in re.split(r"(?<=[.!?…])\s+", text or ""):
        x = x.strip()
        if not x or (cg._EN_NUM.search(x) and re.search(r"[а-яё]", x, re.I)):
            continue
        f = cg._SELF_FIX.sub("", x)
        out.append(f[:1].upper() + f[1:] if f != x else x)
    return " ".join(out)
