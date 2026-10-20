"""Волна 20.10, Principal по направлениям (devops, data_eng, mobile, analyst): числовые mcq_concept.
Регистрирует описания в _w2010_defs.DEFS; модули семейств — тонкие обёртки ``generate = make(FAMILY_ID)``."""
from __future__ import annotations

from assessment_bank.families._w2010_defs import cap, define
from assessment_bank.families._w2010_kit import num

_CD = "def cd(a, b):\n    return -(-a // b)\n"

# ---------------------------------------------------------------- devops: minReplicas под рост трафика до реакции HPA
define("devops.k8s.principal_hpa_ramp_mcq",
       contexts=["API каталога", "сервис авторизации", "API корзины", "сервис поиска", "API ленты", "сервис тарифов",
                 "API бронирования", "сервис уведомлений"],
       model=_CD + '''
def reps(P, t=None, at_target=False, growth=True):
    if t is None:
        t = P["sync"] + P["start"] + P["ready"]
    load = P["R0"] + (P["g"] * t if growth else 0)
    return cd(load * 100, P["c"] * P["u"]) if at_target else cd(load, P["c"])

def answer(P):
    return max(cd(P["R0"] * 100, P["c"] * P["u"]), reps(P))

def brute(P):
    t = P["sync"] + P["start"] + P["ready"]
    n = 1
    while not (all(n * P["c"] >= P["R0"] + P["g"] * s for s in range(t + 1)) and n * P["c"] * P["u"] >= P["R0"] * 100):
        n += 1
    return n

def traps(P):
    return {"no_startup": reps(P, t=P["sync"]), "no_ready": reps(P, t=P["sync"] + P["start"]),
            "steady_only": cd(P["R0"] * 100, P["c"] * P["u"]), "at_target": reps(P, at_target=True),
            "double_t": reps(P, t=2 * (P["sync"] + P["start"] + P["ready"])), "x2": 2 * answer(P)}

def fmt(x):
    return f"minReplicas = {x}"
''',
       sample=lambda r: {"R0": r.choice([600, 900, 1200, 1800, 2400]), "g": r.choice([5, 10, 20, 30]),
                         "c": r.choice([40, 50, 80, 100]), "u": r.choice([60, 70, 80]), "sync": 15,
                         "start": r.choice([30, 45, 60, 90]), "ready": r.choice([10, 20, 30])},
       accept=lambda P, ns: ns["reps"](P) > ns["cd"](P["R0"] * 100, P["c"] * P["u"]) and 4 <= ns["answer"](P) <= 120,
       stem=lambda P, c: (f"{cap(c)}: под держит до {P['c']} RPS при 100 % CPU, HPA целится в {P['u']} % CPU. Сейчас "
                          f"{num(P['R0'])} RPS, в пик трафик растёт линейно на {P['g']} RPS каждую секунду. Худший случай "
                          f"реакции: до {P['sync']} с до очередного цикла HPA, затем {P['start']} с на запуск пода и "
                          f"{P['ready']} с до readiness. Пока новые поды не готовы, нагрузку несут текущие.\n\nКакой "
                          "наименьший minReplicas гарантирует, что до готовности новых подов загрузка не превысит 100 %?"),
       explain=lambda P, a, t: (f"Реакция — {P['sync']} + {P['start']} + {P['ready']} = "
                                f"{P['sync'] + P['start'] + P['ready']} с; за это время трафик дорастёт до "
                                f"{num(P['R0'] + P['g'] * (P['sync'] + P['start'] + P['ready']))} RPS, и его должны "
                                f"выдержать текущие поды на 100 % CPU (по {P['c']} RPS). Не меньше и обычного числа "
                                f"подов по цели {P['u']} %. Итого {a}."),
       trap_desc={"no_startup": "только цикл HPA", "no_ready": "без ожидания readiness",
                  "steady_only": "только по текущему трафику", "at_target": "текущие поды на целевой загрузке",
                  "double_t": "двойное время реакции", "x2": "двойной запас"},
       trap_first="no_ready", rel=0.0, abs_min=1)

# ---------------------------------------------------------------- devops: порог алерта по burn rate
define("devops.sre.principal_burn_rate_mcq",
       contexts=["API платежей", "сервис входа", "API заказов", "поиск", "лента", "API доставки", "биллинг",
                 "сервис отчётов"],
       model='''from fractions import Fraction as F

def thr(P, frac=True, period=720, window=None):
    w = P["W"] if window is None else window
    burn = (F(P["X"], 100) if frac else F(P["X"])) * period / w
    return burn * F(P["e"], 10000)          # доля ошибок в процентах (e — бюджет в сотых долях процента)

def answer(P):
    return thr(P)

def brute(P):
    # перебор долей ошибок с шагом 0,0001 %: наименьшая, при которой за окно W ч сгорает X % месячного бюджета
    budget = P["e"] * 720                    # «процент·час» ×10000 за 30 дней
    r = 0
    while r * P["W"] * 100 < P["X"] * budget:
        r += 1
    return F(r, 10000)

def traps(P):
    t = {"no_period": F(P["X"], 100) * F(P["e"], 10000), "days": thr(P, period=30),
         "window_days": thr(P, window=P["W"] * 24), "no_frac": thr(P, frac=False),
         "full_budget": F(720, P["W"]) * F(P["e"], 10000), "remaining": (1 - F(P["X"], 100)) * 720 / P["W"] * F(P["e"], 10000)}
    return {k: v for k, v in t.items() if v <= 100}

def fmt(x):
    return (f"{float(x):.4f}".rstrip("0").rstrip(".") + " %").replace(".", ",")
''',
       sample=lambda r: (lambda X, W: {"e": r.choice([10, 20, 25, 50, 100]), "X": X, "W": W})(
           *r.choice([(2, 1), (5, 6), (10, 72), (2, 6), (5, 1), (10, 24), (1, 1), (3, 6), (5, 24), (10, 48), (4, 12), (2, 3)])),
       accept=lambda P, ns: ns["brute"](P) == ns["answer"](P),
       stem=lambda P, c: (f"{cap(c)}: SLO доступности — {100 - P['e'] / 100:g} % за 30 дней (720 ч), то есть бюджет "
                          f"ошибок {P['e'] / 100:g} % запросов. Политика алертов: страница дежурному, если за окно "
                          f"{P['W']} ч сгорело {P['X']} % месячного бюджета.\n\nПри какой доле ошибочных запросов "
                          "(постоянной на окне) должен срабатывать этот алерт?").replace("0.", "0,").replace("9.", "9,"),
       explain=lambda P, a, t: (f"Burn rate = {P['X']} % · 720 ч / {P['W']} ч = {num(P['X'] * 7.2 / P['W'], 2)}; "
                                f"порог доли ошибок = burn rate × бюджет ({P['e'] / 100:g} %)."),
       trap_desc={"no_period": "X % от бюджета без пересчёта на окно", "days": "период в днях вместо часов",
                  "window_days": "окно в днях вместо часов", "no_frac": "X % взято как X",
                  "full_budget": "весь бюджет за окно", "remaining": "оставшаяся часть бюджета"},
       trap_first="no_period", rel=0.1, abs_min=0.0001)

# ---------------------------------------------------------------- data_eng: разбор лага Kafka, лишние консьюмеры простаивают
define("data_eng.kafka.principal_lag_recovery_mcq",
       contexts=["поток кликов", "события заказов", "CDC из PostgreSQL", "логи приложений", "события платежей",
                 "телеметрия устройств", "события корзины", "поток показов"],
       model=_CD + '''
def minutes(P, k=None, prod=True):
    k = min(P["k"], P["n"]) if k is None else k
    rate = k * P["c"] - (P["p"] if prod else 0)
    if rate <= 0:
        return None
    return cd(P["L"], rate * 60)

def answer(P):
    return minutes(P)

def brute(P):
    lag, t = P["L"], 0
    while lag > 0:
        lag -= min(P["k"], P["n"]) * P["c"] * 60 - P["p"] * 60
        t += 1
    return t

def traps(P):
    return {"use_k": minutes(P, k=P["k"]), "no_produce": minutes(P, prod=False),
            "use_k_no_p": minutes(P, k=P["k"], prod=False), "group_c": minutes(P, k=1),
            "old_k": minutes(P, k=P["n"] // 2),
            "x2": 2 * minutes(P)}

def fmt(x):
    return f"≈ {x} мин"
''',
       sample=lambda r: (lambda n: {"n": n, "k": n + r.choice([2, 4, 6, 8]), "c": r.choice([800, 1000, 1500, 2000]),
                                    "p": r.choice([3000, 5000, 8000, 12000]),
                                    "L": r.choice([6, 9, 12, 18, 24, 36]) * 1_000_000})(r.choice([6, 8, 12, 16])),
       accept=lambda P, ns: P["n"] // 2 * P["c"] > 1.2 * P["p"] and 5 <= ns["answer"](P) <= 400,
       stem=lambda P, c: (f"Consumer group читает топик «{c}» из {P['n']} партиций; после инцидента лаг — "
                          f"{num(P['L'])} сообщений. Чтобы разобрать быстрее, группу расширили с {P['n'] // 2} до {P['k']} "
                          f"консьюмеров, каждый обрабатывает до {num(P['c'])} сообщений в секунду. Продюсеры продолжают "
                          f"писать {num(P['p'])} сообщений в секунду.\n\nЧерез сколько минут лаг уйдёт в ноль?"),
       explain=lambda P, a, t: (f"Партиций {P['n']}, поэтому работают только {P['n']} консьюмеров из {P['k']} (лишние "
                                f"простаивают). Скорость разбора — {P['n']}·{num(P['c'])} − {num(P['p'])} = "
                                f"{num(P['n'] * P['c'] - P['p'])} в секунду; {num(P['L'])} / это / 60 ≈ {a} мин."),
       trap_desc={"use_k": "все консьюмеры работают", "no_produce": "без продолжающейся записи",
                  "use_k_no_p": "все консьюмеры и без записи", "group_c": "скорость одного консьюмера на группу",
                  "old_k": "прежнее число консьюмеров",
                  "x2": "двойной запас"},
       trap_first="use_k", rel=0.1, abs_min=1, n_above=(0, 1, 2))

# ---------------------------------------------------------------- data_eng: горячее и холодное хранение
define("data_eng.storage.principal_tiering_cost_mcq",
       contexts=["сырые события", "логи", "кликстрим", "CDC-снимки", "телеметрия", "аудит-журнал",
                 "транзакции", "выгрузки партнёров"],
       model='''from fractions import Fraction as F

def cost(P, rf=True, comp=True, hot_days=None, cold_days=None, hot_comp=False):
    h = P["h"] if hot_days is None else hot_days
    cdays = P["r"] - P["h"] if cold_days is None else cold_days
    hot = F(P["D"] * h * (P["rf"] if rf else 1) * P["a"], P["k"] if hot_comp else 1)
    cold = F(P["D"] * cdays * P["b"], P["k"] if comp else 1)
    return round((hot + cold) / 1000)

def answer(P):
    return cost(P)

def brute(P):
    total = F(0)
    for age in range(P["r"]):
        total += P["D"] * P["rf"] * P["a"] if age < P["h"] else F(P["D"] * P["b"], P["k"])
    return round(total / 1000)

def traps(P):
    return {"no_rf": cost(P, rf=False), "no_comp": cost(P, comp=False), "all_hot": cost(P, hot_days=P["r"], cold_days=0),
            "cold_full": cost(P, cold_days=P["r"]), "hot_only": cost(P, cold_days=0), "hot_comp": cost(P, hot_comp=True)}

def fmt(x):
    return f"{x:,}".replace(",", " ") + " тыс. ₽/мес"
''',
       sample=lambda r: {"D": r.choice([200, 400, 600, 1000, 1500]), "h": r.choice([7, 14, 30]),
                         "r": r.choice([180, 365, 730]), "rf": 3, "a": r.choice([8, 10, 12]),
                         "b": r.choice([1, 2]), "k": r.choice([3, 4, 5])},
       accept=lambda P, ns: ns["answer"](P) >= 50,
       stem=lambda P, c: (f"Хранилище «{c}»: приходит {P['D']} ГБ в сутки (до сжатия). Первые {P['h']} суток данные "
                          f"лежат в горячем слое без сжатия с репликацией ×{P['rf']} по {P['a']} ₽ за ГБ·месяц, затем "
                          f"переезжают в объектное хранилище в Parquet со сжатием в {P['k']} раза по {P['b']} ₽ за "
                          f"ГБ·месяц (надёжность входит в цену) и хранятся до {P['r']} суток от поступления.\n\n"
                          "Сколько стоит хранение в месяц в установившемся режиме?"),
       explain=lambda P, a, t: (f"В горячем слое — {P['D']}·{P['h']} ГБ ×{P['rf']} реплики по {P['a']} ₽; в холодном — "
                                f"{P['D']}·({P['r']} − {P['h']}) ГБ / {P['k']} по {P['b']} ₽. Сумма ≈ {a:,} тыс. ₽."
                                .replace(",", " ")),
       trap_desc={"no_rf": "без репликации горячего слоя", "no_comp": "без сжатия холодного слоя",
                  "all_hot": "всё в горячем слое", "cold_full": "холодный слой на весь срок",
                  "hot_only": "без холодного слоя", "hot_comp": "сжатие и в горячем слое"},
       trap_first="no_rf", rel=0.1, abs_min=5)

# ---------------------------------------------------------------- mobile: поэтапный релиз и обнаружение регресса крэшей
define("mobile.principal.staged_rollout_mcq",
       contexts=["банковское приложение", "маркетплейс", "приложение такси", "доставка еды", "стриминг",
                 "трекер привычек", "приложение авиакомпании", "мессенджер"],
       model=_CD + '''
def pct(P, rate=None, hours=True, sessions=True, H=None):
    rate = P["d"] if rate is None else rate
    H = P["H"] if H is None else H
    den = P["DAU"] * (P["s"] if sessions else 1) * (H if hours else 24) * rate
    v = cd(P["K"] * 100 * 24 * 10000, den)
    return v if v <= 100 else None

def answer(P):
    return pct(P)

def brute(P):
    for q in range(1, 101):
        excess = P["DAU"] * q * P["s"] * P["H"] * P["d"]      # ×(1/100 · 1/24 · 1/10000)
        if excess >= P["K"] * 100 * 24 * 10000:
            return q

def traps(P):
    return {"total_c1": pct(P, rate=P["c0"] + P["d"]), "no_hours": pct(P, hours=False), "baseline": pct(P, rate=P["c0"]),
            "no_sessions": pct(P, sessions=False), "per_hour": pct(P, H=1), "x2": 2 * pct(P) if pct(P) <= 50 else None}

def fmt(x):
    return f"{x} % аудитории"
''',
       sample=lambda r: {"DAU": r.choice([200_000, 500_000, 1_000_000, 2_000_000]), "s": r.choice([3, 4, 6]),
                         "c0": r.choice([4, 6, 10, 15]), "d": r.choice([2, 3, 5]), "K": r.choice([40, 60, 100]),
                         "H": r.choice([4, 6, 12])},
       accept=lambda P, ns: ns["answer"](P) is not None and 2 <= ns["answer"](P) <= 40 and P["c0"] != P["d"],
       stem=lambda P, c: (f"{cap(c)}: {num(P['DAU'])} DAU, в среднем {P['s']} сессии на пользователя в сутки, сессии "
                          f"равномерно по суткам. Базовый уровень — {P['c0']} крэшей на 10 000 сессий; регресс, который "
                          f"нужно ловить, добавляет ещё {P['d']} на 10 000. Чтобы отличить регресс от шума, нужно "
                          f"увидеть не меньше {P['K']} лишних крэшей за первые {P['H']} ч поэтапного релиза.\n\n"
                          "На какую наименьшую долю аудитории (целый процент) выкатить первую ступень?"),
       explain=lambda P, a, t: (f"Лишние крэши за {P['H']} ч: DAU · доля · {P['s']} · {P['H']}/24 · {P['d']}/10 000 ≥ "
                                f"{P['K']}; считаются только добавочные {P['d']} на 10 000, а не весь уровень. Итого {a} %."),
       trap_desc={"total_c1": "весь уровень крэшей вместо добавки", "no_hours": "за сутки вместо окна",
                  "baseline": "по базовому уровню", "no_sessions": "по пользователям, а не сессиям",
                  "per_hour": "за один час", "x2": "двойной запас"},
       trap_first="total_c1", rel=0.0, abs_min=1)

# ---------------------------------------------------------------- mobile: синхронизация офлайн-очереди
define("mobile.principal.offline_queue_mcq",
       contexts=["приложение курьера", "полевой сотрудник", "трекер тренировок", "инвентаризация склада",
                 "приложение мерчандайзера", "медицинские обходы", "приложение инспектора", "сбор показаний счётчиков"],
       model=_CD + '''from fractions import Fraction as F

def secs(P, rtt=True, batch=True, x8=True, rtt_mult=1, transfer=True):
    N = P["t"] * 60 * P["e"]
    req = cd(N, P["B"]) if batch else N
    s = F(req * P["rtt"] * rtt_mult, 1000) if rtt else 0
    if transfer:
        s += F(N * P["sz"] * (8 if x8 else 1), P["bw"] * 1000)
    return cd(s.numerator, s.denominator) if isinstance(s, F) else s

def answer(P):
    return secs(P)

def brute(P):
    N = P["t"] * 60 * P["e"]
    ms, left = F(0), N
    while left > 0:
        n = min(P["B"], left)
        ms += P["rtt"] + F(n * P["sz"] * 8, P["bw"])      # мс: RTT + передача пачки
        left -= n
    s = ms / 1000
    return cd(s.numerator, s.denominator)

def traps(P):
    return {"no_rtt": secs(P, rtt=False), "no_x8": secs(P, x8=False), "rtt_only": secs(P, transfer=False),
            "per_event": secs(P, batch=False), "double_rtt": secs(P, rtt_mult=2), "x2": 2 * secs(P)}

def fmt(x):
    return f"≈ {x} с"
''',
       sample=lambda r: {"t": r.choice([2, 4, 6, 8]), "e": r.choice([2, 4, 6, 10]), "sz": r.choice([400, 800, 1500]),
                         "B": r.choice([50, 100, 200]), "rtt": r.choice([200, 400, 800]), "bw": r.choice([256, 512, 1024])},
       accept=lambda P, ns: 10 <= ns["answer"](P) <= 3000,
       stem=lambda P, c: (f"{cap(c)}: без сети {P['t']} ч, приложение копит в офлайн-очереди {P['e']} событий в минуту по "
                          f"{P['sz']} байт. После появления сети очередь отправляется последовательно пачками до "
                          f"{P['B']} событий; каждый запрос — RTT {P['rtt']} мс плюс передача тела на {P['bw']} кбит/с "
                          "(1 кбит = 1000 бит), служебными заголовками пренебречь.\n\nЗа сколько секунд очередь уйдёт?"),
       explain=lambda P, a, t: (f"Событий {P['t']}·60·{P['e']} = {num(P['t'] * 60 * P['e'])}; запросов — по {P['B']} в "
                                f"пачке, каждый стоит RTT {P['rtt']} мс; тело — события × {P['sz']} байт × 8 бит / "
                                f"{P['bw']} кбит/с. Сумма ≈ {a} с."),
       trap_desc={"no_rtt": "без RTT", "no_x8": "байты как биты", "rtt_only": "только RTT",
                  "per_event": "по запросу на событие", "double_rtt": "два RTT на запрос", "x2": "двойной запас"},
       trap_first="per_event", rel=0.1, abs_min=2)

# ---------------------------------------------------------------- analyst: пиковый RPS из бизнес-метрик (НФТ)
define("analyst.principal.peak_rps_mcq",
       contexts=["онлайн-кинотеатр", "маркетплейс", "приложение банка", "сервис доставки", "портал госуслуг региона",
                 "сервис бронирования", "образовательная платформа", "сервис объявлений"],
       model=_CD + '''
def rps(P, users=None, req=True, factor=True, period=3600, share=True):
    u = P["MAU"] * P["dau"] // 100 if users is None else users
    num_ = u * P["act"] * (P["req"] if req else 1) * (P["sh"] if share else 100) * (P["f"] if factor else 1)
    return cd(num_, 100 * period)

def answer(P):
    return rps(P)

def brute(P):
    dau = P["MAU"] * P["dau"] // 100
    per_hour = dau * P["act"] * P["req"] * P["sh"] / 100
    r = 0
    while r * 3600 < per_hour * P["f"] - 1e-6:
        r += 1
    return r

def traps(P):
    return {"avg_day": rps(P, share=False, factor=False, period=86400), "no_req": rps(P, req=False),
            "no_factor": rps(P, factor=False), "mau": rps(P, users=P["MAU"]), "x2": 2 * rps(P), "per_minute": rps(P, period=60)}

def fmt(x):
    return f"{x:,}".replace(",", " ") + " RPS"
''',
       sample=lambda r: {"MAU": r.choice([1, 2, 3, 5, 8, 12]) * 1_000_000, "dau": r.choice([20, 25, 30, 40]),
                         "act": r.choice([10, 15, 20, 30]), "req": r.choice([3, 5, 8]), "sh": r.choice([8, 10, 12, 15]),
                         "f": r.choice([2, 3])},
       accept=lambda P, ns: ns["brute"](P) == ns["answer"](P),
       stem=lambda P, c: (f"Нефункциональные требования для «{c}»: MAU {num(P['MAU'])}, DAU — {P['dau']} % от MAU, "
                          f"пользователь совершает {P['act']} действий в сутки, каждое — {P['req']} запроса к API. На "
                          f"пиковый час приходится {P['sh']} % суточных действий, а внутри часа минутные пики в "
                          f"{P['f']} раза выше среднего по часу.\n\nКакой пиковый RPS записать в требования?"),
       explain=lambda P, a, t: (f"DAU = {num(P['MAU'] * P['dau'] // 100)}; запросов в пиковый час — DAU·{P['act']}·"
                                f"{P['req']}·{P['sh']} %; делим на 3600 и умножаем на {P['f']}: ≈ {a:,} RPS."
                                .replace(",", " ")),
       trap_desc={"avg_day": "среднее за сутки", "no_req": "действия вместо запросов", "no_factor": "без минутных пиков",
                  "mau": "MAU вместо DAU", "x2": "двойной запас", "per_minute": "за минуту вместо секунды"},
       trap_first="avg_day", rel=0.1, abs_min=2)

# ---------------------------------------------------------------- analyst: число партиций топика в требованиях к интеграции
define("analyst.principal.kafka_partitions_mcq",
       contexts=["события заказов", "статусы платежей", "изменения остатков", "события пользователей",
                 "заявки на доставку", "журнал операций", "события тарифов", "уведомления партнёров"],
       model=_CD + '''
def parts(P, growth=True, head=True, per=None):
    per = P["c"] if per is None else per
    load = P["T"] * (P["g"] if growth else 1) * (100 + (P["h"] if head else 0))
    return cd(load, 100 * per)

def answer(P):
    return max(parts(P), parts(P, per=P["p"]))

def brute(P):
    n = 1
    while n * min(P["c"], P["p"]) * 100 < P["T"] * P["g"] * (100 + P["h"]):
        n += 1
    return n

def traps(P):
    a = answer(P)
    p2 = 1
    while p2 < a:
        p2 *= 2
    return {"no_growth": parts(P, growth=False), "no_head": parts(P, head=False), "producer": parts(P, per=P["p"]),
            "sum": parts(P) + parts(P, per=P["p"]), "x2": 2 * a, "pow2": p2 if p2 != a else None,
            "no_growth_head": parts(P, growth=False, head=False)}

def fmt(x):
    return f"{x} партиций"
''',
       sample=lambda r: {"T": r.choice([4000, 6000, 10000, 15000, 25000]), "g": r.choice([2, 3]), "h": r.choice([20, 30, 50]),
                         "c": r.choice([500, 800, 1000, 1500]), "p": r.choice([5000, 8000, 10000])},
       accept=lambda P, ns: 6 <= ns["answer"](P) <= 300 and P["c"] < P["p"],
       stem=lambda P, c: (f"Требования к топику «{c}»: сейчас {num(P['T'])} сообщений в секунду в пик, через два года "
                          f"ожидается рост в {P['g']} раза, запас по пропускной способности — {P['h']} %. Нагрузочный тест: "
                          f"один консьюмер на партицию обрабатывает {num(P['c'])} сообщений в секунду, продюсер пишет в "
                          f"партицию до {num(P['p'])} в секунду. Число партиций потом не меняют (иначе ломается порядок "
                          "по ключу).\n\nСколько партиций заложить?"),
       explain=lambda P, a, t: (f"Целевой поток — {num(P['T'])}·{P['g']}·(1 + {P['h']} %) = "
                                f"{num(P['T'] * P['g'] * (100 + P['h']) // 100)} в секунду; узкое место — консьюмер "
                                f"({num(P['c'])} на партицию). Итого {a}."),
       trap_desc={"no_growth": "без роста", "no_head": "без запаса", "producer": "по продюсеру",
                  "sum": "сумма по продюсеру и консьюмеру", "x2": "двойной запас", "pow2": "до степени двойки",
                  "no_growth_head": "без роста и запаса"},
       trap_first="no_growth", rel=0.05, abs_min=1, n_above=(1, 2, 3))
