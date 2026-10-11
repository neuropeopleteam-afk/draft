"""analyst.principal.pilot_value_mcq — mcq_concept (Principal, короткое): запускать инициативу сразу, сначала
провести пилот (малый или большой) или закрыть её — по ожидаемой ценности с учётом неточности пилота.

Инициатива успешна с вероятностью p: успех приносит V, неудача — потери C (млн ₽). Пилот стоит K и сдвигает
запуск (потеря D); пилот показывает «успех» на успешной инициативе с вероятностью se и на неуспешной — с
вероятностью 1 − sp; запуск — только при «успехе» пилота. Ожидаемая ценность:
«сразу» p·V − (1 − p)·C; «закрыть» 0; «пилот» −K − D + p·se·V − (1 − p)(1 − sp)·C.

Варианты — четыре решения; верное — с наибольшей ожидаемой ценностью (отрыв от второго не меньше 5 % от
масштаба V). Какое решение верное, задаётся по seed поровну (числа подбираются под него). Ключ проверяется
исполнением: программа раскладывает исходы по дереву решений точными дробями и печатает лучшее.
"""
from __future__ import annotations

from assessment_bank.families._principal_c_utils import choice_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "analyst.principal.pilot_value_mcq"

CONTEXTS = [("банк", "кредитная карта для самозанятых"), ("ритейлер", "доставка из магазина за час"),
            ("страховая компания", "страхование по подписке"), ("телеком-оператор", "семейный тариф с общим пакетом"),
            ("онлайн-школа", "курс с наставником"), ("маркетплейс", "рассрочка для покупателей"),
            ("сервис такси", "подписка на поездки"), ("авиакомпания", "абонемент на перелёты")]

DECISIONS = ["запустить сразу на всех клиентов", "не запускать, закрыть инициативу",
             "малый пилот, при успехе — запуск", "большой пилот, при успехе — запуск"]

PROGRAM = """from fractions import Fraction as F

DECISIONS = {decisions!r}
p, V, C = F({p}, 100), {V}, {C}                  # вероятность успеха; выигрыш и потери, млн ₽
PILOTS = {{2: (F({se1}, 100), F({sp1}, 100), {K1}, {D1}),   # чувствительность, специфичность, цена, потеря от сдвига
          3: (F({se2}, 100), F({sp2}, 100), {K2}, {D2})}}
def value(decision):
    if decision == 0:
        return p * V - (1 - p) * C
    if decision == 1:
        return F(0)
    se, sp, K, D = PILOTS[decision]
    ev = -K - D
    for success, prob in ((True, p), (False, 1 - p)):
        says_go = se if success else 1 - sp       # пилот показал «успех» — запускаем
        ev += prob * says_go * (V if success else -C)
    return ev
vals = [value(i) for i in range(4)]
print(DECISIONS[vals.index(max(vals))])
"""


def _mln(x):
    return f"{x:.1f}".replace(".", ",").replace("-", "−")


def _values(p, V, C, piles):
    P = p / 100
    out = [P * V - (1 - P) * C, 0.0]
    for se, sp, K, D in piles:
        out.append(-K - D + P * se / 100 * V - (1 - P) * (1 - sp / 100) * C)
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    org, idea = rng.choice(CONTEXTS)
    target = rng.choice([0, 1, 2, 3])
    for _ in range(20000):
        p = rng.choice([20, 30, 40, 50, 60, 70, 80])
        V = rng.choice([100, 150, 200, 300, 400])
        C = rng.choice([50, 80, 100, 150, 200, 300])
        se1, sp1 = rng.choice([70, 75, 80]), rng.choice([60, 70, 75])
        se2, sp2 = rng.choice([90, 95]), rng.choice([85, 90, 95])
        K1, D1 = rng.choice([2, 4, 6, 8]), rng.choice([2, 5, 10])
        K2, D2 = K1 + rng.choice([4, 8, 12, 20]), D1 + rng.choice([5, 10, 15, 25])
        vals = _values(p, V, C, [(se1, sp1, K1, D1), (se2, sp2, K2, D2)])
        order = sorted(range(4), key=lambda i: -vals[i])
        if order[0] == target and vals[order[0]] - vals[order[1]] >= 0.05 * V:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    code = "\n".join([f"Вероятность, что инициатива успешна (оценка по похожим запускам): {p} %",
                      f"Успех: +{V} млн ₽; неудача: −{C} млн ₽ (разработка, маркетинг, отток)",
                      f"Малый пилот: {K1} млн ₽, сдвиг запуска стоит {D1} млн ₽; на успешной инициативе показывает "
                      f"«успех» в {se1} % случаев, на неуспешной — «неудачу» в {sp1} %",
                      f"Большой пилот: {K2} млн ₽, сдвиг запуска стоит {D2} млн ₽; на успешной — «успех» в {se2} %, "
                      f"на неуспешной — «неудачу» в {sp2} %",
                      "После пилота запускают только при «успехе»."])
    stem = (f"{org[0].upper() + org[1:]}: комитет решает судьбу инициативы «{idea}». Какое решение даёт наибольшую "
            f"ожидаемую ценность?")
    best = order[0]
    v_txt = "; ".join(f"«{DECISIONS[i]}» — {_mln(vals[i])} млн ₽" for i in range(4))
    why = (f"Ожидаемая ценность по дереву решений: {v_txt}. Лучшее — «{DECISIONS[best]}». Пилот ценен, только "
           f"если его точность меняет решение настолько, что окупает цену и сдвиг; без пилота выбор — между "
           f"p·V − (1 − p)·C и нулём. Вывод: ценность информации считается по дереву решений с учётом неточности "
           f"пилота, а не по принципу «пилот всегда безопаснее».")
    program = PROGRAM.format(decisions=DECISIONS, p=p, V=V, C=C, se1=se1, sp1=sp1, K1=K1, D1=D1,
                             se2=se2, sp2=sp2, K2=K2, D2=D2)
    return choice_mcq(FAMILY_ID, seed, rng, ctx=org, stem=stem, correct=DECISIONS[best],
                      distractors=[DECISIONS[i] for i in order[1:]], program=program, why=why, code=code,
                      params={"p": p, "V": V, "C": C, "pilot_small": [se1, sp1, K1, D1],
                              "pilot_big": [se2, sp2, K2, D2], "target": target},
                      note="Программа раскладывает исходы по дереву решений точными дробями и печатает лучшее.")
