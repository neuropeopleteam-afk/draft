"""Путь без модели: вопросы из шаблонов по плану и оценка по правилам. Используется при недоступной модели и в заглушке."""
from __future__ import annotations

from .planning import plan, task_by_id
from .schemas import InterviewContext, SessionSpec, Transcript
from .textnorm import first_sentence, normalize, overlap

_OPEN = {
    "defense": "Здравствуйте, {name}! Я задам {n} по вашим письменным ответам — это займёт несколько минут и не меняет результат теста. ",
    "interview": "Здравствуйте, {name}! Я задам {n} о вашем опыте — это займёт около {m}. ",
}


def plural(n: int, one: str, few: str, many: str) -> str:
    """3 коротких вопроса / 5 коротких вопросов / 1 короткий вопрос."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"
_CLOSE = {
    "defense": "Спасибо, {name}, на этом всё. Ваши объяснения переданы работодателю как подтверждение результатов теста; сам результат теста не меняется. Хорошего дня!",
    "interview": "Спасибо, {name}, на этом всё. Итог интервью увидит работодатель, решение принимает человек. Хорошего дня!",
}
_DEFENSE_Q = (
    "В задании «{title}» вы написали про {topic}. Расскажите своими словами: как это работает и почему вы выбрали именно такой путь?",
    "Вернёмся к заданию «{title}». Почему именно так, а не иначе — какие альтернативы вы отбросили и чем они хуже?",
    "По заданию «{title}»: что пойдёт не так в крайнем случае и как вы это заметите?",
    "По заданию «{title}»: как убедиться, что решение работает — что бы вы проверили и в каком порядке?",
)
_INTERVIEW_Q = (
    "Давайте про навык «{skill}». Вспомните конкретный случай: какая была задача, что вы делали сами и чем всё закончилось?",
    "Ещё про «{skill}»: расскажите о ситуации, где было по-настоящему трудно, и как вы выкрутились.",
    "Как вы учились «{skill}» и по чему понимаете, что получается?",
)


def rules_turn(spec: SessionSpec, transcript: Transcript, kind: str, k: int | None) -> str:
    name = spec.candidate_name
    if kind == "closing":
        return _CLOSE[spec.mode].format(name=name)
    items = plan(spec)
    if kind == "repeat":
        last = next((u for u in reversed(transcript.items) if u.who == "interviewer" and u.kind in ("opening", "question")), None)
        core = last.text.split(". ", 1)[-1] if last else ""
        return f"Повторю проще. {core}".strip() if core else "Повторю: расскажите своими словами, как это работает."
    item = items[(k or 1) - 1]
    angle_idx = (item.k - 1) // max(1, len({i.task_id or i.skill for i in items}))
    if spec.mode == "defense":
        t = task_by_id(spec, item.task_id)
        topic = (t.topics[(item.k - 1) % len(t.topics)] if t and t.topics else "ваше решение")
        q = _DEFENSE_Q[angle_idx % len(_DEFENSE_Q)].format(title=item.title, topic=f"«{topic}»" if topic != "ваше решение" else topic)
    else:
        q = _INTERVIEW_Q[angle_idx % len(_INTERVIEW_Q)].format(skill=item.skill)
    prefix = ""
    if kind == "opening":
        n = plural(spec.max_questions, "короткий вопрос", "коротких вопроса", "коротких вопросов")
        m = plural(spec.duration_min, "минуты", "минут", "минут")
        prefix = _OPEN[spec.mode].format(name=name, n=n, m=m)
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
