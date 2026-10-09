"""И27: вторая оценка спорных развёрнутых ответов — в фоне, итог теста её не ждёт.

Раньше при сомнении (grader.doubts) ответ кандидата синхронно ждал вторую модель (Claude Fable 5.1, ≈ 9,5 с).
Теперь (LLM_GRADING_SECOND_ASYNC=true, по умолчанию) ответ получает балл первой оценки сразу, а в оценке части
пишется second={"status": "pending"}. После сохранения ответа (service.submit_answer / finish_session) задачи
уходят в поток процесса api (schedule): вызов модели — без блокировки сессии, запись результата — под
блокировкой строки сессии (SELECT … FOR UPDATE на PostgreSQL; те же блокировки берут answer/next/finish).

Запись результата (apply) — с пометкой label «пересмотрено второй моделью» и revised_at:
  тест идёт (in_progress): agree → балл = среднее двух оценок (method llm2, как при синхронной второй оценке);
      disagree / manipulation / failed → балл снимается (x = None, «на проверке»), ответ — эксперту, повторно
      модель его не переоценивает (bank_engine._grade_text);
  тест завершён (finished): балл и грейд задним числом НЕ меняются. agree — только отметка; иначе — disputed=True:
      ответ встаёт в очередь эксперта «ждут оценки», оценка эксперта применяется и сессия пересчитывается
      (review.submit → recompute, метка recomputed_at) — как для любого ответа «на проверке».
Путь без LLM и таймауты — прежние: модель не ответила → verdict failed → эксперт.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

log = logging.getLogger("second_opinion")
STALE_S = 180  # pending дольше (процесс перезапущен) — в сводке «не получена», балл первой оценки остаётся


def _spawn(fn, *args) -> None:
    """Фоновый запуск (поток процесса api). В тестах подменяется на синхронный или отложенный запуск."""
    threading.Thread(target=fn, args=args, daemon=True, name="second-opinion").start()


def _parts(state: dict):
    for it in state.get("items") or []:
        for part, g in enumerate(it.get("grading") or []):
            if isinstance(g, dict) and isinstance(g.get("second"), dict):
                yield it, part, g


def take_new(state: dict) -> list[tuple[str, int]]:
    """Отметить новые ожидающие вторые оценки как поставленные в очередь (до commit) и вернуть их."""
    out = []
    for it, part, g in _parts(state):
        sec = g["second"]
        if sec.get("status") == "pending" and not sec.get("queued_at"):
            sec["queued_at"] = time.time()
            out.append((it["token"], part))
    return out


def schedule(session_id: uuid.UUID, todo: list[tuple[str, int]]) -> None:
    for token, part in todo:
        _spawn(run, session_id, token, part)


def summary(state: dict) -> dict:
    """Сводка для итога теста: сколько вторых оценок ещё идёт, сколько пересмотрено, сколько ушло эксперту."""
    now = time.time()
    c = {"pending": 0, "revised": 0, "disputed": 0, "lost": 0}
    for _, _, g in _parts(state):
        sec = g["second"]
        if sec.get("status") == "pending":
            c["lost" if now - float(sec.get("queued_at") or now) > STALE_S else "pending"] += 1
        elif sec.get("status") == "done" and sec.get("label"):
            c["revised"] += 1
            c["disputed"] += sec.get("verdict") != "agree"
    return c


def _find(state: dict, token: str, part: int):
    it = next((i for i in state.get("items") or [] if i.get("token") == token), None)
    if it is None or part >= len(it.get("grading") or []):
        return None, None
    return it, it["grading"][part]


def _inputs(it: dict, part: int) -> dict:
    steps = it["public"].get("steps") or []
    return {"stem": it["public"]["stem"], "code": it["public"]["code"], "rubric": it["rubric"],
            "step_prompt": steps[part]["prompt"] if it["format"] == "open_book_3step" and len(steps) > part else None,
            "answer": (it["answers"].get(str(part + 1)) or {}).get("value") or ""}


def apply(ts, token: str, part: int, res: dict) -> bool:
    """Записать результат второй оценки в состояние сессии (вызывать под блокировкой строки)."""
    from app.core.enums import TestSessionStatus

    state = ts.result["state"]
    it, g = _find(state, token, part)
    if g is None or (g.get("second") or {}).get("status") != "pending":
        return False
    g["second"] = {**g["second"], **res}
    expert_done = g.get("method") == "expert" or (it.get("expert_reviews") or {}).get(str(part))
    agree = res.get("verdict") == "agree"
    if ts.status == TestSessionStatus.in_progress and not expert_done:
        if agree:
            comb = res["combined"]
            it["x"][part] = comb["score"]
            g.update(status="scored", method="llm2", score=comb["score"], criteria=comb["criteria"])
            g["scores"] = [*(g.get("scores") or []), res.get("score")] if res.get("score") is not None else g.get("scores")
        else:
            it["x"][part] = None
            g.update(status="pending", score=None, error={"disagree": "graders_disagree",
                                                          "manipulation": "prompt_injection_suspected"}.get(
                res.get("verdict"), "second_opinion_failed"))
            g["comment"] = {"disagree": "Две автоматические оценки разошлись — ответ передан эксперту.",
                            "manipulation": "Вторая проверка отметила в ответе попытку повлиять на оценку. "
                                            "Передан эксперту."}.get(res.get("verdict"),
                                                                     "Вторая оценка не получена — ответ передан эксперту.")
    else:  # тест уже завершён: балл и грейд не меняются задним числом
        g["second"]["after_finish"] = True
        if not agree and not expert_done:
            g["disputed"] = True
    state.setdefault("outbox", []).append({"type": "review", "token": token})
    flag_modified(ts, "result")
    return True


def run(session_id: uuid.UUID, token: str, part: int) -> None:
    from app.core.db import SessionLocal
    from app.modules.assessment import grader, service
    from app.modules.assessment.models import TestSession

    db = SessionLocal()
    try:
        ts = db.get(TestSession, session_id)
        if ts is None:
            return
        it, g = _find(ts.result.get("state") or {}, token, part)
        if g is None or (g.get("second") or {}).get("status") != "pending":
            return
        first = {"score": g.get("score"), "criteria": g.get("criteria") or {}}
        res = grader.second_opinion(**_inputs(it, part), first=first)  # без блокировки: модель думает ≈ 10 с
        db.rollback()
        ts = db.scalar(select(TestSession).where(TestSession.id == session_id).with_for_update()
                       .execution_options(populate_existing=True))
        if ts is None or not apply(ts, token, part, res):
            db.rollback()
            return
        service._drain_outbox(db, ts)
        db.commit()
    except Exception:  # noqa: BLE001 — фоновая задача не роняет процесс; балл первой оценки остаётся
        log.exception("вторая оценка в фоне упала")
        db.rollback()
    finally:
        db.close()
