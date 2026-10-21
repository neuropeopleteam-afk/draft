"""security.principal.attack_path_shift_mcq — mcq_concept (Principal, короткое): вероятность успеха атакующего после
защитной меры, если он выбирает лучший для себя путь в дереве атак.

Цель атакующего достижима тремя путями (И-цепочки шагов, у шага — вероятность успеха; шаги независимы). Атакующий
выбирает один путь с наибольшей вероятностью успеха. Мера снижает успех одного шага на прежнем лучшем пути
(иногда шаг общий с другим путём). Ключ — max по путям после меры: атакующий переключается на следующий путь.

Ловушки: ниже ключа — ``prev_after`` (успех прежнего лучшего пути после меры — «мера закрыла атаку»),
``avg_after`` (среднее по путям после меры); выше ключа — ``before`` (до меры), ``union_after``
(1 − Π(1 − p_путь): атакующий пробует все пути), ``sum_after`` (сумма путей). Сколько ловушек меньше ключа —
0–2 равновероятно. Ключ проверяется исполнением: программа рекурсивно вычисляет дерево «ИЛИ — по максимуму, И — по
произведению» точными дробями.
"""
from __future__ import annotations

from fractions import Fraction as F
from math import prod

from assessment_bank.families._principal_c_utils import formatter, numeric_mcq, pick_traps
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.principal.attack_path_shift_mcq"

CONTEXTS = ["база клиентов банка", "платёжный шлюз", "медицинские карты клиники", "кабинет поставщика маркетплейса",
            "исходный код и ключи подписи сборок", "персональные данные службы доставки", "биллинг оператора связи",
            "архив договоров страховой компании"]
STEP_POOL = {
    "фишинг": ["фишинговое письмо сотруднику", "вход в VPN по украденному паролю", "переход к серверу базы"],
    "уязвимость": ["уязвимость в публичном API", "SSRF к метаданным облака", "чтение ключа доступа к хранилищу"],
    "подрядчик": ["компрометация ноутбука подрядчика", "общая учётная запись подрядчика", "выгрузка через отчёты"],
    "цепочка": ["подмена зависимости сборки", "выполнение в конвейере сборки", "доступ к секретам выкатки"],
}
CONTROLS = {
    "вход в VPN по украденному паролю": "MFA с аппаратными ключами для VPN",
    "SSRF к метаданным облака": "запрет доступа к метаданным из приложений (IMDSv2, сетевой фильтр)",
    "общая учётная запись подрядчика": "персональные учётные записи подрядчиков с MFA",
    "выполнение в конвейере сборки": "изолированные одноразовые исполнители сборки",
    "фишинговое письмо сотруднику": "фильтрация почты и обучение",
    "уязвимость в публичном API": "межсетевой экран приложений и срочное исправление",
}

PROGRAM = """from fractions import Fraction as F

{fmt}
TREE = ("OR", [("AND", [F(n, 100) for n in path]) for path in {paths!r}])

def value(node):
    kind, kids = node
    if kind == "AND":
        r = F(1)
        for k in kids:
            r *= value(k) if isinstance(k, tuple) else k
        return r
    return max(value(k) for k in kids)       # атакующий выбирает лучший путь

print(fmt(float(value(TREE))))
"""


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    n_below = rng.choice([0, 1, 2, 3])  # ранг ключа равномерный; недостающие — контрольные значения
    fmt, fmt_src = formatter("p1")
    names = rng.sample(sorted(STEP_POOL), 3)
    for _ in range(5000):
        paths = {n: [rng.choice([40, 50, 60, 70, 80, 90]) for _ in STEP_POOL[n]] for n in names}
        val = {n: prod(F(x, 100) for x in v) for n, v in paths.items()}
        best = max(val, key=val.get)
        ctrl_steps = [i for i, s in enumerate(STEP_POOL[best]) if s in CONTROLS]
        if len(set(val.values())) != 3 or not ctrl_steps:
            continue
        i = rng.choice(ctrl_steps)
        new = rng.choice([5, 10, 15, 20])
        after = {n: list(v) for n, v in paths.items()}
        after[best][i] = new
        va = {n: prod(F(x, 100) for x in v) for n, v in after.items()}
        good = float(max(va.values()))
        pool = {"prev_after": float(va[best]), "avg_after": float(sum(va.values()) / 3), "before": float(val[best]),
                "union_after": float(1 - prod(1 - x for x in va.values())), "sum_after": float(sum(va.values()))}
        if max(va, key=va.get) == best:
            continue
        traps = pick_traps(good, pool, n_below, rng, fmt, "p1", rel=0.1, lo=0.1, hi=1.0)
        if traps:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    step = STEP_POOL[best][i]
    lines = []
    for k, n in enumerate(names, 1):
        lines.append(f"Путь {k}: " + " → ".join(f"{s} ({p} %)" for s, p in zip(STEP_POOL[n], paths[n])))
    code = "\n".join(["Дерево атак (в скобках — вероятность успеха шага при попытке; шаги независимы):", *lines,
                      f"Мера: {CONTROLS[step]} — успех шага «{step}» снижается до {new} %."])
    stem = (f"Цель атакующего — {ctx}. Он оценивает пути заранее и выбирает один, с наибольшей вероятностью успеха. "
            f"Какова вероятность успеха атакующего после внедрения меры?")
    why = (f"До меры лучший путь — «{STEP_POOL[best][0]} → …» ({fmt(float(val[best]))}). Мера снижает его до "
           f"{fmt(float(va[best]))}, и атакующий переключается на следующий путь: max по путям после меры — "
           f"{fmt(good)}. Ошибки: «мера закрыла атаку» (прежний путь после меры) — {fmt(pool['prev_after'])}; "
           f"среднее по путям — {fmt(pool['avg_after'])}; без учёта меры — {fmt(pool['before'])}; «пробует все пути» — "
           f"{fmt(pool['union_after'])}. Вывод: эффект меры ограничен следующим по силе путём — снижение риска "
           f"оценивается по дереву целиком, а не по одному закрытому шагу.")
    program = PROGRAM.format(fmt=fmt_src, paths=[after[n] for n in names])
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=good, pool=pool, traps=traps, fmt=fmt,
                       program=program, why=why, code=code, params={"paths": names, "control_step": step, "new": new},
                       note="Программа рекурсивно вычисляет дерево атак: «ИЛИ» — максимум, «И» — произведение.")
