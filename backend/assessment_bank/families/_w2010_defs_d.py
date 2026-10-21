"""Волна 20.10, Senior/Lead по ключевым навыкам вакансий hh.ru, которых не хватало банку
(spark, clickhouse, postgresql, pytorch, numpy, manual testing, selenium, kafka, statistics, rest-api, react native).
Числовые mcq_concept; регистрирует описания в _w2010_defs.DEFS."""
from __future__ import annotations

from assessment_bank.families._w2010_defs import cap, define
from assessment_bank.families._w2010_kit import num

_CD = "def cd(a, b):\n    return -(-a // b)\n"
_F = "from fractions import Fraction as F\n"

def _end(x):
    import datetime as dt
    return (dt.date.fromisoformat(x[0]) + dt.timedelta(days=x[1])).isoformat()


def _d(n):
    return f"{float(n):.1f}".replace(".", ",")

# ---------------------------------------------------------------- spark: перекос ключа и salting
define("data_eng.spark.spark_skew_salting_mcq",
       contexts=["join кликов с профилями", "агрегация заказов по продавцу", "join логов с устройствами",
                 "группировка событий по стране", "join платежей с мерчантами", "агрегация показов по баннеру",
                 "join сессий с пользователями", "группировка отзывов по товару"],
       model=_F + '''
def mx(P, salt=True, others=True):
    hot = F(P["N"] * P["f"], 100 * (P["s"] if salt else 1))
    rest = F(P["N"] * (100 - P["f"]), 100 * P["P"])
    return max(hot, rest) if others else hot

def answer(P):
    return mx(P)

def brute(P):
    tasks = [F(0)] * P["P"]
    rest = F(P["N"] * (100 - P["f"]), 100 * P["P"])
    tasks = [rest] * P["P"]
    for i in range(P["s"]):                       # каждая «соль» горячего ключа — отдельная задача
        tasks.append(F(P["N"] * P["f"], 100 * P["s"]))
    return max(tasks)

def traps(P):
    return {"no_salt": mx(P, salt=False), "even": F(P["N"], P["P"]), "salt_all": F(P["N"], P["s"]),
            "salt_x_p": F(P["N"] * P["f"], 100 * P["s"] * P["P"]), "rest": F(P["N"] * (100 - P["f"]), 100 * P["P"]),
            "x2": 2 * mx(P)}

def fmt(x):
    return (f"{float(x):.2f}".rstrip("0").rstrip(".") + " млн строк").replace(".", ",")
''',
       sample=lambda r: {"N": r.choice([200, 400, 600, 800, 1200]), "f": r.choice([10, 20, 30, 40]),
                         "P": r.choice([200, 400, 800]), "s": r.choice([8, 16, 32, 64])},
       accept=lambda P, ns: ns["mx"](P) > 1.5 * ns["traps"](P)["rest"],
       stem=lambda P, c: (f"Spark, {c}: {P['N']} млн строк, на один «горячий» ключ приходится {P['f']} % строк, остальные "
                          f"ключи распределены равномерно по {P['P']} партициям shuffle. Горячий ключ «посолили»: к нему "
                          f"добавили случайную соль от 0 до {P['s'] - 1}, и каждая соль обрабатывается отдельной задачей "
                          "(частичная агрегация с последующим объединением).\n\nСколько строк у самой тяжёлой задачи?"),
       explain=lambda P, a, t: (f"Горячий ключ делится на {P['s']} задач: {P['N']}·{P['f']} % / {P['s']}; остальные — "
                                f"{P['N']}·{100 - P['f']} % / {P['P']}. Самая тяжёлая — большее из двух."),
       trap_desc={"no_salt": "без соли", "even": "всё равномерно", "salt_all": "все строки на число солей",
                  "salt_x_p": "соль × партиции", "rest": "обычная партиция", "x2": "двойной запас"},
       trap_first="no_salt", rel=0.1, abs_min=0.01)

# ---------------------------------------------------------------- spark: партиции shuffle и волны задач
define("data_eng.spark.spark_shuffle_waves_mcq",
       contexts=["ночной пересчёт витрины", "дедупликация событий", "join фактов с измерениями", "агрегация логов",
                 "пересчёт рекомендаций", "сборка признаков", "сверка платежей", "расчёт когорт"],
       model=_CD + '''
def waves(P, parts=None, slots=None):
    parts = cd(P["S"] * 1024, P["t"]) if parts is None else parts
    slots = P["e"] * P["c"] if slots is None else slots
    return cd(parts, slots)

def answer(P):
    return waves(P)

def brute(P):
    left, w = cd(P["S"] * 1024, P["t"]), 0
    while left > 0:
        left -= P["e"] * P["c"]
        w += 1
    return w

def traps(P):
    return {"default200": waves(P, parts=200), "execs_only": waves(P, slots=P["e"]), "cores_only": waves(P, slots=P["c"]),
            "half": cd(waves(P), 2), "one": 1, "x2": 2 * waves(P), "gb_tasks": waves(P, parts=P["S"])}

def fmt(x):
    return f"{x} волн(ы)"
''',
       sample=lambda r: {"S": r.choice([60, 120, 200, 300, 500, 800]), "t": r.choice([128, 256]),
                         "e": r.choice([5, 10, 20]), "c": r.choice([2, 4, 5])},
       accept=lambda P, ns: 4 <= ns["answer"](P) <= 60,
       stem=lambda P, c: (f"Spark, {c}: объём shuffle — {P['S']} ГБ, AQE выключен, spark.sql.shuffle.partitions выставлен "
                          f"так, чтобы партиция была ≈ {P['t']} МБ (1 ГБ = 1024 МБ). Кластер — {P['e']} executors по "
                          f"{P['c']} ядра, одна задача занимает одно ядро.\n\nСколько волн задач понадобится стадии после "
                          "shuffle?"),
       explain=lambda P, a, t: (f"Партиций {P['S']}·1024 / {P['t']} = {-(-P['S'] * 1024 // P['t'])}; одновременно идёт "
                                f"{P['e']}·{P['c']} = {P['e'] * P['c']} задач; волн {a}."),
       trap_desc={"default200": "200 партиций по умолчанию", "execs_only": "задача на executor", "cores_only": "ядра одного executor",
                  "half": "половина", "one": "одна волна", "x2": "двойной запас", "gb_tasks": "партиция на гигабайт"},
       trap_first="default200", rel=0.0, abs_min=1)

# ---------------------------------------------------------------- clickhouse: count() FINAL у ReplacingMergeTree
define("data_eng.clickhouse.ch_replacing_final_mcq",
       contexts=["балансы пользователей", "статусы заказов", "профили клиентов", "остатки на складе",
                 "тарифы абонентов", "состояния устройств", "цены товаров", "лимиты карт"],
       model='''
def answer(P):
    return len({(u, d) for u, d, v in P["rows"]})

def brute(P):
    last = {}
    for u, d, v in P["rows"]:
        k = f"{u}|{d}"
        if k not in last or v >= last[k]:
            last[k] = v
    return len(last)

def traps(P):
    rows = P["rows"]
    return {"total": len(rows), "users": len({u for u, d, v in rows}), "days": len({d for u, d, v in rows}),
            "with_version": len({(u, d, v) for u, d, v in rows}), "users_x_days": len({u for u, d, v in rows}) * len({d for u, d, v in rows}),
            "top_version": sum(1 for u, d, v in rows if v == max(r[2] for r in rows))}

def fmt(x):
    return f"{x}"
''',
       sample=lambda r: (lambda us, ds: {"rows": [(r.choice(us), r.choice(ds), r.randint(1, 4)) for _ in range(r.randint(11, 15))]})(
           r.sample([101, 102, 103, 104, 105, 106, 107], r.choice([3, 4])), r.sample(["2026-10-01", "2026-10-02", "2026-10-03"], 3)),
       accept=lambda P, ns: True,
       stem=lambda P, c: (f"ClickHouse, таблица «{c}»: ENGINE = ReplacingMergeTree(version) ORDER BY (user_id, day). "
                          "Вставлены строки (user_id, day, version), фоновые слияния ещё не прошли:\n"
                          + "\n".join(f"({u}, '{d}', {v})" for u, d, v in P["rows"])
                          + "\n\nЧто вернёт SELECT count() FROM t FINAL?"),
       explain=lambda P, a, t: ("FINAL схлопывает строки с одинаковым ключом сортировки (user_id, day), оставляя строку с "
                                f"наибольшей версией; версия в ключ не входит. Уникальных пар — {a}."),
       trap_desc={"total": "все строки (без FINAL)", "users": "уникальные user_id", "days": "уникальные дни",
                  "with_version": "версия в ключе", "users_x_days": "все сочетания пользователей и дней",
                  "top_version": "только строки с максимальной версией"},
       trap_first="total", rel=0.0, abs_min=1)

# ---------------------------------------------------------------- clickhouse: сколько кусков создают вставки
define("data_eng.clickhouse.ch_insert_parts_mcq",
       contexts=["события приложения", "логи nginx", "метрики устройств", "заказы", "показы рекламы", "звонки колл-центра",
                 "транзакции", "клики"],
       model='''import datetime as dt

def rng(x):
    a = dt.date.fromisoformat(x[0])
    return a, a + dt.timedelta(days=x[1])

def months(a, b):
    return (b.year * 12 + b.month) - (a.year * 12 + a.month) + 1

def answer(P):
    return sum(months(*rng(x)) for x in P["batches"])

def brute(P):
    total = 0
    for x in P["batches"]:
        a, b = rng(x)
        seen, d = set(), a
        while d <= b:
            seen.add(d.strftime("%Y%m"))
            d += dt.timedelta(days=1)
        total += len(seen)
    return total

def traps(P):
    allm = set()
    for a, b in map(rng, P["batches"]):
        d = a
        while d <= b:
            allm.add((d.year, d.month))
            d += dt.timedelta(days=1)
    return {"batches": len(P["batches"]), "distinct_months": len(allm),
            "days": sum(x[1] + 1 for x in P["batches"]), "months_x_batches": len(allm) * len(P["batches"]),
            "minus_one": sum(months(*rng(x)) - 1 for x in P["batches"]) or None,
            "plus_batches": answer(P) + len(P["batches"])}

def fmt(x):
    return f"{x}"
''',
       sample=lambda r: {"batches": [(f"2026-{r.randint(1, 8):02d}-{r.randint(1, 28):02d}", r.choice([3, 10, 25, 40, 70]))
                                     for _ in range(r.choice([3, 4]))]},
       accept=lambda P, ns: ns["answer"](P) > len(P["batches"]),
       stem=lambda P, c: (f"ClickHouse, таблица «{c}»: MergeTree, PARTITION BY toYYYYMM(event_date). Выполнено "
                          f"{len(P['batches'])} отдельных INSERT, каждый со строками за непрерывный диапазон дат:\n"
                          + "\n".join(f"— с {x[0]} по {_end(x)}" for x in P["batches"])
                          + "\n\nСколько новых кусков (parts) создано до фоновых слияний?"),
       explain=lambda P, a, t: ("Один INSERT создаёт отдельный кусок на каждую затронутую партицию (месяц); куски разных "
                                f"вставок не объединяются до слияния. Сумма месяцев по вставкам — {a}."),
       trap_desc={"batches": "кусок на вставку", "distinct_months": "кусок на месяц вообще",
                  "days": "кусок на день", "months_x_batches": "месяцы × вставки",
                  "minus_one": "без первого месяца", "plus_batches": "плюс по куску на вставку"},
       trap_first="batches", rel=0.0, abs_min=1)

# ---------------------------------------------------------------- postgresql: отсечение секций (partition pruning)
define("data_eng.pg.pg_partition_pruning_mcq",
       contexts=["events", "payments", "orders", "logs", "metrics", "sessions", "clicks", "audit"],
       model='''import datetime as dt

def mi(d):
    return d.year * 12 + d.month - 1

def D(x):
    return dt.date.fromisoformat(x)

def answer(P):
    a, b = D(P["a"]), D(P["b"])
    last = b - dt.timedelta(days=1)                # граница b не входит
    return mi(last) - mi(a) + 1

def brute(P):
    seen, d = set(), D(P["a"])
    while d < D(P["b"]):
        seen.add((d.year, d.month))
        d += dt.timedelta(days=1)
    return len(seen)

def traps(P):
    a, b = D(P["a"]), D(P["b"])
    full = answer(P) - (1 if a.day != 1 else 0)
    return {"inclusive": mi(b) - mi(a) + 1, "diff": mi(b) - mi(a), "all": P["total"], "all_default": P["total"] + 1,
            "one": 1, "plus_default": answer(P) + 1, "minus_one": answer(P) - 1, "full_only": full}

def fmt(x):
    return f"{x}"
''',
       sample=lambda r: (lambda mo, day, m: {"a": f"2026-{mo:02d}-{day:02d}", "b": f"2026-{mo + m:02d}-01", "total": 24})(
           r.randint(1, 6), r.choice([1, 1, 10, 15]), r.choice([2, 3, 4, 5])),
       accept=lambda P, ns: ns["answer"](P) >= 2,
       stem=lambda P, c: (f"PostgreSQL: таблица {c} секционирована по диапазону ts — по секции на каждый месяц 2025–2026 "
                          f"(всего {P['total']}) плюс DEFAULT. Запрос:\n\nSELECT count(*) FROM {c}\nWHERE ts >= "
                          f"'{P['a']}' AND ts < '{P['b']}';\n\nСколько секций останется в плане "
                          "после отсечения (partition pruning)?"),
       explain=lambda P, a, t: ("Условие по ключу секционирования с константами — секции отсекаются при планировании; "
                                f"правая граница строгая, поэтому секция месяца {P['b'][:7]} не нужна, DEFAULT "
                                f"тоже не подходит. Остаётся {a}."),
       trap_desc={"inclusive": "правая граница включительно", "diff": "разность месяцев", "all": "без отсечения",
                  "all_default": "все секции и DEFAULT", "one": "одна секция", "plus_default": "плюс DEFAULT",
                  "minus_one": "без первой секции", "full_only": "только полные месяцы"},
       trap_first="inclusive", rel=0.0, abs_min=1, n_above=(0, 1, 2, 3))  # ранг ключа — весь диапазон; недостающие — контрольные значения

# ---------------------------------------------------------------- pytorch: размер входа Linear после свёрток
define("data_ml.dl.pytorch_conv_flatten_mcq",
       contexts=["классификатор дефектов", "распознавание цифр", "детектор брака на конвейере", "классификатор снимков",
                 "модель для документов", "классификатор жестов", "модель для спутниковых снимков", "детектор логотипов"],
       model='''
def out(n, k, s, p, mode="floor", plus=True, pad=True):
    v = n + (2 * p if pad else 0) - k
    q = -(-v // s) if mode == "ceil" else v // s
    return q + (1 if plus else 0)

def feats(P, **kw):
    h = out(P["H"], P["k1"], P["s1"], P["p1"], **kw)
    h = h // 2 if P["pool"] else h
    h = out(h, P["k2"], P["s2"], P["p2"], **kw)
    return P["c2"] * h * h

def answer(P):
    return feats(P)

def brute(P):
    def slide(n, k, s, p):
        return sum(1 for i in range(0, n + 2 * p - k + 1) if i % s == 0)
    h = slide(P["H"], P["k1"], P["s1"], P["p1"])
    if P["pool"]:
        h = sum(1 for i in range(0, h - 2 + 1) if i % 2 == 0)
    h = slide(h, P["k2"], P["s2"], P["p2"])
    return P["c2"] * h * h

def traps(P):
    h = out(out(P["H"], P["k1"], P["s1"], P["p1"]) // (2 if P["pool"] else 1), P["k2"], P["s2"], P["p2"])
    return {"no_pad": feats(P, pad=False), "ceil": feats(P, mode="ceil"), "no_plus": feats(P, plus=False),
            "in_channels": P["c1"] * h * h, "one_side": P["c2"] * h, "no_pool": (P["c2"] * out(out(P["H"], P["k1"], P["s1"], P["p1"]), P["k2"], P["s2"], P["p2"]) ** 2) if P["pool"] else None}

def fmt(x):
    return f"{x:,}".replace(",", " ")
''',
       sample=lambda r: {"H": r.choice([28, 32, 64, 96, 128]), "k1": r.choice([3, 5, 7]), "s1": r.choice([1, 2]),
                         "p1": r.choice([0, 1, 2]), "c1": r.choice([16, 32]), "pool": r.choice([True, False]),
                         "k2": r.choice([3, 5]), "s2": r.choice([1, 2]), "p2": r.choice([0, 1]), "c2": r.choice([32, 64])},
       accept=lambda P, ns: P["c1"] != P["c2"] and ((P["H"] + 2 * P["p1"] - P["k1"]) % P["s1"] or (P["s2"] > 1)),
       stem=lambda P, c: (f"PyTorch, {c}: вход — батч изображений 3×{P['H']}×{P['H']}.\n\nnn.Conv2d(3, {P['c1']}, "
                          f"kernel_size={P['k1']}, stride={P['s1']}, padding={P['p1']}) → ReLU"
                          + (" → nn.MaxPool2d(2)" if P["pool"] else "")
                          + f" → nn.Conv2d({P['c1']}, {P['c2']}, kernel_size={P['k2']}, stride={P['s2']}, "
                          f"padding={P['p2']}) → ReLU → nn.Flatten()\n\nКакой in_features должен быть у следующего "
                          "nn.Linear?"),
       explain=lambda P, a, t: ("Размер по стороне: ⌊(n + 2p − k) / s⌋ + 1 (округление вниз), MaxPool2d(2) делит пополам "
                                f"вниз; in_features = каналы последней свёртки × H × W = {a:,}.".replace(",", " ")),
       trap_desc={"no_pad": "без padding", "ceil": "округление вверх", "no_plus": "без +1",
                  "in_channels": "каналы первой свёртки", "one_side": "только одна сторона", "no_pool": "без пулинга"},
       trap_first="ceil", rel=0.0, abs_min=1)

# ---------------------------------------------------------------- numpy: форма результата broadcasting
define("data_ml.numpy.numpy_broadcast_size_mcq",
       contexts=["признаки × пороги", "эмбеддинги × центроиды", "цены × курсы", "сигналы × фильтры", "пользователи × товары",
                 "кадры × маски", "датчики × калибровки", "скоры × веса"],
       model='''
def shape(a, b):
    a, b = list(a), list(b)
    n = max(len(a), len(b))
    a, b = [1] * (n - len(a)) + a, [1] * (n - len(b)) + b
    res = []
    for x, y in zip(a, b):
        if x != y and 1 not in (x, y):
            return None
        res.append(max(x, y))
    return res

def size(s):
    r = 1
    for x in s:
        r *= x
    return r

def answer(P):
    s = shape(P["A"], P["B"])
    return size(s[:P["ax"]] + s[P["ax"] + 1:])

def brute(P):
    # явное построение индексов результата, затем свёртка по оси ax
    A, B = P["A"], P["B"]
    n = max(len(A), len(B))
    A2, B2 = (1,) * (n - len(A)) + tuple(A), (1,) * (n - len(B)) + tuple(B)
    dims = [max(x, y) for x, y in zip(A2, B2)]
    keep = [d for i, d in enumerate(dims) if i != P["ax"]]
    out = 1
    for d in keep:
        out *= d
    return out

def traps(P):
    s = shape(P["A"], P["B"])
    return {"sum_sizes": size(P["A"]) + size(P["B"]), "full": size(s), "a_only": size(P["A"]),
            "prod": size(P["A"]) * size(P["B"]), "wrong_axis": size(s[:P["ax"] - 1] + s[P["ax"]:]) if P["ax"] > 0 else None,
            "b_only": size(P["B"])}

def fmt(x):
    return f"{x:,}".replace(",", " ") + " элементов"
''',
       sample=lambda r: (lambda a, b, c: {"A": (a, 1, c), "B": (b, 1), "ax": r.choice([1, 2])})(
           r.choice([8, 16, 32, 64]), r.choice([10, 20, 50, 100]), r.choice([3, 5, 7, 12])),
       accept=lambda P, ns: len(set(P["A"]) | set(P["B"])) == 4,
       stem=lambda P, c: (f"NumPy, {c}: A.shape == {P['A']}, B.shape == {P['B']}.\n\nC = (A + B).sum(axis={P['ax']})\n\n"
                          "Сколько элементов в C?"),
       explain=lambda P, a, t: ("Формы выравниваются справа, единичные оси растягиваются: (A + B) имеет форму "
                                "(a, b, c); sum по оси убирает её. "
                                f"Итого {a:,}.".replace(",", " ")),
       trap_desc={"sum_sizes": "сумма размеров", "full": "без свёртки", "a_only": "размер A", "prod": "произведение размеров",
                  "wrong_axis": "не та ось", "b_only": "размер B"},
       trap_first="full", rel=0.0, abs_min=1)

# ---------------------------------------------------------------- pytorch: шаги оптимизатора при DDP и накоплении градиента
define("data_ml.dl.pytorch_grad_accum_steps_mcq",
       contexts=["дообучение BERT", "обучение ResNet", "дообучение LLM с LoRA", "обучение рекомендательной модели",
                 "обучение ViT", "дообучение ASR", "обучение детектора", "дообучение энкодера поиска"],
       model=_CD + '''
def steps(P, gpus=True, acc=True, mode="ceil"):
    per_rank = cd(P["N"], P["g"] if gpus else 1)        # DistributedSampler: поровну по рангам (с дополнением)
    micro = cd(per_rank, P["b"]) if mode == "ceil" else per_rank // P["b"]
    return cd(micro, P["a"] if acc else 1) if mode == "ceil" else micro // (P["a"] if acc else 1)

def answer(P):
    return steps(P)

def brute(P):
    per_rank = -(-P["N"] // P["g"])
    micro = 0
    while micro * P["b"] < per_rank:
        micro += 1
    s = 0
    while s * P["a"] < micro:
        s += 1
    return s

def traps(P):
    return {"no_gpus": steps(P, gpus=False), "no_acc": steps(P, acc=False), "both": steps(P, gpus=False, acc=False),
            "floor": steps(P, mode="floor") or None, "half": cd(steps(P), 2), "a_sq": cd(steps(P), P["a"])}

def fmt(x):
    return f"{x:,}".replace(",", " ") + " шагов"
''',
       sample=lambda r: {"N": r.choice([50_000, 120_000, 250_000, 1_000_000]) + r.randint(1, 999), "g": r.choice([2, 4, 8]),
                         "b": r.choice([8, 16, 32]), "a": r.choice([2, 4, 8])},
       accept=lambda P, ns: ns["answer"](P) >= 20,
       stem=lambda P, c: (f"PyTorch, {c}: {num(P['N'])} примеров, DDP на {P['g']} GPU (DistributedSampler), "
                          f"batch_size={P['b']} на GPU, накопление градиента на {P['a']} микробатча (optimizer.step() "
                          "раз в accum шагов, неполный хвост эпохи тоже завершается шагом), drop_last=False.\n\n"
                          "Сколько раз за эпоху вызовется optimizer.step()?"),
       explain=lambda P, a, t: (f"На каждый GPU — ⌈{num(P['N'])}/{P['g']}⌉ примеров, микробатчей ⌈…/{P['b']}⌉, шагов — "
                                f"⌈…/{P['a']}⌉ = {a:,}.".replace(",", " ")),
       trap_desc={"no_gpus": "без деления на GPU", "no_acc": "без накопления", "both": "без GPU и накопления",
                  "floor": "округление вниз", "half": "половина", "a_sq": "накопление учтено дважды"},
       trap_first="no_acc", rel=0.05, abs_min=1)

# ---------------------------------------------------------------- manual testing: граничные значения (3 точки) с совпадениями
define("qa.manual.manual_boundary_values_mcq",
       contexts=["форма заявки на кредит", "анкета страхования", "форма бронирования", "настройки тарифа",
                 "форма доставки", "профиль пациента", "форма заказа пропуска", "калькулятор вклада"],
       model='''
def pts(lo, hi, three=True):
    return {lo - 1, lo, lo + 1, hi - 1, hi, hi + 1} if three else {lo - 1, lo, hi, hi + 1}

def answer(P):
    return sum(len(pts(lo, hi)) for _, lo, hi in P["f"])

def brute(P):
    total = 0
    for _, lo, hi in P["f"]:
        vals = []
        for b in (lo, hi):
            for d in (-1, 0, 1):
                if b + d not in vals:
                    vals.append(b + d)
        total += len(vals)
    return total

def traps(P):
    k = len(P["f"])
    return {"six_each": 6 * k, "two_point": sum(len(pts(lo, hi, False)) for _, lo, hi in P["f"]), "eq_classes": 3 * k,
            "plus_nominal": answer(P) + 1, "valid_only": sum(len({lo, lo + 1, hi - 1, hi}) for _, lo, hi in P["f"]),
            "seven_each": 7 * k}

def fmt(x):
    return f"{x} значений"
''',
       sample=lambda r: {"f": [(n, lo, lo + r.choice([1, 2, 2, 3, 50, 99])) for n, lo in
                               zip(r.sample(["возраст", "срок, мес", "стаж, лет", "число гостей", "этаж", "сумма, тыс.", "дети"], 4),
                                   [r.choice([0, 1, 18]), r.choice([1, 3, 6]), r.choice([0, 1]), r.choice([1, 2])])]},
       accept=lambda P, ns: sum(1 for _, lo, hi in P["f"] if hi - lo <= 2) in (1, 2),
       stem=lambda P, c: (f"{cap(c)}: числовые поля с допустимыми целыми диапазонами (включительно):\n"
                          + "\n".join(f"— {n}: от {lo} до {hi}" for n, lo, hi in P["f"])
                          + "\n\nМетодика — трёхточечный анализ граничных значений: для каждой границы проверяются "
                          "значение границы и соседние слева и справа. Поля проверяются независимо, одинаковые значения "
                          "одного поля не повторяются.\n\nСколько разных проверяемых значений получится по всем полям?"),
       explain=lambda P, a, t: ("Для поля [lo, hi] — {lo−1, lo, lo+1, hi−1, hi, hi+1}; в узких диапазонах (hi − lo ≤ 2) "
                                f"точки совпадают, и их меньше шести. Итого {a}."),
       trap_desc={"six_each": "по 6 на поле без совпадений", "two_point": "двухточечная методика",
                  "eq_classes": "классы эквивалентности", "plus_nominal": "плюс номинальное значение",
                  "valid_only": "только допустимые", "seven_each": "по 7 на поле"},
       trap_first="six_each", rel=0.0, abs_min=1)

# ---------------------------------------------------------------- qa: нижняя граница pairwise
define("qa.manual.manual_pairwise_bound_mcq",
       contexts=["настройки поиска отелей", "конфигуратор тарифа", "матрица браузеров и ОС", "фильтры каталога",
                 "параметры отчёта", "настройки уведомлений", "конфигуратор ноутбука", "параметры доставки"],
       model='''
def answer(P):
    v = sorted(P["v"], reverse=True)
    return v[0] * v[1]

def brute(P):
    best = 0
    for i in range(len(P["v"])):
        for j in range(len(P["v"])):
            if i != j:
                best = max(best, P["v"][i] * P["v"][j])
    return best

def traps(P):
    v = sorted(P["v"], reverse=True)
    full = 1
    for x in v:
        full *= x
    return {"full": full, "sum": sum(v), "max": v[0], "pairs": len(v) * (len(v) - 1) // 2, "top3": v[0] * v[1] * v[2],
            "min_pair": v[-1] * v[-2]}

def fmt(x):
    return f"{x:,}".replace(",", " ") + " тестов"
''',
       sample=lambda r: {"v": [r.choice([2, 2, 3, 3, 4, 5, 6, 7]) for _ in range(r.choice([4, 5, 6]))]},
       accept=lambda P, ns: len(set(sorted(P["v"])[-2:] + sorted(P["v"])[:2])) >= 3,
       stem=lambda P, c: (f"{cap(c)}: независимые параметры с числом значений {', '.join(map(str, P['v']))}. Нужен "
                          "набор, покрывающий все пары значений любых двух параметров (pairwise).\n\nКакова нижняя "
                          "граница числа тестов в таком наборе?"),
       explain=lambda P, a, t: ("Все пары значений двух самых «широких» параметров должны встретиться, а в одном тесте "
                                f"только одна такая пара: не меньше произведения двух наибольших — {a}."),
       trap_desc={"full": "полный перебор", "sum": "сумма значений", "max": "наибольший параметр", "pairs": "число пар параметров",
                  "top3": "три наибольших", "min_pair": "два наименьших"},
       trap_first="full", rel=0.0, abs_min=1)

# ---------------------------------------------------------------- selenium/playwright: явные ожидания с опросом
define("qa.ui.ui_explicit_wait_mcq",
       contexts=["оформление заказа", "вход в личный кабинет", "загрузка отчёта", "поиск по каталогу",
                 "подтверждение платежа", "создание заявки", "фильтр в таблице", "загрузка аватара"],
       model=_F + '''
def total(P, mode="poll", extra=0):
    s = 0
    for x in P["x"]:
        if mode == "poll":
            s += -(-x // P["p"]) * P["p"] + extra
        elif mode == "raw":
            s += x
        elif mode == "floor":
            s += (x // P["p"]) * P["p"]
        elif mode == "timeout":
            s += P["E"] * 1000
        elif mode == "sleep":
            s += P["S"] * 1000
    return F(s, 1000)

def answer(P):
    return total(P)

def brute(P):
    s = 0
    for x in P["x"]:
        t = 0
        while t < x:                 # условие проверяется в моменты 0, p, 2p, ...
            t += P["p"]
        s += t
    return F(s, 1000)

def traps(P):
    return {"raw": total(P, "raw"), "floor": total(P, "floor"), "timeout": total(P, "timeout"), "sleep": total(P, "sleep"),
            "plus_poll": total(P, extra=P["p"]), "max_only": F(max(P["x"]), 1000)}

def fmt(x):
    return (f"{float(x):.2f}".rstrip("0").rstrip(".") + " с").replace(".", ",")
''',
       sample=lambda r: {"x": [r.choice([300, 700, 1200, 1800, 2600, 3300, 4100]) + r.randint(0, 99) for _ in range(r.choice([4, 5, 6]))],
                         "p": r.choice([250, 500]), "E": r.choice([10, 15]), "S": r.choice([5, 6])},
       accept=lambda P, ns: True,
       stem=lambda P, c: (f"UI-тест «{c}»: {len(P['x'])} шагов, на каждом ждём появления элемента. Элемент появляется "
                          f"через (мс): {', '.join(map(str, P['x']))}. Используется явное ожидание (WebDriverWait / "
                          f"expect-polling) с таймаутом {P['E']} с и опросом каждые {P['p']} мс: первая проверка сразу, "
                          f"дальше через каждые {P['p']} мс; implicit wait выключен. Раньше стоял time.sleep({P['S']}) на "
                          "каждом шаге.\n\nСколько суммарно тест проведёт в ожиданиях?"),
       explain=lambda P, a, t: (f"Ожидание завершается на первой проверке после появления: ⌈x/{P['p']}⌉·{P['p']} мс на шаг; "
                                f"таймаут не достигается. Сумма — {fmt_s(a)}."),
       trap_desc={"raw": "ровно время появления", "floor": "проверка до появления", "timeout": "весь таймаут",
                  "sleep": "фиксированный sleep", "plus_poll": "лишний интервал опроса", "max_only": "только самый долгий шаг"},
       trap_first="raw", rel=0.03, abs_min=0.1)


def fmt_s(x):
    return (f"{float(x):.2f}".rstrip("0").rstrip(".") + " с").replace(".", ",")

# ---------------------------------------------------------------- analyst: догон лага после пика (асинхронная интеграция)
define("analyst.integration.kafka_lag_catchup_mcq",
       contexts=["выгрузка заказов в ERP", "статусы доставки партнёрам", "начисление кешбэка", "синхронизация остатков",
                 "события CRM", "передача платежей в учёт", "уведомления клиентам", "интеграция с антифродом"],
       model=_CD + '''
def mins(P, base=True, lag_full=False, in_peak=True):
    lag = (P["p"] if lag_full else P["p"] - (P["c"] if in_peak else 0)) * P["W"] * 60
    rate = P["c"] - (P["p0"] if base else 0)
    return cd(lag, rate * 60)

def answer(P):
    return mins(P)

def brute(P):
    lag = 0
    for _ in range(P["W"] * 60):
        lag += P["p"] - P["c"]
    t = 0
    while lag > 0:
        lag -= P["c"] - P["p0"]
        t += 1
    return -(-t // 60)

def traps(P):
    return {"no_base": mins(P, base=False), "lag_full": mins(P, lag_full=True), "x2": 2 * mins(P),
            "half": cd(mins(P), 2), "peak_len": P["W"], "lag_full_no_base": mins(P, base=False, lag_full=True)}

def fmt(x):
    return f"{x} мин"
''',
       sample=lambda r: {"p": r.choice([1500, 2000, 3000, 4000]), "c": r.choice([1000, 1200, 1500]),
                         "p0": r.choice([300, 500, 700]), "W": r.choice([20, 30, 45, 60])},
       accept=lambda P, ns: P["p"] > P["c"] > P["p0"] and len({ns["answer"](P), P["W"]}) == 2,
       stem=lambda P, c: (f"Интеграция «{c}» через Kafka: в пиковые {P['W']} мин продюсер пишет {num(P['p'])} сообщений "
                          f"в секунду, потребитель стабильно обрабатывает {num(P['c'])} в секунду. После пика поток падает "
                          f"до {num(P['p0'])} в секунду.\n\nЧерез сколько минут после конца пика лаг уйдёт в ноль? Это "
                          "значение нужно указать в требованиях как допустимую задержку."),
       explain=lambda P, a, t: (f"За пик накопится ({num(P['p'])} − {num(P['c'])})·{P['W']}·60 сообщений; после пика "
                                f"разбор идёт со скоростью {num(P['c'])} − {num(P['p0'])} в секунду. Итого {a} мин."),
       trap_desc={"no_base": "без потока после пика", "lag_full": "весь поток пика в лаг", "x2": "двойной запас",
                  "half": "половина", "peak_len": "длительность пика", "lag_full_no_base": "весь поток и без потока после пика"},
       trap_first="no_base", rel=0.1, abs_min=1)

# ---------------------------------------------------------------- devops: диск брокера Kafka под retention
define("devops.kafka.kafka_broker_disk_mcq",
       contexts=["кластер событий", "кластер логов", "кластер CDC", "кластер метрик", "кластер платежей",
                 "кластер кликов", "кластер аудита", "кластер телеметрии"],
       model=_CD + '''
def gb(P, rf=None, fill=True, brokers=True):
    rf = P["rf"] if rf is None else rf
    raw = P["m"] * P["s"] * P["h"] * 3600 * rf
    den = (P["n"] if brokers else 1) * 10**9
    if fill:
        raw *= 100
        den *= P["fill"]
    return cd(raw, den)

def answer(P):
    return gb(P)

def brute(P):
    per_broker_bytes = P["m"] * P["s"] * P["h"] * 3600 * P["rf"] / P["n"]
    g = 0
    while g * 10**9 * P["fill"] / 100 < per_broker_bytes - 1e-3:
        g += 1
    return g

def traps(P):
    return {"no_rf": gb(P, rf=1), "no_fill": gb(P, fill=False), "half": cd(gb(P), 2), "no_brokers": gb(P, brokers=False),
            "x2": 2 * gb(P), "rf_plus1": gb(P, rf=P["rf"] + 1)}

def fmt(x):
    return f"{x:,}".replace(",", " ") + " ГБ"
''',
       sample=lambda r: {"m": r.choice([5000, 10000, 20000, 50000]), "s": r.choice([500, 1000, 2000]),
                         "h": r.choice([24, 72, 168]), "rf": 3, "n": r.choice([3, 6, 9]), "fill": r.choice([70, 80])},
       accept=lambda P, ns: ns["brute"](P) == ns["answer"](P),
       stem=lambda P, c: (f"Kafka, {c}: {num(P['m'])} сообщений в секунду по {P['s']} байт (после сжатия), retention "
                          f"{P['h']} ч, replication factor {P['rf']}, {P['n']} брокеров, партиции распределены равномерно. "
                          f"Диск не должен заполняться больше чем на {P['fill']} %. 1 ГБ = 10⁹ байт.\n\n"
                          "Какой объём диска нужен на каждом брокере?"),
       explain=lambda P, a, t: (f"{num(P['m'])}·{P['s']} байт·{P['h']}·3600 с ×{P['rf']} реплики / {P['n']} брокеров / "
                                f"{P['fill']} % ≈ {a:,} ГБ.".replace(",", " ")),
       trap_desc={"no_rf": "без реплик", "no_fill": "без запаса заполнения", "half": "половина",
                  "no_brokers": "на весь кластер", "x2": "двойной запас", "rf_plus1": "лидер плюс RF реплик"},
       trap_first="no_rf", rel=0.1, abs_min=1)

# ---------------------------------------------------------------- frontend: курсорная пагинация REST API
define("frontend.api.rest_cursor_pagination_mcq",
       contexts=["история заказов", "лента уведомлений", "журнал операций", "список транзакций", "каталог товаров",
                 "лог аудита", "список задач", "сообщения чата"],
       model=_CD + _F + '''
def secs(P, parallel=False, server=True, rtt=1):
    pages = cd(P["N"], P["s"])
    seq = cd(pages, P["k"]) if parallel else pages
    return F(seq * (P["rtt"] * rtt + (P["t"] if server else 0)), 1000)

def answer(P):
    return secs(P)

def brute(P):
    ms, cursor, loaded = 0, 0, 0
    while True:
        ms += P["rtt"] + P["t"]
        got = min(P["s"], P["N"] - loaded)
        loaded += got
        if loaded >= P["N"]:
            break
    return F(ms, 1000)

def traps(P):
    return {"parallel": secs(P, parallel=True), "no_server": secs(P, server=False), "rtt2": secs(P, rtt=2),
            "x2": 2 * secs(P), "rtt_only_parallel": secs(P, parallel=True, server=False), "half": secs(P) / 2}

def fmt(x):
    return (f"{float(x):.1f}".rstrip("0").rstrip(".") + " с").replace(".", ",")
''',
       sample=lambda r: {"N": r.choice([1200, 2500, 4000, 7000]) + r.randint(1, 99), "s": r.choice([50, 100, 200]),
                         "k": r.choice([4, 6]), "rtt": r.choice([60, 120, 200]), "t": r.choice([40, 80, 150])},
       accept=lambda P, ns: ns["answer"](P) >= 2,
       stem=lambda P, c: (f"Фронтенд выгружает «{c}» целиком для экспорта: {num(P['N'])} записей, API с курсорной "
                          f"пагинацией (GET ?limit={P['s']}&cursor=…, следующий cursor приходит в ответе). Браузер "
                          f"держит до {P['k']} параллельных запросов к домену, RTT — {P['rtt']} мс, сервер отвечает за "
                          f"{P['t']} мс, CORS-preflight не нужен.\n\nСколько займёт загрузка всех страниц?"),
       explain=lambda P, a, t: (f"Курсор следующей страницы известен только из ответа предыдущей — запросы строго "
                                f"последовательны, параллелизм браузера не помогает: ⌈N/{P['s']}⌉ × ({P['rtt']} + "
                                f"{P['t']}) мс."),
       trap_desc={"parallel": "параллельные запросы", "no_server": "без времени сервера", "rtt2": "два RTT на запрос",
                  "x2": "двойной запас", "rtt_only_parallel": "параллельно и только RTT", "half": "половина"},
       trap_first="parallel", rel=0.1, abs_min=0.1)

# ---------------------------------------------------------------- react native: окно FlatList
define("mobile.rn.rn_flatlist_window_mcq",
       contexts=["лента новостей", "каталог товаров", "список чатов", "история операций", "список контактов",
                 "лента фотографий", "список заказов", "лента отзывов"],
       model='''
def mounted(P, w=None):
    w = P["w"] if w is None else w
    return min(P["N"], P["v"] * w)

def answer(P):
    return mounted(P)

def brute(P):
    # окно — w высот экрана, центрированное на видимой области: (w − 1)/2 экрана сверху и снизу
    side = (P["w"] - 1) * P["v"] // 2
    return min(P["N"], side + P["v"] + side)

def traps(P):
    return {"visible": P["v"], "half": P["v"] * P["w"] // 2, "all": P["N"], "initial": P["init"],
            "w_items": P["w"], "double": P["v"] * P["w"] * 2, "plus_one": P["v"] * (P["w"] + 1)}

def fmt(x):
    return f"≈ {x} элементов"
''',
       sample=lambda r: {"v": r.choice([6, 8, 10, 12]), "w": r.choice([5, 7, 11, 21]), "N": r.choice([1000, 5000]),
                         "init": 10},
       accept=lambda P, ns: P["v"] * P["w"] * 2 < P["N"] and P["v"] != 10,
       stem=lambda P, c: (f"React Native, «{c}» на FlatList: {num(P['N'])} элементов одинаковой высоты, на экране "
                          f"помещается {P['v']}. windowSize={P['w']}, initialNumToRender=10, "
                          "removeClippedSubviews выключен. Пользователь прокрутил в середину списка и остановился.\n\n"
                          "Сколько элементов будет смонтировано?"),
       explain=lambda P, a, t: (f"windowSize измеряется в высотах экрана: окно — {P['w']} экранов (видимый плюс "
                                f"({P['w']} − 1)/2 сверху и снизу), то есть {P['v']}·{P['w']} = {a} элементов."),
       trap_desc={"visible": "только видимые", "half": "половина окна", "all": "весь список", "initial": "initialNumToRender",
                  "w_items": "windowSize в элементах", "double": "двойное окно", "plus_one": "окно плюс экран"},
       trap_first="visible", rel=0.0, abs_min=1)

# ---------------------------------------------------------------- data quality: порог аномалии mean + kσ
define("data_eng.dq.dq_sigma_threshold_mcq",
       contexts=["строки в витрине заказов", "события в сыром слое", "платежи за сутки", "новые пользователи",
                 "строки в CDC-потоке", "записи в логе", "показы рекламы", "транзакции партнёра"],
       model=_F + '''
import math

def thr(P, sample=False, k=None, sd=True, mean=True, var=False):
    x = P["x"]
    n = len(x)
    m = F(sum(x), n)
    v = sum((F(t) - m) ** 2 for t in x) / (n - 1 if sample else n)
    k = P["k"] if k is None else k
    spread = v if var else F(math.isqrt(int(v * 10**6))) / 1000      # σ с точностью до 0,001
    return round((m if mean else 0) + (k * spread if sd else 0))

def answer(P):
    return thr(P)

def brute(P):
    import statistics
    return round(statistics.fmean(P["x"]) + P["k"] * statistics.pstdev(P["x"]))

def traps(P):
    return {"sample_sd": thr(P, sample=True), "mean_only": thr(P, sd=False), "k_minus": thr(P, k=P["k"] - 1),
            "two_k": thr(P, k=2 * P["k"]), "sd_only": thr(P, mean=False), "var": thr(P, var=True)}

def fmt(x):
    return f"{x:,}".replace(",", " ")
''',
       sample=lambda r: (lambda base: {"x": [base + r.randint(-40, 40) * 10 for _ in range(r.choice([5, 6, 8]))],
                                       "k": r.choice([2, 3])})(r.choice([5000, 8000, 12000, 20000])),
       accept=lambda P, ns: abs(ns["answer"](P) - ns["brute"](P)) == 0 and len(set(P["x"])) == len(P["x"]),
       stem=lambda P, c: (f"Проверка качества данных: «{c}» за последние дни — {', '.join(num(t) for t in P['x'])}. "
                          f"Правило: алерт, если завтрашнее значение выше среднего плюс {P['k']} стандартных отклонения "
                          "(отклонение по генеральной совокупности, как numpy.std по умолчанию).\n\nКакой верхний порог "
                          "(округлённый до целого) получится?"),
       explain=lambda P, a, t: (f"Среднее {num(sum(P['x']) / len(P['x']), 1)}, σ (делим на n) — "
                                f"{num((sum((t - sum(P['x']) / len(P['x'])) ** 2 for t in P['x']) / len(P['x'])) ** 0.5, 1)}; "
                                f"порог = среднее + {P['k']}σ ≈ {a:,}.".replace(",", " ")),
       trap_desc={"sample_sd": "выборочное отклонение (n − 1)", "mean_only": "только среднее", "k_minus": "на σ меньше",
                  "two_k": "удвоенное k", "sd_only": "без среднего", "var": "дисперсия вместо отклонения"},
       trap_first="sample_sd", rel=0.0, abs_min=1)
