"""devops.cloud.principal_region_topology_mcq — mcq_concept (Principal): топология регионов под SLO и бюджет задержки.

Сервис в одном регионе на трёх зонах. Отказы региона — n раз в год по D часов; собственный простой приложения — B
минут в год при любой топологии. Четыре топологии с ценой в год: один регион на трёх зонах (простой — весь отказ
региона); холодный резерв во втором регионе (подъём из резервных копий за RTO_cold часов); тёплый резерв (переключение
за RTO_warm минут); активный–активный в двух регионах (отказ региона — минута-две ошибок на переключение трафика,
но синхронная запись между регионами добавляет L мс к p99 записи). Нужна доступность не ниже SLO и p99 записи не
выше бюджета. Какая топология одна выполняет оба требования и дешевле остальных таких?

Ловушки: самая дешёвая топология; самая доступная (активный–активный); без бюджета задержки; «переключение
мгновенное» (RTO не учтён — холодный резерв не хуже тёплого). Цены — не по возрастанию надёжности: тёплый резерв
держит простаивающую мощность и бывает дороже активного–активного. Ответ выбирается по seed до подбора чисел —
равновероятен среди четырёх; отличается хотя бы от двух ловушек (один регион — хотя бы от одной); простой каждой топологии отстоит от допустимого
не меньше чем на 5 %. Ключ проверяется исполнением: программа считает минуты простоя в год и p99 записи для каждой
топологии и печатает букву самой дешёвой допустимой.
"""
from __future__ import annotations

from assessment_bank.families._principal_b_kit import cap, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "devops.cloud.principal_region_topology_mcq"

CONTEXTS = ["платёжный шлюз", "сервис бронирования", "личный кабинет банка", "API приёма заказов",
            "сервис авторизации", "платформа онлайн-записи к врачам", "сервис откликов на вакансии"]
NAMES = {"single": "один регион на трёх зонах", "cold": "холодный резерв во втором регионе",
         "warm": "тёплый резерв во втором регионе", "aa": "активный–активный в двух регионах"}
ORDER = ["single", "cold", "warm", "aa"]
MIN_YEAR = 525600

PROGRAM = """opts = __OPTS__
P = {P!r}
cost = {cost!r}
names = {names!r}
allowed = (1 - P["slo"] / 100) * 525600          # минут простоя в год по SLO

def downtime(t):                                 # минут в год
    per_outage = {{"single": P["D"] * 60, "cold": min(P["D"], P["rto_cold"]) * 60,
                   "warm": min(P["D"] * 60, P["rto_warm"]), "aa": P["blip"]}}[t]
    return P["B"] + P["n"] * per_outage

def p99(t):
    return P["p99"] + (P["L"] if t == "aa" else 0)

ok = [t for t in cost if downtime(t) <= allowed + 1e-9 and p99(t) <= P["p99_max"]]
best = min(ok, key=lambda t: cost[t])
hit = [k for k, x in opts.items() if x == names[best]]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _down(p, t, *, instant=False):
    if instant and t in ("cold", "warm"):
        return p["B"] + p["n"] * p["blip"]
    per = {"single": p["D"] * 60, "cold": min(p["D"], p["rto_cold"]) * 60, "warm": min(p["D"] * 60, p["rto_warm"]),
           "aa": p["blip"]}[t]
    return p["B"] + p["n"] * per


def _sample(rng):
    C = rng.choice([20, 40, 80])
    w = rng.choice([0.3, 0.5, 1.0])
    h = rng.choice([0.6, 0.75])
    return {"n": rng.choice([0.5, 1, 2]), "D": rng.choice([2, 4, 8]), "B": rng.choice([20, 30, 45, 90, 150, 240]),
            "slo": rng.choice([99.9, 99.95, 99.99]), "rto_cold": rng.choice([2, 3]), "rto_warm": rng.choice([10, 20, 30]),
            "blip": 2, "p99": rng.choice([80, 120, 200]), "p99_room": rng.choice([20, 40, 80]),
            "L": rng.choice([30, 60, 90]), "C": C,
            "cost": {"single": float(C), "cold": round(C * rng.choice([1.03, 1.06]), 1), "warm": round(C * (1 + w), 1),
                     "aa": round(C * (2 * h + rng.choice([0.05, 0.1])), 1)}}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)

    def accept(p):
        if len(set(p["cost"].values())) < 4:
            return None
        p["p99_max"] = p["p99"] + p["p99_room"]
        allowed = (1 - p["slo"] / 100) * MIN_YEAR
        down = {t: _down(p, t) for t in ORDER}
        if any(abs(d - allowed) < 0.05 * allowed for d in down.values()) or p["L"] == p["p99_room"]:
            return None
        lat_ok = {t: (p["p99"] + (p["L"] if t == "aa" else 0)) <= p["p99_max"] for t in ORDER}
        ok = [t for t in ORDER if down[t] <= allowed and lat_ok[t]]
        if not ok or len(ok) == 4:
            return None
        good = min(ok, key=lambda t: p["cost"][t])
        if good != target:
            return None
        cheap = min(ORDER, key=lambda t: p["cost"][t])
        ok_nl = [t for t in ORDER if down[t] <= allowed]
        ok_in = [t for t in ORDER if _down(p, t, instant=True) <= allowed and lat_ok[t]]
        if not ok_in:
            return None
        traps = {"cheap": cheap, "most_available": "aa", "no_latency": min(ok_nl, key=lambda t: p["cost"][t]),
                 "instant_failover": min(ok_in, key=lambda t: p["cost"][t])}
        if sum(1 for v in traps.values() if v != good) < (1 if good == "single" else 2):
            return None
        return good, down, allowed, traps

    p, (good, down, allowed, traps) = search(rng, _sample, accept)
    c = p["cost"]
    hours = lambda x: f"{fmt_num(x, 0)} {plural(int(x), 'час', 'часа', 'часов')}"
    mins = lambda x: f"{fmt_num(x, 0)} {plural(int(x), 'минута', 'минуты', 'минут')}"
    times = {0.5: "раз в два года", 1: "раз в год", 2: "два раза в год"}[p["n"]]
    rows = [f"• {cap(NAMES['single'])} — при отказе региона сервис лежит весь отказ; {fmt_num(c['single'], 1)} млн ₽;",
            f"• {cap(NAMES['cold'])} — подъём из резервных копий за {hours(p['rto_cold'])}; {fmt_num(c['cold'], 1)} млн ₽;",
            f"• {cap(NAMES['warm'])} — переключение за {mins(p['rto_warm'])}; {fmt_num(c['warm'], 1)} млн ₽;",
            f"• {cap(NAMES['aa'])} — при отказе региона ≈ {mins(p['blip'])} ошибок на переключение трафика, но "
            f"синхронная запись между регионами добавляет {p['L']} мс к p99 записи; {fmt_num(c['aa'], 1)} млн ₽."]
    stem = (f"{cap(ctx)} сейчас работает в одном регионе на трёх зонах. Отказ региона целиком случается ≈ {times} и "
            f"длится ≈ {hours(p['D'])}; собственный простой приложения — ≈ {mins(p['B'])} в год при любой топологии. "
            f"Требования: доступность не ниже {fmt_num(p['slo'], 2)} % за год и p99 записи не выше {p['p99_max']} мс "
            f"(сейчас {p['p99']} мс). Топологии (цена в год):\n" + "\n".join(rows) +
            "\n\nКакая топология одна выполняет оба требования и дешевле остальных таких?")
    expl = (f"По SLO допустимо {fmt_num(allowed, 0)} мин простоя в год. Простой: " +
            "; ".join(f"{NAMES[t]} — {fmt_num(down[t], 0)} мин" for t in ORDER) +
            f"; p99 записи у активного–активного — {p['p99'] + p['L']} мс при бюджете {p['p99_max']} мс. Оба требования "
            f"выполняют: {', '.join(NAMES[t] for t in ORDER if down[t] <= allowed and (t != 'aa' or p['p99'] + p['L'] <= p['p99_max']))}; "
            f"дешевле — {NAMES[good]}. Ловушки: самая дешёвая — {NAMES[traps['cheap']]}; самая доступная — {NAMES['aa']}; "
            f"без бюджета задержки — {NAMES[traps['no_latency']]}; «переключение мгновенное» — "
            f"{NAMES[traps['instant_failover']]}.")
    P = {k: v for k, v in p.items() if k not in ("cost", "p99_room")}
    program = PROGRAM.format(P=P, cost=c, names=NAMES)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[t] for t in ORDER if t != good], program=program, explanation=expl,
                       params={**P, **{f"cost_{k}": v for k, v in c.items()}, "good": good,
                               **{f"trap_{k}": v for k, v in traps.items()}},
                       note="Ответ проверяется программой: минуты простоя в год и p99 записи по топологиям.")
