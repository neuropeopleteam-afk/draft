"""qa.runs.t21_run_timeline_output — predict_output (набор t21, порог Стажёра): накопительная сумма в цикле и место
print относительно прибавления.

Тесты прогона идут подряд; программа печатает отметки времени таймлайна, накапливая длительности. В половине
вариантов print стоит до прибавления (печатаются моменты начала), в половине — после (моменты окончания); иногда
отсчёт начинается не с нуля (подготовка окружения). Ключ — независимая накопительная сумма в генераторе; проверка —
исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.runs.t21_run_timeline_output"

CTX = ["смоук-набор перед релизом", "прогон API-тестов корзины", "UI-регресс формы оплаты",
       "интеграционные тесты уведомлений", "нагрузочный прогон поиска"]
VARS = [("durations", "d", "t"), ("timings", "sec", "clock"), ("costs", "s", "elapsed")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    lst, item, acc = rng.choice(VARS)
    n = rng.randint(3, 5)
    durs = [rng.randint(3, 40) for _ in range(n)]
    start = rng.choice([0, 0, rng.randint(5, 20)])
    before = rng.random() < 0.5
    body = ([f"    print({acc})", f"    {acc} += {item}"] if before
            else [f"    {acc} += {item}", f"    print({acc})"])
    code = "\n".join([f"{lst} = {durs}", f"{acc} = {start}", f"for {item} in {lst}:", *body,
                      f"print(\"end\", {acc})"])
    marks, t = [], start
    for d in durs:
        if before:
            marks.append(t)
            t += d
        else:
            t += d
            marks.append(t)
    out = "\n".join([*map(str, marks), f"end {t}"])
    where = ("print стоит ДО прибавления — печатается значение до текущего теста (момент его начала), первым "
             f"выводится стартовое {start}" if before else
             "print стоит ПОСЛЕ прибавления — печатается уже увеличенное значение (момент окончания теста)")
    expl = (f"Отсчёт с {start}, длительности {durs}. В цикле {where}: {', '.join(map(str, marks))}. "
            f"После цикла {acc} = {start} + {' + '.join(map(str, durs))} = {t}, печатается «end {t}». "
            "Ловушка — порядок print и +=, а также стартовое значение.")
    stem = (f"Таймлайн прогона ({ctx}): тесты идут подряд, программа печатает отметки времени в секундах, "
            "накапливая длительности тестов.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"durations": durs, "start": start, "print_before": before}, language="python")
