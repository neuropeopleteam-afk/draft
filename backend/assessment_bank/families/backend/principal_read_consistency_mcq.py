"""backend.strategy.principal_read_consistency_mcq — mcq_concept (Principal, короткое): откуда читать в реплицированной БД.

Нагрузка на базу растёт, нужно решить, откуда обслуживать чтения. Четыре варианта:
  * все чтения с лидера — строгая согласованность; лидер и его резерв нужно увеличить (I_lead млн ₽ в год);
  * чтения с асинхронных реплик — дёшево (I_rep), но доля f чтений идёт сразу после собственной записи
    пользователя и попадает в отставание реплики: каждое такое чтение — устаревшие данные, цена s ₽;
  * «чтение своих записей»: после записи пользователь T секунд читает с лидера, остальное — с реплик:
    I_rep + доля f нагрузки на лидера (f · (I_lead − I_rep)) + сопровождение маршрутизации C_s;
  * синхронная репликация кворумом и чтения с любой реплики — без устаревания, I_sync, но каждая запись
    дольше на Δ мс: потеря выручки W · x % · Δ / 100 по сценариям с записью.
Ловушки: «строгая согласованность всегда» (лидер), «самое дешёвое железо» (реплики), синхронная репликация без цены
задержки записи. Верный вариант распределён поровну по четырём и отличается хотя бы от двух ловушек (если верна
сама ловушка — хотя бы от одной). Ключ проверяется исполнением: программа проводит поток из 10 000 модельных
чтений (доля f — сразу после своей записи), маршрутизирует каждое по правилу варианта, считает устаревшие и
нагрузку на лидера и печатает букву минимума.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.strategy.principal_read_consistency_mcq"

CONTEXTS = ["профили пользователей", "корзины и заказы", "объявления", "бронирования", "счета клиентов",
            "комментарии и лайки", "настройки уведомлений", "задачи и доски"]
NAMES = {"leader": "все чтения с лидера", "replicas": "чтения с асинхронных реплик",
         "ryw": "чтение своих записей с лидера, остальное с реплик",
         "sync": "синхронная репликация кворумом, чтения с любой реплики"}
ORDER = ["leader", "replicas", "ryw", "sync"]

PROGRAM = """opts = __OPTS__
R, f, s = {R}, {f}, {s}
I_lead, I_rep, I_sync, C_s = {I_lead}, {I_rep}, {I_sync}, {C_s}
W, x, delta = {W}, {x}, {delta}
labels = {labels!r}
N = 10000
after_write = int(round(N * f))                  # первые after_write чтений — сразу после своей записи
cost = {{}}
for plan, label in labels.items():
    stale = to_leader = 0
    for i in range(N):
        own = i < after_write
        if plan == "leader":
            to_leader += 1
        elif plan == "replicas":
            stale += 1 if own else 0
        elif plan == "ryw":
            to_leader += 1 if own else 0
    if plan == "leader":
        infra = I_lead
    elif plan == "ryw":
        infra = I_rep + to_leader / N * (I_lead - I_rep) + C_s
    elif plan == "sync":
        infra = I_sync + W * x / 100 * delta / 100
    else:
        infra = I_rep
    cost[label] = infra + R * 1e3 * stale / N * s      # R — млрд чтений; s — ₽; итог в млн ₽
best = min(cost, key=cost.get)
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _argmin(d, rel=0.04):
    v = sorted(d.values())
    return min(d, key=d.get) if v[1] - v[0] >= rel * v[1] else None


def _costs(R, f, s, I_lead, I_rep, I_sync, C_s, W, x, delta, with_latency=True):
    return {"leader": I_lead, "replicas": I_rep + R * 1e3 * f * s,
            "ryw": I_rep + f * (I_lead - I_rep) + C_s,
            "sync": I_sync + (W * x / 100 * delta / 100 if with_latency else 0)}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)
    for _ in range(60000):
        R = rng.choice([1, 2, 5, 10])                     # млрд чтений в год
        f = rng.choice([0.001, 0.002, 0.005, 0.01, 0.02])
        s = rng.choice([0.5, 1, 2, 5])                    # ₽ за устаревшее чтение
        I_rep = rng.choice([10, 15, 20])
        I_lead = I_rep + rng.choice([3, 5, 10, 20, 40])
        I_sync = I_rep + rng.choice([5, 10, 15])
        C_s = rng.choice([2, 4, 8, 12])
        W = rng.choice([500, 1000, 3000])
        x = rng.choice([0.2, 0.5, 1.0])
        delta = rng.choice([20, 40, 80])
        a = (R, f, s, I_lead, I_rep, I_sync, C_s, W, x, delta)
        full = _costs(*a)
        good = _argmin(full)
        if good != target:
            continue
        no_lat = _argmin(_costs(*a, with_latency=False))
        if no_lat is None:
            continue
        traps = ("leader", "replicas", no_lat)
        if sum(t != good for t in traps) >= (1 if good in ("leader", "replicas") else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    cap = lambda t: t[0].upper() + t[1:]
    rows = [f"• {cap(NAMES['leader'])}: лидер и его резерв придётся увеличить — всего {I_lead} млн ₽ в год (реплики "
            f"для чтения не нужны).",
            f"• {cap(NAMES['replicas'])}: {I_rep} млн ₽ в год; чтение сразу после своей записи попадает в отставание "
            f"реплики и показывает старые данные.",
            f"• {cap(NAMES['ryw'])}: {I_rep} млн ₽ в год за реплики; к лидеру идут только чтения сразу после своей "
            f"записи, поэтому из разницы {I_lead} − {I_rep} млн ₽ (увеличение лидера) нужна та же доля; "
            f"сопровождение маршрутизации — {C_s} млн ₽ в год.",
            f"• {cap(NAMES['sync'])}: {I_sync} млн ₽ в год, устаревших чтений нет, но каждая запись дольше на "
            f"{delta} мс."]
    intro = rng.choice([
        f"Вы — главный инженер. Таблица «{ctx}» упирается в лидера базы, и нужно решить, откуда обслуживать чтения.",
        f"Нагрузка на базу «{ctx}» выросла; архитектурный совет просит главного инженера выбрать схему чтений.",
        f"База «{ctx}» перестала справляться с чтениями; решение о схеме чтения — за вами как за главным инженером.",
    ])
    stem = (f"{intro} Чтений ≈ {R} млрд в год; {fmt_num(100 * f, 1)} % из них — сразу после собственной записи "
            f"пользователя (обновил профиль — открыл страницу). Устаревшие данные в таком чтении обходятся в "
            f"{fmt_num(s, 1)} ₽ (повторные действия, обращения в поддержку). Выручка сценариев с записью ≈ "
            f"{fmt_num(W, 0)} млн ₽ в год, каждые 100 мс задержки записи стоят {fmt_num(x, 1)} % этой выручки. "
            f"Варианты:\n" + "\n".join(rows) +
            "\n\nКакой вариант даёт минимальную годовую цену (инфраструктура, устаревшие чтения и задержка записи)?")
    expl = ("Цены: лидер — I_lead; реплики — I_rep + чтения × доля после записи × цена устаревшего; чтение своих "
            "записей — I_rep + доля × (I_lead − I_rep) + сопровождение; синхронная — I_sync + выручка × x % × Δ / 100 "
            "мс. Итоги: " + "; ".join(f"{NAMES[k]} — {fmt_num(full[k], 1)} млн ₽" for k in ORDER) +
            f". Минимум — {NAMES[good]}. Без цены задержки записи вышло бы: {NAMES[no_lat]}.")
    program = PROGRAM.format(R=R, f=f, s=s, I_lead=I_lead, I_rep=I_rep, I_sync=I_sync, C_s=C_s, W=W, x=x,
                             delta=delta, labels={k: NAMES[k] for k in ORDER})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={"R": R, "f": f, "s": s, "I_lead": I_lead, "I_rep": I_rep, "I_sync": I_sync,
                               "C_s": C_s, "W": W, "x": x, "delta": delta, "good": good, "no_lat": no_lat},
                       note="Ответ проверяется программой: маршрутизация потока модельных чтений по правилу варианта.")
