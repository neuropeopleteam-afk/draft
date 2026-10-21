"""Контекст для сервиса интервьюера (разделы 2.1 и 2.2 контракта) — только то, что кандидат сам написал, и темы.

В сервис не уходят: рубрики, эталоны и ключи заданий, ФИО и контакты (ответы проходят resume.pii.redact), резюме,
зарплата. Защищаются развёрнутые ответы (open_answer, шаг 3 open_book_3step) длиной от INTERVIEW_DEFENSE_MIN_CHARS.

KF2 (20.10, мост «подозрение античита → устная защита»): если защита рекомендована по достоверности попытки
(service.defense_recommendation — уровень «средняя»/«низкая», l_z < −2, ИИ-метка, канарейки/предзнание), а развёрнутых
ответов нет или они короче порога, защищаются **код и выбранные решения** заданий сессии (choice_tasks): интервьюер
просит устно объяснить ход решения. Человек, которому подсказывали, своё решение объяснить не сможет — это ловит то,
чего не ловит l_z.
"""
from __future__ import annotations

import os
import re

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.assessment.models import TestSession
from app.modules.catalog.seed_data import DIRECTIONS, tag_title

TEXT_PARTS = {"open_answer": (0,), "open_book_3step": (2,)}
# Обязательная устная часть (решение владельца 21.10): после последнего задания — разговор с Настей для каждого, 2–3
# вопроса. Развёрнутых ответов нет — защищаются код и выбранные решения (как в KF2), без рекомендации по достоверности.
ORAL_REQUIRED = os.environ.get("INTERVIEW_ORAL_REQUIRED", "1") == "1"
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


def integrity_of(ts: TestSession | None) -> dict | None:
    """Сохранённая достоверность попытки (engine_result.details.integrity) или None."""
    if ts is None:
        return None
    integ = (((ts.result or {}).get("engine_result") or {}).get("details") or {}).get("integrity")
    return integ if isinstance(integ, dict) else None


def eligible(ts: TestSession) -> tuple[list[dict], str | None]:
    """(годные ответы, причина отказа). Годные — от min_chars знаков; защищать нечего — причина по-русски.

    KF2: защита рекомендована по достоверности (service.defense_recommendation), а развёрнутых ответов от min_chars
    нет — годными считаются код и выбранные решения заданий сессии (choice_tasks, basis="code")."""
    from app.core.enums import TestSessionStatus

    if ts.status != TestSessionStatus.finished:
        return [], "Попытка ещё не завершена"
    ans = open_answers(ts)
    n = get_settings().interview_defense_min_chars
    good = [a for a in ans if len(a["answer"]) >= n]
    if good:
        return good, None
    from app.modules.interview.service import defense_recommendation  # service импортирует context — здесь лениво

    if ORAL_REQUIRED or defense_recommendation(integrity_of(ts))[0]:
        tasks = choice_tasks(ts)
        if tasks:
            return tasks, None
    if not ans:
        return [], "В этой попытке нет развёрнутых ответов — устная защита не нужна"
    return [], f"Развёрнутые ответы короче {n} знаков — защищать нечего"


def _done_items(ts: TestSession) -> list[dict]:
    st = (ts.result or {}).get("state") or {}
    return [it for it in st.get("items") or [] if it.get("done") and not it.get("canary")]


def choice_tasks(ts: TestSession, limit: int | None = None) -> list[dict]:
    """KF2: задания сессии для устной защиты по коду и выбранным решениям — сначала задания с сигналами честности
    (вставка текста, слишком быстрый ответ, ИИ-метка), затем с кодом, затем самые трудные, свежие первыми; до
    interview_defense_max_tasks. Порядок результата — как в тесте."""
    lim = limit or get_settings().interview_defense_max_tasks
    done = _done_items(ts)

    def hard(it: dict) -> float:
        for k in ("b", "difficulty", "item_b"):
            v = it.get(k)
            if isinstance(v, (int, float)):
                return float(v)
        return 0.0

    pick = sorted(done, key=lambda it: (not _item_flags(it), not bool((it.get("public") or {}).get("code")), -hard(it),
                                        -(it.get("position") or 0)))[:lim]
    out = [_choice_task(it) for it in sorted(pick, key=lambda it: it.get("position") or 0)]
    return [{**t, "basis": "code"} for t in out]


def last_task(ts: TestSession) -> dict | None:
    """Д2: последнее выполненное задание попытки без развёрнутого ответа (экспресс-тест жюри) — опора для живой устной
    защиты в песочнице жюри: условие и выбранный кандидатом ответ; интервьюер просит устно объяснить ход решения.
    Ответ — то, что кандидат выбрал или ввёл (вариант, строка, вывод), с пояснением, что развёрнутого ответа нет."""
    done = _done_items(ts)
    if not done:
        return None
    return _choice_task(max(done, key=lambda x: x.get("position") or 0))


def _item_flags(it: dict) -> list[str]:
    """Сигналы честности задания (те же, что у развёрнутых ответов)."""
    flags = []
    sig = it.get("signals") or {}
    if (sig.get("paste_chars") or 0) >= 30:
        flags.append("paste")
    if it.get("fast_text"):
        flags.append("fast_text")
    if it.get("ai_mark_hit"):
        flags.append("ai_mark")
    return flags + [f for f in it.get("typing") or [] if isinstance(f, str)]


def _choice_task(it: dict) -> dict:
    """Задание без развёрнутого ответа → вход защиты: условие, код и то, что кандидат выбрал или ввёл."""
    pub = it.get("public") or {}
    opts = {str(o.get("id")): o for o in pub.get("options") or [] if isinstance(o, dict)}
    picked = []
    for k in sorted((it.get("answers") or {}).keys()):
        v = ((it.get("answers") or {}).get(k) or {}).get("value")
        if v is None or v == "":
            continue
        o = opts.get(str(v).strip().upper()) or opts.get(str(v))
        if o is not None:
            picked.append(_clean(str(o.get("text") or o.get("code") or v))[:300])
        elif it.get("format") == "find_bug":
            picked.append(f"строка {v}")
        else:
            picked.append(_clean(str(v))[:300])
    chosen = "; ".join(p for p in picked if p) or "ответ без текста"
    answer = (f"Мой ответ в тесте: {chosen}. Развёрнутого ответа в этом задании не было — объясню устно, почему "
              f"выбрал(а) именно это, какие варианты отбросил(а) и как проверил(а) бы решение на практике.")
    topics = [tag_title(t) for t in it.get("skills") or []]
    return {"id": f"t{it.get('position')}", "position": it.get("position"), "kind": it.get("format"),
            "stem": _clean(pub.get("stem") or ""), "code": pub.get("code"), "step_prompt": None,
            "answer": answer, "topics": [t for t in topics if t][:8], "score": None, "integrity_flags": _item_flags(it)}


def _title(a: dict) -> str:
    first = re.split(r"(?<=[.!?:])\s|\n", a["stem"].strip(), maxsplit=1)[0].rstrip(" :;,")  # без «: ·» в карточке
    return (first[:77] + "…") if len(first) > 80 else first or f"Задание {a['position']}"


def defense_context(ts: TestSession, good: list[dict]) -> tuple[dict, dict]:
    """(context для сервиса, context_meta для БД). Берутся до max_tasks самых длинных ответов, порядок — как в тесте."""
    s = get_settings()
    # сначала задания с сигналами честности, затем самые развёрнутые ответы; порядок — как в тесте
    pick = sorted(sorted(good, key=lambda a: (not a.get("integrity_flags"), -len(a["answer"])))[: s.interview_defense_max_tasks],
                  key=lambda a: a["position"])
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
            "grade": ts.claimed_grade_id,
            # KF2: защита по коду и выбранным решениям — мост «подозрение античита → устная защита»
            **({"basis": "code", "reason": "integrity"} if any(a.get("basis") == "code" for a in pick) else {})}
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
        name = tag_title(t)
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
