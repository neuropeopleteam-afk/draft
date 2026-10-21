"""qa.asserts.t21_expected_actual_output — predict_output (набор t21, порог Стажёра): цикл по индексам range(len())
со счётчиком расхождений.

API-сценарий: список ожидаемых кодов ответа по шагам и фактические коды; цикл по индексам сравнивает их, печатает
индекс шага и фактический код при расхождении и в конце — число расхождений. Ловушки: печатается индекс с нуля, а не
номер шага; совпадающие шаги не печатаются. Ключ — независимое сравнение через zip/enumerate в генераторе; проверка —
исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.asserts.t21_expected_actual_output"

CTX = ["сценарий оформления заказа", "сценарий регистрации и входа", "сценарий возврата платежа",
       "сценарий загрузки аватара", "сценарий смены тарифа"]
WRONG = {200: [500, 201, 404], 201: [200, 400, 409], 204: [200, 404], 400: [200, 422], 401: [200, 403],
         404: [200, 410], 409: [201, 200], 422: [400, 200]}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    ev, av = rng.choice([("expected", "actual"), ("want", "got"), ("plan", "fact")])
    for _ in range(200):
        n = rng.randint(4, 6)
        exp = [rng.choice(list(WRONG)) for _ in range(n)]
        k = rng.randint(1, min(3, n - 2))
        bad = sorted(rng.sample(range(n), k))
        act = [rng.choice(WRONG[c]) if i in bad else c for i, c in enumerate(exp)]
        if bad != [0]:
            break
    code = (f"{ev} = {exp}\n"
            f"{av} = {act}\n"
            "mismatch = 0\n"
            f"for i in range(len({ev})):\n"
            f"    if {ev}[i] != {av}[i]:\n"
            "        mismatch += 1\n"
            f"        print(\"step\", i, {av}[i])\n"
            "print(\"mismatches:\", mismatch)")
    rows = [(i, a) for i, (e, a) in enumerate(zip(exp, act)) if e != a]
    out = "\n".join([*(f"step {i} {a}" for i, a in rows), f"mismatches: {len(rows)}"])
    expl = ("Цикл перебирает индексы 0…" + f"{n - 1}; расхождения: "
            + ", ".join(f"индекс {i} (ожидали {exp[i]}, пришёл {a})" for i, a in rows)
            + f". Печатаются только они — с индексом с нуля, затем «mismatches: {len(rows)}». Ловушка — индекс "
              "range начинается с 0, а не с 1.")
    stem = (f"API-тест ({ctx}): программа сверяет ожидаемые коды ответа по шагам с фактическими и печатает "
            "расхождения.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"expected": exp, "actual": act}, language="python")
