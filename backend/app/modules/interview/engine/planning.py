"""Пределы режимов, нормализация параметров сессии и план вопросов (детерминированный)."""
from __future__ import annotations

from .errors import EngineError
from .schemas import DefenseContext, InterviewContext, PlanItem, SessionSpec

# (минимум, максимум, по умолчанию)
LIMITS = {
    "defense": {"duration": (3, 5, 4), "questions": (2, 4, 3), "items": (1, 6), "min_answer": 120},
    "interview": {"duration": (5, 15, 10), "questions": (3, 8, 6), "items": (1, 8), "min_answer": 0},
}
JURY_MAX_MIN = 5

# Углы вопросов: по одному на заход; при повторном заходе на то же задание — следующий угол.
DEFENSE_ANGLES = (
    "почему он выбрал именно это решение",
    "какой другой вариант был и чем он хуже",
    "где это решение может сломаться",
    "как проверить, что решение работает",
)
INTERVIEW_ANGLES = (
    "один случай из работы: что за задача и что делал сам",
    "когда с этим было трудно и как справился",
    "как учился этому и как понимает, что получается",
)

INTEGRITY_LABELS = {
    "paste": "вставка готового текста", "fast_text": "текст набран быстрее, чем его можно напечатать",
    "ai_mark": "в ответе невидимая метка для ИИ", "injection": "инструкции для автоматического оценщика",
    "tab_switch": "уход со вкладки теста", "fullscreen_exit": "выход из полноэкранного режима",
}
LEVEL_LABELS = {
    "confirmed": "подтверждено", "partial": "частично", "discrepancy": "расхождение", "no_data": "нет данных",
    "strong": "сильный", "medium": "средний", "weak": "слабый",
}
VERDICT_LABELS = {
    "confirmed": "подтверждено устно", "discrepancies": "есть расхождения", "insufficient": "мало данных",
    "strong": "сильный результат", "medium": "средний результат", "weak": "слабый результат",
}


def _clamp(value: int, bounds: tuple[int, int, int]) -> int:
    lo, hi, default = bounds
    if not value:
        return default
    return max(lo, min(hi, int(value)))


def normalize_spec(spec: SessionSpec) -> SessionSpec:
    """Подрезает длительность и число вопросов, режим жюри ≤ 5 мин; отбрасывает задания без развёрнутого ответа."""
    lim = LIMITS[spec.mode]
    duration = _clamp(spec.duration_min, lim["duration"])
    if spec.jury:
        duration = min(duration, JURY_MAX_MIN)
    questions = _clamp(spec.max_questions, lim["questions"])
    name = " ".join(spec.candidate_name.split())[:60]
    if not name:
        raise EngineError("bad_request", "Нужно имя кандидата (как обращаться)")
    ctx = spec.context
    if spec.mode == "defense":
        if not isinstance(ctx, DefenseContext):
            raise EngineError("bad_request", "Для режима defense нужен контекст с заданиями")
        if not 1 <= len(ctx.tasks) <= lim["items"][1]:
            raise EngineError("bad_request", f"Заданий должно быть от 1 до {lim['items'][1]}")
        tasks = [t for t in ctx.tasks if len(t.answer.strip()) >= lim["min_answer"]]
        if not tasks:
            raise EngineError("insufficient_context",
                              f"Нет развёрнутых ответов длиной от {lim['min_answer']} знаков — защищать нечего")
        ctx = ctx.model_copy(update={"tasks": tasks})
    else:
        if not isinstance(ctx, InterviewContext):
            raise EngineError("bad_request", "Для режима interview нужен контекст с навыками")
        skills = [s for s in ctx.unconfirmed_skills if s.name.strip()]
        if not skills:
            raise EngineError("insufficient_context", "Нет непроверенных навыков — интервью не о чем")
        if len(skills) > lim["items"][1]:
            raise EngineError("bad_request", f"Навыков должно быть не больше {lim['items'][1]}")
        ctx = ctx.model_copy(update={"unconfirmed_skills": skills})
    return spec.model_copy(update={"duration_min": duration, "max_questions": questions, "candidate_name": name,
                                   "context": ctx})


def plan(spec: SessionSpec) -> list[PlanItem]:
    """Задания с признаками целостности — первыми, затем по длине ответа; нехватка заданий — новый угол на то же."""
    out: list[PlanItem] = []
    if spec.mode == "defense":
        ctx = spec.context
        assert isinstance(ctx, DefenseContext)
        ordered = sorted(ctx.tasks, key=lambda t: (0 if t.integrity_flags else 1, -len(t.answer), t.id))
        if not ordered:
            return out
        for k in range(1, spec.max_questions + 1):
            t = ordered[(k - 1) % len(ordered)]
            angle = DEFENSE_ANGLES[((k - 1) // len(ordered)) % len(DEFENSE_ANGLES)]
            out.append(PlanItem(k=k, task_id=t.id, title=t.title or t.id, angle=angle))
        return out
    ctx = spec.context
    assert isinstance(ctx, InterviewContext)
    skills = ctx.unconfirmed_skills
    if not skills:
        return out
    for k in range(1, spec.max_questions + 1):
        s = skills[(k - 1) % len(skills)]
        angle = INTERVIEW_ANGLES[((k - 1) // len(skills)) % len(INTERVIEW_ANGLES)]
        out.append(PlanItem(k=k, skill=s.name, title=s.name, angle=angle))
    return out


def task_by_id(spec: SessionSpec, task_id: str | None):
    if spec.mode != "defense" or not task_id:
        return None
    ctx = spec.context
    assert isinstance(ctx, DefenseContext)
    return next((t for t in ctx.tasks if t.id == task_id), None)
