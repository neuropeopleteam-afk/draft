"""data_ml.eval.lp3_threshold_cost_output — predict_output: порог классификатора под цену ошибок и ограничение.

Валидационная выборка: оценка модели и истинная метка. Положительный ответ — если оценка ≥ порога. Бизнес задаёт
цену пропуска (FN) и ложной тревоги (FP) и требование «полнота не ниже R». Нужен порог из оценок выборки,
минимизирующий суммарную цену среди порогов, где полнота ≥ R (при равной цене — больший порог: меньше ручной
работы). Ловушки: максимизировать точность (accuracy); забыть ограничение по полноте; взять порог 0,5.
Ответ — порог с двумя знаками после запятой.
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.eval.lp3_threshold_cost_output"
TASKS = [("антифрод платежей", "мошенническая операция", "проверка аналитиком"),
         ("отток абонентов", "абонент уйдёт", "звонок удержания"),
         ("модерация объявлений", "запрещённое объявление", "ручная модерация"),
         ("кредитный скоринг", "дефолт по кредиту", "ручной андеррайтинг"),
         ("дефекты на конвейере", "бракованная деталь", "повторный контроль")]

CALC = r'''
import re
cfg, rows = {}, []
for l in DATA.splitlines():
    m = re.match(r"^([^|:]+):\s*([\d,]+)", l)
    if m:
        cfg[m.group(1).strip()] = float(m.group(2).replace(",", "."))
    elif l.count("|") == 2 and not l.startswith("№"):
        n, s, y = [x.strip() for x in l.split("|")]
        rows.append((float(s.replace(",", ".")), int(y)))
P = sum(y for _, y in rows)
best = None
for t in sorted({s for s, _ in rows}):
    tp = sum(1 for s, y in rows if s >= t and y == 1)
    fp = sum(1 for s, y in rows if s >= t and y == 0)
    fn = P - tp
    if tp / P * 100 < cfg["минимальная полнота, %"] - 1e-9:
        continue
    cost = fn * cfg["цена пропуска"] + fp * cfg["цена ложной тревоги"]
    if best is None or cost < best[0] or (cost == best[0] and t > best[1]):
        best = (cost, t)
print(f"{best[1]:.2f}".replace(".", ","))
'''


def _f(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _best(rows, cfn, cfp, rmin, with_recall=True):
    P = sum(y for _, y in rows)
    best = None
    for t in sorted({s for s, _ in rows}):
        tp = sum(1 for s, y in rows if s >= t and y == 1)
        fp = sum(1 for s, y in rows if s >= t and y == 0)
        if with_recall and tp / P * 100 < rmin - 1e-9:
            continue
        cost = (P - tp) * cfn + fp * cfp
        if best is None or cost < best[0] or (cost == best[0] and t > best[1]):
            best = (cost, t)
    return best


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    task, pos, action = rng.choice(TASKS)
    for _ in range(4000):
        n = rng.randint(16, 22)
        scores = rng.sample(range(5, 99), n)
        rows = []
        for s in scores:
            p = 0.08 + 0.84 * (s / 100) ** 1.3
            rows.append((s / 100, 1 if rng.random() < p else 0))
        P = sum(y for _, y in rows)
        if not 5 <= P <= n - 5:
            continue
        cfn = rng.choice([5, 8, 10, 20, 30])
        cfp = rng.choice([1, 2, 3])
        rmin = rng.choice([70, 80, 85, 90])
        b = _best(rows, cfn, cfp, rmin)
        if b is None:
            continue
        good = b[1]
        nr = _best(rows, cfn, cfp, rmin, with_recall=False)[1]
        acc = max(sorted({s for s, _ in rows}), key=lambda t: sum(1 for s, y in rows if (s >= t) == (y == 1)))
        if good in (nr, acc, 0.5) and rng.random() < 0.8:
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    rows.sort(key=lambda r: -r[0])
    lines = [f"цена пропуска: {cfn}", f"цена ложной тревоги: {cfp}", f"минимальная полнота, %: {rmin}", "",
             "№ | оценка | метка"]
    for i, (s, y) in enumerate(rows, 1):
        lines.append(f"{i} | {_f(s)} | {y}")
    block = "\n".join(lines)
    stem = (f"Модель для задачи «{task}» выдаёт оценку от 0 до 1; метка 1 — «{pos}». Положительный ответ модели "
            f"отправляет случай на «{action}». Цены ошибок и требование бизнеса к полноте — ниже, вместе с "
            "валидационной выборкой. Какой порог (одна из оценок выборки; положительно, если оценка ≥ порога) "
            "выбрать, чтобы суммарная цена ошибок на выборке была минимальной при выполнении требования к "
            "полноте? При равной цене — больший порог. Ответ — порог с двумя знаками после запятой, например 0,37.")
    expl = (f"Перебираем пороги из оценок: полнота = TP / {P}, цена = FN · {cfn} + FP · {cfp}. Среди порогов с "
            f"полнотой ≥ {rmin} % минимальная цена {b[0]:g} — при пороге {_f(good)}. Без ограничения по полноте "
            f"выбор был бы {_f(nr)}, по максимуму точности — {_f(acc)}; порог 0,5 не учитывает цены ошибок.")
    acc_forms = [f"{good:.2f}", _f(good).lstrip("0"), f"{good:.2f}".lstrip("0")]
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=_f(good), expl=expl, ctx=task,
                         accept=acc_forms, params={"cfn": cfn, "cfp": cfp, "rmin": rmin, "rows": rows})
