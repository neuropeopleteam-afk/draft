"""security.principal.fix_order_mcq — mcq_concept (Principal): очерёдность исправления уязвимостей по ожидаемому ущербу.

Одна команда исправляет уязвимости по очереди; пока уязвимость открыта, она даёт ожидаемый ущерб в неделю
r = p × D (p — вероятность эксплуатации за неделю, D — ущерб при эксплуатации); для одной уязвимости уже действует
компенсирующая мера (правило межсетевого экрана приложений), снижающая p в m раз. Суммарный ожидаемый ущерб до
закрытия всех уязвимостей — Σ rᵢ · Cᵢ (Cᵢ — неделя завершения исправления). Минимум даёт порядок по убыванию
rᵢ / eᵢ (правило Смита; e — трудоёмкость, недели).

Дистракторы (фиксированный состав, все — разные порядки): ``cvss`` — по убыванию оценки CVSS; ``risk`` — по
убыванию ожидаемого ущерба в неделю без учёта трудоёмкости; ``no_control`` — по rᵢ / eᵢ, но без учёта
компенсирующей меры. Ключ проверяется исполнением: программа перебирает все 120 порядков и печатает лучший.
"""
from __future__ import annotations

from itertools import permutations

from assessment_bank.families._lead_b_utils import computed_mcq, ru_num
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "security.principal.fix_order_mcq"

CONTEXTS = ["платёжный шлюз", "интернет-банк", "портал поставщиков", "сервис телемедицины", "кабинет страхователя",
            "маркетплейс", "сервис электронных подписей", "учебная платформа"]
KINDS = ["обход авторизации в API отчётов", "внедрение SQL в поиске заказов", "подделка запросов сервером (SSRF) при загрузке "
         "по ссылке", "устаревшая библиотека разбора XML", "небезопасная десериализация в очереди задач",
         "открытый административный интерфейс", "слабая проверка подписи вебхуков", "утечка токенов в журналах",
         "перебор паролей без ограничения частоты", "хранимый XSS в комментариях"]
NAMES = ["У1", "У2", "У3", "У4", "У5"]

PROGRAM = '''from fractions import Fraction
from itertools import permutations

# имя: (вероятность эксплуатации за неделю, %, ущерб, млн руб., трудоёмкость, недель, во сколько раз мера снижает p)
V = {data!r}


def rate(v):
    p, dmg, _, m = V[v]
    return Fraction(p, 100) * dmg / m


def loss(order):
    t, total = 0, Fraction(0)
    for v in order:
        t += V[v][2]
        total += rate(v) * t   # уязвимость приносит ущерб, пока не закрыта
    return total


best = min(permutations(V), key=loss)
print(" → ".join(best))
'''


def _order_text(order) -> str:
    return " → ".join(order)


def _build(rng):
    kinds = rng.sample(KINDS, 5)
    vs = {}
    for n, k in zip(NAMES, kinds):
        vs[n] = dict(kind=k, p=rng.choice([1, 2, 3, 4, 5, 6, 8, 10]), d=rng.choice([2, 3, 5, 8, 12, 20, 30]),
                     e=rng.choice([1, 2, 3, 4, 6]), m=1)
    cvss = rng.sample([5.3, 6.1, 6.5, 7.2, 7.5, 8.1, 8.8, 9.1, 9.8], 5)
    for n, c in zip(NAMES, cvss):
        vs[n]["cvss"] = c
    ctl = rng.choice(NAMES)
    vs[ctl]["m"] = rng.choice([4, 5, 10])
    return vs, ctl


def _rate(v, with_control=True):
    return v["p"] * v["d"] * 10 / (v["m"] if with_control else 1)   # тыс. руб. в неделю


def _loss(vs, order):
    t, total = 0, 0.0
    for n in order:
        t += vs[n]["e"]
        total += _rate(vs[n]) * t
    return total


def _solve(vs):
    losses = sorted((_loss(vs, o), o) for o in permutations(NAMES))
    if losses[1][0] - losses[0][0] < 1e-9:
        return None
    good = losses[0][1]
    ratios = {n: _rate(v) / v["e"] for n, v in vs.items()}
    if len(set(ratios.values())) < 5 or tuple(sorted(NAMES, key=lambda n: -ratios[n])) != good:
        return None
    cv = tuple(sorted(NAMES, key=lambda n: -vs[n]["cvss"]))
    rk = [_rate(v) for v in vs.values()]
    if len(set(rk)) < 5:
        return None
    risk = tuple(sorted(NAMES, key=lambda n: -_rate(vs[n])))
    nc_r = {n: _rate(v, False) / v["e"] for n, v in vs.items()}
    if len(set(nc_r.values())) < 5:
        return None
    nc = tuple(sorted(NAMES, key=lambda n: -nc_r[n]))
    orders = [good, cv, risk, nc]
    if len(set(orders)) != 4:
        return None
    # ошибка должна стоить заметно: каждый неверный порядок хуже лучшего хотя бы на 5 %
    if min(_loss(vs, o) for o in orders[1:]) < 1.05 * _loss(vs, good):
        return None
    # верный порядок не «центральный» среди вариантов: у какого-то дистрактора совпадений позиций с остальными
    # не меньше (иначе его можно угадать по сходству вариантов, не решая задачу)
    def agree(a, b):
        return sum(x == y for x, y in zip(a, b))

    score = [sum(agree(o, u) for u in orders if u is not o) for o in orders]
    if max(score[1:]) < score[0]:
        return None
    return good, cv, risk, nc


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    for _ in range(3000):
        vs, ctl = _build(rng)
        res = _solve(vs)
        if res is not None:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось построить вариант")
    good, cv, risk, nc = res
    rows = ["имя | уязвимость | CVSS | p за неделю | ущерб при эксплуатации | трудоёмкость исправления"]
    for n, v in vs.items():
        rows.append(f"{n} | {v['kind']} | {ru_num(v['cvss'])} | {v['p']} % | {v['d']} млн руб. | {v['e']} нед.")
    code = "\n".join(rows)
    m = vs[ctl]["m"]
    stem = (f"{ctx.capitalize()}: аудит нашёл пять уязвимостей (таблица). Исправляет одна команда, по одной "
            f"уязвимости за раз, трудоёмкость — в неделях работы команды. Для {ctl} уже включено правило межсетевого "
            f"экрана приложений: оно снижает вероятность эксплуатации в {m} {plural(m, 'раз', 'раза', 'раз')} (в таблице — вероятность без "
            f"правила). Пока уязвимость открыта, каждую неделю она может быть эксплуатирована с указанной "
            f"вероятностью. В каком порядке исправлять, чтобы суммарный ожидаемый ущерб до закрытия всех пяти был "
            f"наименьшим?")
    parts = []
    for n, v in vs.items():
        r = _rate(v)
        parts.append(f"{n}: {ru_num(round(r, 2))} тыс. руб./нед ÷ {v['e']} = {ru_num(round(r / v['e'], 2))}")

    def lt(o):
        return ru_num(round(_loss(vs, o) / 1000, 2))

    why = (f"Пока уязвимость открыта, она даёт ожидаемый ущерб r = p × D в неделю (для {ctl} — с учётом правила, "
           f"p ÷ {m}); суммарный ущерб — Σ r × неделя закрытия. Перестановка соседних уязвимостей показывает, что "
           f"первой выгоднее та, у которой больше r ÷ трудоёмкость (правило Смита): {'; '.join(parts)}. Порядок "
           f"{_order_text(good)} — ожидаемый ущерб {lt(good)} млн руб. По CVSS ({_order_text(cv)}) — {lt(cv)} млн "
           f"руб.: оценка CVSS описывает тяжесть, а не вероятность и ущерб в этой системе. По наибольшему ущербу "
           f"в неделю без трудоёмкости ({_order_text(risk)}) — {lt(risk)} млн руб.: долгое исправление держит "
           f"открытыми остальные. Без учёта правила ({_order_text(nc)}) — {lt(nc)} млн руб.: компенсирующая мера "
           f"уже снизила риск {ctl}. Перебор всех 120 порядков подтверждает ключ.")
    data = {n: (v["p"], v["d"], v["e"], v["m"]) for n, v in vs.items()}
    return computed_mcq(FAMILY_ID, seed, rng, stem=stem, correct=_order_text(good),
                        distractors=[_order_text(cv), _order_text(risk), _order_text(nc)],
                        program=PROGRAM.format(data=data), why=why, context=ctx, code=code, language="text",
                        note="Программа перебирает все 120 порядков исправления по тем же числам (точные дроби) "
                             "и печатает порядок с наименьшим ожидаемым ущербом.",
                        params={"control": ctl, "m": m})
