"""devops.release.principal_canary_plan_mcq — mcq_concept (Principal): политика канареечной выкатки по ожидаемой цене.

Команда выкатывает релизы часто; доля плохих релизов — p_bad, плохой релиз добавляет Δ к доле ошибок на канарейке.
Чтобы отличить плохой релиз от шума, канарейке нужно увидеть не меньше M запросов, а медленные дефекты (утечки,
переполнение очередей) проявляются не раньше чем через D_min минут. Канарейка блокирует конвейер: минута ожидания
стоит c_d (очередь релизов, люди на дежурстве), ошибочный запрос клиента — c_e. Четыре плана «доля трафика × время».
Какой допустимый план (обнаруживает плохой релиз) даёт минимальную ожидаемую цену одного релиза
(ожидание у всех релизов + ошибки клиентов у плохих)?

У ответа обе составляющие цены — не меньше 15 % каждая (иначе задача сводится к одному критерию).
Ловушки: «меньше всего клиентов под риском» (наименьшая доля), «быстрее всего» (наименьшее время), выбор без цены
ожидания, без цены ошибок клиентов; часть ловушек недопустима (план не набирает M запросов или короче D_min).
План-ответ выбирается по seed до подбора чисел — равновероятен по месту доли среди четырёх. Ключ проверяется
исполнением: программа поминутно имитирует канарейку для хорошего и плохого релиза, проверяет обнаружение и
складывает ожидаемую цену с весами p_bad и 1 − p_bad.
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import ru_num
from assessment_bank.families._principal_b_kit import argmin_sep, search
from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "devops.release.principal_canary_plan_mcq"

CONTEXTS = ["API мобильного банка", "витрину маркетплейса", "платёжный шлюз", "сервис бронирования",
            "API поиска вакансий", "личный кабинет абонента", "сервис доставки"]
SHARES = [1, 2, 5, 10, 20, 25, 50]
DURS = [5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240]

PROGRAM = """opts = __OPTS__
R, M, d_min, delta, p_bad, c_d, c_e = {R}, {M}, {d_min}, {delta}, {p_bad}, {c_d}, {c_e}
plans = {plans!r}      # текст плана -> (доля трафика %, минут)
best, best_cost = None, None
for text, (share, minutes) in plans.items():
    seen, bad_errors = 0.0, 0.0
    for minute in range(minutes):             # поминутно: запросы канарейки и лишние ошибки плохого релиза
        seen += R * share / 100
        bad_errors += R * share / 100 * delta
    if seen < M or minutes < d_min:
        continue                               # плохой релиз не обнаружен — план недопустим
    good_release = minutes * c_d
    bad_release = minutes * c_d + bad_errors * c_e
    cost = (1 - p_bad) * good_release + p_bad * bad_release
    if best_cost is None or cost < best_cost - 1e-9:
        best, best_cost = text, cost
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _plan_text(share: int, minutes: int) -> str:
    return f"{share} % трафика на {minutes} {plural(minutes, 'минуту', 'минуты', 'минут')}"


def _cost(p, share, minutes, *, wait=True, errors=True, check=True):
    seen = p["R"] * share / 100 * minutes
    if check and (seen < p["M"] or minutes < p["d_min"]):
        return None
    bad = seen * p["delta"]
    return (minutes * p["c_d"] if wait else 0) + (p["p_bad"] * bad * p["c_e"] if errors else 0)


def _sample(rng):
    shares = sorted(rng.sample(SHARES, 4))
    durs = sorted(rng.sample(DURS, 4), reverse=True)        # меньшая доля — дольше
    return {"plans": list(zip(shares, durs)), "R": rng.choice([2000, 5000, 10000, 20000, 40000]),
            "M": rng.choice([5000, 10000, 20000, 40000]), "d_min": rng.choice([10, 15, 20, 30]),
            "delta": rng.choice([0.01, 0.02, 0.05]), "p_bad": rng.choice([0.03, 0.05, 0.1, 0.15]),
            "c_d": rng.choice([200, 500, 1000, 2000, 5000]), "c_e": rng.choice([5, 20, 50, 100, 300])}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    pos = rng.choice([0, 1, 2, 3])

    def accept(p):
        plans = p["plans"]
        full = {i: _cost(p, s, m) for i, (s, m) in enumerate(plans)}
        ok = {i: c for i, c in full.items() if c is not None}
        if len(ok) < 2 or len(ok) == 4:
            return None
        good = argmin_sep({str(i): c for i, c in ok.items()}, 0.08)
        if good is None or int(good) != pos:
            return None
        s_, m_ = plans[pos]
        w_part, e_part = _cost(p, s_, m_, errors=False), _cost(p, s_, m_, wait=False)
        if min(w_part, e_part) < 0.15 * (w_part + e_part):
            return None                          # обе составляющие цены должны влиять на выбор
        nw = argmin_sep({str(i): _cost(p, s, m, wait=False) for i, (s, m) in enumerate(plans) if i in ok}, 0.02)
        ne = argmin_sep({str(i): _cost(p, s, m, errors=False) for i, (s, m) in enumerate(plans) if i in ok}, 0.02)
        if None in (nw, ne):
            return None
        traps = {"least_users": 0, "fastest": 3, "no_wait": int(nw), "no_errors": int(ne)}
        if sum(1 for v in traps.values() if v != pos) < 2:
            return None
        return pos, full, traps

    p, (good, full, traps) = search(rng, _sample, accept)
    plans = p["plans"]
    texts = [_plan_text(s, m) for s, m in plans]
    stem = (f"Вы задаёте политику выкатки для {ctx}: {fmt_num(p['R'], 0)} запросов в минуту, релизы — несколько раз в день. "
            f"По истории плохим оказывается ≈ {fmt_num(100 * p['p_bad'], 0)} % релизов; плохой релиз добавляет "
            f"{fmt_num(100 * p['delta'], 0)} п. п. к доле ошибок. Чтобы отличить плохой релиз от шума, канарейке нужно "
            f"увидеть не меньше {fmt_num(p['M'], 0)} запросов, а медленные дефекты (утечки, рост очередей) проявляются "
            f"не раньше чем через {p['d_min']} {plural(p['d_min'], 'минуту', 'минуты', 'минут')}. Пока идёт канарейка, "
            f"конвейер стоит: минута ожидания обходится ≈ {fmt_num(p['c_d'], 0)} ₽ (очередь релизов, дежурные), каждый "
            f"ошибочный запрос клиента — ≈ {fmt_num(p['c_e'], 0)} ₽. Планы канарейки: " + "; ".join(texts) +
            ". Какой план, который обнаруживает плохой релиз, даёт минимальную ожидаемую цену одного релиза?")
    def rub(x):
        return "не обнаруживает" if x is None else f"{fmt_num(x, 0)} ₽"
    expl = (f"Цена релиза = минуты × {fmt_num(p['c_d'], 0)} ₽ + {fmt_num(p['p_bad'], 2)} × (запросы канарейки × "
            f"{fmt_num(p['delta'], 2)} × {fmt_num(p['c_e'], 0)} ₽); план допустим, если запросов канарейки ≥ "
            f"{fmt_num(p['M'], 0)} и время ≥ {p['d_min']} мин. По планам: " +
            "; ".join(f"{texts[i]} — {rub(full[i])}" for i in range(4)) +
            f". Минимум — {texts[good]}. Ловушки: меньше всего клиентов под риском — {texts[traps['least_users']]}; "
            f"быстрее всего — {texts[traps['fastest']]}; без цены ожидания — {texts[traps['no_wait']]}; без цены "
            f"ошибок — {texts[traps['no_errors']]}.")
    program = PROGRAM.format(R=p["R"], M=p["M"], d_min=p["d_min"], delta=p["delta"], p_bad=p["p_bad"], c_d=p["c_d"],
                             c_e=p["c_e"], plans={t: pl for t, pl in zip(texts, plans)})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=texts[good],
                       distractors=[t for i, t in enumerate(texts) if i != good], program=program, explanation=expl,
                       params={**{k: v for k, v in p.items() if k != "plans"}, "plans": [list(x) for x in plans],
                               "good": good, **{f"trap_{k}": v for k, v in traps.items()}},
                       note="Ответ проверяется программой: поминутная имитация канарейки для хорошего и плохого релиза.")
