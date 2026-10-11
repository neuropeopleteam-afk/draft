"""data_ml.strategy.principal_llm_cascade_mcq — mcq_concept (Principal): на чём обслуживать языковую модель.

Четыре стратегии обслуживания задачи на языковой модели: внешний API большой модели (плата за запрос), своя малая
модель на своих GPU (фиксированная плата за месяц), каскад «своя малая модель, неуверенные ответы — во внешний API»
и своя большая открытая модель (дороже по GPU). У каждой — качество по офлайн-оценке на размеченной выборке
(у каскада — качество малой модели на уверенной части и доля эскалации). Даны поток запросов в месяц, цена одной
ошибки для бизнеса (разбор обращения, компенсация) и нижняя граница качества от владельца продукта. Вопрос —
какая допустимая стратегия даёт минимальную полную цену в месяц (инфраструктура + ожидаемая цена ошибок).

Ловушки: «самая дешёвая инфраструктура», «самое высокое качество», выбор без нижней границы качества, без цены
ошибок. Цель (ответ) выбирается по seed до подбора чисел — ключ равновероятен среди четырёх стратегий; генератор
подбирает числа так, что ответ отличается хотя бы от двух ловушек и минимум отделён от второго места ≥ 4 %.
Ключ проверяется исполнением: программа раскладывает поток по маршрутам (доля, цена запроса, точность),
считает качество и полную цену каждой стратегии, отбрасывает недопустимые и печатает букву минимума.
"""
from __future__ import annotations

from assessment_bank.families._principal_b_kit import argmin_sep, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.strategy.principal_llm_cascade_mcq"

CONTEXTS = ["ответы на обращения клиентов в поддержку", "разбор входящих документов (классификация и поля)",
            "проверку объявлений перед публикацией", "подсказки операторам колл-центра",
            "разметку отзывов по темам", "сопоставление резюме с требованиями вакансии"]

NAMES = {"api": "внешний API большой модели",
         "small": "своя малая модель на своих GPU",
         "cascade": "каскад: своя малая модель, неуверенные ответы — во внешний API",
         "selfbig": "своя большая открытая модель на своих GPU"}
ORDER = ["api", "small", "cascade", "selfbig"]

PROGRAM = """opts = __OPTS__
R, L, qmin = {R}, {L}, {qmin}          # млн запросов в месяц, ₽ за ошибку, нижняя граница качества
# стратегия -> (фиксированная плата млн ₽ в месяц, маршруты [(доля потока, ₽ за запрос, точность)])
plans = {plans!r}
best, best_cost = None, None
for name, (fixed, routes) in plans.items():
    quality = sum(share * acc for share, _price, acc in routes)
    if quality < qmin - 1e-12:
        continue
    per_request = sum(share * (price + (1 - acc) * L) for share, price, acc in routes)
    cost = fixed + R * per_request      # млн запросов × ₽ = млн ₽
    if best_cost is None or cost < best_cost - 1e-9:
        best, best_cost = name, cost
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _plans(p):
    e, qc = p["esc"], p["q_conf"]
    return {
        "api": (0.0, [(1.0, p["c_api"], p["q_api"])]),
        "small": (p["f_small"], [(1.0, 0.0, p["q_small"])]),
        "cascade": (p["f_small"], [(1 - e, 0.0, qc), (e, p["c_api"], p["q_api"])]),
        "selfbig": (p["f_big"], [(1.0, 0.0, p["q_big"])]),
    }


def _eval(p, *, floor=True, errors=True):
    out, qual = {}, {}
    for k, (fixed, routes) in _plans(p).items():
        q = sum(s * a for s, _c, a in routes)
        qual[k] = q
        if floor and q < p["qmin"] - 1e-12:
            continue
        per = sum(s * (c + ((1 - a) * p["L"] if errors else 0.0)) for s, c, a in routes)
        out[k] = fixed + p["R"] * per
    return out, qual


def _sample(rng):
    return {"R": rng.choice([1, 2, 4, 8, 15, 30]), "L": rng.choice([3, 5, 10, 20, 40, 80]),
            "c_api": rng.choice([0.6, 1.0, 1.5, 2.5]), "q_api": rng.choice([0.95, 0.96, 0.97]),
            "f_small": rng.choice([1.2, 2.0, 3.0]), "q_small": rng.choice([0.84, 0.87, 0.9]),
            "esc": rng.choice([0.15, 0.2, 0.3, 0.4]), "q_conf": rng.choice([0.92, 0.94, 0.96]),
            "f_big": rng.choice([4.0, 6.0, 9.0, 12.0]), "q_big": rng.choice([0.9, 0.92, 0.93]),
            "qmin": rng.choice([0.85, 0.87, 0.89, 0.91, 0.93])}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)

    def accept(p):
        full, qual = _eval(p)
        if len(full) < 3 or any(abs(q - p["qmin"]) < 0.004 for q in qual.values()):
            return None
        good = argmin_sep(full)
        if good != target:
            return None
        infra = {k: v[0] + p["R"] * sum(s * c for s, c, _a in v[1]) for k, v in _plans(p).items()}
        cheap = min(infra, key=infra.get)
        best_q = max(qual, key=qual.get)
        no_floor = argmin_sep(_eval(p, floor=False)[0])
        no_err = argmin_sep(_eval(p, errors=False)[0])
        if None in (no_floor, no_err):
            return None
        traps = {"cheap": cheap, "best_q": best_q, "no_floor": no_floor, "no_err": no_err}
        if sum(1 for v in traps.values() if v != good) < (1 if good == "small" else 2):
            return None
        return good, full, qual, infra, traps

    p, (good, full, qual, infra, traps) = search(rng, _sample, accept)
    pc = lambda x: fmt_num(100 * x, 1 if abs(100 * x - round(100 * x)) > 1e-9 else 0)
    rub = lambda x: fmt_num(x, 1 if abs(x - round(x)) > 1e-9 else 0)
    rows = [
        f"• {_cap(NAMES['api'])}: {fmt_num(p['c_api'], 1)} ₽ за запрос, качество {pc(p['q_api'])} %.",
        f"• {_cap(NAMES['small'])}: GPU {rub(p['f_small'])} млн ₽ в месяц (хватает на весь поток), "
        f"качество {pc(p['q_small'])} %.",
        f"• Каскад: та же малая модель отвечает на все запросы; {pc(p['esc'])} % ответов, где она не уверена, "
        f"повторно отправляются во внешний API (его ответ и идёт пользователю). На уверенной части качество малой "
        f"модели {pc(p['q_conf'])} %.",
        f"• {_cap(NAMES['selfbig'])}: GPU {rub(p['f_big'])} млн ₽ в месяц, качество {pc(p['q_big'])} %.",
    ]
    stem = (f"Вы отвечаете за техническую стратегию ML и выбираете, на чём обслуживать {ctx}: "
            f"{fmt_num(p['R'], 0)} млн запросов в месяц. Каждая ошибка модели обходится бизнесу ≈ {fmt_num(p['L'], 0)} ₽ "
            f"(ручной разбор, компенсация). Владелец продукта требует качество не ниже {pc(p['qmin'])} % (доля верных "
            f"ответов на всём потоке). Офлайн-оценка на размеченной выборке:\n" + "\n".join(rows) +
            "\n\nКакая допустимая стратегия даёт минимальную полную цену в месяц (инфраструктура плюс ожидаемая цена "
            "ошибок)?")
    allowed = "; ".join(f"{NAMES[k]} — качество {fmt_num(100 * qual[k], 1)} %, {fmt_num(full[k], 2)} млн ₽"
                        for k in ORDER if k in full)
    banned = [f"{NAMES[k]} ({fmt_num(100 * qual[k], 1)} %)" for k in ORDER if k not in full]
    expl = (f"Полная цена = плата за GPU + {fmt_num(p['R'], 0)} млн × (цена запроса + доля ошибок × "
            f"{fmt_num(p['L'], 0)} ₽). Качество каскада = (1 − {fmt_num(p['esc'], 2)}) × {fmt_num(p['q_conf'], 2)} + "
            f"{fmt_num(p['esc'], 2)} × {fmt_num(p['q_api'], 2)}; эскалированные запросы оплачиваются в API дополнительно "
            f"к GPU малой модели. Допустимые: {allowed}" + (f"; ниже границы: {', '.join(banned)}" if banned else "") +
            f". Минимум — {NAMES[good]}. Ловушки: самая дешёвая инфраструктура — {NAMES[traps['cheap']]}; самое высокое "
            f"качество — {NAMES[traps['best_q']]}; без нижней границы качества — {NAMES[traps['no_floor']]}; без цены "
            f"ошибок — {NAMES[traps['no_err']]}.")
    program = PROGRAM.format(R=p["R"], L=p["L"], qmin=p["qmin"],
                             plans={NAMES[k]: v for k, v in _plans(p).items()})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={**p, "good": good, **{f"trap_{k}": v for k, v in traps.items()}},
                       note="Ответ проверяется программой: поток разложен по маршрутам (доля, цена запроса, точность), "
                            "недопустимые по качеству стратегии отброшены.")
