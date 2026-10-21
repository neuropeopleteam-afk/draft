"""data_eng.dq.t21_rowcount_check_output — predict_output (набор t21, порог Стажёра): простая функция сверки числа
строк источника и приёмника с двумя if и return.

После загрузки программа сверяет число строк в источнике и в хранилище для нескольких таблиц: функция возвращает
«ok», «dup <лишних>» или «lost <потерянных>». Ловушки чтения: порядок аргументов (src, dst) и знак разности;
первая сработавшая ветка завершает функцию. Ключ — независимый расчёт в генераторе; проверка — исполнение показанного
кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_eng.dq.t21_rowcount_check_output"

CTX = ["ночная загрузка заказов", "перенос справочников в хранилище", "загрузка платежей за день",
       "репликация таблиц склада", "выгрузка событий приложения"]
FN = ["check", "reconcile", "compare_counts", "verify"]


def _ref(src: int, dst: int, order: str) -> str:
    if order == "eq_first":
        if dst == src:
            return "ok"
        if dst > src:
            return f"dup {dst - src}"
        return f"lost {src - dst}"
    if dst < src:
        return f"lost {src - dst}"
    if dst > src:
        return f"dup {dst - src}"
    return "ok"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    fn = rng.choice(FN)
    order = rng.choice(["eq_first", "lost_first"])
    for _ in range(200):
        k = rng.randint(3, 4)
        pairs = []
        for _ in range(k):
            src = rng.randrange(50, 3000, 5)
            kind = rng.choice(["ok", "dup", "lost"])
            d = rng.randint(1, 40)
            dst = src if kind == "ok" else (src + d if kind == "dup" else src - d)
            pairs.append((src, dst))
        kinds = {("ok" if s == d else "dup" if d > s else "lost") for s, d in pairs}
        if len(kinds) >= 2 and len(set(pairs)) == k:
            break
    else:
        raise RuntimeError("t21_rowcount_check: не собрались пары")
    if order == "eq_first":
        body = (f"def {fn}(src, dst):\n"
                "    if dst == src:\n"
                "        return \"ok\"\n"
                "    if dst > src:\n"
                "        return \"dup \" + str(dst - src)\n"
                "    return \"lost \" + str(src - dst)\n")
    else:
        body = (f"def {fn}(src, dst):\n"
                "    if dst < src:\n"
                "        return \"lost \" + str(src - dst)\n"
                "    if dst > src:\n"
                "        return \"dup \" + str(dst - src)\n"
                "    return \"ok\"\n")
    lst = ", ".join(f"({s}, {d})" for s, d in pairs)
    code = body + f"for src, dst in [{lst}]:\n    print({fn}(src, dst))"
    res = [_ref(s, d, order) for s, d in pairs]
    out = "\n".join(res)
    expl = ("Пары — (строк в источнике, строк в хранилище). "
            + "; ".join(f"({s}, {d}) → «{r}»" for (s, d), r in zip(pairs, res))
            + ". Больше строк в хранилище — дубли (dst − src), меньше — потери (src − dst); return сразу завершает "
              "функцию.")
    stem = f"Задача «{ctx}» завершилась; программа сверяет число строк в источнике и в хранилище по каждой таблице."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"pairs": [list(p) for p in pairs], "order": order}, language="python")
