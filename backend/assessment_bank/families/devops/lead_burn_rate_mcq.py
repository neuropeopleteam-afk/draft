"""devops.sre.lead_burn_rate_mcq — mcq_concept (Lead): порог алерта по скорости расхода бюджета SLO и время до исчерпания.

SLO доступности X % за 30 дней (720 ч). Алерт: «за последние h часов израсходовано не меньше q % месячного
бюджета ошибок». Нужно (1) порог доли ошибок за окно: e* = q · (720 / h) · (1 − X); (2) при текущей доле
ошибок r и остатке бюджета z % — через сколько часов бюджет закончится: T = z · 720 · (1 − X) / r.
Ответ — пара «порог; время».

Дистракторы (каждый ошибается ровно в одной части, «почти верные»):
  * burn_as_share — скорость расхода (q·720/h) записана как доля ошибок, время верное;
  * per_day — бюджет посчитан на сутки вместо 30 дней (24 вместо 720 в пороге), время верное;
  * full_budget — порог верный, время посчитано по полному бюджету, без учёта остатка z.
Ключ проверяется исполнением: программа-модель поминутно «расходует» бюджет — подбирает порог двоичным
поиском по доле ошибок, при которой за окно расходуется q % бюджета, и шагает по минутам до исчерпания.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq, well_separated
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "devops.sre.lead_burn_rate_mcq"

CONTEXTS = ["API платежей", "поиск вакансий", "оформление заказа", "личный кабинет", "приём заявок",
            "выдача документов"]

PROGRAM = """slo, q, h, r, z = {slo}, {q}, {h}, {r}, {z}
MONTH_MIN = 30 * 24 * 60
budget = (1 - slo) * MONTH_MIN           # «минуты ошибок»: доля ошибок × минуты
def spent_in_window(err):
    return sum(err for _ in range(int(h * 60))) / budget
lo, hi = 0.0, 1.0
for _ in range(200):                      # порог: минимальная доля ошибок, при которой за окно ушло q бюджета
    mid = (lo + hi) / 2
    if spent_in_window(mid) >= q:
        hi = mid
    else:
        lo = mid
thr = hi * 100
left, minutes = z * budget, 0
while left > 0:
    left -= r
    minutes += 1
hours = minutes / 60
opts = __OPTS__
def parse(t):
    a, b = t.split(";")
    return (float(a.split("≈ ")[1].split(" %")[0].replace(" ", "").replace(",", ".")),
            float(b.split("≈ ")[1].split(" ч")[0].replace(" ", "").replace(",", ".")))
hit = [k for k, t in opts.items()
       if abs(parse(t)[0] - thr) <= 0.03 * thr and abs(parse(t)[1] - hours) <= max(0.03 * hours, 0.15)]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _fmt_pct(x: float) -> str:
    return fmt_num(x, 3 if x < 0.1 else 2)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    for _ in range(500):
        slo_s, slo = rng.choice([("99,9", 0.999), ("99,95", 0.9995), ("99,5", 0.995)])
        q_pct, h = rng.choice([(2, 1), (5, 6), (10, 72), (2, 2), (5, 3)])
        q = q_pct / 100
        z_pct = rng.choice([30, 45, 60, 75])
        burn_now = rng.choice([3, 6, 10, 20])
        r = burn_now * (1 - slo)                 # текущая доля ошибок
        thr = q * (720 / h) * (1 - slo) * 100
        t_good = z_pct / 100 * 720 * (1 - slo) / r
        t_full = 720 * (1 - slo) / r
        thr_burn = q * 720 / h
        thr_day = q * (24 / h) * (1 - slo) * 100
        if well_separated([thr, thr_burn, thr_day], 0.2) and well_separated([t_good, t_full], 0.2) and t_good >= 1:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    opt = lambda a, b: f"порог ≈ {_fmt_pct(a)} % ошибок за окно; бюджет закончится через ≈ {fmt_num(b, 1)} ч"
    text = {"good": opt(thr, t_good), "burn_as_share": opt(thr_burn, t_good), "per_day": opt(thr_day, t_good),
            "full_budget": opt(thr, t_full)}
    r_pct = r * 100
    hh = f"{h} {plural(h, 'час', 'часа', 'часов')}"
    stem = (f"SLO «{ctx}» — {slo_s} % успешных запросов за 30 дней. Нужен алерт для дежурного: «за последние {hh} "
            f"израсходовано не меньше {q_pct} % месячного бюджета ошибок» (нагрузку считайте равномерной). (1) Какой "
            f"порог доли ошибок за окно задать? (2) Сейчас доля ошибок держится на {_fmt_pct(r_pct)} %, от месячного "
            f"бюджета осталось {z_pct} %. Если ничего не делать, через сколько часов бюджет закончится?")
    program = PROGRAM.format(slo=slo, q=q, h=h, r=r, z=z_pct / 100)
    burn = q * 720 / h
    expl = (f"Скорость расхода (burn rate), при которой за {hh} уходит {q_pct} % бюджета 30 дней: {q_pct} % × 720 / {h} = "
            f"{fmt_num(burn, 1)}; порог доли ошибок — скорость × (1 − SLO) = {_fmt_pct(thr)} %. Текущая скорость — "
            f"{_fmt_pct(r_pct)} % / {fmt_num(100 * (1 - slo), 2)} % = {burn_now}; оставшиеся {z_pct} % бюджета уйдут за "
            f"{z_pct} % × 720 ч / {burn_now} ≈ {fmt_num(t_good, 1)} ч. Ошибки: скорость {fmt_num(thr_burn, 1)} — не доля "
            f"ошибок; бюджет «на сутки» даёт порог {_fmt_pct(thr_day)} %; без учёта остатка — {fmt_num(t_full, 1)} ч.")
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=text["good"],
                       distractors=[text["burn_as_share"], text["per_day"], text["full_budget"]], program=program,
                       explanation=expl,
                       params={"slo": slo_s, "q": q_pct, "h": h, "z": z_pct, "burn_now": burn_now,
                               "thr": round(thr, 4), "hours": round(t_good, 2)},
                       note="Ответ проверяется программой-моделью: поминутный расход бюджета, порог — двоичным "
                            "поиском.")
