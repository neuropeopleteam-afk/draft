"""common.strategy.principal_exit_option_mcq — mcq_concept (Principal, короткое): цена зависимости от поставщика.

Выбор платформы на горизонте H лет с риском, что поставщик поднимет цены или уйдёт с рынка (вероятность p в год,
событие происходит не больше одного раза; после него нужно переезжать). Четыре варианта:
  * проприетарный управляемый сервис — самая низкая эксплуатация, дорогой переезд M_prop;
  * управляемый сервис со стандартным интерфейсом — эксплуатация чуть дороже, переезд M_std;
  * своя установка открытого решения — эксплуатация дороже (люди), переезд не нужен (событие не касается);
  * свой слой совместимости над несколькими поставщиками — доплата за слой каждый год, переезд M_abs (дешёвый).
Ожидаемая цена = Σ по годам эксплуатация + Σ по годам P(событие в этом году) · цена переезда (после переезда
эксплуатация не меняется — для простоты).

Ловушки: «дешевле в эксплуатации» (без риска), «минимальный риск» (слой совместимости), «худший случай» (событие
наверняка). Верный вариант распределён поровну по четырём и отличается хотя бы от двух ловушек (если верна сама
ловушка — хотя бы от одной). Ключ проверяется исполнением: программа перебирает все 2^H исходов по годам («событие
было / не было», с весами вероятности; учитывается только первое событие) и печатает букву минимума.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "common.strategy.principal_exit_option_mcq"

CONTEXTS = [("очередь сообщений", "брокер"), ("база данных документов", "СУБД"), ("поиск по каталогу", "поисковый движок"),
            ("хранилище файлов", "объектное хранилище"), ("распознавание речи", "сервис распознавания"),
            ("аналитическое хранилище", "аналитическую СУБД"), ("отправка уведомлений", "сервис рассылок")]
NAMES = {"prop": "проприетарный управляемый сервис", "std": "управляемый сервис со стандартным интерфейсом",
         "self": "своя установка открытого решения", "abs": "свой слой совместимости над поставщиками"}
ORDER = ["prop", "std", "self", "abs"]

PROGRAM = """from itertools import product
opts = __OPTS__
H, p = {H}, {p}
plans = {plans!r}       # подпись -> (эксплуатация, млн ₽ в год; цена переезда, млн ₽)
cost = {{}}
for label, (run, move) in plans.items():
    exp = run * H
    for years in product([0, 1], repeat=H):        # 1 — в этом году поставщик поднял цены или ушёл
        w = 1.0
        for e in years:
            w *= p if e else 1 - p
        if any(years):
            exp += w * move                         # переезжаем один раз — после первого события
    cost[label] = exp
best = min(cost, key=cost.get)
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _argmin(d, rel=0.04):
    v = sorted(d.values())
    return min(d, key=d.get) if v[1] - v[0] >= rel * v[1] else None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, kind = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)
    for _ in range(60000):
        H = rng.choice([3, 4, 5])
        p = rng.choice([0.05, 0.1, 0.15, 0.2, 0.3])
        run_prop = rng.choice([10, 15, 20, 30])
        run = {"prop": run_prop, "std": round(run_prop * rng.choice([1.1, 1.2, 1.3]), 1),
               "self": round(run_prop * rng.choice([1.4, 1.7, 2.0]), 1),
               "abs": round(run_prop * rng.choice([1.0, 1.1, 1.2]) + rng.choice([3, 5, 8]), 1)}
        move = {"prop": rng.choice([40, 60, 90, 120]), "std": rng.choice([10, 15, 25]), "self": 0,
                "abs": rng.choice([3, 5, 8])}
        q = 1 - (1 - p) ** H                               # вероятность хотя бы одного события за горизонт
        full = {k: run[k] * H + q * move[k] for k in ORDER}
        good = _argmin(full)
        if good != target:
            continue
        worst = _argmin({k: run[k] * H + move[k] for k in ORDER})
        if worst is None:
            continue
        cheapest = min(ORDER, key=lambda k: (run[k], ORDER.index(k)))
        traps = (cheapest, "abs", worst)
        if sum(t != good for t in traps) >= (1 if good in (cheapest, "abs") else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    hy = plural(H, "год", "года", "лет")
    cap = lambda t: t[0].upper() + t[1:]
    rows = [f"• {cap(NAMES['prop'])}: эксплуатация {fmt_num(run['prop'], 1)} млн ₽ в год; переезд — "
            f"{move['prop']} млн ₽ (свой интерфейс, данные и код придётся переделать).",
            f"• {cap(NAMES['std'])}: эксплуатация {fmt_num(run['std'], 1)} млн ₽ в год; переезд к другому "
            f"поставщику — {move['std']} млн ₽.",
            f"• {cap(NAMES['self'])}: эксплуатация {fmt_num(run['self'], 1)} млн ₽ в год (с людьми); от поставщика не "
            f"зависит.",
            f"• {cap(NAMES['abs'])}: эксплуатация {fmt_num(run['abs'], 1)} млн ₽ в год (с поддержкой слоя); "
            f"переключение — {move['abs']} млн ₽."]
    intro = rng.choice([
        f"Вы — главный инженер. Для задачи «{ctx}» выбирают {kind} на {H} {hy}.",
        f"Архитектурный совет выбирает {kind} для задачи «{ctx}» на {H} {hy}; решение — за вами как за главным "
        f"инженером.",
        f"Для задачи «{ctx}» нужно выбрать {kind} на {H} {hy}; закупка просит главного инженера решить.",
    ])
    stem = (f"{intro} По оценке закупки, каждый год с вероятностью {fmt_num(100 * p, 0)} % поставщик управляемого "
            f"сервиса резко поднимет цены или уйдёт с рынка — тогда придётся переезжать (один раз; цена "
            f"эксплуатации после переезда та же). Варианты:\n" + "\n".join(rows) +
            f"\n\nКакой вариант даёт минимальную ожидаемую цену за {H} {hy} (эксплуатация и ожидаемый переезд)?")
    expl = (f"Ожидаемая цена = эксплуатация × {H} + P(хотя бы одно событие за {H} {hy}) × цена переезда; P = 1 − (1 − "
            f"{fmt_num(p, 2)})^{H} = {fmt_num(100 * q, 1)} %. Итоги: " +
            "; ".join(f"{NAMES[k]} — {fmt_num(full[k], 1)} млн ₽" for k in ORDER) +
            f". Минимум — {NAMES[good]}. Ловушки: дешевле в эксплуатации — {NAMES[cheapest]}, «минимальный риск» — "
            f"{NAMES['abs']}, худший случай (событие наверняка) — {NAMES[worst]}.")
    program = PROGRAM.format(H=H, p=p, plans={NAMES[k]: (run[k], move[k]) for k in ORDER})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={"H": H, "p": p, "good": good, "worst": worst, "cheapest": cheapest,
                               **{f"run_{k}": run[k] for k in ORDER}, **{f"move_{k}": move[k] for k in ORDER}},
                       note="Ответ проверяется программой: перебор исходов по годам с весами вероятности.")
