"""Оценка: аналитик → скептик → сборка КОДОМ → сверка цитат КОДОМ → уровни → балл → вердикт. Модель предлагает, код решает."""
from __future__ import annotations

import logging

from .cost import llm_cost
from .planning import LEVEL_LABELS, VERDICT_LABELS, plan
from .prompts import JUDGE_ANALYST_SYSTEM, JUDGE_SKEPTIC_SYSTEM, judge_input
from .rules import rules_levels
from .schemas import QuestionVerdict, Quote, SessionSpec, Transcript, Verdict
from .settings import get_interview_settings
from .textnorm import contains, excerpt
from .turn import is_stub

log = logging.getLogger("interview.engine")

LEVELS = {"defense": ("confirmed", "partial", "discrepancy", "no_data"), "interview": ("strong", "medium", "weak", "no_data")}
POINTS = {"confirmed": 100, "partial": 60, "discrepancy": 10, "strong": 100, "medium": 60, "weak": 25}
MIN_ANSWERS, MIN_CHARS = 2, 150


def verify_quotes(quotes: list, transcript: Transcript) -> tuple[list[Quote], int]:
    """Цитата (≥ 8 знаков после нормализации) должна содержаться в реплике n собеседника, иначе ищется в любой его
    реплике; не нашлась — отбрасывается. Возвращает оставшиеся (не больше трёх) и число убранных."""
    answers = {u.n: u.text for u in transcript.items if u.who == "candidate" and u.n}
    kept: list[Quote] = []
    removed = 0
    for q in quotes or []:
        if isinstance(q, Quote):
            n, text = q.n, q.text
        elif isinstance(q, dict):
            n, text = q.get("n"), str(q.get("text") or "")
        else:
            removed += 1
            continue
        text = " ".join(text.split())
        if len(text) < 8:
            removed += 1
            continue
        try:
            n_int = int(n) if n is not None else None
        except (TypeError, ValueError):
            n_int = None
        if n_int in answers and contains(answers[n_int], text):
            kept.append(Quote(n=n_int, text=text))
            continue
        found = next((k for k, v in sorted(answers.items()) if contains(v, text)), None)
        if found is None:
            removed += 1
        else:
            kept.append(Quote(n=found, text=text))
    # одинаковые цитаты не дублируем
    uniq: list[Quote] = []
    for q in kept:
        if not any(u.n == q.n and u.text == q.text for u in uniq):
            uniq.append(q)
    return uniq[:3], removed


def verdict_from_levels(mode: str, levels: list[str], answers: int, chars: int) -> tuple[str, int | None, str]:
    """Чистая таблица вердикта (контракт, раздел 3)."""
    with_data = [lv for lv in levels if lv != "no_data"]
    insufficient = answers < MIN_ANSWERS or chars < MIN_CHARS or not with_data
    score = None if insufficient else round(sum(POINTS.get(lv, 0) for lv in with_data) / len(with_data))
    if mode == "defense":
        if insufficient:
            v = "insufficient"
        elif "discrepancy" in with_data or (score or 0) < 50:
            v = "discrepancies"
        elif (score or 0) >= 70:
            v = "confirmed"
        else:
            v = "insufficient"
    else:
        v = "insufficient" if insufficient else "strong" if (score or 0) >= 70 else "medium" if (score or 0) >= 45 else "weak"
    return v, (None if v == "insufficient" else score), VERDICT_LABELS[v]


def _apply_remarks(analyst: dict, skeptic: dict | None, mode: str) -> dict:
    """Сборка кодом: замечание скептика принимается, если предлагает допустимый уровень; его цитата добавляется к
    цитатам вопроса (сверка потом общая). Понижение — всегда; повышение — только с цитатой."""
    if not isinstance(skeptic, dict):
        return analyst
    allowed = LEVELS[mode]
    rank = {lv: i for i, lv in enumerate(allowed)}  # меньше — сильнее
    by_k = {int(q.get("k", 0) or 0): q for q in analyst.get("questions", []) if isinstance(q, dict)}
    for r in skeptic.get("remarks", []) or []:
        if not isinstance(r, dict):
            continue
        try:
            k = int(r.get("k"))
        except (TypeError, ValueError):
            continue
        q = by_k.get(k)
        new = r.get("level")
        if not q or new not in allowed:
            continue
        cur = q.get("level") if q.get("level") in allowed else "no_data"
        quote = r.get("quote") if isinstance(r.get("quote"), dict) else None
        if rank[new] > rank[cur] or (rank[new] < rank[cur] and quote):
            q["level"] = new
            if quote:
                q.setdefault("quotes", []).append(quote)
            q["reasoning"] = " ".join(x for x in [str(q.get("reasoning") or ""), f"Скептик: {r.get('issue') or ''}".strip()] if x)
    return analyst


def _build(spec: SessionSpec, transcript: Transcript, raw: dict, source: str, llm_info: dict | None, cost: float,
           raw_dump: dict | None) -> Verdict:
    allowed = LEVELS[spec.mode]
    answers = {u.n: u.text for u in transcript.items if u.who == "candidate" and u.n}
    asked = [u for u in transcript.items if u.who == "interviewer" and u.kind in ("opening", "question")]
    by_k = {}
    for q in raw.get("questions", []) or []:
        if isinstance(q, dict):
            try:
                by_k[int(q.get("k"))] = q
            except (TypeError, ValueError):
                continue
    out: list[QuestionVerdict] = []
    removed_total = 0
    for item in plan(spec):
        q = by_k.get(item.k, {})
        level = q.get("level") if q.get("level") in allowed else "no_data"
        quotes, removed = verify_quotes(q.get("quotes") or [], transcript)
        removed_total += removed
        reasoning = str(q.get("reasoning") or "").strip()
        answer = answers.get(item.k, "")
        lowered = False
        if not answer.strip():
            level, reasoning = "no_data", reasoning or "Собеседник на этот вопрос не ответил."
            quotes = []
        elif level != "no_data" and not quotes:
            lowered = True
            level = "partial" if level == "discrepancy" else "no_data"
            reasoning = (reasoning + " " if reasoning else "") + "Уровень снижен проверкой: цитаты, на которые опиралась оценка, в расшифровке не нашлись."
        question_text = asked[item.k - 1].text if item.k - 1 < len(asked) else ""
        out.append(QuestionVerdict(k=item.k, task_id=item.task_id, skill=item.skill, question=question_text,
                                   answer_excerpt=excerpt(answer), level=level, level_label=LEVEL_LABELS[level],
                                   quotes=quotes, reasoning=reasoning, lowered=lowered))
    n_answers = len(answers)
    chars = sum(len(" ".join(t.split())) for t in answers.values())
    verdict, score, label = verdict_from_levels(spec.mode, [q.level for q in out], n_answers, chars)
    coverage = round(100 * sum(1 for q in out if q.level != "no_data") / max(1, len(out)))
    flags = [str(f).strip() for f in (raw.get("flags") or []) if str(f).strip()][:6]
    if verdict == "insufficient" and not flags:
        flags.append(f"Мало данных: {n_answers} ответов, {chars} знаков.")
    summary = str(raw.get("summary") or "").strip() or ("Разговор слишком короткий для вывода." if verdict == "insufficient" else "")
    return Verdict(verdict=verdict, verdict_label=label, score=score, summary=summary, questions=out, flags=flags,
                   coverage=coverage, removed_quotes=removed_total, source=source, llm=llm_info, cost_usd=cost, raw=raw_dump)


def _judge(system: str, user: str, timeout_s: float, max_tokens: int):
    from app.modules.llm import client as llm

    s = get_interview_settings()
    return llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}], temperature=0.2,
                    max_tokens=max_tokens, want_json=True, model=s.interview_model_judge, timeout_s=timeout_s,
                    validate=lambda d: isinstance(d, dict))


def evaluate(spec: SessionSpec, transcript: Transcript) -> Verdict:
    answers = transcript.candidate_items()
    chars = sum(len(" ".join(u.text.split())) for u in answers)
    if is_stub():
        return _build(spec, transcript, rules_levels(spec, transcript), "stub", None, 0.0, None)
    if len(answers) < MIN_ANSWERS or chars < MIN_CHARS:
        return _build(spec, transcript, {"questions": [], "flags": [], "summary": "Разговор слишком короткий: собеседник почти ничего не ответил."},
                      "rules", None, 0.0, None)
    s = get_interview_settings()
    user = judge_input(spec, transcript)
    analyst = _judge(JUDGE_ANALYST_SYSTEM, user, s.interview_judge_timeout_s, 4000)
    if not analyst.ok or not isinstance(analyst.data, dict):
        log.warning("interview evaluate: аналитик недоступен (%s) — оценка по правилам", analyst.error)
        return _build(spec, transcript, rules_levels(spec, transcript), "rules", {"analyst": analyst.info()}, 0.0, None)
    cost = llm_cost(analyst.usage)
    skeptic = _judge(JUDGE_SKEPTIC_SYSTEM, f"{user}\n\nОЦЕНКА АНАЛИТИКА\n{analyst.text}", s.interview_judge_timeout_s, 2500)
    skeptic_data = skeptic.data if skeptic.ok and isinstance(skeptic.data, dict) else None
    cost += llm_cost(skeptic.usage) if skeptic.ok else 0.0
    merged = _apply_remarks(dict(analyst.data), skeptic_data, spec.mode)
    info = {"analyst": analyst.info(), "skeptic": skeptic.info()}
    raw = {"analyst": analyst.data, "skeptic": skeptic_data}
    return _build(spec, transcript, merged, "llm", info, round(cost, 6), raw)
