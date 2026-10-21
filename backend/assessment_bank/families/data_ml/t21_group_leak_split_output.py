"""data_ml.cv.t21_group_leak_split_output — predict_output (набор t21, порог Senior): разбиение журнала событий
«по строкам» против «по пользователям» и утечка пользователей между частями.

Журнал — user_id по строкам в порядке времени. Первый способ режет строки срезами rows[:n] / rows[n:] (n — целой
арифметикой от длины), и пользователи с несколькими строками попадают в обе части — печатаются размеры частей и
число общих пользователей (пересечение множеств). Второй способ сначала упорядочивает пользователей (по варианту:
``sorted(set(rows))`` — строки сравниваются ЛЕКСИКОГРАФИЧЕСКИ, «u10» < «u3»; ``list(dict.fromkeys(rows))`` —
порядок первого появления; ``sorted(..., key=lambda u: int(u[1:]))`` — по номеру), берёт первых cut пользователей
в обучение и раскладывает строки по принадлежности пользователя — печатаются размеры частей в строках и пересечение
(0). Ловушки: лексикографический порядок id, размер части по пользователям считается в строках, а не в
пользователях, пересечение при разбиении по строкам. Ключ — независимая модель в генераторе (сравнение id по
символам, явный порядок первого появления); проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.cv.t21_group_leak_split_output"

CTX = [("журнал кликов в ленте новостей", "u", "clicks"),
       ("покупки в интернет-магазине", "c", "orders"),
       ("прослушивания в музыкальном сервисе", "u", "plays"),
       ("поездки в сервисе такси", "p", "trips"),
       ("обращения в службу поддержки", "c", "tickets")]
RATIOS = [(7, 10), (3, 4), (4, 5), (2, 3)]
ORDERS = ["lex", "lex", "first", "num"]


def _lex_less(a: str, b: str) -> bool:
    """Сравнение строк посимвольно (как у str в Python): первый различный символ, иначе короче — меньше."""
    for x, y in zip(a, b):
        if x != y:
            return ord(x) < ord(y)
    return len(a) < len(b)


def _lex_sorted(xs):
    res: list[str] = []
    for x in xs:
        pos = len(res)
        for j, o in enumerate(res):
            if _lex_less(x, o):
                pos = j
                break
        res.insert(pos, x)
    return res


def _first_seen(rows):
    res: list[str] = []
    for r in rows:
        if r not in res:
            res.append(r)
    return res


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pfx, var = rng.choice(CTX)
    order = rng.choice(ORDERS)
    for _ in range(3000):
        n_users = rng.randint(4, 6)
        small = rng.sample(range(1, 10), rng.randint(1, 3))
        big = rng.sample(range(10, 40), n_users - len(small))
        nums = small + big
        users = [f"{pfx}{x}" for x in nums]
        rows = []
        for u in users:
            rows += [u] * rng.randint(1, 3)
        if not 9 <= len(rows) <= 13:
            continue
        rng.shuffle(rows)
        num, den = rng.choice(RATIOS)
        n = len(rows) * num // den
        train, test = rows[:n], rows[n:]
        leak_rows = [u for u in _first_seen(train) if u in test]
        if not 1 <= len(leak_rows):
            continue
        if order == "lex":
            uorder = _lex_sorted(_first_seen(rows))
        elif order == "first":
            uorder = _first_seen(rows)
        else:
            uorder = [f"{pfx}{x}" for x in sorted(int(u[len(pfx):]) for u in _first_seen(rows))]
        cut = len(uorder) * num // den
        if not 1 <= cut < len(uorder):
            continue
        fit = uorder[:cut]
        num_fit = [f"{pfx}{x}" for x in sorted(int(u[len(pfx):]) for u in _first_seen(rows))][:cut]
        if order == "lex" and set(fit) == set(num_fit):
            continue                      # лексикографический порядок должен менять состав обучения
        if order == "first" and set(fit) == set(num_fit):
            continue
        train_g = [u for u in rows if u in fit]
        test_g = [u for u in rows if u not in fit]
        if len(train_g) == n:
            continue                      # размеры частей двух способов различаются
        break
    else:
        raise RuntimeError("t21_group_leak_split: не собрался журнал")
    if order == "lex":
        users_expr = f"sorted(set({var}))"
    elif order == "first":
        users_expr = f"list(dict.fromkeys({var}))"
    else:
        users_expr = f"sorted(set({var}), key=lambda u: int(u[1:]))"
    lex_pair = ("", "")
    if order == "lex":
        num_of = {u: int(u[len(pfx):]) for u in uorder}
        lex_pair = next((a, b) for i, a in enumerate(uorder) for b in uorder[i + 1:] if num_of[a] > num_of[b])
    rows_lit = "[" + ", ".join(f'"{u}"' for u in rows) + "]"
    code = (f"{var} = {rows_lit}\n"
            f"n = len({var}) * {num} // {den}\n"
            f"train, test = {var}[:n], {var}[n:]\n"
            "print(len(train), len(test), len(set(train) & set(test)))\n"
            f"users = {users_expr}\n"
            f"cut = len(users) * {num} // {den}\n"
            "fit = set(users[:cut])\n"
            f"train_g = [u for u in {var} if u in fit]\n"
            f"test_g = [u for u in {var} if u not in fit]\n"
            "print(len(train_g), len(test_g), len(set(train_g) & set(test_g)))")
    out = f"{len(train)} {len(test)} {len(leak_rows)}\n{len(train_g)} {len(test_g)} 0"
    how = {"lex": "sorted(set(...)) сравнивает строки посимвольно, поэтому порядок",
           "first": "dict.fromkeys сохраняет порядок первого появления:",
           "num": "сортировка по числу после префикса:"}[order]
    expl = (f"Строк {len(rows)}: n = {len(rows)} * {num} // {den} = {n}, train — {n} строк, test — {len(rows) - n}; "
            f"в обеих частях встречаются {', '.join(leak_rows)} → пересечение {len(leak_rows)}. "
            f"Пользователей {len(uorder)}: {how} {' '.join(uorder)}; cut = {len(uorder)} * {num} // {den} = {cut}, "
            f"в обучение идут {', '.join(fit)} со всеми своими строками — {len(train_g)} строк, в проверку — "
            f"{len(test_g)}; общих пользователей нет → 0."
            + (f" Ловушка — сортировать id как числа: строки сравниваются посимвольно, и «{lex_pair[0]}» < "
               f"«{lex_pair[1]}»." if order == "lex" else
               " Ловушка — считать размер части в пользователях, а не в строках, или забыть, что при разбиении по "
               "строкам один пользователь попадает в обе части."))
    stem = (f"Подготовка выборки для модели ({ctx}): журнал хранит id пользователя каждой строки в порядке времени, "
            f"и программа сравнивает разбиение на обучение и проверку по строкам и по пользователям.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"rows": rows, "ratio": [num, den], "order": order}, language="python")
