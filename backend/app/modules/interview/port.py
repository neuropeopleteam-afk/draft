"""Порт движка интервью: продукт ↔ app/modules/interview/engine (Я14) и заглушка продукта.

Продукт хранит сессию, расшифровку и состояние разговора (InterviewSession.state) и на каждую реплику зовёт движок:
start → первая реплика; reply → следующая реплика и признак конца; evaluate → итог (вердикт, вопросы с цитатами);
transcribe / speak — распознавание («нажми и говори») и голос ведущего. Видео-аватара в продукте нет (регламент п. 5.11):
визуал — собственная анимация волны голоса на экране. Интерфейс движка — engine/CONTRACT.md v1.0 (Я14): normalize_spec,
next_turn, evaluate, stt, tts, check_limits, status, is_stub.

Заглушка (INTERVIEW_ENGINE=stub или движка нет): вопросы — по шаблону из собственного ответа кандидата и тем задания,
оценка — правилом (совпадение ключевых слов устного и письменного ответа), без моделей и голоса; итог помечен stub=true.
INTERVIEW_STT_STUB=true (только e2e/демо) — «нажми и говори» в заглушке отдаёт начало письменного ответа текущего вопроса. Нужна тестам, CI, e2e и стенду до выкладки движка.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import get_settings

log = logging.getLogger("interview.port")


class EngineUnavailable(Exception):
    """Канал или движок недоступен — продукт переключает канал (голос → текст) или показывает ошибку."""


# ------------------------------------------------------------------ заглушка продукта

# подпись правила заглушки в разборе; готовый пример жюри (demo.example_wording) заменяет её на «(правило примера)»
STUB_RULE = "правило заглушки"
STUB_RULE_BY = "правилом заглушки"  # так было в итоге примеров, засеянных до Д3

_WORD = re.compile(r"[a-zа-яё0-9_]{4,}", re.I)
_STOP = {"чтобы", "этого", "потому", "который", "которые", "когда", "если", "тогда", "будет", "можно", "нужно", "также",
         "только", "этом", "этот", "этой", "есть", "было", "были", "после", "перед", "через", "между", "with", "that",
         "this", "from", "then", "have", "will"}
LEVEL_POINTS = {"confirmed": 90, "partial": 65, "discrepancy": 30, "no_data": 0, "strong": 90, "medium": 65, "weak": 35}
VERDICT_LABELS = {"confirmed": "подтверждено устно", "discrepancies": "есть расхождения", "insufficient": "мало данных",
                  "strong": "сильный результат", "medium": "средний результат", "weak": "слабый результат"}


def keywords(text: str) -> set[str]:
    return {w.lower()[:7] for w in _WORD.findall(text or "") if w.lower() not in _STOP}


def _genitive(product: str) -> str:
    p = (product or "").strip()
    return p + "а" if p and p[-1].lower() in "бвгджзклмнпрстфхцчшщ" else p


_TAIL = {"и", "а", "но", "в", "во", "на", "с", "со", "к", "по", "за", "из", "от", "до", "для", "или", "что", "чтобы", "как", "при"}
_CODE = re.compile(r"\([^)]*\)|`[^`]*`|«[^»]*»|\"[^\"]*\"")


def _trim(words: list[str], n: int) -> str:
    w = [x for x in words if any(ch.isalnum() for ch in x)][:n]
    while len(w) > 1 and w[-1].lower() in _TAIL:
        w.pop()
    return " ".join(w).strip(" ,.-")


def short_title(title: str, n: int = 5) -> str:
    """Название задания вслух: без кода, скобок, кавычек и обрезанного хвоста, до двоеточия, не длиннее n слов."""
    raw = (title or "").strip()
    t = _CODE.sub(" ", raw.replace("…", " ").replace("...", " "))
    if raw.endswith(("…", "...")) and len(t.split()) > 1:
        t = t.rsplit(None, 1)[0]
    parts = [x for x in re.split(r"[:.;!?—]", t) if x.strip()]
    head = parts[0] if parts else ""
    if len(parts) > 1 and head.strip().lower() in ("контекст", "задача", "задание", "ситуация", "кейс", "условие", "сценарий"):
        head = parts[1]  # «Контекст: сервис уведомлений…» → «сервис уведомлений»
    out = _trim(head.split(), n)
    return out[:1].upper() + out[1:] if out else "задание"


def short_fragment(text: str, n: int = 7) -> str:
    """Первые слова письменного ответа (до запятой/двоеточия, не больше n) — напоминание, а не длинная цитата."""
    t = _CODE.sub(" ", first_phrase(text, 400))
    t = re.split(r"[:;—]|,\s", t, maxsplit=1)[0]
    return _trim([x.strip("«»\"'`") for x in t.split()], n)


def first_phrase(text: str, n: int = 160) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    m = re.match(r"(.{20,}?[.!?…])(\s|$)", t)
    return (m.group(1) if m else t)[:n].strip()


class StubPort:
    name = "stub"

    def channels(self) -> dict:
        return {"voice": False, "stt": bool(get_settings().interview_stt_stub), "text": True, "avatar": False}

    def _plan(self, mode: str, ctx: dict, max_q: int) -> list[dict]:
        out: list[dict] = []
        if mode == "defense":
            tasks = ctx.get("tasks") or []
            for k in range(min(max_q, 2 * len(tasks))):
                t = tasks[k % len(tasks)]
                title = short_title(t.get("title") or "задание")
                if k < len(tasks):
                    frag = short_fragment(t.get("answer") or "", 7)
                    ask = ("Почему вы решили именно так?", "Почему именно так, а не иначе?",
                           "Как вы проверите, что это работает?")[k % 3]
                    q = (f"В задании «{title}» вы написали: «{frag}». {ask}" if frag else
                         f"Вернёмся к вашему ответу в задании «{title}». {ask}")
                else:
                    q = f"Вернёмся к заданию «{title}». Что изменится, если условие станет строже?"
                out.append({"n": k + 1, "task_id": t.get("id"), "skill": None, "question": q})
        else:
            for k, s in enumerate((ctx.get("unconfirmed_skills") or [])[:max_q]):
                out.append({"n": k + 1, "task_id": None, "skill": s.get("name"),
                            "question": f"Про «{s.get('name')}»: вспомните один случай из работы. Что за задача, что "
                                        f"делали вы сами?"})
        return out

    def is_stub(self) -> bool:
        return True

    def start(self, mode: str, ctx: dict, *, max_questions: int, minutes: int, name: str, jury: bool = False,
              channel: str = "text") -> tuple[dict, str, bool]:
        plan = self._plan(mode, ctx, max_questions)
        if not plan:
            raise EngineUnavailable("нет вопросов")
        hello = (f"Здравствуйте, {name}, я — ИИ-интервьюер {_genitive(get_settings().product_name)} в режиме заглушки, "
                 f"без модели. ")
        return {"mode": mode, "ctx": ctx, "plan": plan, "i": 0}, hello + plan[0]["question"], False

    def reply(self, state: dict, answer: str, channel: str = "text") -> tuple[dict, str, bool]:
        i = int(state.get("i", 0)) + 1
        state = {**state, "i": i}
        plan = state.get("plan") or []
        if i < len(plan):
            return state, plan[i]["question"], False
        return state, "Спасибо, я всё записала, это все вопросы.", True

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
                # доля от min(|kw|, 12): пересечение может быть больше 12 — без предела было «183 %»; не больше 100 %
                overlap = min(1.0, len(keywords(a) & kw) / max(1, min(len(kw), 12)))
                level = ("no_data" if len(a) < 40 else "confirmed" if overlap >= 0.3 else "partial" if overlap >= 0.15
                         else "discrepancy")
                why = f"Совпадение ключевых слов с письменным ответом — {round(overlap * 100)} % ({STUB_RULE})"
            else:
                level = "no_data" if len(a) < 20 else "strong" if len(a) >= 200 else "medium" if len(a) >= 80 else "weak"
                why = f"Длина ответа — {len(a)} знаков ({STUB_RULE})"
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
                "questions": qs, "flags": [f"Устный ответ на вопрос {q['n']} мало совпадает с письменным ({STUB_RULE})"
                                           for q in qs if q["level"] == "discrepancy"],
                "coverage": round(100 * sum(x != "no_data" for x in lv) / len(lv)) if lv else 0,
                "cost": {"usd": 0.0, "estimated": False}, "stub": True}

    def transcribe(self, audio: bytes, mime: str, stub_text: str | None = None) -> tuple[str, float, bool]:
        if get_settings().interview_stt_stub and (stub_text or "").strip():
            return stub_text.strip(), 0.0, True
        raise EngineUnavailable("распознавание речи в заглушке не работает — ответьте текстом")

    def speak(self, text: str, fmt: str = "mp3") -> tuple[bytes, str, float]:
        raise EngineUnavailable("голос в заглушке не работает")

    def avatar_token(self) -> dict:
        raise EngineUnavailable("avatar_unavailable")

    def check_limits(self, jury: bool, last_hour: list[dict], spent_today_usd: float) -> None:
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
        stt = bool(ch.get("stt")) or (self.is_stub() and get_settings().interview_stt_stub)
        # avatar — живой аватар Anam с нашим лицом (INTERVIEW_ANAM_ENABLED + ключ + ANAM_AVATAR_ID); экран берёт токен
        # через /sessions/{id}/avatar-token и при любом сбое тихо показывает свой портрет
        return {"voice": bool(ch.get("voice")), "stt": stt, "text": True, "avatar": bool(ch.get("avatar"))}

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

    def transcribe(self, audio: bytes, mime: str, stub_text: str | None = None) -> tuple[str, float, bool]:
        stub_ok = get_settings().interview_stt_stub
        try:
            t = self.eng.stt(audio, mime, stub_text=stub_text if stub_ok else None)
        except Exception as x:  # noqa: BLE001
            raise self._err(x) from None
        stub = bool(getattr(t, "stub", False))
        if (stub and not stub_ok) or not (t.text or "").strip():
            raise EngineUnavailable("stt_unavailable")
        return t.text, float(t.cost_usd or 0), stub

    def speak(self, text: str, fmt: str = "mp3") -> tuple[bytes, str, float]:
        """fmt: mp3 — канал «голос» (браузер); pcm_16000 — канал «аватар» (Anam, передача звука pcm_s16le 16 кГц моно)."""
        try:
            a = self.eng.tts(text, fmt)
        except Exception as x:  # noqa: BLE001
            raise self._err(x) from None
        if getattr(a, "stub", False) or not a.data:
            raise EngineUnavailable("tts_unavailable")
        return a.data, a.mime or "audio/mpeg", float(a.cost_usd or 0)

    def avatar_token(self) -> dict:
        """Токен сессии Anam (наш аватар ANAM_AVATAR_ID, режим передачи звука — голос наш). Нет флага/ключа/сети → EngineUnavailable."""
        try:
            t = self.eng.avatar_token()
        except Exception as x:  # noqa: BLE001
            raise self._err(x) from None
        return t.model_dump(mode="json") if hasattr(t, "model_dump") else dict(t)

    def check_limits(self, jury: bool, last_hour: list[dict], spent_today_usd: float) -> None:
        """last_hour — сессии песочницы жюри за час: [{"created_at": datetime, "active": bool}] (контракт, раздел 4)."""
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
