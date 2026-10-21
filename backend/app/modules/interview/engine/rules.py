"""Путь без модели: вопросы из шаблонов по плану и оценка по правилам. Используется при недоступной модели и в заглушке."""
from __future__ import annotations

from .planning import plan, task_by_id
from .schemas import InterviewContext, SessionSpec, Transcript
from .textnorm import first_sentence, normalize, overlap, short_fragment, short_title, word_count

# Ведущая — женский образ «ИИ-интервьюер Драфта»: приветствие и представление — одна фраза, вопросы — до 25 слов.
_OPEN = {
    "defense": "Здравствуйте, {name}, я — ИИ-интервьюер {product} Настя, финальный этап теста: задам {n} по вашим ответам. ",
    "interview": "Здравствуйте, {name}, я — ИИ-интервьюер {product}, задам {n} о вашем опыте, это около {m}. ",
}
_OPEN_GENERIC = {
    "defense": "Здравствуйте, я — ИИ-интервьюер {product} Настя, финальный этап теста: задам {n} по вашим ответам. ",
    "interview": "Здравствуйте, я — ИИ-интервьюер {product}, задам {n} о вашем опыте, это около {m}. ",
}
MAX_QUESTION_WORDS = 25


def is_generic_name(name: str | None) -> bool:
    return (name or "").strip().lower() in ("", "кандидат", "собеседник", "гость", "участник", "эксперт")


def plural(n: int, one: str, few: str, many: str) -> str:
    """3 коротких вопроса / 5 коротких вопросов / 1 короткий вопрос."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"
_CLOSE = {
    "defense": "Спасибо, {name}, я всё записала. Объяснения увидит работодатель, результат теста не меняется. Хорошего дня.",
    "interview": "Спасибо, {name}, я всё записала. Итог увидит работодатель, решение принимает человек. Хорошего дня.",
}
_CLOSE_GENERIC = {
    "defense": "Спасибо, я всё записала. Объяснения увидит работодатель, результат теста не меняется. Хорошего дня.",
    "interview": "Спасибо, я всё записала. Итог увидит работодатель, решение принимает человек. Хорошего дня.",
}
# {lead} — «В задании «…» вы написали: «первые слова ответа».» (короткий фрагмент, не цитата целиком)
_FIRST_ASK = ("Почему вы решили именно так?", "Почему именно так, а не иначе?", "Как вы проверите, что это работает?")
_DEFENSE_Q = (
    "{lead} {ask}",
    "Вернёмся к заданию «{title}». Какой другой вариант вы видели и чем он хуже?",
    "В задании «{title}»: где ваше решение может сломаться?",
    "В задании «{title}»: как вы проверите, что решение работает?",
)
_INTERVIEW_Q = (
    "Про «{skill}»: вспомните один случай из работы. Что за задача, что делали вы сами?",
    "Ещё про «{skill}»: когда было трудно и как вы справились?",
    "Как вы учились «{skill}» и как понимаете, что получается?",
)


def _lead(title: str, answer: str) -> str:
    frag = short_fragment(answer, 7)
    return f"В задании «{title}» вы написали: «{frag}»." if frag else f"Вернёмся к вашему ответу в задании «{title}»."


def rules_turn(spec: SessionSpec, transcript: Transcript, kind: str, k: int | None, product: str = "Драфт") -> str:
    from .prompts import genitive

    name = spec.candidate_name
    generic = is_generic_name(name)
    if kind == "closing":
        return _CLOSE_GENERIC[spec.mode] if generic else _CLOSE[spec.mode].format(name=name)
    items = plan(spec)
    if kind == "repeat":
        last = next((u for u in reversed(transcript.items) if u.who == "interviewer" and u.kind in ("opening", "question")), None)
        if last is not None and last.k and 1 <= last.k <= len(items):
            return "Повторю проще. " + rules_turn(spec, transcript, "question", last.k, product)
        return "Повторю проще: расскажите своими словами, как это работает."
    item = items[(k or 1) - 1]
    angle_idx = (item.k - 1) // max(1, len({i.task_id or i.skill for i in items}))
    if spec.mode == "defense":
        t = task_by_id(spec, item.task_id)
        title = short_title(item.title)
        ask = _FIRST_ASK[(item.k - 1) % len(_FIRST_ASK)]
        q = _DEFENSE_Q[angle_idx % len(_DEFENSE_Q)].format(title=title, lead=_lead(title, t.answer if t else ""), ask=ask)
        if word_count(q) > MAX_QUESTION_WORDS:  # длинное название или фрагмент — без фрагмента
            q = _DEFENSE_Q[angle_idx % len(_DEFENSE_Q)].format(title=title, ask=ask,
                                                               lead=f"Вернёмся к вашему ответу в задании «{title}».")
    else:
        q = _INTERVIEW_Q[angle_idx % len(_INTERVIEW_Q)].format(skill=item.skill)
    prefix = ""
    if kind == "opening":
        n = plural(spec.max_questions, "короткий вопрос", "коротких вопроса", "коротких вопросов")
        m = plural(spec.duration_min, "минуты", "минут", "минут")
        tpl = _OPEN_GENERIC[spec.mode] if generic else _OPEN[spec.mode]
        prefix = tpl.format(name=name, n=n, m=m, product=genitive(product))
    return prefix + q


VAGUE = ("в целом главное", "наверное", "подробно не скажу", "как то", "какой то", "обычно помогает", "так принято")


def rules_levels(spec: SessionSpec, transcript: Transcript) -> dict:
    """Сырая оценка в формате аналитика: уровень по длине ответа и пересечению значимых слов с письменным ответом."""
    answers = {u.n: u.text for u in transcript.items if u.who == "candidate" and u.n}
    asked = [u for u in transcript.items if u.who == "interviewer" and u.kind in ("opening", "question")]
    questions, flags = [], []
    for item in plan(spec):
        n = item.k
        text = answers.get(n, "")
        length = len(normalize(text))
        quote = first_sentence(text)
        if spec.mode == "defense":
            t = task_by_id(spec, item.task_id)
            share = overlap(text, t.answer if t else "")
            low = normalize(text)
            if length < 40:
                level, why = "no_data", "Ответа нет или он слишком короткий."
            elif length < 200 and any(w in low for w in ("не помню", "не знаю", "затрудняюсь", "не писал", "не мой")):
                level, why = "discrepancy", "Собеседник говорит, что не помнит или не знает содержание собственного ответа."
            elif share >= 0.6 and length < 200:
                level, why = "partial", f"Почти дословный пересказ письменного ответа без объяснения (пересечение {round(share * 100)} %)."
            elif any(w in low for w in VAGUE):
                level, why = "partial", "Общие слова без причин и деталей."
            elif length >= 120 and share >= 0.2:
                level, why = "confirmed", f"Объяснение развёрнутое ({length} знаков), пересечение значимых слов с письменным ответом {round(share * 100)} %."
            else:
                level, why = "partial", f"Объяснение короткое или мало связано с письменным ответом (пересечение {round(share * 100)} %)."
        else:
            low = normalize(text)
            if length < 40:
                level, why = "no_data", "Ответа нет или он слишком короткий."
            elif length >= 200 and any(w in low for w in ("в итоге", "результат", "получилось", "сделал", "сделала", "запустил", "запустила")):
                level, why = "strong", "Есть конкретный случай с действиями и результатом."
            elif length >= 80:
                level, why = "medium", "Пример есть, но без результата или с размытым личным вкладом."
            else:
                level, why = "weak", "Общие слова без примера."
        questions.append({"k": n, "level": level, "quotes": [{"n": n, "text": quote}] if len(quote) >= 8 and level != "no_data" else [],
                          "reasoning": why})
        if level == "discrepancy":
            flags.append(f"Вопрос {n}: собеседник не смог объяснить собственный письменный ответ («{quote[:120]}»).")
    del asked
    summary = ("Оценка по правилам (модель недоступна или выключена): уровни выставлены по длине ответов и пересечению значимых слов "
               "с письменными ответами.") if spec.mode == "defense" else "Оценка по правилам (модель недоступна или выключена): по длине и конкретности ответов."
    if isinstance(spec.context, InterviewContext) and not spec.context.unconfirmed_skills:
        summary = "Нет навыков для оценки."
    return {"questions": questions, "flags": flags, "summary": summary, "confidence": 40}
