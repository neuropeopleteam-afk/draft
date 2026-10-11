"""analyst.principal.launch_effect_mcq — mcq_concept (Principal): эффект запуска функции по данным «до/после» с контролем.

Функция запущена в тестовых регионах, в контрольных — нет; данные за четыре недели до и после запуска по двум
сегментам (новые и вернувшиеся пользователи): число пользователей и конверсия. Одновременно в тестовых регионах шла
рекламная кампания — доля новых пользователей (у них конверсия ниже) выросла. Сезонный сдвиг в сегментах одинаков в
тестовых и контрольных регионах, эффект функции одинаков в обоих сегментах. Верная оценка — разность разностей
внутри сегментов (у обоих сегментов одна и та же); решение о раскатке — по порогу из условия.

Дистракторы (фиксированный состав): ``naive`` — «после минус до» по тестовым регионам в целом (сезон и смена
структуры); ``did_total`` — разность разностей по общим конверсиям (смена структуры аудитории); ``after_only`` —
тест против контроля только после запуска (исходная разница регионов). Ключ проверяется исполнением: программа
пересчитывает конверсии по таблице.
"""
from __future__ import annotations

from fractions import Fraction

from assessment_bank.families._lead_b_utils import computed_mcq, ru_num
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "analyst.principal.launch_effect_mcq"

CONTEXTS = [("сервис доставки продуктов", "оплата в один шаг"), ("интернет-магазин электроники", "сравнение товаров"),
            ("сервис бронирования отелей", "календарь цен"), ("онлайн-аптека", "повтор прошлого заказа"),
            ("маркетплейс одежды", "примерка по меркам"), ("сервис объявлений", "безопасная сделка"),
            ("кинотеатр онлайн", "семейная подписка"), ("сервис такси", "заказ к точному времени")]

PROGRAM = '''from fractions import Fraction as F

# группа, период, сегмент: (пользователей, конверсия в процентах — строкой как в таблице)
DATA = {data!r}
THRESHOLD = F({thr!r})


def conv(g, p, s):
    return F(DATA[(g, p, s)][1])


did = {{s: (conv("тест", "после", s) - conv("тест", "до", s)) - (conv("контроль", "после", s) - conv("контроль", "до", s))
       for s in ("новые", "вернувшиеся")}}
assert did["новые"] == did["вернувшиеся"]   # эффект одинаков в сегментах
e = did["новые"]
sign = "+" if e > 0 else "−" if e < 0 else ""
val = f"{{abs(float(e)):.1f}}".replace(".", ",")
print(f"эффект {{sign}}{{val}} п.п. — " + ("раскатывать" if e >= THRESHOLD else "не раскатывать"))
'''


def _f(x: Fraction) -> str:
    v = f"{abs(float(x)):.1f}".replace(".", ",")
    return ("+" if x > 0 else "−" if x < 0 else "") + v


def _opt(x: Fraction, thr: Fraction) -> str:
    return f"эффект {_f(x)} п.п. — " + ("раскатывать" if x >= thr else "не раскатывать")


def _d(k: int) -> Fraction:
    return Fraction(k, 10)


def _total(data, g, p):
    n = sum(data[(g, p, s)][0] for s in ("новые", "вернувшиеся"))
    conv = sum(data[(g, p, s)][0] * Fraction(data[(g, p, s)][1]) for s in ("новые", "вернувшиеся"))
    return conv / n


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, feature = rng.choice(CONTEXTS)
    want_roll = seed % 2 == 0   # половина вариантов — «раскатывать», половина — «не раскатывать»
    for _ in range(20000):
        cn = _d(rng.randint(15, 35))          # конверсия новых в тесте до, %
        cr = _d(rng.randint(70, 120))         # конверсия вернувшихся в тесте до, %
        on, orr = _d(rng.randint(-4, 4)), _d(rng.randint(-8, 8))   # разница контроля
        tn, tr = _d(rng.randint(-6, 6)), _d(rng.randint(-8, 8))    # сезонный сдвиг
        e = _d(rng.randint(1, 12))
        thr = _d(rng.choice([3, 5, 8]))
        if abs(e - thr) < Fraction(1, 10) or (e >= thr) != want_roll:
            continue
        n_tb = rng.choice([30000, 40000, 50000, 60000])
        n_cb = rng.choice([30000, 40000, 50000, 60000])
        w0 = Fraction(rng.choice([25, 30, 35, 40]), 100)
        w1 = w0 + Fraction(rng.choice([15, 20, 25, 30]), 100)
        v0 = Fraction(rng.choice([25, 30, 35, 40]), 100)
        growth = Fraction(rng.choice([120, 130, 140, 150]), 100)
        n_ta = int(n_tb * growth)
        n_ca = int(n_cb * Fraction(rng.choice([95, 100, 105]), 100))
        vals = {("тест", "до", "новые"): cn, ("тест", "до", "вернувшиеся"): cr,
                ("тест", "после", "новые"): cn + tn + e, ("тест", "после", "вернувшиеся"): cr + tr + e,
                ("контроль", "до", "новые"): cn + on, ("контроль", "до", "вернувшиеся"): cr + orr,
                ("контроль", "после", "новые"): cn + on + tn, ("контроль", "после", "вернувшиеся"): cr + orr + tr}
        if min(vals.values()) <= Fraction(1, 2):
            continue
        users = {("тест", "до"): (n_tb, w0), ("тест", "после"): (n_ta, w1), ("контроль", "до"): (n_cb, v0),
                 ("контроль", "после"): (n_ca, v0)}
        data = {}
        for (g, p, s), c in vals.items():
            n, w = users[(g, p)]
            k = int(n * w) if s == "новые" else n - int(n * w)
            data[(g, p, s)] = (k, f"{float(c):.1f}")
        t = {(g, p): _total(data, g, p) for g in ("тест", "контроль") for p in ("до", "после")}
        naive = t[("тест", "после")] - t[("тест", "до")]
        did_total = naive - (t[("контроль", "после")] - t[("контроль", "до")])
        after_only = t[("тест", "после")] - t[("контроль", "после")]
        cands = [e, naive, did_total, after_only]
        rounded = [round(float(x), 1) for x in cands]
        if min(abs(a - b) for i, a in enumerate(rounded) for b in rounded[i + 1:]) < 0.2 - 1e-9:
            continue
        opts = [_opt(x, thr) for x in cands]
        dec = [o.split(" — ")[1] for o in opts]
        # решение верного варианта не выделяется: оно есть и у дистрактора, а другое решение — тоже в вариантах
        if len(set(opts)) == 4 and dec.count(dec[0]) in (2, 3):
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось построить вариант")
    rows = ["группа | период | сегмент | пользователей | конверсия в заказ"]
    for (g, p, s), (k, c) in data.items():
        rows.append(f"{g} | {p} | {s} | {ru_num(k)} | {c.replace('.', ',')} %")
    code = "\n".join(rows)
    stem = (f"{ctx.capitalize()}: функцию «{feature}» запустили в тестовых регионах, в контрольных её нет. Данные "
            f"за четыре недели до и четыре недели после запуска — в таблице (сегменты: новые и вернувшиеся "
            f"пользователи). В те же недели в тестовых регионах шла рекламная кампания, привлекавшая новых "
            f"пользователей; сезонные изменения в тестовых и контрольных регионах одинаковы. Раскатку на все "
            f"регионы решено делать, если эффект функции на конверсию не меньше {_f(thr)} п.п. Какая оценка эффекта и "
            f"какое решение верны?")
    tt = {k: ru_num(round(float(v), 2)) for k, v in t.items()}
    why = (f"Внутри каждого сегмента разность разностей одна и та же: (после − до в тесте) − (после − до в контроле) "
           f"= {_f(e)} п.п. — это эффект функции, сезон вычитается контролем. Общая конверсия теста: {tt[('тест', 'до')]} "
           f"% → {tt[('тест', 'после')]} %, контроля: {tt[('контроль', 'до')]} % → {tt[('контроль', 'после')]} %. «После "
           f"минус до» по тесту ({_f(naive)} п.п.) содержит сезон и смену структуры; разность разностей по общим "
           f"конверсиям ({_f(did_total)} п.п.) искажена тем, что кампания подняла долю новых пользователей с "
           f"{ru_num(round(100 * float(w0)))} % до {ru_num(round(100 * float(w1)))} %, а у них конверсия ниже; "
           f"сравнение только после запуска ({_f(after_only)} п.п.) содержит исходную разницу регионов. Решение — по "
           f"оценке внутри сегментов и порогу {_f(thr)} п.п.")
    data_lit = {k: v for k, v in data.items()}
    program = PROGRAM.format(data=data_lit, thr=str(thr))
    return computed_mcq(FAMILY_ID, seed, rng, stem=stem, correct=opts[0], distractors=opts[1:], program=program,
                        why=why, context=ctx, code=code, language="text",
                        note="Программа пересчитывает разность разностей внутри сегментов по тем же числам "
                             "(точные дроби) и применяет порог.",
                        params={"effect": str(e), "threshold": str(thr)}, max_ratio=1.6)
