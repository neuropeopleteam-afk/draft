"""backend.strategy.principal_concurrency_model_mcq — mcq_concept (Principal, короткое): модель конкурентности по цене.

Сервис на пике обслуживает λ запросов в секунду; каждый занимает c мс процессора и w мс ждёт нижний сервис.
Инстанс: k ядер (загрузка не выше 70 %) и пул из n потоков; поток занят всё время запроса (c + w). По закону
Литтла число одновременно занятых потоков = λ · (c + w) / 1000. Нужное число инстансов = max(по потокам, по
процессору), с округлением вверх. Четыре варианта:
  * оставить как есть — n потоков, цена инстанса P;
  * удвоить пул потоков — 2n потоков, памяти больше: инстанс P · m;
  * асинхронный ввод-вывод — ожидание не держит поток (ограничение только процессор), переписывание R млн ₽ в год
    (с распределением на срок службы);
  * вынести медленный вызов в очередь — доля q запросов не ждёт нижний сервис (w → 0), очередь и обработчики Q
    млн ₽ в год.
Годовая цена = инстансы × P (или P · m) × 12 + разовые/годовые доплаты.

Ловушки: «асинхронный ввод-вывод всегда выгоднее», «без переписывания» (удвоить пул) и расчёт только по процессору
(без ограничения потоков). Верный вариант распределён поровну по четырём и отличается хотя бы от двух ловушек
(если верна сама ловушка — хотя бы от одной). Ключ проверяется исполнением: программа раскладывает поток запросов
одной секунды пика по типам (с ожиданием и без), считает занятые потоки и процессор, число инстансов каждого
варианта и печатает букву минимума цены.
"""
from __future__ import annotations

import math

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "backend.strategy.principal_concurrency_model_mcq"

CONTEXTS = [("расчёт доставки", "сервис тарифов"), ("проверка платежа", "антифрод"), ("выдача ленты", "рекомендации"),
            ("поиск рейсов", "агрегатор тарифов"), ("оформление полиса", "скоринг"), ("загрузка корзины", "склад"),
            ("отправка сообщений", "сервис доставки уведомлений")]
NAMES = {"keep": "оставить как есть", "pool": "удвоить пул потоков", "async": "переписать на асинхронный ввод-вывод",
         "queue": "вынести медленный вызов в очередь"}
ORDER = ["keep", "pool", "async", "queue"]

PROGRAM = """import math
opts = __OPTS__
lam, c, w, k, n = {lam}, {c}, {w}, {k}, {n}
P, m, R, Q, q = {P}, {m}, {R}, {Q}, {q}
labels = {labels!r}
deferred = int(round(lam * q))                  # запросов в секунду, которым ответ нижнего сервиса не нужен сразу
cost = {{}}
for plan, label in labels.items():
    busy_ms = cpu_ms = 0.0                      # поток-мс и процессор-мс за секунду пика
    for i in range(lam):
        waits = not (plan == "queue" and i < deferred)
        cpu_ms += c
        if plan != "async":
            busy_ms += c + (w if waits else 0)
    threads = {{"pool": 2 * n}}.get(plan, n)
    by_cpu = math.ceil(cpu_ms / 1000 / (k * 0.7))
    by_threads = math.ceil(busy_ms / 1000 / threads) if plan != "async" else 0
    inst = max(by_cpu, by_threads)
    price = P * m if plan == "pool" else P
    cost[label] = inst * price * 12 + {{"async": R, "queue": Q}}.get(plan, 0)
best = min(cost, key=cost.get)
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _argmin(d, rel=0.04):
    v = sorted(d.values())
    return min(d, key=d.get) if v[1] - v[0] >= rel * v[1] else None


def _costs(lam, c, w, k, n, P, m, R, Q, q, threads_limit=True):
    deferred = int(round(lam * q))
    by_cpu = math.ceil(lam * c / 1000 / (k * 0.7))

    def inst(threads, busy):
        return max(by_cpu, math.ceil(busy / 1000 / threads)) if threads_limit else by_cpu
    busy_full = lam * (c + w)
    busy_q = lam * c + (lam - deferred) * w
    return {"keep": inst(n, busy_full) * P * 12, "pool": inst(2 * n, busy_full) * P * m * 12,
            "async": by_cpu * P * 12 + R, "queue": inst(n, busy_q) * P * 12 + Q}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, down = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)
    for _ in range(80000):
        lam = rng.choice([2000, 4000, 6000, 10000])
        c = rng.choice([5, 10, 20])
        w = rng.choice([50, 100, 200, 400])
        k = rng.choice([4, 8])
        n = rng.choice([100, 200, 400])
        P = rng.choice([0.03, 0.05, 0.08])              # млн ₽ в месяц за инстанс
        m = rng.choice([1.2, 1.4, 1.7])
        R = rng.choice([3, 6, 10, 20])
        Q = rng.choice([1, 2, 4, 8])
        q = rng.choice([0.3, 0.5, 0.7])
        a = (lam, c, w, k, n, P, m, R, Q, q)
        full = _costs(*a)
        good = _argmin(full)
        if good != target:
            continue
        cpu_only = _argmin(_costs(*a, threads_limit=False))
        if cpu_only is None:
            continue
        traps = ("async", "pool", cpu_only)
        if sum(t != good for t in traps) >= (1 if good in ("async", "pool") else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    cap = lambda t: t[0].upper() + t[1:]
    kw = plural(k, "ядро", "ядра", "ядер")
    nw = plural(n, "поток", "потока", "потоков")
    rows = [f"• {cap(NAMES['keep'])}: {n} {nw} на инстанс, {fmt_num(1000 * P, 0)} тыс. ₽ в месяц за инстанс.",
            f"• {cap(NAMES['pool'])}: {2 * n} потоков на инстанс; памяти нужно больше, инстанс дороже в "
            f"{fmt_num(m, 1)} раза.",
            f"• {cap(NAMES['async'])}: ожидание не занимает поток, остаётся только ограничение процессора; "
            f"переписывание — {R} млн ₽ в год (с распределением на срок службы).",
            f"• {cap(NAMES['queue'])}: {fmt_num(100 * q, 0)} % запросов не ждут ответа «{down}» (результат "
            f"досылается позже); очередь и обработчики — {Q} млн ₽ в год."]
    intro = rng.choice([
        f"Вы — главный инженер. Сценарий «{ctx}» к пику сезона упирается в инстансы, и нужно выбрать, что менять.",
        f"Сервис сценария «{ctx}» на пике требует всё больше инстансов; архитектурный совет просит главного "
        f"инженера выбрать вариант.",
        f"Перед сезоном нужно подготовить сценарий «{ctx}» к пику; решение о модели обработки запросов — за вами как "
        f"за главным инженером.",
    ])
    stem = (f"{intro} На пике ≈ {fmt_num(lam, 0)} запросов в секунду; каждый занимает {c} мс процессора и {w} мс ждёт "
            f"ответа сервиса «{down}». Инстанс: {k} {kw} (загрузка не выше 70 %), пул потоков; поток занят всё время "
            f"запроса. Инстансов держат на пик весь год (12 месяцев), число округляется вверх. Варианты:\n" +
            "\n".join(rows) + "\n\nКакой вариант даёт минимальную годовую цену?")
    expl = ("Занятые потоки = λ × (c + w) / 1000 (закон Литтла), инстансы = max(⌈потоки / пул⌉, ⌈λ × c / 1000 / "
            "(ядра × 0,7)⌉); у асинхронного — только процессор, у очереди ожидание остаётся у (1 − q) запросов. "
            "Итоги: " + "; ".join(f"{NAMES[k_]} — {fmt_num(full[k_], 1)} млн ₽" for k_ in ORDER) +
            f". Минимум — {NAMES[good]}. Только по процессору вышло бы: {NAMES[cpu_only]}.")
    program = PROGRAM.format(lam=lam, c=c, w=w, k=k, n=n, P=P, m=m, R=R, Q=Q, q=q,
                             labels={k_: NAMES[k_] for k_ in ORDER})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k_] for k_ in ORDER if k_ != good], program=program, explanation=expl,
                       params={"lam": lam, "c": c, "w": w, "k": k, "n": n, "P": P, "m": m, "R": R, "Q": Q, "q": q,
                               "good": good, "cpu_only": cpu_only},
                       note="Ответ проверяется программой: раскладка секунды пика по запросам и число инстансов.")
