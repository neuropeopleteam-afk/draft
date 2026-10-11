"""devops.sre.principal_slo_investment_mcq — mcq_concept (Principal): самое дешёвое вложение, которое выводит на SLO.

Путь запроса: балансировщик → k экземпляров приложения (достаточно одного живого) → основная БД и обязательный вызов
зависимой системы. Даны доступности звеньев за год, текущая доступность ниже цели SLO. Четыре меры, у каждой цена
в год: реплика БД с автоматическим переключением (переключение срабатывает с вероятностью f), кэш-фолбэк для
зависимости (при её отказе ответ из кэша с долей попаданий h), ещё один экземпляр приложения, второй балансировщик
в другой зоне (переключение с той же f). Какая мера ОДНА выводит на цель и дешевле остальных таких?

Ловушки: самая дешёвая мера (не выводит на цель), «самое слабое звено» (мера для звена с наибольшей
недоступностью), «наибольший прирост» (обычно самая дорогая), расчёт без вероятности неудачного переключения
(f = 1). Ответ выбирается по seed до подбора чисел — равновероятен среди четырёх мер; числа подобраны так, что
приближение «недоступности складываются» даёт тот же ответ, а доступность каждой меры отстоит от цели не меньше
чем на 0,005 п. п. Ключ проверяется исполнением: программа перебирает все состояния звеньев (живо/отказ, удалось
ли переключение, есть ли ответ в кэше) с их вероятностями, считает доступность пути для каждой меры и печатает
букву самой дешёвой из достигших цели.
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import ru_num
from assessment_bank.families._principal_b_kit import cap, search
from assessment_bank.families.common._lead_kit import numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.sre.principal_slo_investment_mcq"

CONTEXTS = [("оформление заказа", "сервис цен"), ("вход в личный кабинет", "сервис профилей"),
            ("оплату картой", "антифрод"), ("запись на приём", "расписание врачей"),
            ("поиск по каталогу", "сервис остатков"), ("отклик на вакансию", "сервис резюме"),
            ("бронирование столика", "сервис лояльности")]

NAMES = {"db": "реплика БД с автоматическим переключением", "cache": "кэш-фолбэк для зависимой системы",
         "app": "ещё один экземпляр приложения", "lb": "второй балансировщик в другой зоне"}
ORDER = ["db", "cache", "app", "lb"]

PROGRAM = """import itertools
opts = __OPTS__
P = {P!r}
target = {target}
cost = {cost!r}
names = {names!r}

def avail(measure):
    comps = [("lb", P["a_lb"]), ("lb2", P["a_lb"] if measure == "lb" else 0.0), ("lb_sw", P["f"]),
             ("db", P["a_db"]), ("db2", P["a_db"] if measure == "db" else 0.0), ("db_sw", P["f"]),
             ("dep", P["a_dep"]), ("hit", P["h"] if measure == "cache" else 0.0)]
    k = P["k"] + (1 if measure == "app" else 0)
    comps += [(f"app{{i}}", P["a_app"]) for i in range(k)]
    total = 0.0
    for state in itertools.product((True, False), repeat=len(comps)):
        pr = 1.0
        for (name, a), up in zip(comps, state):
            pr *= a if up else 1 - a
        if pr == 0.0:
            continue
        s = {{name: up for (name, _a), up in zip(comps, state)}}
        lb = s["lb"] or (s["lb2"] and s["lb_sw"])
        db = s["db"] or (s["db2"] and s["db_sw"])
        dep = s["dep"] or s["hit"]
        app = any(s[f"app{{i}}"] for i in range(k))
        if lb and db and dep and app:
            total += pr
    return total

ok = [m for m in cost if avail(m) >= target]
best = min(ok, key=lambda m: cost[m])
hit = [k for k, t in opts.items() if t == names[best]]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _avail(p, m, f=None):
    f = p["f"] if f is None else f
    a_lb = p["a_lb"] + (1 - p["a_lb"]) * p["a_lb"] * f if m == "lb" else p["a_lb"]
    a_db = p["a_db"] + (1 - p["a_db"]) * p["a_db"] * f if m == "db" else p["a_db"]
    a_dep = p["a_dep"] + (1 - p["a_dep"]) * p["h"] if m == "cache" else p["a_dep"]
    k = p["k"] + (1 if m == "app" else 0)
    return a_lb * (1 - (1 - p["a_app"]) ** k) * a_db * a_dep


def _approx(p, m):
    """Приближение «недоступности складываются» (как считает кандидат)."""
    f = p["f"]
    u_lb = (1 - p["a_lb"]) * ((1 - p["a_lb"] * f) if m == "lb" else 1)
    u_db = (1 - p["a_db"]) * ((1 - p["a_db"] * f) if m == "db" else 1)
    u_dep = (1 - p["a_dep"]) * ((1 - p["h"]) if m == "cache" else 1)
    u_app = (1 - p["a_app"]) ** (p["k"] + (1 if m == "app" else 0))
    return 1 - (u_lb + u_db + u_dep + u_app)


def _sample(rng):
    return {"a_lb": rng.choice([0.998, 0.999, 0.9995, 0.9999]), "a_app": rng.choice([0.95, 0.96, 0.97, 0.98, 0.99]),
            "k": rng.choice([2, 3]), "a_db": rng.choice([0.998, 0.999, 0.9995, 0.9998]),
            "a_dep": rng.choice([0.997, 0.998, 0.999, 0.9995]), "f": rng.choice([0.9, 0.95, 0.98]),
            "h": rng.choice([0.6, 0.75, 0.9]),
            "cost": {"db": rng.choice([4, 6, 9]), "cache": rng.choice([1, 2, 3, 5]),
                     "app": rng.choice([0.5, 1, 1.5]), "lb": rng.choice([0.8, 2, 3.5])},
            "target": rng.choice([0.997, 0.998, 0.9985, 0.999, 0.9992, 0.9995])}


def _pct(a: float) -> str:
    s = f"{100 * a:.3f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") + " %"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, dep = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)

    def accept(p):
        if len(set(p["cost"].values())) < 4 or _avail(p, None) >= p["target"]:
            return None
        av = {m: _avail(p, m) for m in ORDER}
        ap = {m: _approx(p, m) for m in ORDER}
        if any(abs(av[m] - p["target"]) < 5e-5 or abs(ap[m] - p["target"]) < 5e-5 for m in ORDER):
            return None
        if any((av[m] >= p["target"]) != (ap[m] >= p["target"]) for m in ORDER):
            return None
        ok = [m for m in ORDER if av[m] >= p["target"]]
        if not ok or len(ok) == 4:
            return None
        good = min(ok, key=lambda m: p["cost"][m])
        if good != target:
            return None
        cur = {"lb": 1 - p["a_lb"], "db": 1 - p["a_db"], "cache": 1 - p["a_dep"], "app": (1 - p["a_app"]) ** p["k"]}
        cheap = min(ORDER, key=lambda m: p["cost"][m])
        weakest = max(cur, key=cur.get)
        biggest = max(av, key=av.get)
        ok1 = [m for m in ORDER if _avail(p, m, f=1.0) >= p["target"]]
        no_f = min(ok1, key=lambda m: p["cost"][m])
        traps = {"cheap": cheap, "weakest": weakest, "biggest": biggest, "no_f": no_f}
        if sorted(cur.values())[-1] - sorted(cur.values())[-2] < 1e-4:
            return None
        if sum(1 for v in traps.values() if v != good) < 2:
            return None
        return good, av, traps

    p, (good, av, traps) = search(rng, _sample, accept)
    c = p["cost"]
    rows = [f"• {cap(NAMES['db'])} (переключение удаётся в {ru_num(round(100 * p['f']))} % отказов) — "
            f"{ru_num(c['db'])} млн ₽ в год;",
            f"• {cap(NAMES['cache'])}: при её отказе ответ берётся из кэша, попадание — "
            f"{ru_num(round(100 * p['h']))} % запросов — {ru_num(c['cache'])} млн ₽ в год;",
            f"• {cap(NAMES['app'])} ({p['k'] + 1} вместо {p['k']}) — {ru_num(c['app'])} млн ₽ в год;",
            f"• {cap(NAMES['lb'])} (переключение удаётся в {ru_num(round(100 * p['f']))} % отказов) — "
            f"{ru_num(c['lb'])} млн ₽ в год."]
    stem = (f"Цель SLO для сценария «{ctx}» — доступность {_pct(p['target'])} за год, сейчас её не достигаем. "
            f"Путь запроса: балансировщик (доступность {_pct(p['a_lb'])}) → {p['k']} экземпляра приложения, достаточно "
            f"одного живого (каждый — {_pct(p['a_app'])}) → основная БД ({_pct(p['a_db'])}) и обязательный вызов "
            f"системы «{dep}» ({_pct(p['a_dep'])}). Отказы звеньев независимы. Бюджет — на одну меру:\n" +
            "\n".join(rows) + "\n\nКакая мера одна выводит на цель SLO и дешевле остальных таких?")
    cur = _avail(p, None)
    expl = (f"Сейчас ≈ {_pct(cur)}: недоступности звеньев складываются — балансировщик {_pct(1 - p['a_lb'])}, "
            f"приложение {_pct((1 - p['a_app']) ** p['k'])}, БД {_pct(1 - p['a_db'])}, «{dep}» {_pct(1 - p['a_dep'])}. "
            "С мерой: " + "; ".join(f"{NAMES[m]} — {_pct(av[m])}" for m in ORDER) +
            f". Цели {_pct(p['target'])} достигают: {', '.join(NAMES[m] for m in ORDER if av[m] >= p['target'])}; "
            f"самая дешёвая из них — {NAMES[good]}. Ловушки: самая дешёвая мера — {NAMES[traps['cheap']]}; самое "
            f"слабое звено — {NAMES[traps['weakest']]}; наибольший прирост — {NAMES[traps['biggest']]}; без вероятности "
            f"неудачного переключения — {NAMES[traps['no_f']]}.")
    P = {k: v for k, v in p.items() if k not in ("cost", "target")}
    program = PROGRAM.format(P=P, target=p["target"], cost=c, names=NAMES)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[m] for m in ORDER if m != good], program=program, explanation=expl,
                       params={**P, **{f"cost_{k}": v for k, v in c.items()}, "target": p["target"], "good": good,
                               **{f"trap_{k}": v for k, v in traps.items()}},
                       note="Ответ проверяется программой: перебор всех состояний звеньев с вероятностями.")
