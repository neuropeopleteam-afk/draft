"""qa.design.decision_table_bug — find_bug: ошибочная строка тестовых данных по таблице решений.

Бизнес-правило задано таблицей решений (правила по приоритету: срабатывает первое
подходящее). По ней составлен параметризованный тест pytest; в одной строке данных ожидаемый
результат не соответствует таблице — типичная ошибка тест-дизайна (перепутан приоритет
правил, граница «от … включительно», условие «не важно»). Реализация верна, тест красный.
Ключ проверяется исполнением: с ошибочной строкой тест падает на правильной реализации;
после исправления строки — зелёный на правильной и ловит мутанта реализации.
"""
from __future__ import annotations

from assessment_bank.families.qa._shims import (PYTEST_CAUGHT_TAIL, PYTEST_GREEN_TAIL,
                                                pytest_program)
from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "qa.design.decision_table_bug"
B = "граница «от … включительно» понята как строгое неравенство"
P = "перепутан приоритет правил: сработать должно правило выше"
N = "учтено условие, которое в этом правиле не важно, или проигнорировано важное"


def _delivery(rng):
    t = rng.choice([2000, 2500, 3000, 3500, 5000])
    p1, p2 = rng.choice([(99, 299), (149, 349), (79, 249), (129, 399)])
    impl = ("def delivery_cost(pro, order_sum, pickup):\n    if pro:\n        return 0\n"
            f"    if order_sum >= {t}:\n        return 0\n    if pickup:\n        return {p1}\n"
            f"    return {p2}\n")
    mutants = [impl.replace(f"order_sum >= {t}", f"order_sum > {t}"),
               impl.replace("    if pro:\n        return 0\n", ""),
               impl.replace(f"return {p1}", f"return {p2}")]

    def model(pro, s, pick):
        return 0 if pro or s >= t else (p1 if pick else p2)

    mistakes = [lambda pro, s, pick: 0 if pro or s > t else (p1 if pick else p2),       # граница
                lambda pro, s, pick: (p1 if pick else 0) if (pro or s >= t) else (p1 if pick else p2),  # приоритет
                lambda pro, s, pick: 0 if s >= t else (p1 if pick else p2)]               # Pro «не важно»
    sums = [t, t - 1, t + rng.choice([1, 10, 500]), rng.choice([300, 800, 1200]), t * 2]
    rows = [(pro, s, pick) for pro in (True, False) for s in sums for pick in (True, False)]
    why = [B, P, N]
    return dict(why=why, module="shop.delivery", func="delivery_cost", args=["pro", "order_sum", "pickup"],
                ctx="интернет-магазин", impl=impl, mutants=mutants, model=model,
                mistakes=mistakes, rows=rows, lit=lambda v: repr(v),
                rules=[f"подписка Pro — доставка 0 ₽", f"сумма заказа от {t} ₽ включительно — 0 ₽",
                       f"самовывоз из пункта выдачи (pickup) — {p1} ₽", f"иначе — {p2} ₽"],
                need_rules=lambda pro, s, pick: 1 if pro else 2 if s >= t else 3 if pick else 4)


def _credit(rng):
    sc = rng.choice([600, 650, 700, 720])
    impl = ("def credit_decision(score, income_confirmed, has_overdue):\n    if has_overdue:\n"
            "        return 'reject'\n"
            f"    if score >= {sc}:\n        return 'approve' if income_confirmed else 'manual'\n"
            "    return 'manual' if income_confirmed else 'reject'\n")
    mutants = [impl.replace(f"score >= {sc}", f"score > {sc}"),
               impl.replace("    if has_overdue:\n        return 'reject'\n", ""),
               impl.replace("'approve' if income_confirmed else 'manual'", "'approve'")]

    def model(s, inc, od):
        if od:
            return "reject"
        if s >= sc:
            return "approve" if inc else "manual"
        return "manual" if inc else "reject"

    mistakes = [lambda s, inc, od: model(s + (0 if s != sc else -1), inc, od),             # граница
                lambda s, inc, od: model(s, inc, False) if s >= sc else model(s, inc, od),   # приоритет
                lambda s, inc, od: ("approve" if s >= sc else "manual" if inc else "reject")
                if not od else "reject"]                                                    # «доход не важен»
    scores = [sc, sc - 1, sc + rng.choice([5, 40, 90]), rng.choice([480, 520, 560])]
    rows = [(s, inc, od) for s in scores for inc in (True, False) for od in (True, False)]
    why = [B, P, N]
    return dict(why=why, module="bank.scoring", func="credit_decision",
                args=["score", "income_confirmed", "has_overdue"], ctx="кредитный конвейер",
                impl=impl, mutants=mutants, model=model, mistakes=mistakes, rows=rows,
                lit=lambda v: repr(v),
                rules=["есть просрочка — reject", f"скоринговый балл от {sc} включительно и доход "
                       "подтверждён — approve", f"балл от {sc}, доход не подтверждён — manual",
                       f"балл ниже {sc}: доход подтверждён — manual, иначе — reject"],
                need_rules=lambda s, inc, od: 1 if od else (2 if inc else 3) if s >= sc else 4)


def _cashback(rng):
    a = rng.choice([1000, 1500, 3000, 5000])
    hi, mid = rng.choice([(10, 5), (7, 4), (15, 7)])
    impl = ("def cashback_percent(amount, promo_category, premium):\n    if promo_category:\n"
            f"        return {hi} if premium else {mid}\n    if amount >= {a}:\n        return 2\n"
            "    return 1\n")
    mutants = [impl.replace(f"amount >= {a}", f"amount > {a}"),
               impl.replace(f"return {hi} if premium else {mid}", f"return {mid}"),
               impl.replace("        return 2\n", "        return 1\n")]

    def model(am, promo, prem):
        if promo:
            return hi if prem else mid
        return 2 if am >= a else 1

    mistakes = [lambda am, promo, prem: model(am - (1 if am == a else 0), promo, prem),   # граница
                lambda am, promo, prem: mid if (not promo and prem) else model(am, promo, prem),
                lambda am, promo, prem: 2 if am >= a else model(am, promo, prem)]       # приоритет
    amounts = [a, a - 1, a + rng.choice([1, 100, 999]), rng.choice([150, 400, 700])]
    rows = [(am, promo, prem) for am in amounts for promo in (True, False) for prem in (True, False)]
    why = [B, N, P]
    return dict(why=why, module="loyalty.cashback", func="cashback_percent",
                args=["amount", "promo_category", "premium"], ctx="программа лояльности",
                impl=impl, mutants=mutants, model=model, mistakes=mistakes, rows=rows,
                lit=lambda v: repr(v),
                rules=[f"покупка в акционной категории: премиум-клиент — {hi} %, остальные — {mid} %",
                       f"вне акции, сумма покупки от {a} ₽ включительно — 2 % (премиум не важен)",
                       f"вне акции, сумма меньше {a} ₽ — 1 %"],
                need_rules=lambda am, promo, prem: (1 if promo else 2 if am >= a else 3))


def _access(rng):
    impl = ("def document_access(is_admin, is_owner, archived):\n    if is_admin:\n"
            "        return 'edit'\n    if archived:\n        return 'read'\n"
            "    return 'edit' if is_owner else 'read'\n")
    mutants = [impl.replace("    if archived:\n        return 'read'\n", ""),
               impl.replace("    if is_admin:\n        return 'edit'\n", ""),
               impl.replace("'edit' if is_owner else 'read'", "'read'")]

    def model(adm, own, arch):
        if adm:
            return "edit"
        if arch:
            return "read"
        return "edit" if own else "read"

    mistakes = [lambda adm, own, arch: "read" if arch else model(adm, own, arch),      # архив выше админа
                lambda adm, own, arch: "edit" if own else model(adm, own, arch),       # владелец выше архива
                lambda adm, own, arch: "deny" if not adm and not own and arch else model(adm, own, arch)]
    rows = [(adm, own, arch) for adm in (True, False) for own in (True, False) for arch in (True, False)]
    why = [P, P, "в таблице нет действия deny: недостающее правило «додумано» тестировщиком"]
    return dict(why=why, module="docs.acl", func="document_access", args=["is_admin", "is_owner", "archived"],
                ctx="система документооборота", impl=impl, mutants=mutants, model=model,
                mistakes=mistakes, rows=rows, lit=lambda v: repr(v),
                rules=["администратор — edit", "документ в архиве — read (даже для владельца)",
                       "владелец — edit", "иначе — read"],
                need_rules=lambda adm, own, arch: 1 if adm else 2 if arch else 3 if own else 4)


CONTEXTS = [_delivery, _credit, _cashback, _access]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    sc = rng.choice(CONTEXTS)(rng)
    model, n_rules = sc["model"], len(sc["rules"])
    for _ in range(500):
        rows = rng.sample(sc["rows"], rng.randint(6, 8))
        if len({sc["need_rules"](*r) for r in rows}) < n_rules:
            continue
        cands = [(i, m(*rows[i]), mi) for i in range(len(rows))
                 for mi, m in enumerate(sc["mistakes"]) if m(*rows[i]) != model(*rows[i])]
        if not cands:
            continue
        wrong_i, wrong_v, wrong_m = rng.choice(cands)
        expected = [model(*r) for r in rows]
        bad_expected = list(expected)
        bad_expected[wrong_i] = wrong_v
        # исправленный тест ловит хотя бы одного мутанта
        mut_ok = []
        for mi, msrc in enumerate(sc["mutants"]):
            ns: dict = {}
            exec(compile(msrc, "<mutant>", "exec"), ns)  # детерминированный код банка
            if any(ns[sc["func"]](*r) != e for r, e in zip(rows, expected)):
                mut_ok.append(mi)
        if mut_ok:
            break
    else:
        raise RuntimeError("не удалось подобрать строки")
    mutant = sc["mutants"][rng.choice(mut_ok)]
    names = ", ".join(sc["args"] + ["expected"])
    lit = sc["lit"]

    def assemble(exp):
        out = ["import pytest", f"from {sc['module']} import {sc['func']}", "", "",
               f"@pytest.mark.parametrize(\"{names}\", ["]
        for r, e in zip(rows, exp):
            out.append("    (" + ", ".join(lit(v) for v in r) + f", {lit(e)}),")
        out += ["])", f"def test_{sc['func']}({names}):",
                f"    assert {sc['func']}({', '.join(sc['args'])}) == expected"]
        return "\n".join(out)

    buggy, fixed = assemble(bad_expected), assemble(expected)
    key_line = 6 + wrong_i
    assert changed_lines(buggy, fixed) == {key_line}
    ok, bad = {sc["module"]: sc["impl"]}, {sc["module"]: mutant}
    checks = [
        Check(name="buggy_red_on_correct", runner="python", expect="fail",
              program=pytest_program(buggy, PYTEST_GREEN_TAIL, ok)),
        Check(name="fixed_green_on_correct", runner="python", expect="pass",
              embeds_display_code=False, program=pytest_program(fixed, PYTEST_GREEN_TAIL, ok)),
        Check(name="fixed_catches_mutant", runner="python", expect="pass",
              embeds_display_code=False, program=pytest_program(fixed, PYTEST_CAUGHT_TAIL, bad)),
    ]
    rules = "; ".join(f"{i}) {r}" for i, r in enumerate(sc["rules"], 1))
    stem = (f"Бизнес-правило ({sc['ctx']}) задано таблицей решений; правила проверяются по "
            f"порядку, срабатывает первое подходящее: {rules}. По таблице составлен "
            f"параметризованный тест для `{sc['func']}`. Реализация прошла приёмку, но тест "
            f"красный: ошибка в тестовых данных. Укажите номер строки, где ожидаемый результат "
            f"не соответствует таблице решений.")
    r = rows[wrong_i]
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=(f"Строка {key_line}: для {dict(zip(sc['args'], r))} по правилу "
                                f"{sc['need_rules'](*r)} ожидается {lit(expected[wrong_i])}, а в "
                                f"тесте {lit(wrong_v)}: {sc['why'][wrong_m]}."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=sc["ctx"],
                         verification="execution", checks=checks, defect_type="wrong_expected_value",
                         params={"fixed_code": fixed, "module": sc["module"], "wrong_row": wrong_i})
