"""analyst.req.acceptance_scenario_mcq — mcq_concept: какой сценарий приёмки противоречит бизнес-правилу.

Бизнес-правило с порогами и исключением (бесплатная доставка, автоматическое одобрение заявки, возврат
товара) и четыре сценария в стиле Gherkin («Дано / И / Когда / Тогда»). Три сценария согласуются с правилом
(в том числе на границах), один противоречит. Тип ошибки в неверном сценарии — один из: граница порога
(включительно), приоритет исключения над льготой, перепутанное «и»/«или». Ключ проверяется исполнением:
программа на Python разбирает показанные тексты сценариев регулярными выражениями и вычисляет правило.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, plural
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import balanced_options, check_lengths

FAMILY_ID = "analyst.req.acceptance_scenario_mcq"

CHECK_SRC = r'''
import re

def parse_delivery(t):
    s = int(re.search(r"сумма заказа (\d+) ₽", t).group(1))
    gold = "«Gold»" in t
    bulky = "есть крупногабаритные" in t
    claim = "бесплатная" in t.split("Тогда")[1]
    return (not bulky) and (s >= P["x"] or gold), claim

def parse_loan(t):
    age = int(re.search(r"заявителю (\d+)", t).group(1))
    inc = int(re.search(r"доход (\d+) ₽", t).group(1))
    overdue = "просрочки есть" in t
    claim = "одобрена" in t.split("Тогда")[1]
    return P["a"] <= age <= P["b"] and inc >= P["c"] and not overdue, claim

def parse_return(t):
    d = int(re.search(r"получен (\d+)", t).group(1))
    opened = "упаковка вскрыта" in t
    defect = "брак подтверждён" in t
    claim = "принят" in t.split("Тогда")[1]
    return d <= P["n"] and ((not opened) or defect), claim

PARSE = {"delivery": parse_delivery, "loan": parse_loan, "return": parse_return}
bad = [k for k, t in OPTS.items() if PARSE[KIND](t)[0] != PARSE[KIND](t)[1]]
print(bad[0] if len(bad) == 1 else "AMBIGUOUS")
'''
_ns: dict = {}
exec(CHECK_SRC.split("PARSE = ")[0], _ns)  # noqa: S102 — функции разбора те же, что в проверке


def _rule(kind, p, t):
    _ns["P"] = p
    return {"delivery": _ns["parse_delivery"], "loan": _ns["parse_loan"], "return": _ns["parse_return"]}[kind](t)


def _delivery(rng, p, mode):
    """mode: ok | boundary | precedence | andor → (текст, верный ли исход)."""
    x = p["x"]
    if mode == "boundary":
        s, gold, bulky = x, False, False
    elif mode == "precedence":
        s, gold, bulky = rng.choice([x + rng.randint(1, 20) * 100, rng.randint(5, 20) * 100]), True, True
    elif mode == "andor":
        s, gold, bulky = rng.randint(3, (x // 100) - 2) * 100, True, False
    else:
        s = rng.choice([x - 1, x - rng.randint(1, 9) * 100, x + rng.randint(1, 9) * 100, x])
        gold, bulky = rng.random() < 0.4, rng.random() < 0.3
    free = (not bulky) and (s >= x or gold)
    claim = (not free) if mode != "ok" else free
    t = (f"Дано клиент со статусом {'«Gold»' if gold else '«Обычный»'}\nИ сумма заказа {s} ₽\n"
         f"И в заказе {'есть крупногабаритные товары' if bulky else 'нет крупногабаритных товаров'}\n"
         f"Когда клиент оформляет заказ\nТогда доставка {'бесплатная' if claim else 'платная'}")
    return t


def _loan(rng, p, mode):
    a, b, c = p["a"], p["b"], p["c"]
    if mode == "boundary":
        age, inc, od = rng.choice([a, b]), c, False
    elif mode == "precedence":
        age, inc, od = rng.randint(a + 2, b - 2), c + rng.randint(5, 20) * 10000, True
    elif mode == "andor":
        age, inc, od = rng.randint(a + 2, b - 2), c - rng.randint(1, 3) * 5000, False
    else:
        age = rng.choice([a - 1, a, b, b + 1, rng.randint(a + 1, b - 1)])
        inc = rng.choice([c, c - 1000, c + rng.randint(1, 9) * 10000])
        od = rng.random() < 0.3
    ok = a <= age <= b and inc >= c and not od
    claim = (not ok) if mode != "ok" else ok
    t = (f"Дано заявителю {age} {plural(age, 'год', 'года', 'лет')}\nИ подтверждённый доход {inc} ₽ в месяц\n"
         f"И {'просрочки есть' if od else 'просрочек нет'}\nКогда заявка проходит автоматическую проверку\n"
         f"Тогда заявка {'одобрена автоматически' if claim else 'направлена на ручную проверку'}")
    return t


def _return(rng, p, mode):
    n = p["n"]
    if mode == "boundary":
        d, opened, defect = n, False, False
    elif mode == "precedence":
        d, opened, defect = rng.randint(1, n - 1), True, False
    elif mode == "andor":
        d, opened, defect = n + rng.randint(1, 5), True, True
    else:
        d = rng.choice([n, n + 1, rng.randint(1, n - 1)])
        opened, defect = rng.random() < 0.5, rng.random() < 0.4
    ok = d <= n and ((not opened) or defect)
    claim = (not ok) if mode != "ok" else ok
    t = (f"Дано товар получен {d} {plural(d, 'день', 'дня', 'дней')} назад\n"
         f"И {'упаковка вскрыта' if opened else 'упаковка не вскрыта'}\n"
         f"И {'брак подтверждён' if defect else 'брак не обнаружен'}\nКогда покупатель оформляет возврат\n"
         f"Тогда возврат {'принят' if claim else 'отклонён'}")
    return t


KINDS = {
    "delivery": (_delivery, ["интернет-магазин мебели", "магазин бытовой техники", "гипермаркет онлайн"],
                 "Доставка бесплатна, если сумма заказа не меньше {x} ₽ или у клиента статус «Gold». Если в "
                 "заказе есть крупногабаритный товар, доставка платная всегда."),
    "loan": (_loan, ["банк, потребительский кредит", "микрофинансовый сервис", "банк, кредитная карта"],
             "Заявка одобряется автоматически, если заявителю от {a} до {b} лет включительно, подтверждённый доход "
             "не меньше {c} ₽ в месяц и нет текущих просрочек. Иначе заявка направляется на ручную проверку."),
    "return": (_return, ["магазин электроники", "магазин одежды", "маркетплейс"],
               "Возврат принимается в течение {n} дней со дня получения включительно. Товар со вскрытой упаковкой "
               "принимается только при подтверждённом браке. Позже {n} дней возврат не принимается."),
}
MODES = ["boundary", "precedence", "andor"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    kind = rng.choice(sorted(KINDS))
    maker, ctxs, rule_t = KINDS[kind]
    ctx = rng.choice(ctxs)
    p = {"x": rng.choice([3000, 4000, 5000, 7000]), "a": rng.choice([21, 23, 25]), "b": rng.choice([60, 65, 70]),
         "c": rng.choice([40000, 50000, 60000]), "n": rng.choice([7, 14, 30])}
    mode = rng.choice(MODES)
    for _ in range(500):
        bad = maker(rng, p, mode)
        goods = []
        while len(goods) < 3:
            t = maker(rng, p, "ok")
            if t not in goods and t != bad:
                goods.append(t)
        try:
            check_lengths([bad] + goods, max_ratio=1.25)
        except ValueError:
            continue
        if all(_rule(kind, p, t)[0] == _rule(kind, p, t)[1] for t in goods) and \
                _rule(kind, p, bad)[0] != _rule(kind, p, bad)[1] and \
                len({t.split("Тогда")[1] for t in goods}) == 2:
            break
    else:
        raise RuntimeError("нет сценариев")
    opts, key = balanced_options(FAMILY_ID, seed, rng, ("Сценарий:", bad), [("Сценарий:", g) for g in goods])
    rule = rule_t.format(**p)
    stem = (f"Аналитик ({ctx}) согласовал бизнес-правило: «{rule}» Тестировщик написал четыре сценария приёмки. "
            f"Какой сценарий противоречит правилу?")
    opt_map = {o.id: o.code for o in opts}
    prog = f"P = {p!r}\nKIND = {kind!r}\nOPTS = {opt_map!r}\n" + CHECK_SRC
    checks = [Check(name="rule_model", runner="python", program=prog, expect="stdout_equals", expected_stdout=key)]
    why = {"boundary": "граница включительная: значение, равное порогу, удовлетворяет условию",
           "precedence": "исключение из правила действует независимо от льготы — оно сильнее",
           "andor": "условия связаны так, как написано в правиле: одного выполненного условия недостаточно "
                    "(или достаточно) — сценарий их перепутал"}[mode]
    if kind == "delivery" and mode == "andor":
        why = "статус «Gold» сам по себе даёт бесплатную доставку (условия связаны через «или»)"
    if kind == "return" and mode == "andor":
        why = "срок возврата действует и для товара с браком: после срока возврат не принимается"
    if kind == "loan" and mode == "andor":
        why = "все условия автоодобрения нужны одновременно: доход ниже порога — ручная проверка"
    ak = AnswerKey(kind="option", value=key,
                   explanation=f"Противоречит сценарий {key}: {why}. Остальные сценарии согласуются с правилом.")
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Ответ проверяется программой на Python, разбирающей тексты сценариев.",
                         params={"kind": kind, "mode": mode, **p})
