"""Порт движка интервью: продукт ↔ app/modules/interview/engine (Я14) и заглушка продукта.

Продукт хранит сессию, расшифровку и состояние разговора (InterviewSession.state) и на каждую реплику зовёт движок:
start → первая реплика; reply → следующая реплика и признак конца; evaluate → итог (вердикт, вопросы с цитатами);
transcribe / speak — распознавание и голос для канала «голос»; avatar_token — токен сессии видео-аватара (Anam JS SDK в
браузере). Интерфейс движка — engine/CONTRACT.md v1.0 (Я14): normalize_spec, next_turn, evaluate, stt, tts, avatar_token,
check_limits, status, is_stub.

Заглушка (INTERVIEW_ENGINE=stub или движка нет): вопросы — по шаблону из собственного ответа кандидата и тем задания,
оценка — правилом (совпадение ключевых слов устного и письменного ответа), без моделей, голоса и аватара; итог помечен
stub=true. Нужна тестам, CI, e2e и стенду до выкладки движка.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import get_settings

log = logging.getLogger("interview.port")


class EngineUnavailable(Exception):
    """Канал или движок недоступен — продукт переключает канал (аватар → голос → текст) или показывает ошибку."""


# ------------------------------------------------------------------ заглушка продукта

_WORD = re.compile(r"[a-zа-яё0-9_]{4,}", re.I)
_STOP = {"чтобы", "этого", "потому", "который", "которые", "когда", "если", "тогда", "будет", "можно", "нужно", "также",
         "только", "этом", "этот", "этой", "есть", "было", "были", "после", "перед", "через", "между", "with", "that",
         "this", "from", "then", "have", "will"}
LEVEL_POINTS = {"confirmed": 90, "partial": 65, "discrepancy": 30, "no_data": 0, "strong": 90, "medium": 65, "weak": 35}
VERDICT_LABELS = {"confirmed": "подтверждено устно", "discrepancies": "есть расхождения", "insufficient": "мало данных",
                  "strong": "сильный результат", "medium": "средний результат", "weak": "слабый результат"}


def keywords(text: str) -> set[str]:
    return {w.lower()[:7] for w in _WORD.findall(text or "") if w.lower() not in _STOP}


def first_phrase(text: str, n: int = 160) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    m = re.match(r"(.{20,}?[.!?…])(\s|$)", t)
    return (m.group(1) if m else t)[:n].strip()


class StubPort:
    name = "stub"

    def channels(self) -> dict:
        return {"avatar": False, "voice": False, "text": True}

    def _plan(self, mode: str, ctx: dict, max_q: int) -> list[dict]:
        out: list[dict] = []
        if mode == "defense":
            tasks = ctx.get("tasks") or []
            for k in range(min(max_q, 2 * len(tasks))):
                t = tasks[k % len(tasks)]
                title = t.get("title") or "задание"
                if k < len(tasks):
                    topic = (t.get("topics") or [title])[0]
                    q = (f"В задании «{title}» вы написали: «{first_phrase(t.get('answer') or '', 120)}». Объясните своими "
                         f"словами, почему решили именно так и что здесь главное про «{topic}».")
                else:
                    q = f"Вернёмся к заданию «{title}»: что изменится в вашем решении, если условие станет строже?"
                out.append({"n": k + 1, "task_id": t.get("id"), "skill": None, "question": q})
        else:
            for k, s in enumerate((ctx.get("unconfirmed_skills") or [])[:max_q]):
                out.append({"n": k + 1, "task_id": None, "skill": s.get("name"),
                            "question": f"Расскажите о своём опыте: {s.get('name')}. Какая задача была самой сложной и "
                                        f"что именно сделали вы?"})
        return out

    def is_stub(self) -> bool:
        return True

    def start(self, mode: str, ctx: dict, *, max_questions: int, minutes: int, name: str, jury: bool = False,
              channel: str = "text") -> tuple[dict, str, bool]:
        plan = self._plan(mode, ctx, max_questions)
        if not plan:
            raise EngineUnavailable("нет вопросов")
        hello = f"{name}, здравствуйте! Это заглушка интервью: разговор по шаблону, без модели. "
        return {"mode": mode, "ctx": ctx, "plan": plan, "i": 0}, hello + plan[0]["question"], False

    def reply(self, state: dict, answer: str, channel: str = "text") -> tuple[dict, str, bool]:
        i = int(state.get("i", 0)) + 1
        state = {**state, "i": i}
        plan = state.get("plan") or []
        if i < len(plan):
            return state, plan[i]["question"], False
        return state, "Спасибо, это все вопросы.", True

    def hint(self, state: dict, n: int) -> str | None:
        plan = state.get("plan") or []
        tid = plan[n - 1].get("task_id") if 0 < n <= len(plan) else None
        t = next((x for x in (state.get("ctx") or {}).get("tasks") or [] if x.get("id") == tid), None)
        return (t.get("answer") or "")[:300] if t else None

    def evaluate(self, state: dict, transcript: list[dict]) -> dict:
        mode, ctx, plan = state.get("mode"), state.get("ctx") or {}, state.get("plan") or []
        by_task = {t.get("id"): t for t in ctx.get("tasks") or []}
        answers: dict[int, str] = {}
        for r in transcript:
            if r.get("who") == "candidate" and isinstance(r.get("n"), int):
                answers[r["n"]] = (answers.get(r["n"], "") + " " + (r.get("text") or "")).strip()
        qs, answered, total = [], 0, 0
        for q in plan:
            a = re.sub(r"\s+", " ", answers.get(q["n"], "")).strip()
            total += len(a)
            answered += len(a) >= 40
            if mode == "defense":
                kw = keywords((by_task.get(q.get("task_id")) or {}).get("answer") or "")
                overlap = len(keywords(a) & kw) / max(1, min(len(kw), 12))
                level = ("no_data" if len(a) < 40 else "confirmed" if overlap >= 0.3 else "partial" if overlap >= 0.15
                         else "discrepancy")
                why = f"Совпадение ключевых слов с письменным ответом — {round(overlap * 100)} % (правило заглушки)"
            else:
                level = "no_data" if len(a) < 20 else "strong" if len(a) >= 200 else "medium" if len(a) >= 80 else "weak"
                why = f"Длина ответа — {len(a)} знаков (правило заглушки)"
            quote = first_phrase(a) if len(a) >= 40 and level not in ("discrepancy", "weak") else ""
            qs.append({**q, "answer_excerpt": a[:400], "level": level, "reasoning": why if a else "Ответа нет",
                       "lowered": False, "quotes": [{"text": quote}] if quote else []})
        lv = [q["level"] for q in qs]
        score = round(sum(LEVEL_POINTS[x] for x in lv) / len(lv)) if lv else None
        if mode == "defense":
            if (answered < 2 and len(qs) >= 2) or total < 150:
                verdict, score = "insufficient", None
            elif "discrepancy" in lv or (score or 0) < 50:
                verdict = "discrepancies"
            else:
                verdict = "confirmed" if (score or 0) >= 70 else "insufficient"
        else:
            verdict = ("insufficient" if not answered else "strong" if (score or 0) >= 80 else
                       "medium" if (score or 0) >= 55 else "weak")
        return {"verdict": verdict, "verdict_label": VERDICT_LABELS[verdict], "score": score,
                "summary": "Заглушка интервью: вопросы по шаблону, оценка правилом по ключевым словам ответов — не модель.",
                "questions": qs, "flags": [f"Устный ответ на вопрос {q['n']} мало совпадает с письменным (правило заглушки)"
                                           for q in qs if q["level"] == "discrepancy"],
                "coverage": round(100 * sum(x != "no_data" for x in lv) / len(lv)) if lv else 0,
                "cost": {"usd": 0.0, "estimated": False}, "stub": True}

    def transcribe(self, audio: bytes, mime: str) -> tuple[str, float]:
        raise EngineUnavailable("распознавание речи в заглушке не работает — ответьте текстом")

    def speak(self, text: str) -> tuple[bytes, str, float]:
        raise EngineUnavailable("голос в заглушке не работает")

    def avatar_token(self, max_seconds: int = 300) -> dict | None:
        return None

    def check_limits(self, jury: bool, last_hour: int, spent_today_usd: float) -> None:
        return None


# ------------------------------------------------------------------ движок Я14 (engine/CONTRACT.md v1.0)

class EnginePort:
    """Адаптер к app.modules.interview.engine: движок без состояния — продукт хранит spec и расшифровку в state."""
    name = "engine"

    def __init__(self, eng: Any):
        self.eng = eng

    def _err(self, e: Exception) -> EngineUnavailable:
        return EngineUnavailable(getattr(e, "code", None) or type(e).__name__)

    def is_stub(self) -> bool:
        try:
            return bool(self.eng.is_stub())
        except Exception:  # noqa: BLE001
            return True

    def channels(self) -> dict:
        try:
            ch = (self.eng.status() or {}).get("channels") or {}
        except Exception:  # noqa: BLE001
            ch = {}
        return {"avatar": bool(ch.get("avatar")) and get_settings().interview_avatar,
                "voice": bool(ch.get("voice")) and bool(ch.get("stt")), "text": True}

    def _spec(self, state: dict):
        return self.eng.SessionSpec.model_validate(state["spec"])

    def _turn(self, state: dict, text: str | None, channel: str) -> tuple[dict, str, bool]:
        e = self.eng
        out = e.next_turn(e.TurnInput(spec=self._spec(state), transcript=e.Transcript.model_validate(state["transcript"]),
                                      candidate_text=text, channel=channel))
        spec = dict(state["spec"])
        if out.started_at and not spec.get("started_at"):
            spec["started_at"] = out.started_at.isoformat()
        cost = dict(state.get("cost") or {})
        cost["llm_usd"] = round(float(cost.get("llm_usd") or 0) + float(out.cost_usd or 0), 6)
        st = {**state, "spec": spec, "transcript": out.transcript.model_dump(mode="json"), "cost": cost,
              "source": out.source}
        return st, out.text, bool(out.finished)

    def start(self, mode: str, ctx: dict, *, max_questions: int, minutes: int, name: str, jury: bool = False,
              channel: str = "text") -> tuple[dict, str, bool]:
        e = self.eng
        Ctx = e.DefenseContext if mode == "defense" else e.InterviewContext
        try:
            spec = e.normalize_spec(e.SessionSpec(mode=mode, candidate_name=name[:60] or "кандидат", duration_min=minutes,
                                                  max_questions=max_questions, jury=jury, context=Ctx.model_validate(ctx)))
            return self._turn({"spec": spec.model_dump(mode="json"), "transcript": {"items": []}}, None, channel)
        except Exception as x:  # noqa: BLE001
            raise self._err(x) from None

    def reply(self, state: dict, answer: str, channel: str = "text") -> tuple[dict, str, bool]:
        try:
            return self._turn(state, answer, channel)
        except Exception as x:  # noqa: BLE001
            raise self._err(x) from None

    def evaluate(self, state: dict, transcript: list[dict]) -> dict:
        e = self.eng
        v = e.evaluate(self._spec(state), e.Transcript.model_validate(state["transcript"]))
        cost = dict(state.get("cost") or {})
        cost["llm_usd"] = round(float(cost.get("llm_usd") or 0) + float(v.cost_usd or 0), 6)
        cost["usd"] = round(sum(float(cost.get(k) or 0) for k in ("llm_usd", "tts_usd", "stt_usd", "avatar_usd")), 6)
        cost["estimated"] = True
        return {"verdict": v.verdict, "verdict_label": v.verdict_label, "score": v.score, "summary": v.summary,
                "questions": [{"n": q.k, "task_id": q.task_id, "skill": q.skill, "question": q.question,
                               "answer_excerpt": q.answer_excerpt, "level": q.level, "reasoning": q.reasoning,
                               "lowered": q.lowered, "quotes": [{"n": c.n, "text": c.text} for c in q.quotes]}
                              for q in v.questions],
                "flags": list(v.flags), "coverage": v.coverage, "cost": cost, "stub": v.source == "stub",
                "source": v.source, "removed_quotes": v.removed_quotes}

    def transcribe(self, audio: bytes, mime: str) -> tuple[str, float]:
        try:
            t = self.eng.stt(audio, mime)
        except Exception as x:  # noqa: BLE001
            raise self._err(x) from None
        if getattr(t, "stub", False) or not (t.text or "").strip():
            raise EngineUnavailable("stt_unavailable")
        return t.text, float(t.cost_usd or 0)

    def speak(self, text: str) -> tuple[bytes, str, float]:
        try:
            a = self.eng.tts(text, "mp3")
        except Exception as x:  # noqa: BLE001
            raise self._err(x) from None
        if getattr(a, "stub", False) or not a.data:
            raise EngineUnavailable("tts_unavailable")
        return a.data, a.mime or "audio/mpeg", float(a.cost_usd or 0)

    def avatar_token(self, max_seconds: int = 300) -> dict | None:
        try:
            t = self.eng.avatar_token()
        except Exception:  # noqa: BLE001
            return None
        return {"session_token": t.session_token, "ice_servers": t.ice_servers, "max_seconds": t.max_seconds,
                "relay_only": t.relay_only, "persona_name": t.persona_name}

    def check_limits(self, jury: bool, last_hour: int, spent_today_usd: float) -> None:
        self.eng.check_limits(jury, last_hour, spent_today_usd)  # EngineError(jury_limit | daily_cap) — ловит сервис

    def hint(self, state: dict, n: int) -> str | None:
        """Только заглушка движка (e2e): начало письменного ответа задания текущего вопроса."""
        try:
            items = self.eng.plan(self._spec(state))
            last = next((u for u in reversed(state["transcript"]["items"]) if u.get("who") == "interviewer"), None)
            k = (last or {}).get("k") or n
            tid = next((p.task_id for p in items if p.k == k), None)
            t = next((x for x in state["spec"]["context"].get("tasks") or [] if x.get("id") == tid), None)
            return (t.get("answer") or "")[:300] if t else None
        except Exception:  # noqa: BLE001
            return None


def get_port():
    s = get_settings()
    if (s.interview_engine or "auto") != "stub":
        try:
            from app.modules.interview import engine as eng  # type: ignore[attr-defined]  # Я14, feat/interview-engine
        except ImportError:
            eng = None
        if eng is not None and hasattr(eng, "next_turn"):
            return EnginePort(eng)
    return StubPort()


def is_stub() -> bool:
    """Заглушка продукта или движок в режиме заглушки (нет ключа модели / INTERVIEW_STUB=1)."""
    return get_port().is_stub()
