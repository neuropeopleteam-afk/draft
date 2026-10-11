"""analyst.req.decision_table_mcq — mcq_concept: пропуск или противоречие в таблице решений.

Таблица решений из трёх условий («Да» / «Нет» / «—» — любое значение) и 4–6 правил с действиями. Подтипы
вопроса: (gap) какая комбинация условий не покрыта ни одним правилом; (conflict) для какой комбинации два
правила предписывают разные действия. Таблица строится как полное дерево решений (каждая комбинация
покрыта ровно одним правилом), затем одно правило сужается (пропуск) или добавляется пересекающееся правило
(противоречие) — ровно одна такая комбинация. Дистракторы — покрытые комбинации, в том числе через «—».
Ключ проверяется исполнением: программа на Python разбирает показанную таблицу и перебирает 8 комбинаций.
"""
from __future__ import annotations

import itertools

from assessment_bank.gen_utils import build_variant, make_rng, text_table
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import balanced_options, py_literal_block

FAMILY_ID = "analyst.req.decision_table_mcq"

CTX = [("скидка в интернет-магазине", ["клиент в программе лояльности", "сумма заказа от 5000 ₽", "введён промокод"],
        ["скидка 5 %", "скидка 10 %", "без скидки", "скидка 15 %"]),
       ("маршрутизация обращения в поддержку", ["клиент — юрлицо", "обращение о платеже", "приоритет высокий"],
        ["первая линия", "финансовый отдел", "менеджер клиента", "дежурный инженер"]),
       ("выдача кредитной карты", ["есть зарплатный проект", "кредитная история хорошая", "доход подтверждён"],
        ["одобрить", "отказать", "ручная проверка", "одобрить с меньшим лимитом"]),
       ("страховой тариф для поездки", ["поездка дольше 30 дней", "активный отдых", "возраст старше 65 лет"],
        ["базовый", "расширенный", "спортивный", "индивидуальный расчёт"]),
       ("доставка заказа", ["товар в наличии на складе", "адрес в черте города", "заказ оплачен онлайн"],
        ["доставка завтра", "доставка через 3 дня", "самовывоз", "под заказ"])]

CHECK_SRC = r'''
import itertools
lines = [l for l in TABLE.strip().splitlines()]
rows = [[c.strip() for c in l.split("|")] for l in lines[2:]]
conds, act = rows[:-1], rows[-1]
rules = []
for j in range(1, len(act)):
    rules.append(([r[j] for r in conds], act[j]))
def match(rule, combo):
    return all(v == "—" or (v == "Да") == c for v, c in zip(rule, combo))
def label(combo):
    return "; ".join(f"{n} — {'да' if c else 'нет'}" for n, c in zip(NAMES, combo))
bad = []
for combo in itertools.product([True, False], repeat=len(conds)):
    acts = {a for r, a in rules if match(r, combo)}
    if (MODE == "gap" and not acts) or (MODE == "conflict" and len(acts) > 1):
        bad.append(label(combo))
hit = [k for k, v in OPTS.items() if v in bad]
print(hit[0] if len(hit) == 1 and len(bad) == 1 else "AMBIGUOUS")
'''


def _tree(rng, depth_left, prefix, avail):
    """Дерево решений → правила [(значения по условиям: True/False/None), действие]."""
    if not avail or (depth_left < 3 and rng.random() < 0.35):
        return [(dict(prefix), None)]
    c = rng.choice(avail)
    out = []
    for val in (True, False):
        out += _tree(rng, depth_left - 1, {**prefix, c: val}, [a for a in avail if a != c])
    return out


def _covers(rule, combo):
    return all(rule.get(i) is None or rule[i] == combo[i] for i in range(3))


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, names, actions = rng.choice(CTX)
    mode = rng.choice(["gap", "conflict"])
    combos = list(itertools.product([True, False], repeat=3))
    for _ in range(2000):
        leaves = _tree(rng, 3, {}, [0, 1, 2])
        if not 4 <= len(leaves) <= 6:
            continue
        rules = [(r, rng.choice(actions)) for r, _ in leaves]
        if len({a for _, a in rules}) < 3:
            continue
        if mode == "gap":
            cand = [i for i, (r, _) in enumerate(rules) if len(r) == 3]
            if not cand:
                cand2 = [i for i, (r, _) in enumerate(rules) if len(r) == 2]
                if not cand2:
                    continue
                i = rng.choice(cand2)
                free = [k for k in range(3) if k not in rules[i][0]][0]
                rules[i] = ({**rules[i][0], free: rng.choice([True, False])}, rules[i][1])
            else:
                i = rng.choice(cand)
                rules.pop(i)
        else:
            combo = rng.choice(combos)
            owner_rule, owner = [(r, a) for r, a in rules if _covers(r, combo)][0]
            if len(owner_rule) == 3:
                continue  # противоречие — между общим правилом с «—» и частным
            other = rng.choice([a for a in actions if a != owner])
            rules.insert(rng.randint(0, len(rules)), ({i: combo[i] for i in range(3)}, other))
        bad = []
        for combo in combos:
            acts = {a for r, a in rules if _covers(r, combo)}
            if (mode == "gap" and not acts) or (mode == "conflict" and len(acts) > 1):
                bad.append(combo)
        if len(bad) != 1:
            continue
        if any(sum(_covers(r, c) for r, _ in rules) != 1 for c in combos if c not in bad):
            continue
        covered = [c for c in combos if c not in bad]
        via_dash = [c for c in covered if any(_covers(r, c) and len(r) < 3 for r, _ in rules)]
        if len(via_dash) < 2 or len(rules) > 7:
            continue
        break
    else:
        raise RuntimeError("нет таблицы")

    def label(combo):
        return "; ".join(f"{n} — {'да' if c else 'нет'}" for n, c in zip(names, combo))
    rng.shuffle(via_dash)
    rest = [c for c in covered if c not in via_dash[:2]]
    distract = via_dash[:2] + [rng.choice(rest)]
    opts, key = balanced_options(FAMILY_ID, seed, rng, (label(bad[0]), None), [(label(c), None) for c in distract])
    headers = ["Условие / правило"] + [f"R{i + 1}" for i in range(len(rules))]
    sym = lambda v: "—" if v is None else ("Да" if v else "Нет")  # noqa: E731
    trows = [[names[k]] + [sym(r.get(k)) for r, _ in rules] for k in range(3)] + [["Действие"] + [a for _, a in rules]]
    table = text_table(headers, trows)
    q = ("Какая комбинация условий не покрыта ни одним правилом?" if mode == "gap" else
         "Для какой комбинации условий правила таблицы предписывают разные действия?")
    stem = (f"Аналитик описал таблицу решений ({ctx}); «—» означает «любое значение»:\n\n{table}\n\n{q}")
    opt_map = {o.id: o.text for o in opts}
    prog = (py_literal_block("TABLE", table) + f"NAMES = {names!r}\nMODE = {mode!r}\nOPTS = {opt_map!r}\n" + CHECK_SRC)
    checks = [Check(name="table_model", runner="python", program=prog, expect="stdout_equals", expected_stdout=key)]
    expl = ("Нужно перебрать все 8 комбинаций и для каждой найти подходящие правила (с учётом «—»). " +
            (f"Комбинацию «{label(bad[0])}» не покрывает ни одно правило — таблица неполна."
             if mode == "gap" else
             f"Комбинация «{label(bad[0])}» подходит под два правила с разными действиями — таблица противоречива.")
            + " Остальные варианты покрыты ровно одним правилом.")
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Ответ проверяется программой на Python, разбирающей показанную таблицу.",
                         params={"mode": mode, "n_rules": len(rules)})
