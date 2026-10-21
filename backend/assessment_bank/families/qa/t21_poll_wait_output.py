"""qa.ui.t21_poll_wait_output — predict_output (набор t21, порог Стажёра): цикл while со счётчиком — опрос до
таймаута.

Явное ожидание в UI-тесте: программа «опрашивает» элемент с фиксированным интервалом, пока накопленное время меньше
таймаута (`<`) или не больше его (`<=`), и печатает число опросов и итоговое время. Ловушки: последний шаг выходит за
таймаут (перелёт), а при `<=` и таймауте, кратном интервалу, делается ещё один опрос. Ключ — независимая модель
(ceil / деление) в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "qa.ui.t21_poll_wait_output"

CTX = [("кнопка «Оплатить»", "timeout", "interval"), ("спиннер загрузки отчёта", "limit", "step"),
       ("toast-уведомление об ошибке", "max_wait", "poll"), ("строка в таблице заказов", "deadline", "tick")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, tv, iv = rng.choice(CTX)
    step = rng.choice([2, 3, 4, 5, 6])
    op = rng.choice(["<", "<="])
    k = rng.randint(2, 5)
    exact = rng.random() < 0.5
    timeout = step * k if exact else step * k + rng.randint(1, step - 1)
    acc = rng.choice(["waited", "elapsed", "spent"])
    code = (f"{tv} = {timeout}\n"
            f"{iv} = {step}\n"
            f"{acc} = 0\n"
            f"polls = 0\n"
            f"while {acc} {op} {tv}:\n"
            f"    {acc} += {iv}\n"
            f"    polls += 1\n"
            f"print(polls, {acc})")
    # модель: наименьшее кратное шага, при котором условие ложно
    if op == "<":
        polls = -(-timeout // step)            # ceil(timeout / step)
    else:
        polls = timeout // step + 1
    waited = polls * step
    out = f"{polls} {waited}"
    why = (f"Цикл идёт, пока {acc} {op} {timeout}; значения после шагов: "
           + ", ".join(str(step * i) for i in range(1, polls + 1)))
    extra = (f" При «<=» значение {timeout} ещё проходит проверку, поэтому делается лишний опрос."
             if op == "<=" and exact else "")
    expl = (f"{why}. На {waited} условие {waited} {op} {timeout} ложно — выход: {polls} {plural(polls, 'опрос', 'опроса', 'опросов')}, {acc} = "
            f"{waited} (больше таймаута {timeout}).{extra} Ловушка — проверка условия перед каждым шагом и перелёт "
            "за таймаут.")
    stem = (f"Явное ожидание в UI-тесте: тест ждёт, пока появится {ctx}, опрашивая страницу через равные "
            "промежутки времени (в секундах); элемент так и не появился.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"timeout": timeout, "step": step, "op": op}, language="python")
