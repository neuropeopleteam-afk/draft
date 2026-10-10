"""Ход разговора: добавить ответ собеседника, решить, что сейчас (вопрос k / повтор / прощание), сформулировать реплику —
моделью (строгий JSON) → правилами → заглушкой. Сервер хранит расшифровку; клиент только показывает и озвучивает."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.config import get_settings

from .cost import llm_cost
from .errors import EngineError
from .planning import plan
from .prompts import host_messages, service_line
from .rules import rules_turn
from .schemas import TurnInput, TurnOutput, Utterance
from .settings import get_interview_settings

log = logging.getLogger("interview.engine")
MAX_ANSWERS = 60


def is_stub() -> bool:
    s = get_interview_settings()
    if s.interview_stub:
        return True
    try:
        return not get_settings().llm_configured
    except Exception:  # pragma: no cover — настройки продукта недоступны
        return True


def _clean(text: str) -> str:
    """Реплика к озвучке: без разметки, служебных скобок и двойных пробелов."""
    t = (text or "").replace("*", "").replace("#", "").replace("`", "")
    t = t.replace("[[", "").replace("]]", "")
    return " ".join(t.split()).strip()


def _llm_turn(messages: list[dict], timeout_s: float) -> tuple[str | None, str | None, dict | None, float]:
    """(text, kind, info, cost) или (None, None, info, 0) при сбое. Явная модель: одна попытка без цепочки — дальше правила."""
    from app.modules.llm import client as llm

    s = get_interview_settings()

    def ok(data: object) -> bool:
        return isinstance(data, dict) and isinstance(data.get("text"), str) and len(data["text"].strip()) >= 8

    res = llm.chat(messages, temperature=0.6, max_tokens=400, want_json=True, model=s.interview_model_turn,
                   timeout_s=timeout_s, validate=ok)
    if not res.ok or not isinstance(res.data, dict):
        return None, None, res.info() if res else None, 0.0
    kind = res.data.get("kind") if res.data.get("kind") in ("opening", "question", "repeat", "closing") else None
    return _clean(str(res.data["text"])), kind, res.info(), llm_cost(res.usage)


def next_turn(inp: TurnInput) -> TurnOutput:
    spec, tr = inp.spec, inp.transcript.model_copy(deep=True)
    now = inp.now or datetime.now(timezone.utc)
    if any(u.kind == "closing" for u in tr.items if u.who == "interviewer"):
        raise EngineError("finished", "Разговор уже завершён")
    started = spec.started_at
    text_in = (inp.candidate_text or "").strip()
    if len(text_in) > 6000:
        raise EngineError("bad_request", "Слишком длинная реплика")
    if text_in:
        if started is None:
            started = now
        n = len(tr.candidate_items()) + 1
        if n > MAX_ANSWERS:
            raise EngineError("finished", "Разговор слишком длинный")
        tr.items.append(Utterance(who="candidate", text=text_in, at=now, n=n, channel=inp.channel))
    elif tr.items and not inp.repeat:
        if tr.items[-1].who == "interviewer":
            raise EngineError("bad_request", "Пустая реплика: ждём ответ собеседника")
    if inp.repeat and tr.items and tr.items[-1].who == "interviewer" and tr.items[-1].kind != "opening":
        tr.items.pop()  # прошлая реплика ведущего не дошла — заменяем переформулировкой

    answers = len(tr.candidate_items())
    asked = tr.questions_asked()
    minute = (now - started).total_seconds() / 60 if started else 0.0
    items = plan(spec)
    if inp.repeat and asked:
        kind, item = "repeat", None
    elif asked >= spec.max_questions or (started and minute >= spec.duration_min):
        kind, item = "closing", None
    else:
        kind = "opening" if asked == 0 else "question"
        item = items[asked] if asked < len(items) else None
        if item is None:
            kind = "closing"
    last_answer = tr.candidate_items()[-1].text if answers else ""
    short = bool(last_answer) and len(last_answer.split()) < 12

    host = get_interview_settings().interviewer_name
    product = get_settings().product_name
    source, info, cost, text, model_kind = "rules", None, 0.0, None, None
    if is_stub():
        source = "stub"
    else:
        msgs = host_messages(spec, tr, service_line(spec, item, kind, minute, answers, short), host, product)
        text, model_kind, info, cost = _llm_turn(msgs, get_interview_settings().interview_turn_timeout_s)
        if text:
            source = "llm"
    if not text:
        text = rules_turn(spec, tr, kind, item.k if item else None)
    # Вид реплики решает код (план и время), модель лишь подсказывает; расхождение — в журнал.
    if model_kind and model_kind != kind:
        log.info("interview turn: модель предложила kind=%s, по плану %s", model_kind, kind)
    tr.items.append(Utterance(who="interviewer", text=text, at=now, channel=inp.channel, kind=kind, k=item.k if item else None))
    return TurnOutput(text=text, kind=kind, k=item.k if item else None, finished=(kind == "closing"), transcript=tr,
                      started_at=started, source=source, llm=info, cost_usd=cost)
