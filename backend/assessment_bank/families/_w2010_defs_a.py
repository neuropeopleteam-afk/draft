"""Волна 20.10: Principal направлений backend, frontend, data_ml, qa, security (по 2)."""
from __future__ import annotations

from assessment_bank.families._w2010_kit import num
from assessment_bank.gen_utils import plural


def _d():
    from assessment_bank.families._w2010_defs import define, cap, M
    return define, cap, M


define, cap, M = _d()

# ---------------------------------------------------------------- backend: outbox relay после простоя
define("backend.outbox.principal_outbox_catchup_mcq",
       contexts=["заказы → брокер", "платежи → брокер", "события профиля → брокер", "статусы доставки → брокер",
                 "начисления бонусов → брокер", "события склада → брокер", "заявки на кредит → брокер",
                 "уведомления → брокер"],
       model='''
from fractions import Fraction as F

def workers(P, backlog=True, steady=True, rho=True, batch=True):
    need = (F(P["lam"]) if steady else 0) + (F(P["Q"], P["T"] * 60) if backlog else 0)
    per = F((P["B"] if batch else 1) * 1000, P["L"]) * (F(P["rho"], 100) if rho else 1)
    q = need / per
    return -(-q.numerator // q.denominator)

def answer(P):
    return workers(P)

def brute(P):
    w = 1
    while True:
        # целочисленно: (Q + lam·T·60)·L·100 <= w·B·1000·rho·T·60
        if (P["Q"] + P["lam"] * P["T"] * 60) * P["L"] * 100 <= w * P["B"] * 1000 * P["rho"] * P["T"] * 60:
            return w
        w += 1

def traps(P):
    return {"no_backlog": workers(P, backlog=False), "no_steady": workers(P, steady=False), "no_rho": workers(P, rho=False),
            "per_event": workers(P, batch=False), "no_backlog_no_rho": workers(P, backlog=False, rho=False),
            "double": 2 * workers(P)}

def fmt(x):
    return f"{x} " + ("воркер" if x % 10 == 1 and x % 100 != 11 else "воркера" if 2 <= x % 10 <= 4 and not 12 <= x % 100 <= 14 else "воркеров")
''',
       sample=lambda r: {"lam": r.choice([300, 500, 800, 1200, 2000]), "Q": r.choice([600_000, 1_200_000, 2_400_000, 3_600_000]),
                         "T": r.choice([10, 15, 20, 30]), "B": r.choice([50, 100, 200]), "L": r.choice([40, 60, 80, 120]),
                         "rho": r.choice([60, 70, 80])},
       accept=lambda P, ns: 3 <= ns["answer"](P) <= 80,
       stem=lambda P, c: (f"Transactional outbox ({c}): relay-воркер забирает из таблицы outbox пачку до {P['B']} событий, "
                          f"публикует и помечает отправленными — цикл занимает ≈ {P['L']} мс. Поток новых событий — "
                          f"{num(P['lam'])} в секунду. После простоя брокера в outbox накопилось {num(P['Q'])} событий; их "
                          f"нужно разобрать за {P['T']} минут, продолжая отправлять новые. Чтобы не мешать основной нагрузке "
                          f"на БД, воркер занят не больше чем на {P['rho']} %. Порядок внутри агрегата обеспечивается "
                          "блокировкой по ключу и на число воркеров не влияет.\n\nСколько relay-воркеров нужно?"),
       explain=lambda P, a, t: (f"Нужная пропускная способность — новые события плюс разбор накопленного: {num(P['lam'])} + "
                                f"{num(P['Q'])} / ({P['T']}·60) = {num(P['lam'] + P['Q'] / P['T'] / 60, 1)} в секунду. Воркер "
                                f"делает {P['B']} событий за {P['L']} мс с занятостью {P['rho']} %: "
                                f"{num(P['B'] * 1000 / P['L'] * P['rho'] / 100, 1)} в секунду. Итого {a}."),
       trap_desc={"no_backlog": "без разбора накопленного", "no_steady": "без продолжающегося потока",
                  "no_rho": "без запаса занятости", "per_event": "по одному событию за цикл (без пачек)",
                  "no_backlog_no_rho": "без накопленного и без запаса", "double": "двойной запас"},
       trap_first="no_backlog", rel=0.0, abs_min=1)

# ---------------------------------------------------------------- backend: локальные token bucket на шлюзах
define("backend.ratelimit.principal_split_bucket_mcq",
       contexts=["публичный API партнёров", "API отправки SMS", "API поиска", "API выгрузки отчётов",
                 "API создания заказов", "API проверки адресов", "API геокодирования", "API курсов валют"],
       model='''
def rejected(P, split=True, skew=True, burst=True):
    K = P["K"] if split else 1
    cap = P["C"] / K
    rate = P["r"] / K
    share = (P["h"] / 100 if skew else 1 / P["K"]) if split else 1.0
    tokens = cap if burst else 0.0
    rej = 0.0
    for sec in range(P["T"]):
        tokens = min(cap, tokens + (rate if sec > 0 else 0))
        demand = P["s"] * share
        ok = min(tokens, demand)
        tokens -= ok
        rej += demand - ok
    return round(rej)

def answer(P):
    return rejected(P)

def traps(P):
    return {"global_bucket": rejected(P, split=False), "even_split": rejected(P, skew=False),
            "no_burst": rejected(P, burst=False), "x_nodes": rejected(P) * P["K"],
            "even_no_burst": rejected(P, skew=False, burst=False), "half": rejected(P) // 2}

def fmt(x):
    return f"{x:,} запросов".replace(",", "\\u00a0")
''',
       sample=lambda r: {"K": r.choice([3, 4, 5, 6]), "C": r.choice([600, 1200, 1800, 2400]), "r": r.choice([200, 300, 400, 600]),
                         "h": r.choice([40, 45, 50, 60]), "s": r.choice([500, 700, 900, 1200]), "T": r.choice([10, 20, 30])},
       accept=lambda P, ns: ns["answer"](P) >= 50 and ns["traps"](P)["even_split"] > 0 and P["s"] > P["r"],
       stem=lambda P, c: (f"{cap(c)}: лимит клиента — token bucket ёмкостью {num(P['C'])} запросов с пополнением "
                          f"{P['r']} в секунду. Лимит реализован локально на каждом из {P['K']} шлюзов: у каждого — свой "
                          f"bucket с ёмкостью и скоростью, делёнными на {P['K']} (в начале bucket полный). Балансировщик "
                          f"привязывает клиента неравномерно: на самый загруженный шлюз приходит {P['h']} % его запросов. "
                          f"Клиент шлёт ровно {P['s']} запросов в секунду в течение {P['T']} с.\n\nСколько запросов этого "
                          "клиента отклонит самый загруженный шлюз за это время (пополнение — раз в секунду, начиная со "
                          "второй)?"),
       explain=lambda P, a, t: (f"У шлюза bucket {num(P['C'] / P['K'], 1)} и пополнение {num(P['r'] / P['K'], 1)} в секунду, "
                                f"а приходит {num(P['s'] * P['h'] / 100, 1)} в секунду: сначала тратится запас, затем "
                                f"проходит только пополнение. Посекундный расчёт даёт {num(a)} отклонённых. Локальные bucket "
                                "при неравномерной привязке режут клиента раньше глобального лимита."),
       trap_desc={"global_bucket": "один глобальный bucket", "even_split": "равномерная привязка к шлюзам",
                  "no_burst": "bucket в начале пустой", "x_nodes": "умножено на число шлюзов",
                  "even_no_burst": "равномерно и без запаса", "half": "половина отклонённых"},
       trap_first="global_bucket", rel=0.06, abs_min=10)

# ---------------------------------------------------------------- frontend: бюджет JS по TTI
define("frontend.perf.principal_js_budget_mcq",
       contexts=["лендинг акции", "каталог интернет-магазина", "личный кабинет банка", "страница статьи",
                 "форма записи к врачу", "карточка товара", "страница оплаты", "поиск билетов"],
       model='''
from fractions import Fraction as F

def budget(P, gzip=True, parse=True, rtt=True):
    t = P["TTI"] - (P["rtts"] * P["rtt"] if rtt else 0) - F(P["html"] * 1000, P["bw"]) - P["other"]
    per_kb = F((P["gz"] if gzip else 100) * 1000, 100 * P["bw"]) + (P["parse"] if parse else 0)
    return int(t // per_kb) if t > 0 else None

def answer(P):
    return budget(P)

def brute(P):
    kb = 0
    while True:
        # целочисленно, ×100·bw: время до конца разбора (kb + 1)-го КБ против TTI
        t = (P["rtts"] * P["rtt"] + P["other"]) * 100 * P["bw"] + P["html"] * 1000 * 100 \
            + (kb + 1) * P["gz"] * 1000 + (kb + 1) * P["parse"] * 100 * P["bw"]
        if t > P["TTI"] * 100 * P["bw"]:
            return kb
        kb += 1

def traps(P):
    return {"no_gzip": budget(P, gzip=False), "no_parse": budget(P, parse=False), "no_rtt": budget(P, rtt=False),
            "no_parse_no_rtt": budget(P, parse=False, rtt=False), "parse_on_gzip": int(budget(P) * P["gz"] / 100),
            "double": budget(P) * 2}

def fmt(x):
    return f"{x:,} КБ".replace(",", "\\u00a0")
''',
       sample=lambda r: {"TTI": r.choice([3500, 4000, 5000, 6000]), "rtt": r.choice([150, 200, 300]), "rtts": r.choice([4, 5]),
                         "bw": r.choice([200, 300, 400]), "html": r.choice([30, 50, 80]), "other": r.choice([300, 500, 800]),
                         "gz": r.choice([25, 30, 35]), "parse": r.choice([1, 2, 3])},
       accept=lambda P, ns: (ns["answer"](P) or 0) >= 100,
       stem=lambda P, c: (f"{cap(c)}: бюджет производительности — TTI не позже {num(P['TTI'])} мс на эталонном устройстве. "
                          f"Сеть: RTT {P['rtt']} мс, полоса {P['bw']} КБ/с; до первого байта JS уходит {P['rtts']} RTT "
                          f"(DNS, TCP, TLS, запрос HTML и JS), HTML — {P['html']} КБ. Разбор и исполнение JS на этом "
                          f"устройстве — ≈ {P['parse']} мс на каждый КБ несжатого кода; gzip сжимает JS до {P['gz']} %. "
                          f"Прочее (стили, шрифты, рендер) — {P['other']} мс. Всё скачивается последовательно.\n\n"
                          "Какой наибольший объём JS (КБ несжатого кода) укладывается в бюджет?"),
       explain=lambda P, a, t: (f"Свободно: {P['TTI']} − {P['rtts']}·{P['rtt']} − HTML − {P['other']} мс. КБ несжатого JS "
                                f"стоит {num(P['gz'] / 100 / P['bw'] * 1000, 2)} мс скачивания (после gzip) и {P['parse']} мс "
                                f"разбора — разбор идёт по несжатому коду. Итого ≈ {num(a)} КБ."),
       trap_desc={"no_gzip": "скачивание без сжатия", "no_parse": "без разбора и исполнения JS", "no_rtt": "без RTT",
                  "no_parse_no_rtt": "без разбора и без RTT", "parse_on_gzip": "бюджет пересчитан в сжатые КБ",
                  "double": "вдвое больше"},
       trap_first="no_parse", rel=0.08, abs_min=10)

# ---------------------------------------------------------------- frontend: overscan виртуального списка
define("frontend.perf.principal_virtual_overscan_mcq",
       contexts=["лента сообщений", "таблица заказов", "список товаров", "журнал событий", "список контактов",
                 "лента новостей", "таблица транзакций", "список задач"],
       model='''
def k(P, overhead=True, both=True, hz=True, layout=True, lmul=1, omul=1):
    frame = 1000 / (P["hz"] if hz else 60) - (P["o"] * omul if overhead else 0)
    per_row = P["c"] + (P["l"] * lmul if layout else 0)
    rows = int(frame * 1000 // per_row)
    free = rows - P["v"]
    if free < 0:
        return None
    return free // (2 if both else 1)

def answer(P):
    return k(P)

def brute(P):
    n = 0
    while (P["v"] + 2 * (n + 1)) * (P["c"] + P["l"]) <= (1000 / P["hz"] - P["o"]) * 1000 + 1e-9:
        n += 1
    return n

def traps(P):
    return {"no_overhead": k(P, overhead=False), "one_side": k(P, both=False), "hz60": k(P, hz=False) if P["hz"] != 60 else None,
            "no_layout": k(P, layout=False), "no_overhead_one_side": k(P, overhead=False, both=False),
            "half": (k(P) or 0) // 2, "layout_twice": k(P, lmul=2), "overhead_twice": k(P, omul=2)}

def fmt(x):
    return f"overscan = {x}"
''',
       sample=lambda r: {"hz": r.choice([90, 120]), "o": r.choice([3, 4, 5]), "c": r.choice([40, 60, 80, 120]),
                         "l": r.choice([20, 30, 40]), "v": r.choice([12, 18, 24, 30])},
       accept=lambda P, ns: (ns["answer"](P) or 0) >= 4,
       stem=lambda P, c: (f"{cap(c)} — виртуальный список: рендерятся видимые строки ({P['v']}) и overscan строк сверху и "
                          f"снизу. На прокрутке все отрисованные строки пересчитываются каждый кадр: рендер строки — "
                          f"≈ {P['c']} мкс, layout и paint — ещё {P['l']} мкс. Экран — {P['hz']} Гц; браузеру на кадр "
                          f"нужно ≈ {P['o']} мс собственной работы.\n\nКакой наибольший overscan (строк с каждой стороны) "
                          "держит прокрутку без пропуска кадров?"),
       explain=lambda P, a, t: (f"Кадр {num(1000 / P['hz'], 2)} мс минус {P['o']} мс браузера; строка стоит {P['c']} + "
                                f"{P['l']} мкс; из влезающих строк {P['v']} видимые, остаток делится на две стороны — {a}."),
       trap_desc={"no_overhead": "без работы браузера в кадре", "one_side": "overscan только с одной стороны",
                  "hz60": "кадр 60 Гц", "no_layout": "без layout и paint", "no_overhead_one_side": "без работы браузера и с одной стороны",
                  "half": "половина допустимого", "layout_twice": "layout учтён дважды",
                  "overhead_twice": "работа браузера учтена дважды"},
       trap_first="one_side", rel=0.0, abs_min=1)
