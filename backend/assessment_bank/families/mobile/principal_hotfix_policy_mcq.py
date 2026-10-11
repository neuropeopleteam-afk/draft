"""mobile.principal.hotfix_policy_mcq — mcq_concept (Principal, короткое): какую политику выпусков мобильного
приложения выбрать — частоту поезда и правила срочных выпусков — по месячной стоимости.

За месяц (30 дней) находят λc критических и λn обычных дефектов (в среднем, моменты — равномерно); день, пока
исправление не дошло до пользователей, стоит c_c и c_n. Плановый выпуск (поезд) стоит F, срочный — H. После выпуска
исправление идёт R дней проверку магазина и A дней обновление пользователей. Исправление, найденное между поездами,
ждёт следующего поезда в среднем T / 2 дней. Стоимость политики в месяц = выпуски + задержки исправлений.

Варианты ответа — четыре политики; верная — с наименьшей стоимостью (отрыв от второй не меньше 5 %). Какая
политика верная, задаётся по seed поровну (числа подбираются под неё), поэтому форма подписи не выдаёт ключ.
Ключ проверяется исполнением: программа считает стоимость каждой политики и печатает лучшую.
"""
from __future__ import annotations

from assessment_bank.families._principal_c_utils import choice_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.principal.hotfix_policy_mcq"

CONTEXTS = ["мобильный банк", "приложение доставки еды", "приложение такси", "приложение маркетплейса",
            "приложение онлайн-кинотеатра", "приложение авиакомпании", "приложение сети АЗС", "приложение медклиники"]

POLICIES = ["еженедельный поезд, без срочных выпусков",
            "поезд раз в две недели, без срочных выпусков",
            "поезд раз в две недели и срочные — для критических",
            "поезд раз в две недели и срочные — для всех дефектов"]

PROGRAM = """POLICIES = {policies!r}
lc, ln, cc, cn = {lc}, {ln}, {cc}, {cn}        # дефектов в месяц; стоимость дня задержки, тыс. ₽
F, H, R, A = {F}, {H}, {R}, {A}                # поезд и срочный выпуск, тыс. ₽; дни проверки и обновления
def cost(train_days, hot_critical, hot_normal):
    total = 30 / train_days * F                # плановые выпуски за месяц
    for rate, per_day, hot in ((lc, cc, hot_critical), (ln, cn, hot_normal)):
        wait = 0 if hot else train_days / 2    # ожидание поезда — в среднем половина периода
        total += rate * ((H if hot else 0) + per_day * (wait + R + A))
    return total
costs = [cost(7, False, False), cost(14, False, False), cost(14, True, False), cost(14, True, True)]
print(POLICIES[costs.index(min(costs))])
"""


def _costs(lc, ln, cc, cn, F, H, R, A):
    def cost(train, hc, hn):
        total = 30 / train * F
        for rate, per_day, hot in ((lc, cc, hc), (ln, cn, hn)):
            total += rate * ((H if hot else 0) + per_day * ((0 if hot else train / 2) + R + A))
        return total
    return [cost(7, False, False), cost(14, False, False), cost(14, True, False), cost(14, True, True)]


def _thousands(x):
    return f"{round(x):,}".replace(",", " ")


def _num(x):
    return f"{x:g}".replace(".", ",")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice([0, 1, 2, 3])
    for _ in range(20000):
        lc, ln = rng.choice([0.5, 1, 1.5, 2, 3]), rng.choice([4, 6, 8, 10, 12, 16])
        cc, cn = rng.choice([50, 100, 200, 300, 500, 800]), rng.choice([2, 5, 10, 20, 40])
        F, H = rng.choice([100, 150, 200, 300, 400, 600]), rng.choice([60, 100, 150, 250, 400, 600, 900, 1200])
        R, A = rng.choice([1, 2]), rng.choice([2, 3, 4])
        if H <= F / 4:
            continue
        c = _costs(lc, ln, cc, cn, F, H, R, A)
        order = sorted(range(4), key=lambda i: c[i])
        if order[0] == target and c[order[1]] - c[order[0]] >= 0.05 * c[order[0]]:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    code = "\n".join([f"Дефекты за месяц (в среднем): критических — {_num(lc)}, обычных — {ln}",
                      f"Стоимость дня, пока исправление не у пользователей: критический — {cc} тыс. ₽, обычный — {cn} тыс. ₽",
                      f"Плановый выпуск (поезд): {F} тыс. ₽ (регресс, выкладка); срочный выпуск: {H} тыс. ₽",
                      f"После выпуска: проверка магазина — {R} дн., обновление большинства пользователей — {A} дн.",
                      "Дефекты находят в случайные моменты; исправление готово в день обнаружения."])
    stem = (f"{ctx[0].upper() + ctx[1:]}: команда платформы выбирает политику выпусков. Какая из политик даёт "
            f"наименьшую ожидаемую стоимость в месяц (выпуски плюс задержка исправлений)?")
    best = order[0]
    why = (f"Исправление, найденное между поездами, ждёт в среднем половину периода. Стоимость в месяц: "
           + "; ".join(f"«{POLICIES[i]}» — {_thousands(c[i])} тыс. ₽" for i in range(4))
           + f". Лучшая — «{POLICIES[best]}». Типичные ошибки — считать ожидание полным периодом, забыть стоимость "
           f"самих выпусков или выбирать по одной цене дефекта. Вывод: частота поезда и правила срочных выпусков "
           f"выбираются по цене задержки разных классов дефектов против цены выпуска.")
    program = PROGRAM.format(policies=POLICIES, lc=lc, ln=ln, cc=cc, cn=cn, F=F, H=H, R=R, A=A)
    return choice_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, correct=POLICIES[best],
                      distractors=[POLICIES[i] for i in order[1:]], program=program, why=why, code=code,
                      params={"lc": lc, "ln": ln, "cc": cc, "cn": cn, "F": F, "H": H, "R": R, "A": A,
                              "target": target},
                      note="Программа считает месячную стоимость каждой политики и печатает лучшую.")
