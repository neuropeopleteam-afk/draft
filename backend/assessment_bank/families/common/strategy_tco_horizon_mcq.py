"""common.strategy.tco_horizon_mcq — mcq_concept (Principal): какой вариант дешевле на горизонте с ростом нагрузки.

Четыре варианта платформы для одной задачи (внешний сервис по подписке, управляемый сервис в облаке,
своя установка открытого решения, собственная разработка): разовые затраты, ежемесячные затраты на людей
(доля ставки × стоимость инженера) и цена за единицу нагрузки; нагрузка растёт на g % в месяц, горизонт H
месяцев. Вопрос — какой вариант даёт минимальную полную стоимость владения за горизонт.

Верный вариант (управляемый сервис, своя установка или собственная разработка — выбирается равновероятно)
подбирается так, что упрощения ведут к другому ответу: «дешевле на старте» (разовые + первый месяц) — всегда,
и хотя бы одно из двух — без роста нагрузки (нагрузка первого месяца весь горизонт) или без затрат на людей.
Варианты ответа — четыре названия платформ.
Ключ проверяется исполнением: программа помесячно проигрывает горизонт (иной путь, чем сумма
геометрической прогрессии в генераторе) и печатает букву варианта с минимальной суммой.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "common.strategy.tco_horizon_mcq"

CONTEXTS = [("полнотекстовый поиск", "млн запросов"), ("отправка уведомлений", "млн сообщений"),
            ("хранение и выдача файлов", "ТБ·мес"), ("распознавание документов", "тыс. страниц"),
            ("очередь событий", "млрд событий"), ("видеозвонки", "тыс. минут")]

NAMES = {"saas": "внешний сервис по подписке", "managed": "управляемый сервис в облаке",
         "self": "своя установка открытого решения", "build": "собственная разработка"}

PROGRAM = """opts = __OPTS__
plans = {plans!r}
H, g, load0 = {H}, {g}, {load0}
total = {{}}
for name, (upfront, people, unit) in plans.items():
    s, load = upfront, load0
    for month in range(H):
        s += people + unit * load
        load *= 1 + g
    total[name] = s
best = min(total, key=total.get)
hit = [k for k, t in opts.items() if t.startswith(best)]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _totals(plans, H, g, load0):
    geo = ((1 + g) ** H - 1) / g if g else H
    full = {k: u + H * p + c * load0 * geo for k, (u, p, c) in plans.items()}
    first = {k: u + p + c * load0 for k, (u, p, c) in plans.items()}
    flat = {k: u + H * p + c * load0 * H for k, (u, p, c) in plans.items()}
    nopeople = {k: u + c * load0 * geo for k, (u, p, c) in plans.items()}
    return full, first, flat, nopeople


def _argmin_clear(d, rel=0.03):
    s = sorted(d.values())
    return min(d, key=d.get) if s[1] - s[0] >= rel * s[1] else None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, unit_name = rng.choice(CONTEXTS)
    eng = rng.choice([400, 500, 600])            # тыс. ₽ в месяц за инженера с налогами
    target = rng.choice(["managed", "self", "build"])
    for _ in range(20000):
        H = rng.choice([12, 24, 36, 48, 60])
        g = rng.choice([0.02, 0.03, 0.05, 0.08, 0.1])
        load0 = rng.choice([5, 10, 20, 40, 80])
        plans = {
            "saas": (0, round(eng * rng.choice([0.1, 0.2])), rng.choice([40, 60, 80, 120])),
            "managed": (rng.choice([300, 600, 900]), round(eng * rng.choice([0.3, 0.5])), rng.choice([20, 30, 45])),
            "self": (rng.choice([1500, 2500, 4000]), round(eng * rng.choice([1.0, 1.5])), rng.choice([6, 10, 15])),
            "build": (rng.choice([6000, 9000, 12000]), round(eng * rng.choice([1.5, 2.0, 3.0])), rng.choice([2, 4, 6])),
        }
        full, first, flat, nopeople = _totals(plans, H, g, load0)
        picks = [_argmin_clear(d) for d in (full, first, flat, nopeople)]
        if None in picks or picks[0] != target or picks[1] == target:
            continue
        if picks[2] != target or picks[3] != target:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    good, w_first, w_flat, w_nop = picks
    letter_rows = []
    order = ["saas", "managed", "self", "build"]
    for k in order:
        u, p, c = plans[k]
        letter_rows.append(f"• {NAMES[k].capitalize()}: разово {fmt_num(u, 0)} тыс. ₽, люди {fmt_num(p, 0)} тыс. ₽ в месяц, "
                           f"{fmt_num(c, 0)} тыс. ₽ за 1 {unit_name} в месяц.")
    stem = (f"Вы — главный инженер. Выбираете платформу для задачи «{ctx}» на {H} месяцев. Сейчас нагрузка — "
            f"{load0} {unit_name} в месяц, по плану продукта растёт на {fmt_num(100 * g, 0)} % в месяц (сложный "
            f"процент). Стоимость инженера — {eng} тыс. ₽ в месяц. Варианты:\n" + "\n".join(letter_rows) +
            f"\n\nКакой вариант даёт минимальную полную стоимость владения за {H} месяцев (разовые затраты, люди и "
            "инфраструктура)?")
    txt = {k: f"{NAMES[k].capitalize()} — {fmt_num(full[k] / 1000, 1)} млн ₽ за горизонт" for k in order}
    # подпись варианта ответа — название; в программе ключ ищется по началу строки (название варианта)
    opt_text = {k: NAMES[k] for k in order}
    plans_named = {NAMES[k]: plans[k] for k in order}
    program = PROGRAM.format(plans=plans_named, H=H, g=g, load0=load0)
    traps = [f"«дешевле на старте» — {NAMES[w_first]}"]
    traps += [f"без роста нагрузки — {NAMES[w_flat]}"] if w_flat != good else []
    traps += [f"без затрат на людей — {NAMES[w_nop]}"] if w_nop != good else []
    expl = (f"Полная стоимость: разовые + {H} × люди + цена × нагрузка × ((1 + g)^H − 1) / g. Итоги: "
            + "; ".join(txt[k] for k in order) + f". Минимум — {NAMES[good]}. Упрощения ведут к другим ответам: "
            + ", ".join(traps) + ".")
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=opt_text[good],
                       distractors=[opt_text[k] for k in order if k != good], program=program,
                       explanation=expl,
                       params={"H": H, "g": g, "load0": load0, "eng": eng, "good": good, "first": w_first,
                               "flat": w_flat, "no_people": w_nop},
                       note="Ответ проверяется программой: помесячный проигрыш горизонта по всем вариантам.")
