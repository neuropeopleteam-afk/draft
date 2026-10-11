"""devops.release.principal_db_cutover_mcq — mcq_concept (Principal): способ переезда базы под допуски простоя.

Переезд базы S ГБ на новый кластер. Допуски бизнеса: полный простой (нет ни чтения, ни записи) — не больше Dfull
минут, запрет записи (чтение работает) — не больше Dwrite минут. Способы с ценой (работа команды и лицензии):
«остановить и скопировать» — всё копирование при полном простое на скорости r_fast; «только чтение на время копии»
— копия на скорости r_online (идёт параллельно с трафиком), всё это время запись запрещена, переключение — t_sw
минут полного простоя; репликация изменений (CDC) — начальная копия без простоя, затем поток изменений, переключение
— t_cdc минут запрета записи; но поток применяется со скоростью a МБ/с, и при записи W МБ/с ≥ a отставание растёт
и переключиться нельзя; двойная запись из приложения — без простоя, самая дорогая. Какой способ один укладывается в
оба допуска и дешевле остальных таких?

Ловушки: самый дешёвый способ, «без простоя» (двойная запись), CDC без проверки скорости применения, «чтение
работает — значит не простой» (запрет записи не учтён). Ответ выбирается по seed до подбора чисел — равновероятен
среди четырёх; отличается хотя бы от одной ловушки (у средних — хотя бы от двух); простои отстоят от допусков не
меньше чем на 5 %. Ключ проверяется исполнением: программа считает полный простой и запрет записи каждого способа
и печатает букву самого дешёвого допустимого.
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import ru_num
from assessment_bank.families._principal_b_kit import cap, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "devops.release.principal_db_cutover_mcq"

CONTEXTS = ["база заказов интернет-магазина", "база счетов биллинга", "база профилей пользователей",
            "база бронирований", "база откликов на вакансии", "база платёжных операций", "база складских остатков"]
NAMES = {"stop": "остановить сервис и скопировать", "readonly": "только чтение на время копии",
         "cdc": "репликация изменений (CDC) и короткое переключение", "dual": "двойная запись из приложения"}
ORDER = ["stop", "readonly", "cdc", "dual"]

PROGRAM = """opts = __OPTS__
P = {P!r}
cost = {cost!r}
names = {names!r}

def windows(way):                    # (полный простой, запрет записи) в минутах; None — способ невозможен
    copy_fast = P["S"] * 1024 / P["r_fast"] / 60
    copy_online = P["S"] * 1024 / P["r_online"] / 60
    if way == "stop":
        return copy_fast, copy_fast
    if way == "readonly":
        return P["t_sw"], copy_online + P["t_sw"]
    if way == "cdc":
        if P["W"] >= P["a"]:
            return None              # отставание растёт — догнать нельзя
        return 0.0, P["t_cdc"]
    return 0.0, 0.0

def ok(way):
    w = windows(way)
    return w is not None and w[0] <= P["Dfull"] + 1e-9 and w[1] <= P["Dwrite"] + 1e-9

good = min((w for w in cost if ok(w)), key=lambda w: cost[w])
hit = [k for k, t in opts.items() if t == names[good]]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _win(p, way, *, ignore_apply=False):
    fast = p["S"] * 1024 / p["r_fast"] / 60
    online = p["S"] * 1024 / p["r_online"] / 60
    if way == "stop":
        return fast, fast
    if way == "readonly":
        return p["t_sw"], online + p["t_sw"]
    if way == "cdc":
        if p["W"] >= p["a"] and not ignore_apply:
            return None
        return 0.0, p["t_cdc"]
    return 0.0, 0.0


def _ok(p, way, *, ignore_apply=False, ignore_write=False):
    w = _win(p, way, ignore_apply=ignore_apply)
    if w is None:
        return False
    return w[0] <= p["Dfull"] and (ignore_write or w[1] <= p["Dwrite"])


def _sample(rng):
    return {"S": rng.choice([50, 200, 500, 1000, 3000]), "r_fast": rng.choice([200, 400, 800]),
            "r_online_share": rng.choice([0.25, 0.4, 0.6]), "t_sw": rng.choice([2, 5]), "t_cdc": rng.choice([1, 2]),
            "W": rng.choice([5, 10, 20, 40]), "a": rng.choice([8, 15, 30, 60]),
            "Dfull": rng.choice([5, 15, 30, 60, 120]), "Dwrite_x": rng.choice([1, 2, 4, 8]),
            "cost": {"stop": rng.choice([0.3, 0.5]), "readonly": rng.choice([0.8, 1.2]),
                     "cdc": rng.choice([2.0, 3.0]), "dual": rng.choice([5.0, 8.0])}}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)

    def accept(p):
        p["r_online"] = int(p["r_fast"] * p["r_online_share"])
        p["Dwrite"] = p["Dfull"] * p["Dwrite_x"]
        wins = {w: _win(p, w) for w in ORDER}
        for w in wins.values():
            if w is None:
                continue
            for x, lim in ((w[0], p["Dfull"]), (w[1], p["Dwrite"])):
                if x and abs(x - lim) < 0.05 * lim:
                    return None
        if abs(p["W"] - p["a"]) < 0.1 * p["a"]:
            return None
        ok = [w for w in ORDER if _ok(p, w)]
        if not ok or len(ok) == 4:
            return None
        good = min(ok, key=lambda w: p["cost"][w])
        if good != target:
            return None
        cheap = min(ORDER, key=lambda w: p["cost"][w])
        ok_ia = [w for w in ORDER if _ok(p, w, ignore_apply=True)]
        ok_iw = [w for w in ORDER if _ok(p, w, ignore_write=True)]
        traps = {"cheap": cheap, "zero_downtime": "dual", "ignore_apply": min(ok_ia, key=lambda w: p["cost"][w]),
                 "ignore_write_ban": min(ok_iw, key=lambda w: p["cost"][w])}
        need = 1 if good in ("stop", "dual") else 2
        if sum(1 for v in traps.values() if v != good) < need:
            return None
        return good, wins, traps

    p, (good, wins, traps) = search(rng, _sample, accept)
    c = p["cost"]
    mins = lambda x: f"{ru_num(x)} {plural(int(x), 'минута', 'минуты', 'минут')}"
    rows = [f"• {cap(NAMES['stop'])}: копия на {p['r_fast']} МБ/с при полном простое — {fmt_num(c['stop'], 1)} млн ₽;",
            f"• {cap(NAMES['readonly'])}: копия на {p['r_online']} МБ/с параллельно с трафиком, всё это время запись "
            f"запрещена, затем {mins(p['t_sw'])} полного простоя на переключение — {fmt_num(c['readonly'], 1)} млн ₽;",
            f"• {cap(NAMES['cdc'])}: начальная копия без простоя, поток изменений применяется на {p['a']} МБ/с, "
            f"переключение — {mins(p['t_cdc'])} запрета записи — {fmt_num(c['cdc'], 1)} млн ₽;",
            f"• {cap(NAMES['dual'])}: без простоя — {fmt_num(c['dual'], 1)} млн ₽."]
    intro = rng.choice(["Переезд: {ctx}, {S} ГБ, на новый кластер", "Нужно перенести на новый кластер: {ctx}, {S} ГБ",
                        "Платформа меняет кластер СУБД; переезжает {ctx} ({S} ГБ)"]).format(ctx=ctx, S=fmt_num(p["S"], 0))
    stem = (f"{intro}; в часы переезда приложение пишет ≈ {p['W']} МБ/с изменений. Допуски: полный простой (нет ни чтения, ни записи) — не больше {mins(p['Dfull'])}, запрет "
            f"записи (чтение работает) — не больше {mins(p['Dwrite'])} суммарно. Способы:\n" + "\n".join(rows) +
            "\n\n1 ГБ = 1024 МБ. Какой способ один укладывается в оба допуска и дешевле остальных таких?")

    def show(w):
        x = wins[w]
        if x is None:
            return f"невозможно — запись {p['W']} МБ/с не меньше скорости применения {p['a']} МБ/с"
        return f"простой {fmt_num(x[0], 1)} мин, запрет записи {fmt_num(x[1], 1)} мин"
    expl = ("Полный простой и запрет записи по способам: " + "; ".join(f"{NAMES[w]} — {show(w)}" for w in ORDER) +
            f". Допуски {ru_num(p['Dfull'])} и {ru_num(p['Dwrite'])} мин выполняют: "
            f"{', '.join(NAMES[w] for w in ORDER if _ok(p, w))}; дешевле — {NAMES[good]}. Ловушки: самый дешёвый — "
            f"{NAMES[traps['cheap']]}; «без простоя» — {NAMES['dual']}; CDC без проверки скорости применения — "
            f"{NAMES[traps['ignore_apply']]}; без учёта запрета записи — {NAMES[traps['ignore_write_ban']]}.")
    P = {k: v for k, v in p.items() if k not in ("cost", "r_online_share", "Dwrite_x")}
    program = PROGRAM.format(P=P, cost=c, names=NAMES)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[w] for w in ORDER if w != good], program=program, explanation=expl,
                       params={**P, **{f"cost_{k}": v for k, v in c.items()}, "good": good,
                               **{f"trap_{k}": v for k, v in traps.items()}},
                       note="Ответ проверяется программой: полный простой и запрет записи по способам.")
