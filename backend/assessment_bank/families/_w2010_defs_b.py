"""Волна 20.10: Principal направлений data_ml, qa, security (по 2)."""
from __future__ import annotations

from assessment_bank.families._w2010_defs import M, cap, define
from assessment_bank.families._w2010_kit import num

# ---------------------------------------------------------------- data_ml: динамический батчинг на GPU
define("data_ml.serving.principal_gpu_batching_mcq",
       contexts=["ранжирование ленты", "антифрод-скоринг", "классификация обращений", "эмбеддинги поиска",
                 "распознавание документов", "рекомендации товаров", "модерация изображений", "скоринг заявок"],
       model='''
from fractions import Fraction as F

def gpus(P, wait=True, fixed=True, b_one=False, rho=True):
    S, w, t0, k = (F(str(P[x])) for x in ("S", "w", "t0", "k"))
    budget = S - (w if wait else 0) - (t0 if fixed else 0)
    b = 1 if b_one else min(P["bmax"], int(budget // k))
    if b < 1:
        return None
    t = (t0 if fixed else 0) + k * b
    per_gpu = b * 1000 / t * (F(P["rho"], 100) if rho else 1)
    q = F(str(P["lam"])) / per_gpu
    return -(-q.numerator // q.denominator)

def answer(P):
    return gpus(P)

def brute(P):
    S, w, t0, k = (F(str(P[x])) for x in ("S", "w", "t0", "k"))
    best = None
    for b in range(1, P["bmax"] + 1):
        if w + t0 + k * b <= S:
            best = b
    t = t0 + k * best
    g = 1
    while g * best * 1000 * P["rho"] < F(str(P["lam"])) * t * 100:
        g += 1
    return g

def traps(P):
    return {"no_wait": gpus(P, wait=False), "no_fixed": gpus(P, fixed=False), "batch_1": gpus(P, b_one=True),
            "no_rho": gpus(P, rho=False), "no_wait_no_rho": gpus(P, wait=False, rho=False), "double": 2 * gpus(P)}

def fmt(x):
    return f"{x} GPU"
''',
       sample=lambda r: {"S": r.choice([60, 80, 100, 120]), "w": r.choice([5, 10, 15, 20]), "t0": r.choice([8, 10, 15]),
                         "k": r.choice([0.5, 0.8, 1.0, 1.5, 2.0]), "bmax": r.choice([64, 128]),
                         "lam": r.choice([3000, 5000, 8000, 12000, 20000]), "rho": r.choice([60, 70, 80])},
       accept=lambda P, ns: ns["answer"](P) is not None and 3 <= ns["answer"](P) <= 80,
       stem=lambda P, c: (f"Онлайн-инференс ({c}) на GPU с динамическим батчингом: сервер ждёт заполнения батча не дольше "
                          f"{P['w']} мс, время прогона батча из b запросов — {P['t0']} + {num(P['k'], 1)}·b мс (не больше "
                          f"{P['bmax']} в батче). SLO задержки — {P['S']} мс в худшем случае (ожидание + прогон). Поток — "
                          f"{num(P['lam'])} запросов в секунду, GPU загружаем не больше чем на {P['rho']} % (запас на "
                          "всплески).\n\nСколько GPU нужно при наибольшем батче, допустимом по SLO?"),
       explain=lambda P, a, t: (f"Наибольший батч: {P['w']} + {P['t0']} + {num(P['k'], 1)}·b ≤ {P['S']} → b = "
                                f"{min(P['bmax'], int((P['S'] - P['w'] - P['t0']) // P['k']))}. Пропускная способность GPU — "
                                f"b / t(b) с загрузкой {P['rho']} %; {num(P['lam'])} в секунду требуют {a} GPU."),
       trap_desc={"no_wait": "без ожидания заполнения батча", "no_fixed": "без постоянной части времени прогона",
                  "batch_1": "без батчинга", "no_rho": "без запаса загрузки", "no_wait_no_rho": "без ожидания и без запаса",
                  "double": "двойной запас"},
       trap_first="no_wait", rel=0.0, abs_min=1)

# ---------------------------------------------------------------- data_ml: размер разметки для оценки precision
define("data_ml.eval.principal_precision_labeling_mcq",
       contexts=["детектор мошеннических транзакций", "классификатор спама", "модель оттока", "детектор токсичных отзывов",
                 "модель дефектов на конвейере", "детектор дублей объявлений", "модель кредитного дефолта",
                 "классификатор срочных обращений"],
       model='''
from math import ceil
from statistics import NormalDist

def labeled(P, divide=True, two=True, rel=False, fpc=False):
    z = NormalDist().inv_cdf(1 - P["alpha"] / 100 / (2 if two else 1))
    p = P["prec"] / 100
    E = P["E"] / 100 * (p if rel else 1)
    n_pos = ceil(z ** 2 * p * (1 - p) / E ** 2)
    return ceil(n_pos / (P["q"] / 100)) if divide else n_pos

def answer(P):
    return labeled(P)

def traps(P):
    return {"no_divide": labeled(P, divide=False), "one_sided": labeled(P, two=False), "relative": labeled(P, rel=True),
            "by_base_rate": ceil(labeled(P, divide=False) / (P["base"] / 100)),
            "one_sided_no_div": labeled(P, divide=False, two=False), "x_classes": labeled(P) * 2}

def fmt(x):
    return f"{x:,} объектов".replace(",", "\\u00a0")
''',
       sample=lambda r: {"prec": r.choice([60, 70, 80, 85, 90]), "E": r.choice([2, 3, 4, 5]), "alpha": r.choice([5, 10]),
                         "q": r.choice([2, 4, 5, 8, 10]), "base": r.choice([1, 2, 3])},
       accept=lambda P, ns: P["base"] < P["q"],
       stem=lambda P, c: (f"{cap(c)}: нужно оценить precision новой версии на продовом потоке с точностью ±{P['E']} "
                          f"процентных пунктов (доверие {100 - P['alpha']} %, двусторонний интервал, нормальное "
                          f"приближение). Ожидаемая precision — около {P['prec']} %. Модель помечает как положительные "
                          f"≈ {P['q']} % объектов потока, истинная доля положительного класса — ≈ {P['base']} %. Размечаются "
                          "случайные объекты потока, разметка дорогая.\n\nСколько объектов потока нужно отправить на "
                          "разметку, чтобы среди них набралось достаточно предсказанных положительных?"),
       explain=lambda P, a, t: (f"Precision оценивается только по предсказанным положительным: n = z²·p(1 − p)/E² таких "
                                f"объектов, а на разметку уходит n / {num(P['q'] / 100, 2)} объектов потока (доля "
                                f"предсказанных положительных, а не истинная доля класса) — {num(a)}. Стратифицированная "
                                "выборка по предсказаниям сократила бы разметку."),
       trap_desc={"no_divide": "только число предсказанных положительных", "one_sided": "односторонний интервал",
                  "relative": "±E как относительная погрешность", "by_base_rate": "деление на истинную долю класса",
                  "one_sided_no_div": "односторонний и без деления", "x_classes": "удвоено на два класса"},
       trap_first="no_divide", rel=0.1, abs_min=20)

# ---------------------------------------------------------------- qa: допустимая нестабильность теста
define("qa.principal.flaky_budget_mcq",
       contexts=["регресс мобильного приложения", "e2e-набор интернет-магазина", "интеграционные тесты платежей",
                 "UI-тесты личного кабинета", "API-тесты партнёрского шлюза", "смоук перед релизом",
                 "контрактные тесты микросервисов", "набор тестов CRM"],
       model='''
def f_max(P, retries=True, exact=True):
    X = P["X"] / 100
    per_test = 1 - (1 - X) ** (1 / P["N"]) if exact else X / P["N"]
    return 100 * per_test ** (1 / (P["r"] + 1) if retries else 1)

def answer(P):
    return round(f_max(P), 3)

def brute(P):
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        red = 1 - (1 - mid ** (P["r"] + 1)) ** P["N"]
        if red <= P["X"] / 100:
            lo = mid
        else:
            hi = mid
    return round(100 * lo, 3)

def traps(P):
    return {"no_retries": round(f_max(P, retries=False), 3), "linear_no_retries": round(f_max(P, retries=False, exact=False), 3),
            "retries_add": round(f_max(P, retries=False) * (P["r"] + 1), 3), "per_run": round(P["X"] / P["N"] ** 0.5, 3),
            "suite_level": round(100 * (P["X"] / 100) ** (1 / (P["r"] + 1)), 3), "half": round(f_max(P) / 2, 3),
            "extra_try": round(100 * (1 - (1 - P["X"] / 100) ** (1 / P["N"])) ** (1 / (P["r"] + 2)), 3),
            "x2": round(2 * f_max(P), 3), "sqrt_retries": round(100 * (P["X"] / 100 / P["N"] ** 0.5) ** (1 / (P["r"] + 1)), 3)}

def fmt(x):
    return f"{x:.3f} %".replace(".", ",")
''',
       sample=lambda r: {"N": r.choice([300, 400, 600, 800, 1200, 1500, 2000, 3000, 5000]), "r": r.choice([1, 2]),
                         "X": r.choice([1, 2, 3, 5])},
       stem=lambda P, c: (f"{cap(c)}: {num(P['N'])} независимых тестов, упавший тест автоматически перезапускается до "
                          f"{P['r']} раз (тест красный, только если упали все {P['r'] + 1} попытки). Цель команды — ложно-"
                          f"красный прогон всего набора (без реального дефекта) не чаще чем в {P['X']} % прогонов.\n\n"
                          "Какая наибольшая вероятность нестабильного падения одной попытки теста допустима (одинаковая "
                          "для всех тестов)?"),
       explain=lambda P, a, t: (f"Тест красный с вероятностью f^{P['r'] + 1}, набор зелёный — (1 − f^{P['r'] + 1})^N. "
                                f"Условие 1 − (1 − f^{P['r'] + 1})^{P['N']} ≤ {P['X']} % даёт f ≤ {num(a, 3)} %. Перезапуски "
                                "возводят вероятность в степень, а не умножают допуск."),
       trap_desc={"no_retries": "без перезапусков", "linear_no_retries": "линейно X/N без перезапусков",
                  "retries_add": "перезапуски умножают допуск", "per_run": "деление на √N",
                  "suite_level": "перезапуски применены к набору, а не к тесту", "half": "половина допустимого",
                  "extra_try": "на одну попытку больше", "x2": "вдвое больше допустимого",
                  "sqrt_retries": "деление на √N с перезапусками"},
       trap_first="no_retries", rel=0.1, abs_min=0.001)

# ---------------------------------------------------------------- qa: число шардов e2e
define("qa.principal.e2e_shards_mcq",
       contexts=["e2e интернет-магазина", "UI-регресс банка", "e2e мобильного веба", "регресс CRM", "e2e бронирования",
                 "регресс админки", "e2e онбординга", "UI-тесты биллинга"],
       model='''
def lpt(durs, k):
    loads = [0] * k
    for d in sorted(durs, reverse=True):
        i = loads.index(min(loads))
        loads[i] += d
    return max(loads)

def shards(P, setup=True, longest=True, lpt_on=True):
    if (lpt_on or longest) and max(P["d"]) + (P["s"] if setup else 0) > P["T"]:
        return None                      # длинный тест не укладывается ни при каком числе шардов
    k = 1
    while k <= len(P["d"]):
        if lpt_on:
            wall = lpt(P["d"], k)
        else:
            wall = -(-sum(P["d"]) // k)
            if longest:
                wall = max(wall, max(P["d"]))
        if wall + (P["s"] if setup else 0) <= P["T"]:
            return k
        k += 1
    return None

def by_count(P):
    d = P["d"]
    for k in range(1, len(d) + 1):
        m = -(-len(d) // k)
        if max(sum(d[i:i + m]) for i in range(0, len(d), m)) + P["s"] <= P["T"]:
            return k
    return None

def answer(P):
    return shards(P)

def brute(P):
    for k in range(1, 200):
        loads = [0] * k
        for d in sorted(P["d"], reverse=True):
            j = min(range(k), key=lambda i: (loads[i], i))
            loads[j] += d
        if max(loads) + P["s"] <= P["T"]:
            return k

def traps(P):
    return {"no_setup": shards(P, setup=False), "sum_div": shards(P, lpt_on=False, longest=False),
            "sum_div_no_setup": shards(P, lpt_on=False, longest=False, setup=False),
            "sum_div_longest": shards(P, lpt_on=False), "plus_one": shards(P) + 1, "plus_two": shards(P) + 3,
            "by_count": by_count(P)}

def fmt(x):
    return f"{x} " + ("шард" if x % 10 == 1 and x % 100 != 11 else "шарда" if 2 <= x % 10 <= 4 and not 12 <= x % 100 <= 14 else "шардов")
''',
       sample=lambda r: (lambda T, s_: {"d": sorted([r.choice([2, 3, 4, 5, 6, 8]) for _ in range(r.randint(30, 50))]
                                                    + [r.choice([x for x in (14, 18, 22) if x + s_ + 3 <= T])], reverse=True),
                                             "s": s_, "T": T})(r.choice([25, 30, 35, 40]), r.choice([3, 4, 5, 6])),
       accept=lambda P, ns: ns["answer"](P) is not None and ns["answer"](P) >= 4,
       stem=lambda P, c: (f"{cap(c)}: длительности тестов (мин) — {', '.join(map(str, P['d']))}. Тесты раздаются по шардам "
                          f"жадно: самый длинный оставшийся — на наименее загруженный шард. Подготовка каждого шарда "
                          f"(контейнер, браузер, данные) — {P['s']} мин параллельно с остальными. Цель — весь прогон не "
                          f"дольше {P['T']} мин.\n\nСколько шардов нужно как минимум?"),
       explain=lambda P, a, t: (f"Время прогона — подготовка ({P['s']} мин) плюс самый загруженный шард. Сумма тестов "
                                f"{sum(P['d'])} мин, но длинный тест и неделимость тестов не дают поделить её ровно; жадная "
                                f"раздача укладывается в {P['T']} мин начиная с {a} шардов."),
       trap_desc={"no_setup": "без подготовки шарда", "sum_div": "сумма, делённая на шарды (без неделимости)",
                  "sum_div_no_setup": "сумма на шарды без подготовки", "sum_div_longest": "сумма на шарды с длинным тестом",
                  "plus_one": "на шард больше нужного", "plus_two": "с лишним запасом",
                  "by_count": "поровну по числу тестов подряд, без учёта длительности"},
       trap_first="no_setup", rel=0.0, abs_min=1, n_above=(1, 2, 3))

# ---------------------------------------------------------------- security: время хэширования пароля
define("security.principal.password_hash_budget_mcq",
       contexts=["вход в интернет-банк", "вход в маркетплейс", "вход в госуслуги региона", "вход в CRM",
                 "вход в медицинский портал", "вход в игровой сервис", "вход в почту", "вход в B2B-кабинет"],
       model='''
def t_max(P, cpu=True, mem=True, util=True, cores_total=True):
    lim = []
    cores = P["C"] * (P["n"] if cores_total else 1)
    if cpu:
        lim.append(cores * (P["u"] / 100 if util else 1) * 1000 / P["lam"])
    if mem:
        conc = P["n"] * (P["RAM"] * 1024 // P["m"])
        lim.append(conc * 1000 / P["lam"])
    return int(min(lim))

def answer(P):
    return t_max(P)

def traps(P):
    return {"cpu_only": t_max(P, mem=False), "mem_only": t_max(P, cpu=False), "no_util": t_max(P, util=False),
            "one_node": t_max(P, cores_total=False, mem=False), "half": t_max(P) // 2, "x2": t_max(P) * 2}

def fmt(x):
    return f"{x} мс"
''',
       sample=lambda r: {"lam": r.choice([200, 400, 600, 1000, 1500]), "C": r.choice([8, 16, 32]), "n": r.choice([2, 3, 4, 6]),
                         "u": r.choice([50, 60, 70]), "RAM": r.choice([2, 4, 8]), "m": r.choice([64, 128, 256])},
       accept=lambda P, ns: 20 <= ns["answer"](P) <= 2000,
       stem=lambda P, c: (f"{cap(c)}: пик — {num(P['lam'])} попыток входа в секунду, каждая — один хэш Argon2id (одно ядро "
                          f"на всё время хэширования, память {P['m']} МиБ на хэш). Хэшированием заняты {P['n']} узла "
                          f"по {P['C']} ядер; на узле под хэши выделено {P['RAM']} ГиБ памяти; CPU под хэши — не больше "
                          f"{P['u']} % (остальное — TLS и API).\n\nКакое наибольшее время одного хэша (параметры Argon2id) "
                          "выдержит пик?"),
       explain=lambda P, a, t: (f"По CPU: {P['n']}·{P['C']} ядер · {P['u']} % → время хэша ≤ ядра·доля·1000 / λ. По памяти: "
                                f"одновременно считается не больше {P['n']}·⌊{P['RAM']}·1024 / {P['m']}⌋ хэшей, по закону "
                                f"Литтла время хэша ≤ concurrency·1000 / λ. Ограничивает меньшее — {a} мс."),
       trap_desc={"cpu_only": "только по CPU", "mem_only": "только по памяти", "no_util": "CPU целиком под хэши",
                  "one_node": "ядра одного узла", "half": "половина допустимого", "x2": "вдвое больше допустимого"},
       trap_first="cpu_only", rel=0.08, abs_min=3)

# ---------------------------------------------------------------- security: окно использования отозванного токена
define("security.principal.revocation_window_mcq",
       contexts=["мобильный банк", "маркетплейс", "корпоративный SSO", "медицинский портал", "API партнёров",
                 "онлайн-кинотеатр", "система бронирования", "B2B-кабинет"],
       model='''
def window(P, cache=True, skew=True, ttl_cap=True, prop=True):
    via_list = (P["p"] if prop else 0) + (P["c"] if cache else 0)
    ttl = P["T"] + (P["s"] if skew else 0)
    return min(via_list, ttl) if ttl_cap else via_list

def answer(P):
    return window(P)

def traps(P):
    return {"ttl_only": P["T"], "ttl_skew": P["T"] + P["s"], "no_cache": window(P, cache=False),
            "no_prop": window(P, prop=False), "sum_all": P["p"] + P["c"] + P["T"] + P["s"],
            "no_cap": window(P, ttl_cap=False), "no_skew": window(P, skew=False)}

def fmt(x):
    return f"{x} с"
''',
       sample=lambda r: {"T": r.choice([300, 600, 900, 1800]), "s": r.choice([30, 60, 120]), "p": r.choice([60, 120, 300, 600, 900]),
                         "c": r.choice([30, 60, 120, 300])},
       stem=lambda P, c: (f"{cap(c)}: access-токен — JWT со сроком жизни {P['T']} с, шлюзы допускают расхождение часов "
                          f"{P['s']} с (leeway). При отзыве сессии идентификатор токена попадает в deny-list; шлюзы "
                          f"перечитывают deny-list раз в {P['p']} с, а результат проверки токена кэшируют на {P['c']} с. "
                          "Токен украли и использовали сразу после выдачи; сессию отозвали в ту же секунду.\n\n"
                          "Сколько секунд в худшем случае после отзыва украденный токен ещё принимается?"),
       explain=lambda P, a, t: (f"Через deny-list: до {P['p']} с до перечитывания плюс до {P['c']} с кэша проверки — "
                                f"{P['p'] + P['c']} с. Но токен в любом случае перестаёт приниматься по сроку жизни с учётом "
                                f"leeway: {P['T']} + {P['s']} с. Худший случай — меньшее из двух: {a} с."),
       trap_desc={"ttl_only": "только срок жизни без leeway", "ttl_skew": "только срок жизни с leeway",
                  "no_cache": "без кэша проверки", "no_prop": "без интервала перечитывания deny-list",
                  "sum_all": "всё сложено", "no_cap": "без ограничения сроком жизни", "no_skew": "без leeway"},
       trap_first="no_cache", rel=0.03, abs_min=10)
