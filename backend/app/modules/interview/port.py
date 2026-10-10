"""Порт движка интервью: продукт ↔ app/modules/interview/engine (Я14) и заглушка продукта.

Продукт хранит сессию, расшифровку и состояние разговора (InterviewSession.state) и на каждую реплику зовёт движок:
start → первый вопрос; reply → следующий вопрос или конец; evaluate → итог (вердикт, вопросы с цитатами); transcribe /
speak — распознавание и голос для канала «голос»; avatar_token — токен сессии видео-аватара (Anam JS SDK в браузере).

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

    def start(self, mode: str, ctx: dict, *, max_questions: int, minutes: int, name: str) -> tuple[dict, str]:
        plan = self._plan(mode, ctx, max_questions)
        if not plan:
            raise EngineUnavailable("нет вопросов")
        hello = f"{name}, здравствуйте! Это заглушка интервью: разговор по шаблону, без модели. "
        return {"mode": mode, "ctx": ctx, "plan": plan, "i": 0}, hello + plan[0]["question"]

    def reply(self, state: dict, answer: str) -> tuple[dict, str | None]:
        i = int(state.get("i", 0)) + 1
        state = {**state, "i": i}
        plan = state.get("plan") or []
        return state, plan[i]["question"] if i < len(plan) else None

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

    def transcribe(self, audio: bytes, mime: str) -> str:
        raise EngineUnavailable("распознавание речи в заглушке не работает — ответьте текстом")

    def speak(self, text: str) -> tuple[bytes, str]:
        raise EngineUnavailable("голос в заглушке не работает")

    def avatar_token(self) -> dict | None:
        return None


# ------------------------------------------------------------------ движок Я14

class EnginePort:
    """Адаптер к app/modules/interview/engine. Имена функций — по engine/CONTRACT.md (сверить при слиянии)."""
    name = "engine"

    def __init__(self, eng: Any):
        self.eng = eng

    def _f(self, name: str):
        f = getattr(self.eng, name, None)
        if f is None:
            raise EngineUnavailable(f"движок: нет {name}")
        return f

    def channels(self) -> dict:
        try:
            st = self._f("channels")()
        except Exception:  # noqa: BLE001
            st = {}
        return {"avatar": bool(st.get("avatar")) and get_settings().interview_avatar, "voice": bool(st.get("voice")),
                "text": True}

    def start(self, mode: str, ctx: dict, *, max_questions: int, minutes: int, name: str) -> tuple[dict, str]:
        r = self._f("start")(mode=mode, context=ctx, max_questions=max_questions, minutes=minutes, name=name)
        return r["state"], r["question"]

    def reply(self, state: dict, answer: str) -> tuple[dict, str | None]:
        r = self._f("reply")(state=state, answer=answer)
        return r["state"], r.get("question")

    def evaluate(self, state: dict, transcript: list[dict]) -> dict:
        return self._f("evaluate")(state=state, transcript=transcript)

    def transcribe(self, audio: bytes, mime: str) -> str:
        try:
            return str(self._f("transcribe")(audio=audio, mime=mime) or "")
        except EngineUnavailable:
            raise
        except Exception as e:  # noqa: BLE001
            raise EngineUnavailable(type(e).__name__) from None

    def speak(self, text: str) -> tuple[bytes, str]:
        try:
            r = self._f("speak")(text=text)
        except EngineUnavailable:
            raise
        except Exception as e:  # noqa: BLE001
            raise EngineUnavailable(type(e).__name__) from None
        return (r, "audio/mpeg") if isinstance(r, bytes) else (r["audio"], r.get("mime") or "audio/mpeg")

    def avatar_token(self) -> dict | None:
        try:
            return self._f("avatar_token")()
        except Exception:  # noqa: BLE001
            return None


def get_port():
    s = get_settings()
    if (s.interview_engine or "auto") != "stub":
        try:
            from app.modules.interview import engine as eng  # type: ignore[attr-defined]  # Я14, feat/interview-engine
        except ImportError:
            eng = None
        if eng is not None and getattr(eng, "available", lambda: True)():
            return EnginePort(eng)
    return StubPort()


def is_stub() -> bool:
    return get_port().name == "stub"
