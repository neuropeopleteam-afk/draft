"""qa.reports.t21_progress_line_output — predict_output (набор t21, порог Стажёра): len, count и find на строке
прогресса прогона.

Строка прогресса тест-раннера: «.» — тест прошёл, «F» — упал, «E» — ошибка, «s» — пропущен. Программа печатает
длину строки, число точек, «всего минус прошедшие» и номер первого упавшего теста (find + 1). Ловушки: «всего минус
прошедшие» включает и пропущенные; find возвращает индекс с нуля; считать надо все символы. Ключ — независимый
подсчёт по списку результатов в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.reports.t21_progress_line_output"

CTX = ["модульные тесты сервиса скидок", "регресс API заказов", "тесты парсера платёжных выписок",
       "UI-тесты формы регистрации", "контрактные тесты сервиса доставки"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    var = rng.choice(["line", "progress", "dots"])
    for _ in range(200):
        n = rng.randint(8, 12)
        res = [rng.choice(".....FsE") for _ in range(n)]
        if res.count("F") >= 1 and res.count("s") + res.count("E") >= 1 and res[0] == ".":
            break
    else:
        raise RuntimeError("t21_progress_line: не собралась строка")
    line = "".join(res)
    total = n
    passed = sum(1 for c in res if c == ".")
    first = next(i for i, c in enumerate(res) if c == "F") + 1
    code = (f"{var} = \"{line}\"\n"
            f"total = len({var})\n"
            f"passed = {var}.count(\".\")\n"
            f"first_fail = {var}.find(\"F\") + 1\n"
            f"print(total, passed, total - passed)\n"
            f"print(first_fail)")
    out = f"{total} {passed} {total - passed}\n{first}"
    nf, ne, ns = res.count("F"), res.count("E"), res.count("s")
    expl = (f"В строке {total} символов, из них точек {passed}. total − passed = {total - passed}: это все не "
            f"прошедшие — F ({nf}), E ({ne}) и s ({ns}), пропущенные тоже входят. Первая «F» стоит на индексе "
            f"{first - 1} (счёт с нуля), find(\"F\") + 1 = {first}. Ловушки — пропущенные в разности и индекс с нуля.")
    stem = (f"Прогон ({ctx}): строка прогресса тест-раннера, где «.» — тест прошёл, «F» — упал, «E» — ошибка, "
            "«s» — пропущен. Программа считает итоги по этой строке.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"line": line}, language="python")
