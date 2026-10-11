"""common.process.principal_oncall_model_mcq — mcq_concept (Principal, короткое): модель дежурств по годовой цене.

Инцидентов I в год, доля n — ночью. Час инцидента стоит L тыс. ₽. Базовое время устранения — b минут; дежурному
не из команды-владельца нужно ещё e минут на передачу владельцу; разбуженному ночью — ещё w минут. Четыре модели:
  * каждая из T команд дежурит сама — днём b, ночью b + w; доплаты T · S_t;
  * центральная служба эксплуатации круглосуточно — днём и ночью b + e (без пробуждения); S_sre;
  * команды днём, центральная служба ночью — днём b, ночью b + e; T · S_d + S_n;
  * «вслед за солнцем» (два офиса в разных часовых поясах, у каждой команды) — днём b, ночью b + h (передача
    между офисами); S_f.
Годовая цена = доплаты за дежурства + Σ по инцидентам время устранения × L.

Ловушки: «быстрее всего устраняет» (без цены доплат), «дешевле всего по доплатам» и расчёт без ночных инцидентов.
Верная модель распределена поровну по четырём и отличается хотя бы от двух ловушек (если верна сама ловушка — хотя
бы от одной). Ключ проверяется исполнением: программа проходит инциденты года (день/ночь), для каждой модели
определяет, кто отвечает и сколько длится устранение, и печатает букву минимума.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "common.process.principal_oncall_model_mcq"

CONTEXTS = ["платёжная платформа", "сервис доставки", "маркетплейс", "интернет-банк", "сервис такси",
            "облачная касса", "онлайн-кинотеатр", "сервис бронирования"]
NAMES = {"team": "каждая команда дежурит сама", "sre": "центральная служба эксплуатации круглосуточно",
         "hybrid": "команды днём, центральная служба ночью", "fts": "дежурство вслед за солнцем"}
ORDER = ["team", "sre", "hybrid", "fts"]

PROGRAM = """opts = __OPTS__
I, n, L, b, e, w, h = {I}, {n}, {L}, {b}, {e}, {w}, {h}
plans = {plans!r}      # подпись -> (модель, доплаты млн ₽ в год)
night = int(round(I * n))
cost = {{}}
for label, (plan, staff) in plans.items():
    minutes = 0
    for i in range(I):
        at_night = i < night
        t = b
        if plan == "sre":
            t += e                                   # не владелец: передача команде
        elif plan == "team" and at_night:
            t += w                                   # разбудили владельца
        elif plan == "hybrid" and at_night:
            t += e
        elif plan == "fts" and at_night:
            t += h                                   # передача между офисами
        minutes += t
    cost[label] = staff + minutes / 60 * L / 1000
best = min(cost, key=cost.get)
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _argmin(v, rel=0.04):
    o = sorted(v.values())
    return min(v, key=v.get) if o[1] - o[0] >= rel * o[1] else None


def _mins(I, n, b, e, w, h):
    return {"team": I * b + I * n * w, "sre": I * (b + e), "hybrid": I * b + I * n * e, "fts": I * b + I * n * h}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)
    for _ in range(80000):
        I = rng.choice([40, 80, 150, 300])
        n = rng.choice([0.2, 0.3, 0.4])
        L = rng.choice([100, 300, 1000, 3000])              # тыс. ₽ за час
        b = rng.choice([30, 45, 60])
        e, w, h = rng.choice([15, 25, 40]), rng.choice([15, 20, 30]), rng.choice([5, 10])
        T = rng.choice([4, 6, 10])
        S_t, S_d = rng.choice([0.6, 1.0, 1.5]), rng.choice([0.3, 0.5, 0.8])
        S_sre, S_n = rng.choice([4, 6, 10]), rng.choice([2, 3, 5])
        S_f = rng.choice([8, 12, 18])
        staff = {"team": round(T * S_t, 1), "sre": S_sre, "hybrid": round(T * S_d + S_n, 1), "fts": S_f}
        mins = _mins(I, n, b, e, w, h)
        full = {k: staff[k] + mins[k] / 60 * L / 1000 for k in ORDER}
        good = _argmin(full)
        if good != target:
            continue
        day_only = _argmin({k: staff[k] + _mins(I, 0, b, e, w, h)[k] / 60 * L / 1000 for k in ORDER})
        fastest = _argmin({k: mins[k] + 1e-9 for k in ORDER}, rel=0.01)
        cheapest = _argmin({k: staff[k] for k in ORDER}, rel=0.01)
        if None in (day_only, fastest, cheapest):
            continue
        traps = (fastest, cheapest, day_only)
        if sum(t != good for t in traps) >= (1 if good in (fastest, cheapest) else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    cap = lambda t: t[0].upper() + t[1:]
    tw = plural(T, "команда", "команды", "команд")
    rows = [f"• {cap(NAMES['team'])}: днём устраняет владелец сразу, ночью — плюс {w} мин на пробуждение; доплаты — "
            f"{fmt_num(S_t, 1)} млн ₽ в год на команду.",
            f"• {cap(NAMES['sre'])}: никого не будят, но дежурный не владелец — плюс {e} мин на передачу команде "
            f"днём и ночью; {S_sre} млн ₽ в год.",
            f"• {cap(NAMES['hybrid'])}: днём — владелец сразу, ночью — плюс {e} мин на передачу; доплаты командам — "
            f"{fmt_num(S_d, 1)} млн ₽ в год на команду, служба — {S_n} млн ₽ в год.",
            f"• {cap(NAMES['fts'])} (у каждой команды есть люди в двух часовых поясах): ночью — плюс {h} мин на "
            f"передачу между офисами; {S_f} млн ₽ в год."]
    intro = rng.choice([
        f"Вы — главный инженер; продукт — {ctx}, {T} {tw}. Нужно выбрать модель дежурств на год.",
        f"В продукте «{ctx}» ({T} {tw}) пересматривают дежурства; решение — за вами как за главным инженером.",
        f"Для продукта «{ctx}» ({T} {tw}) утверждают модель дежурств на год; выбор — за главным инженером.",
    ])
    stem = (f"{intro} Инцидентов ≈ {I} в год, {fmt_num(100 * n, 0)} % из них — ночью. Час инцидента стоит ≈ "
            f"{fmt_num(L, 0)} тыс. ₽. Базовое время устранения — {b} мин. Модели:\n" + "\n".join(rows) +
            "\n\nКакая модель даёт минимальную годовую цену (доплаты за дежурства и потери от инцидентов)?")
    expl = ("Цена = доплаты + Σ по инцидентам (базовое время + надбавка модели днём или ночью) / 60 × цена часа. "
            "Итоги: " + "; ".join(f"{NAMES[k]} — {fmt_num(full[k], 1)} млн ₽" for k in ORDER) +
            f". Минимум — {NAMES[good]}. Быстрее всего устраняет {NAMES[fastest]}, дешевле по доплатам — "
            f"{NAMES[cheapest]}, без ночных инцидентов вышло бы: {NAMES[day_only]}.")
    program = PROGRAM.format(I=I, n=n, L=L, b=b, e=e, w=w, h=h, plans={NAMES[k]: (k, staff[k]) for k in ORDER})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={"I": I, "n": n, "L": L, "b": b, "e": e, "w": w, "h": h, "T": T, "good": good,
                               "fastest": fastest, "cheapest": cheapest, "day_only": day_only,
                               **{f"staff_{k}": staff[k] for k in ORDER}},
                       note="Ответ проверяется программой: проход инцидентов года для каждой модели.")
