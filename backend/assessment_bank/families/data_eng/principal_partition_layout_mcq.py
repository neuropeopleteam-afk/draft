"""data_eng.dwh.principal_partition_layout_mcq — mcq_concept (Principal): схема разделов таблицы под нагрузку.

Таблица событий: H дней истории по V ГБ в день. Два типа запросов в сутки: «последние w дней по всем клиентам»
(f1 раз) и «один клиент за всю историю» (f2 раз). Время запроса = прочитанные ГБ / скорость чтения r + число
открытых разделов × o секунд (планирование, листинг, открытие файлов). Обслуживание разделов (сжатие мелких файлов,
метаданные) — μ секунд в сутки на раздел. Схемы: по дням; по месяцам; по B корзинам хэша клиента; по дням и
корзинам. Какая схема даёт минимум суммарного времени кластера в сутки?

Ловушки: без накладных расходов на разделы (o = μ = 0 — «чем мельче, тем лучше»), только самый частый запрос,
меньше всего разделов. Ответ выбирается по seed до подбора чисел — равновероятен среди четырёх схем; отличается
хотя бы от одной ловушки (обычно от двух); минимум отделён от второго места ≥ 5 %. Ключ проверяется исполнением:
программа строит список разделов, для каждого запроса отбирает разделы по условию (пересечение диапазона дат,
корзина клиента; окно «последние w дней» — в среднем по дням месяца) и суммирует время.
"""
from __future__ import annotations

from assessment_bank.families._principal_b_kit import argmin_sep, cap, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "data_eng.dwh.principal_partition_layout_mcq"

CONTEXTS = [("событий приложения", "пользователь"), ("кассовых чеков", "покупатель"), ("транзакций", "клиент"),
            ("откликов на вакансии", "соискатель"), ("заказов доставки", "клиент"), ("показов рекламы", "рекламодатель")]
NAMES = {"day": "по дням", "month": "по месяцам", "bucket": "по корзинам хэша клиента",
         "day_bucket": "по дням и корзинам хэша клиента"}
ORDER = ["day", "month", "bucket", "day_bucket"]

PROGRAM = """opts = __OPTS__
P = {P!r}
names = {names!r}
H, V, w, B = P["H"], P["V"], P["w"], P["B"]

def partitions(scheme):                 # (первый день, последний день, корзина или None, ГБ)
    if scheme == "day":
        return [(d, d, None, V) for d in range(H)]
    if scheme == "month":
        return [(m, min(m + 29, H - 1), None, V * (min(m + 29, H - 1) - m + 1)) for m in range(0, H, 30)]
    if scheme == "bucket":
        return [(0, H - 1, b, V * H / B) for b in range(B)]
    return [(d, d, b, V / B) for d in range(H) for b in range(B)]

def cost(parts, pick):
    chosen = [x for x in parts if pick(x)]
    return sum(x[3] for x in chosen) / P["r"] + len(chosen) * P["o"]

def daily(scheme):
    parts = partitions(scheme)
    recent = [x for x in parts if x[1] >= H - 30 - w]     # окну могут попасть только разделы последних дней
    # «последние w дней» — в среднем по положению текущего дня внутри месяца (последний месяц истории полный)
    q1 = sum(cost(recent, lambda x, end=H - 1 - s: x[1] >= end - w + 1 and x[0] <= end) for s in range(30)) / 30
    q2 = cost(parts, lambda x: x[2] is None or x[2] == 0)
    return P["f1"] * q1 + P["f2"] * q2 + len(parts) * P["mu"]

t = {{s: daily(s) for s in names}}
best = min(t, key=t.get)
hit = [k for k, x in opts.items() if x == names[best]]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _months_touched(p):
    """Среднее по 30 положениям текущего дня: сколько разделов-месяцев задевает окно w дней (как в программе)."""
    H, w = p["H"], p["w"]
    starts = list(range(0, H, 30))
    tot = 0
    for s in range(30):
        end = H - 1 - s
        tot += sum(1 for m in starts if min(m + 29, H - 1) >= end - w + 1 and m <= end)
    return tot / 30


def _times(p, *, overhead=True, only=None):
    H, V, w, B, r = p["H"], p["V"], p["w"], p["B"], p["r"]
    o, mu = (p["o"], p["mu"]) if overhead else (0.0, 0.0)
    mt = p["_mt"]
    q1 = {"day": w * V / r + w * o, "month": mt * 30 * V / r + mt * o, "bucket": H * V / r + B * o,
          "day_bucket": w * V / r + w * B * o}
    q2 = {"day": H * V / r + H * o, "month": H * V / r + (H / 30) * o, "bucket": H * V / B / r + o,
          "day_bucket": H * V / B / r + H * o}
    nparts = {"day": H, "month": H / 30, "bucket": B, "day_bucket": H * B}
    f1 = p["f1"] if only in (None, "q1") else 0
    f2 = p["f2"] if only in (None, "q2") else 0
    return {s: f1 * q1[s] + f2 * q2[s] + nparts[s] * mu for s in ORDER}


def _sample(rng):
    return {"H": rng.choice([180, 360, 720]), "V": rng.choice([1, 2, 5]), "w": rng.choice([1, 7, 14, 30]),
            "B": rng.choice([16, 32, 64]), "r": rng.choice([10, 20]), "o": rng.choice([0.02, 0.05, 0.2, 0.5]),
            "mu": rng.choice([0.0, 0.01, 0.05]), "f1": rng.choice([10, 50, 200, 1000]),
            "f2": rng.choice([5, 20, 60, 200])}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, who = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)

    def accept(p):
        p["_mt"] = _months_touched(p)
        full = _times(p)
        good = argmin_sep(full, 0.05)
        if good != target:
            return None
        no_over = argmin_sep(_times(p, overhead=False), 0.01)
        top = "q1" if p["f1"] * 1.0 >= p["f2"] else "q2"
        if p["f1"] == p["f2"]:
            return None
        top_only = argmin_sep(_times(p, only=top), 0.01)
        if None in (no_over, top_only):
            return None
        traps = {"no_overhead": no_over, "top_query_only": top_only, "fewest_parts": "month" if p["H"] / 30 < p["B"]
                 else "bucket"}
        if sum(1 for v in traps.values() if v != good) < 1:
            return None
        return good, full, traps

    p, (good, full, traps) = search(rng, _sample, accept)
    sec = lambda x: f"{fmt_num(x, 2)} с"
    stem = (f"Таблица {ctx}: {p['H']} {plural(p['H'], 'день', 'дня', 'дней')} истории по {p['V']} ГБ в день. За "
            f"сутки — {p['f1']} {plural(p['f1'], 'запрос', 'запроса', 'запросов')} «последние {p['w']} "
            f"{plural(p['w'], 'день', 'дня', 'дней')} по всем» и {p['f2']} {plural(p['f2'], 'запрос', 'запроса', 'запросов')} "
            f"«один {who} за всю историю». Время запроса = прочитанные ГБ / {p['r']} ГБ/с + открытые разделы × "
            f"{sec(p['o'])}; обслуживание (сжатие мелких файлов, метаданные) — {sec(p['mu'])} в сутки на раздел. Месяц "
            f"— 30 дней; окно «последние {p['w']} дн.» в среднем задевает {fmt_num(p['_mt'], 2)} раздела-месяца. "
            f"Схемы разделов: " + "; ".join(f"{NAMES[s]}" + (f" ({p['B']} {plural(p['B'], 'корзина', 'корзины', 'корзин')})" if s == "bucket" else "")
                                            for s in ORDER) +
            ".\n\nКакая схема даёт минимум суммарного времени кластера в сутки?")
    expl = ("Время в сутки = f1 × (ГБ / скорость + разделы × накладные) по окну + f2 × то же по клиенту + "
            "обслуживание разделов. По схемам: " + "; ".join(f"{NAMES[s]} — {fmt_num(full[s], 0)} с" for s in ORDER) +
            f". Минимум — {NAMES[good]}. Ловушки: без накладных на разделы — {NAMES[traps['no_overhead']]}; только "
            f"самый частый запрос — {NAMES[traps['top_query_only']]}; меньше всего разделов — "
            f"{NAMES[traps['fewest_parts']]}.")
    P = {k: v for k, v in p.items() if not k.startswith("_")}
    program = PROGRAM.format(P=P, names=NAMES)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[s] for s in ORDER if s != good], program=program, explanation=expl,
                       params={**P, "months_touched": round(p["_mt"], 4), "good": good,
                               **{f"trap_{k}": v for k, v in traps.items()}},
                       note="Ответ проверяется программой: отбор разделов по условию запроса и сумма времени.")
