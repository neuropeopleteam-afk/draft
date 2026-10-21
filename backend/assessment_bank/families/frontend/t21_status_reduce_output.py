"""frontend.state.t21_status_reduce_output — predict_output (набор t21, порог Junior): подсчёт по статусам
через reduce в объект и обход Object.entries.

Список карточек (задачи, заказы, тикеты) сворачивается reduce в объект «статус → число»; затем Object.entries
печатает пары. В части вариантов перед подсчётом стоит filter (например, только назначенные на текущего
пользователя или дороже порога). Ловушки: начальное значение `{}` и `(acc[s] || 0) + 1`; порядок ключей —
порядок первого появления статуса (строковые ключи), а не алфавит и не частота; отфильтрованные элементы не
считаются. Ключ — независимый подсчёт в генераторе; проверка — исполнение показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.state.t21_status_reduce_output"

CTX = [("канбан-доска", "tasks", "status", ["todo", "doing", "review", "done"], "owner", ["ann", "bob", "kim"]),
       ("список заказов", "orders", "state", ["new", "paid", "shipped", "canceled"], "city", ["msk", "spb", "kzn"]),
       ("тикеты поддержки", "tickets", "status", ["open", "pending", "solved"], "team", ["web", "app", "pay"]),
       ("модерация отзывов", "reviews", "state", ["queued", "approved", "rejected"], "lang", ["ru", "en", "kk"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, arr, field, statuses, attr, attr_vals = rng.choice(CTX)
    for _ in range(200):
        n = rng.randint(5, 7)
        st = [rng.choice(statuses) for _ in range(n)]
        at = [rng.choice(attr_vals) for _ in range(n)]
        use_filter = rng.random() < 0.6
        who = rng.choice(attr_vals)
        kept = [s for s, a in zip(st, at) if (not use_filter or a == who)]
        if len(kept) < 3 or len(set(kept)) < 2:
            continue
        # порядок первого появления не должен совпадать с алфавитом — иначе ловушка не работает
        first = list(dict.fromkeys(kept))
        if first == sorted(first) and rng.random() < 0.8:
            continue
        if use_filter and len(kept) == n:
            continue
        break
    else:
        raise RuntimeError("t21_status_reduce: не собран список")
    counts: dict[str, int] = {}
    for s in kept:
        counts[s] = counts.get(s, 0) + 1
    items = ", ".join(f"{{ {field}: \"{s}\", {attr}: \"{a}\" }}" for s, a in zip(st, at))
    src = f"{arr}.filter((x) => x.{attr} === \"{who}\")" if use_filter else arr
    code = "\n".join([
        f"const {arr} = [{items}];",
        f"const counts = {src}.reduce((acc, x) => {{",
        f"  acc[x.{field}] = (acc[x.{field}] || 0) + 1;",
        "  return acc;",
        "}, {});",
        "for (const [key, n] of Object.entries(counts)) {",
        "  console.log(key, n);",
        "}",
    ])
    out = "\n".join(f"{k} {v}" for k, v in counts.items())
    flt = (f"filter оставляет {len(kept)} из {n} элементов с {attr} = «{who}»; " if use_filter else "")
    expl = (f"{flt}reduce начинает с пустого объекта и для каждого элемента увеличивает acc[статус] "
            f"(при первом появлении undefined || 0 → 0, затем +1). Строковые ключи объекта хранятся в порядке "
            f"первого добавления: {', '.join(counts)} — Object.entries выдаёт пары в этом же порядке. "
            f"Вывод: " + "; ".join(f"«{k} {v}»" for k, v in counts.items()) + ".")
    stem = (f"Интерфейс ({ctx}): программа считает карточки по статусам для счётчиков над колонками.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"statuses": st, "filter": use_filter}, language="javascript")
