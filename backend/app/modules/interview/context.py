"""Контекст для сервиса интервьюера (разделы 2.1 и 2.2 контракта) — только то, что кандидат сам написал, и темы.

В сервис не уходят: рубрики, эталоны и ключи заданий, ФИО и контакты (ответы проходят resume.pii.redact), резюме,
зарплата. Защищаются развёрнутые ответы (open_answer, шаг 3 open_book_3step) длиной от INTERVIEW_DEFENSE_MIN_CHARS.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.assessment.models import TestSession
from app.modules.catalog.seed_data import DIRECTIONS, STACK, tag_title

TEXT_PARTS = {"open_answer": (0,), "open_book_3step": (2,)}
_HIDDEN = re.compile("\u2063[^\u2063]*\u2063")  # скрытые фрагменты ИИ-метки (assessment/ai_mark) — не ответ кандидата


def _clean(text: str) -> str:
    return _HIDDEN.sub("", text or "").replace("\u2063", "").strip()


def redact(text: str, *, ner: bool = True) -> str:
    """ПДн → плейсхолдеры (почта, телефон, ссылки, имена). Без исключений: сбой — пустая строка, не исходный текст."""
    from app.modules.resume.pii import redact as _redact

    try:
        return _redact(text, use_ner=ner, header=False).text
    except Exception:  # noqa: BLE001
        return ""


def open_answers(ts: TestSession) -> list[dict]:
    """Развёрнутые ответы попытки: задание, шаг, ответ, темы, балл, признаки целостности (порядок — как в тесте)."""
    st = (ts.result or {}).get("state") or {}
    out = []
    for it in st.get("items") or []:
        parts = TEXT_PARTS.get(it.get("format"))
        if not parts or not it.get("done") or it.get("canary"):
            continue
        pub = it.get("public") or {}
        for part in parts:
            ans = _clean(str(((it.get("answers") or {}).get(str(part + 1)) or {}).get("value") or ""))
            steps = pub.get("steps") or []
            step_prompt = steps[part].get("prompt") if it.get("format") == "open_book_3step" and len(steps) > part else None
            x = (it.get("x") or [None] * (part + 1))
            flags = []
            sig = it.get("signals") or {}
            if (sig.get("paste_chars") or 0) >= 30:
                flags.append("paste")
            if it.get("fast_text"):
                flags.append("fast_text")
            if it.get("ai_mark_hit"):
                flags.append("ai_mark")
            flags += [f for f in it.get("typing") or [] if isinstance(f, str)]
            topics = [tag_title(t) for t in it.get("skills") or []]
            out.append({"id": f"t{it.get('position')}", "position": it.get("position"), "kind": it.get("format"),
                        "stem": _clean(pub.get("stem") or ""), "code": pub.get("code"), "step_prompt": step_prompt,
                        "answer": ans, "topics": [t for t in topics if t][:8],
                        "score": x[part] if len(x) > part and isinstance(x[part], (int, float)) else None,
                        "integrity_flags": flags})
    return out


def eligible(ts: TestSession) -> tuple[list[dict], str | None]:
    """(годные ответы, причина отказа). Годные — от min_chars знаков; защищать нечего — причина по-русски."""
    from app.core.enums import TestSessionStatus

    if ts.status != TestSessionStatus.finished:
        return [], "Попытка ещё не завершена"
    ans = open_answers(ts)
    if not ans:
        return [], "В этой попытке нет развёрнутых ответов — устная защита не нужна"
    n = get_settings().interview_defense_min_chars
    good = [a for a in ans if len(a["answer"]) >= n]
    if not good:
        return [], f"Развёрнутые ответы короче {n} знаков — защищать нечего"
    return good, None


def _title(a: dict) -> str:
    first = re.split(r"(?<=[.!?:])\s|\n", a["stem"].strip(), maxsplit=1)[0]
    return (first[:77] + "…") if len(first) > 80 else first or f"Задание {a['position']}"


def defense_context(ts: TestSession, good: list[dict]) -> tuple[dict, dict]:
    """(context для сервиса, context_meta для БД). Берутся до max_tasks самых длинных ответов, порядок — как в тесте."""
    s = get_settings()
    pick = sorted(sorted(good, key=lambda a: -len(a["answer"]))[: s.interview_defense_max_tasks], key=lambda a: a["position"])
    tasks = []
    for a in pick:
        prompt = a["stem"] + (f"\n\nШаг: {a['step_prompt']}" if a["step_prompt"] else "")
        if a.get("code"):
            prompt += f"\n\nКод задания:\n{a['code'][:1500]}"
        tasks.append({"id": a["id"], "kind": a["kind"], "title": _title(a), "prompt": prompt[:3000],
                      "topics": a["topics"] or [_title(a)], "answer": redact(a["answer"])[:6000],
                      "score": a["score"], "integrity_flags": a["integrity_flags"]})
    tasks = [t for t in tasks if len(t["answer"]) >= s.interview_defense_min_chars] or tasks
    ctx = {"role": DIRECTIONS.get(ts.direction_id, ts.direction_id), "grade": ts.claimed_grade_id, "tasks": tasks}
    meta = {"tasks": [{"id": t["id"], "title": t["title"], "kind": t["kind"], "chars": len(t["answer"]),
                       "flags": t["integrity_flags"]} for t in tasks], "direction": ts.direction_id,
            "grade": ts.claimed_grade_id}
    return ctx, meta


def interview_context(db: Session, inv, bundle, req: dict) -> tuple[dict, dict, str | None]:
    """ИИ-интервью по потребности приглашения: навыки потребности, которые тест НЕ подтвердил (о них — вопросы),
    подтверждённые (о них не спрашиваем). (context, context_meta, причина отказа)."""
    from app.modules.profiles.facts import skill_confirmed

    tags = [it["tag"] for z in ("stack_required", "stack_desired") for it in req.get(z) or [] if it.get("tag")]
    required = {it["tag"] for it in req.get("stack_required") or []}
    confirmed, unconfirmed = [], []
    for t in dict.fromkeys(tags):
        f = bundle.skills_t1.get(t) if bundle else None
        name = STACK.get(t, (t,))[0]
        if skill_confirmed(f):
            confirmed.append(name)
        else:
            why = ("тест проверял, порог не набран" if f is not None else "в тесте этот навык не проверялся")
            unconfirmed.append({"tag": t, "name": name, "why": why, "level": "уверенный" if t in required else "базовый"})
    unconfirmed = unconfirmed[:8]
    if not unconfirmed:
        return {}, {}, "Все навыки потребности уже подтверждены тестом — спрашивать не о чем"
    summary = redact(re.sub(r"\s+", " ", inv.offer_description or "").strip(), ner=True)[:600]
    ctx = {"need_title": (inv.position_title or "Вакансия")[:200], "need_summary": summary,
           "confirmed_skills": confirmed[:12],
           "unconfirmed_skills": [{k: u[k] for k in ("name", "why", "level")} for u in unconfirmed]}
    meta = {"skills": [{"tag": u["tag"], "name": u["name"], "why": u["why"]} for u in unconfirmed],
            "confirmed": confirmed[:12], "need_id": str(inv.need_id) if inv.need_id else None}
    return ctx, meta, None
