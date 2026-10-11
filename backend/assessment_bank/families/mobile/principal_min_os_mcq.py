"""mobile.principal.min_os_mcq — mcq_concept (Principal, короткое): до какой версии ОС поднять минимальную
поддерживаемую, чтобы годовая выгода (сэкономленная поддержка минус потерянная выручка) была наибольшей.

Даны доли активных пользователей по версиям ОС, годовая стоимость поддержки каждой старой версии (обходные пути,
тестовые устройства, сборки), выручка на пользователя в год и доля пользователей отключаемых версий, которые
обновят ОС или перейдут в веб (их выручка сохраняется). Выгода от минимальной версии m:
Σ_{v < m} (стоимость_v − N · доля_v · (1 − u) · ARPU). Ключ — лучший из четырёх вариантов (оставить как есть или
поднять на 1–3 версии); какой по счёту вариант верный, задаётся по seed поровну, числа подбираются под него.
Ошибки, ведущие к другим вариантам: без доли обновившихся (u = 0), считать, что уходят все и выручка не теряется
(только экономия), выбирать по доле пользователей «меньше 5 %». Ключ проверяется исполнением: программа считает
выгоду каждого варианта по показанной таблице.
"""
from __future__ import annotations

from assessment_bank.families._principal_c_utils import choice_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.principal.min_os_mcq"

CONTEXTS = ["мобильный банк", "приложение доставки еды", "приложение такси", "маркетплейс", "приложение кинотеатра",
            "приложение авиакомпании", "приложение сети аптек", "приложение каршеринга"]
PLATFORMS = [("Android", [8, 9, 10, 11, 12, 13, 14]), ("iOS", [13, 14, 15, 16, 17, 18])]

PROGRAM = """{table}
N, ARPU, U = {N}, {arpu}, {u}          # пользователей, ₽ в год на пользователя, доля сохранившихся (из 100)
OPTIONS = {opts!r}                     # минимальная версия в каждом варианте
def gain(m):
    total = 0
    for v, (share, cost) in VERS.items():
        if v < m:                      # версия отключается
            total += cost * 1_000_000 - N * share / 100 * (100 - U) / 100 * ARPU
    return total
best = max(OPTIONS, key=gain)
print("{plat} " + str(best) + " и новее")
"""


def _opt(plat, v):
    return f"{plat} {v} и новее"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    plat, vers_all = rng.choice(PLATFORMS)
    target = rng.choice([0, 1, 2, 3])
    for _ in range(8000):
        k = rng.choice([5, 6]) if len(vers_all) >= 6 else 5
        start = rng.randrange(0, len(vers_all) - k + 1)
        vers = vers_all[start:start + k]
        shares = sorted(rng.sample([1, 2, 3, 4, 6, 8, 10, 12, 15], 3))
        rest = 100 - sum(shares)
        tail = [rest - rest // 2 - rest // 4, rest // 4, rest // 2][:k - 3]
        tail = tail + [rest - sum(tail)] if k - 3 > len(tail) else tail
        if len(tail) != k - 3 or sum(shares) + sum(tail) != 100 or min(tail) <= 0:
            continue
        share = dict(zip(vers, shares + sorted(tail)))
        cost = {v: (rng.choice([6, 8, 10, 12, 15, 20]) if i < 3 else 0) for i, v in enumerate(vers)}
        N = rng.choice([500_000, 800_000, 1_000_000, 2_000_000, 3_000_000])
        arpu = rng.choice([300, 500, 800, 1200, 2000])
        u = rng.choice([40, 50, 60, 70, 80])
        opts = vers[:4]

        def gain(m, uu=u, keep_rev=False):
            return sum(cost[v] * 1e6 - (0 if keep_rev else N * share[v] / 100 * (100 - uu) / 100 * arpu)
                       for v in vers if v < m)
        g = {m: gain(m) for m in opts}
        order = sorted(opts, key=g.get, reverse=True)
        if opts.index(order[0]) != target or g[order[0]] - g[order[1]] < 1.5e6:
            continue
        alt = {"no_upgrade": max(opts, key=lambda m: gain(m, uu=0)),
               "no_revenue": max(opts, key=lambda m: gain(m, keep_rev=True))}
        if all(x == order[0] for x in alt.values()):
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    best = order[0]
    rows = [f"  {plat} {v}: {share[v]} % пользователей, поддержка {cost[v]} млн ₽ в год" if cost[v] else
            f"  {plat} {v}: {share[v]} % пользователей" for v in vers]
    code = "\n".join([f"Активные пользователи {plat}-версии: {N:,}".replace(",", " "), *rows,
                      f"Выручка на пользователя: {arpu} ₽ в год",
                      f"Из пользователей отключаемых версий {u} % обновят ОС или перейдут в веб (их выручка сохраняется)"])
    stem = (f"{ctx.capitalize()}: команда предлагает поднять минимальную поддерживаемую версию {plat}. Стоимость "
            f"поддержки указана для каждой старой версии отдельно (обходные пути, тестовые устройства). Какую "
            f"минимальную версию выбрать, чтобы годовая выгода — сэкономленная поддержка минус потерянная выручка — "
            f"была наибольшей?")
    mln = lambda x: f"{x / 1e6:.1f}".replace(".", ",").replace("-", "−")  # noqa: E731
    alt_txt = lambda m: "тот же вариант" if m == best else f"{plat} {m}"  # noqa: E731
    why = (f"Выгода варианта — сумма по отключаемым версиям: стоимость поддержки − пользователи × доля, которая "
           f"уйдёт ({100 - u} %), × {arpu} ₽. " + "; ".join(f"{plat} {m}+: {mln(g[m])} млн ₽" for m in opts)
           + f". Лучший — {plat} {best} и новее. Без доли обновившихся — {alt_txt(alt['no_upgrade'])}, "
           f"без потерянной выручки — {alt_txt(alt['no_revenue'])}. Вывод: решение о минимальной версии — по "
           f"предельной выгоде каждой отключаемой версии с учётом тех, кто обновится, а не по порогу доли.")
    table = "VERS = " + repr({v: (share[v], cost[v]) for v in vers}) + "    # версия -> (доля пользователей, %; млн ₽ в год)"
    program = PROGRAM.format(table=table, N=N, arpu=arpu, u=u, opts=opts, plat=plat)
    return choice_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, correct=_opt(plat, best),
                      distractors=[_opt(plat, m) for m in opts if m != best], program=program, why=why, code=code,
                      params={"platform": plat, "options": opts, "best": best, "u": u, "arpu": arpu, "N": N},
                      note="Программа считает годовую выгоду каждого варианта по показанной таблице.")
