"""devops.sre.principal_oncall_load_mcq — mcq_concept (Principal): нагрузка дежурств — какая мера одна укладывает в нормы.

Ротация из N инженеров, дежурство — неделя. За неделю приходит P вызовов, доля «шумных» (не требуют действий) — n,
доля ночных — ν (одинакова для шумных и настоящих). Разбор настоящего вызова — t_act ч, шумного — t_noise ч. Нормы:
не больше M ночных вызовов за дежурную неделю (сон дежурного) и не больше H часов разбора вызовов в месяц
(4 недели) на одного инженера. Четыре меры с ценой в год: ещё два инженера в ротацию, чистка шумных оповещений
(оповещения по SLO, убирает долю ε шумных), авторемонт самого частого класса настоящих вызовов (убирает долю α
настоящих), второй офис в другом часовом поясе берёт ночные вызовы (вместе с часами их разбора). Какая мера одна
укладывает в обе нормы и дешевле остальных таких?

Главное наблюдение: добавление людей в ротацию снижает часы на человека, но не ночные вызовы дежурной недели.
Ловушки: самая дешёвая мера, «добавить людей» (привычное решение), наибольшее сокращение вызовов, выбор без нормы
ночных вызовов. Ответ выбирается по seed до подбора чисел — равновероятен среди четырёх мер; отличается хотя бы от
двух ловушек; значения норм у каждой меры отстоят от границы не меньше чем на 3 %. Ключ проверяется исполнением:
программа раскладывает вызовы месяца по неделям и дежурным (по кругу), считает ночные вызовы каждой недели и часы
каждого инженера и печатает букву самой дешёвой меры, при которой обе нормы выполнены.
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import ru_num
from assessment_bank.families._principal_b_kit import cap, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "devops.sre.principal_oncall_load_mcq"

CONTEXTS = [("платёжной платформы", "кратковременный рост задержки без нарушения SLO", "зависшие воркеры очереди"),
            ("платформы доставки", "одиночные таймауты к картографическому API", "переполнение диска журналами"),
            ("облачной платформы для внутренних команд", "флаппинг проверки живости узла",
             "истёкшие сертификаты на тестовых стендах"),
            ("сервиса онлайн-записи", "предупреждения о загрузке CPU ниже порога SLO", "утечка соединений к БД"),
            ("платформы данных", "задержка второстепенной выгрузки", "упавшие задачи из-за нехватки памяти"),
            ("мобильного банка", "всплески ошибок 4xx от старых версий приложения", "переполнение пула потоков"),
            ("платформы найма", "оповещения о медленных отчётах ночью", "зависшие задачи импорта резюме")]
NAMES = {"add2": "ещё два инженера в ротацию", "noise": "чистка шумных оповещений (оповещения по SLO)",
         "auto": "авторемонт самого частого класса вызовов", "fts": "второй офис в другом часовом поясе берёт ночь"}
ORDER = ["add2", "noise", "auto", "fts"]

PROGRAM = """opts = __OPTS__
P = {P!r}
cost = {cost!r}
names = {names!r}

def norms_ok(measure):
    n_eng = P["N"] + (2 if measure == "add2" else 0)
    noise = P["P"] * P["n"] * ((1 - P["eps"]) if measure == "noise" else 1)
    real = P["P"] * (1 - P["n"]) * ((1 - P["alpha"]) if measure == "auto" else 1)
    away = measure == "fts"                    # ночные вызовы и их разбор уходят во второй офис
    hours = [0.0] * n_eng
    night_weeks = []
    for week in range(4 * n_eng):              # полный круг ротации, месяц = 4 недели
        who = week % n_eng
        for kind, count, t in (("noise", noise, P["t_noise"]), ("real", real, P["t_act"])):
            day, night = count * (1 - P["nu"]), count * P["nu"]
            hours[who] += day * t + (0.0 if away else night * t)
        night_weeks.append(0.0 if away else (noise + real) * P["nu"])
    per_month = [h / n_eng for h in hours]     # 4·n_eng недель = n_eng месяцев
    return max(night_weeks) <= P["M"] + 1e-9 and max(per_month) <= P["H"] + 1e-9

ok = [m for m in cost if norms_ok(m)]
best = min(ok, key=lambda m: cost[m])
hit = [k for k, t in opts.items() if t == names[best]]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _loads(p, m):
    n_eng = p["N"] + (2 if m == "add2" else 0)
    noise = p["P"] * p["n"] * ((1 - p["eps"]) if m == "noise" else 1)
    real = p["P"] * (1 - p["n"]) * ((1 - p["alpha"]) if m == "auto" else 1)
    total_h = noise * p["t_noise"] + real * p["t_act"]
    if m == "fts":
        night, week_hours = 0.0, (1 - p["nu"]) * total_h
    else:
        night, week_hours = (noise + real) * p["nu"], total_h
    return night, 4 * week_hours / n_eng, noise + real


def _sample(rng):
    return {"P": rng.choice([10, 14, 20, 28, 40]), "n": rng.choice([0.3, 0.5, 0.6]), "nu": rng.choice([0.25, 0.35, 0.5]),
            "t_act": rng.choice([1.0, 1.5, 2.0]), "t_noise": rng.choice([0.25, 0.5]), "N": rng.choice([4, 5, 6, 8]),
            "M": rng.choice([2, 3, 4, 5]), "H": rng.choice([6, 8, 12, 16]), "eps": rng.choice([0.6, 0.8]),
            "alpha": rng.choice([0.3, 0.4, 0.5]),
            "cost": {"add2": rng.choice([3.0, 4.5, 6.0]), "noise": rng.choice([0.8, 1.5, 2.5]),
                     "auto": rng.choice([1.0, 2.0, 3.5]), "fts": rng.choice([5.0, 8.0])}}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, noise_ex, auto_ex = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)

    def accept(p):
        if len(set(p["cost"].values())) < 4:
            return None
        ld = {m: _loads(p, m) for m in [None] + ORDER}
        for m in ORDER:
            night, hrs, _t = ld[m]
            if (night and abs(night - p["M"]) < 0.03 * p["M"]) or abs(hrs - p["H"]) < 0.03 * p["H"]:
                return None
        ok = [m for m in ORDER if ld[m][0] <= p["M"] and ld[m][1] <= p["H"]]
        cur_ok = ld[None][0] <= p["M"] and ld[None][1] <= p["H"]
        if cur_ok or not ok or len(ok) == 4:
            return None
        good = min(ok, key=lambda m: p["cost"][m])
        if good != target:
            return None
        cheap = min(ORDER, key=lambda m: p["cost"][m])
        fewest = min(ORDER, key=lambda m: ld[m][2] + (0 if m != "fts" else 1e6))    # меньше всего вызовов
        ok_nonight = [m for m in ORDER if ld[m][1] <= p["H"]]
        no_night = min(ok_nonight, key=lambda m: p["cost"][m]) if ok_nonight else None
        if no_night is None:
            return None
        traps = {"cheap": cheap, "add_people": "add2", "fewest_pages": fewest, "no_night_norm": no_night}
        if sum(1 for v in traps.values() if v != good) < 2:
            return None
        return good, ld, traps

    p, (good, ld, traps) = search(rng, _sample, accept)
    c = p["cost"]
    hrs = lambda x: f"{ru_num(x)} {plural(int(x) if float(x).is_integer() else 2, 'час', 'часа', 'часов')}"
    rows = [f"• {cap(NAMES['add2'])} ({p['N'] + 2} вместо {p['N']}) — {fmt_num(c['add2'], 1)} млн ₽ в год;",
            f"• {cap(NAMES['noise'])}: убирает {fmt_num(100 * p['eps'], 0)} % шумных вызовов — {fmt_num(c['noise'], 1)} "
            f"млн ₽ в год;",
            f"• {cap(NAMES['auto'])} ({auto_ex}): убирает {fmt_num(100 * p['alpha'], 0)} % настоящих вызовов — "
            f"{fmt_num(c['auto'], 1)} млн ₽ в год;",
            f"• {cap(NAMES['fts'])}: все ночные вызовы и их разбор уходят туда — {fmt_num(c['fts'], 1)} млн ₽ в год."]
    stem = (f"Дежурства {ctx}: ротация из {p['N']} инженеров, дежурство — неделя. За неделю приходит ≈ {p['P']} вызовов, "
            f"из них {fmt_num(100 * p['n'], 0)} % шумные (действий не требуют; например, {noise_ex}), {fmt_num(100 * p['nu'], 0)} % — ночью "
            f"(доля одинакова для шумных и настоящих). Разбор настоящего вызова — {hrs(p['t_act'])}, шумного — "
            f"{hrs(p['t_noise'])}. Нормы: не больше {p['M']} ночных вызовов за дежурную неделю и не больше "
            f"{hrs(p['H'])} разбора вызовов в месяц (4 недели) на инженера. Сейчас нормы не выполняются. Варианты:\n" +
            "\n".join(rows) + "\n\nКакая мера одна укладывает дежурства в обе нормы и дешевле остальных таких?")
    def show(m):
        night, h, _t = ld[m]
        return f"ночных за неделю {fmt_num(night, 1)}, часов в месяц на инженера {fmt_num(h, 1)}"
    expl = (f"Сейчас: {show(None)}. С мерой: " + "; ".join(f"{NAMES[m]} — {show(m)}" for m in ORDER) +
            f". Обе нормы (≤ {p['M']} ночных, ≤ {ru_num(p['H'])} ч) выполняют: "
            f"{', '.join(NAMES[m] for m in ORDER if ld[m][0] <= p['M'] and ld[m][1] <= p['H'])}; самая дешёвая — "
            f"{NAMES[good]}. Добавление людей снижает часы на человека, но не ночные вызовы дежурной недели. Ловушки: "
            f"самая дешёвая мера — {NAMES[traps['cheap']]}; «добавить людей» — {NAMES['add2']}; наибольшее сокращение "
            f"вызовов — {NAMES[traps['fewest_pages']]}; без нормы ночных — {NAMES[traps['no_night_norm']]}.")
    P = {k: v for k, v in p.items() if k != "cost"}
    program = PROGRAM.format(P=P, cost=c, names=NAMES)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[m] for m in ORDER if m != good], program=program, explanation=expl,
                       params={**P, **{f"cost_{k}": v for k, v in c.items()}, "good": good,
                               **{f"trap_{k}": v for k, v in traps.items()}},
                       note="Ответ проверяется программой: вызовы месяца разложены по неделям и дежурным.")
