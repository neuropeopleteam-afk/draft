"""analyst.req.rice_priority_mcq — mcq_concept: приоритет бэклога по RICE.

Таблица из четырёх доработок с оценками Reach (пользователей за квартал), Impact (шкала 0,25 / 0,5 / 1 / 2 / 3),
Confidence (%) и Effort (человеко-месяцы). RICE = Reach · Impact · Confidence / Effort. Подтипы вопроса: какая
доработка получит наивысший приоритет; какая — наименьший. Три дистрактора — «ловушки одного множителя»:
доработка с наибольшим охватом, с наибольшим влиянием и с наименьшими трудозатратами (для наименьшего
приоритета — наоборот); каждая из них отличается от верной, разрыв между первым и вторым местом не меньше
10 %. Ключ проверяется исполнением: Python разбирает показанную таблицу и считает RICE точно (Fraction).
"""
from __future__ import annotations

from fractions import Fraction

from assessment_bank.gen_utils import build_variant, make_rng, text_table
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import balanced_options, py_literal_block

FAMILY_ID = "analyst.req.rice_priority_mcq"

CTX = {"мобильный банк": ["Оплата по QR", "Шаблоны платежей", "Тёмная тема", "Кешбэк-категории",
                          "Вход по биометрии", "Выписка в PDF"],
       "интернет-магазин": ["Сравнение товаров", "Повтор заказа", "Отзывы с фото", "Доставка к часу",
                            "Список желаний", "Оплата частями"],
       "сервис доставки еды": ["Групповой заказ", "Чаевые курьеру", "Трекинг на карте", "Любимые рестораны",
                               "Промокоды в профиле", "Заказ к времени"],
       "HR-портал": ["Заявка на отпуск онлайн", "Расчётный листок", "Справка 2-НДФЛ", "Опрос вовлечённости",
                     "Онбординг-чек-лист", "Поиск коллег"],
       "приложение фитнес-клуба": ["Запись на тренировку", "Заморозка абонемента", "План питания",
                                   "Онлайн-тренировки", "Рейтинг посещений", "Оплата в приложении"],
       "портал госуслуг региона": ["Запись к врачу", "Оплата ЖКХ", "Уведомления о штрафах", "Электронная очередь",
                                   "Статус заявления", "Чат с оператором"],
       "сервис аренды самокатов": ["Абонемент на месяц", "Бронь самоката", "Семейный аккаунт", "Пауза поездки",
                                   "Фото при завершении", "Бонусы за парковку"],
       "система учёта для склада": ["Сканирование партиями", "Печать этикеток", "Инвентаризация с ТСД",
                                    "Отчёт по остаткам", "Резерв под заказ", "Подсказка ячейки"]}

IMPACT = [Fraction(1, 4), Fraction(1, 2), Fraction(1), Fraction(2), Fraction(3)]
CONF = [50, 80, 100]

CALC = r'''
from fractions import Fraction
rows = [[c.strip() for c in l.split("|")] for l in TABLE.strip().splitlines()[2:]]
def num(s):
    return Fraction(s.replace(",", ".").replace(" %", "").replace(" ", ""))
score = {r[0]: num(r[1]) * num(r[2]) * num(r[3]) / 100 / num(r[4]) for r in rows}
target = max(score.values()) if MODE == "max" else min(score.values())
winners = [n for n, s in score.items() if s == target]
hit = [k for k, v in OPTS.items() if v in winners]
print(hit[0] if len(hit) == 1 and len(winners) == 1 else "AMBIGUOUS")
'''


def _fmt(x):
    if isinstance(x, Fraction):
        return f"{float(x):g}".replace(".", ",")
    return f"{x:,}".replace(",", " ")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(sorted(CTX))
    names = rng.sample(CTX[ctx], 4)
    mode = "min" if seed % 3 == 0 else "max"
    for _ in range(5000):
        rows = []
        for n in names:
            reach = rng.choice([300, 500, 800, 1200, 2000, 3000, 5000, 8000, 12000])
            rows.append((n, reach, rng.choice(IMPACT), rng.choice(CONF), Fraction(rng.choice([1, 2, 3, 4, 6, 8]),
                                                                                    rng.choice([1, 2]))))
        sc = [r[1] * r[2] * r[3] / 100 / r[4] for r in rows]
        order = sorted(range(4), key=lambda i: sc[i], reverse=(mode == "max"))
        best, second = sc[order[0]], sc[order[1]]
        if mode == "max" and not best >= second * Fraction(11, 10):
            continue
        if mode == "min" and not second >= best * Fraction(11, 10):
            continue
        k = order[0]
        pick = max if mode == "max" else min
        pick_e = min if mode == "max" else max
        reach_i = [i for i in range(4) if rows[i][1] == pick(r[1] for r in rows)]
        imp_i = [i for i in range(4) if rows[i][2] == pick(r[2] for r in rows)]
        eff_i = [i for i in range(4) if rows[i][4] == pick_e(r[4] for r in rows)]
        if len(reach_i) != 1 or len(imp_i) != 1 or len(eff_i) != 1:
            continue
        traps = {reach_i[0], imp_i[0], eff_i[0]}
        if len(traps) != 3 or k in traps:
            continue
        break
    else:
        raise RuntimeError("нет таблицы")
    headers = ["Доработка", "Reach (польз./квартал)", "Impact", "Confidence", "Effort (чел.-мес.)"]
    trows = [[r[0], _fmt(r[1]), _fmt(r[2]), f"{r[3]} %", _fmt(r[4])] for r in rows]
    table = text_table(headers, trows)
    dist = [names[i] for i in (reach_i[0], imp_i[0], eff_i[0])]
    opts, key = balanced_options(FAMILY_ID, seed, rng, (names[k], None), [(d, None) for d in dist])
    opt_map = {o.id: o.text for o in opts}
    prog = py_literal_block("TABLE", table) + f"MODE = {mode!r}\nOPTS = {opt_map!r}\n" + CALC
    checks = [Check(name="rice", runner="python", program=prog, expect="stdout_equals", expected_stdout=key)]
    q = ("Какая доработка получит наивысший приоритет?" if mode == "max" else
         "Какая доработка получит наименьший приоритет?")
    stem = (f"Продукт «{ctx}». Аналитик оценил доработки бэклога по RICE: приоритет = Reach · Impact · "
            f"Confidence / Effort (Confidence — в долях: 80 % = 0,8). Оценки — в таблице. {q}")
    expl = ("RICE: " + "; ".join(f"{r[0]} — {_fmt(r[1])}·{_fmt(r[2])}·{r[3] / 100:g}/{_fmt(r[4])} = "
                                  f"{float(s):.0f}".replace(".", ",") for r, s in zip(rows, sc)) +
            f". {'Наибольший' if mode == 'max' else 'Наименьший'} — «{names[k]}». Ловушки: судить только по охвату "
            f"(«{dist[0]}»), только по влиянию («{dist[1]}») или только по трудозатратам («{dist[2]}»).")
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=table, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Ответ проверяется программой на Python, разбирающей показанную таблицу.",
                         params={"mode": mode, "rows": [[r[0], r[1], str(r[2]), r[3], str(r[4])] for r in rows]})
