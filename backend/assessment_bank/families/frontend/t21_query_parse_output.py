"""frontend.routing.t21_query_parse_output — predict_output (набор t21, порог Junior): разбор строки запроса
через split и деструктуризацию массива.

Роутер разбирает `location.search` вручную: отрезает «?», делит по «&», каждую пару — по «=» с деструктуризацией
`[key, value]` в объект. Затем печатает два параметра, число ключей и выражение с числовым параметром. Ловушки:
повторный параметр перезаписывается (побеждает последний); параметр без «=» получает undefined; значения
остаются строками, и `page + 1` склеивает, а `page * 1 + 1` / `Number(page) + 1` складывает. Ключ — независимая
модель разбора в генераторе; проверка — исполнение показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.routing.t21_query_parse_output"

CTX = [("каталог товаров", "page", ["sort", "brand", "color"], {"sort": ["price", "rating", "new"],
                                                                "brand": ["acme", "nova", "orbit"],
                                                                "color": ["red", "black", "white"]}),
       ("поиск вакансий", "page", ["city", "level", "remote"], {"city": ["msk", "spb", "ekb"],
                                                              "level": ["junior", "middle", "senior"],
                                                              "remote": ["yes", "no"]}),
       ("лента новостей", "offset", ["tag", "lang", "view"], {"tag": ["tech", "sport", "travel"],
                                                             "lang": ["ru", "en"], "view": ["list", "grid"]}),
       ("журнал заказов", "limit", ["status", "from", "group"], {"status": ["paid", "new", "sent"],
                                                                "from": ["2026-10-01", "2026-09-15"],
                                                                "group": ["day", "week"]})]
FLAGS = ["debug", "compact", "preview"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, num_key, keys, vals = rng.choice(CTX)
    k1, k2 = rng.sample(keys, 2)
    n1, n2 = rng.randint(1, 9), rng.randint(2, 30)
    v1a, v1b = rng.sample(vals[k1], 2)
    v2 = rng.choice(vals[k2])
    flag = rng.choice(FLAGS)
    dup = rng.choice(["num", "str"])  # какой параметр повторяется
    pairs = [(num_key, str(n1)), (k1, v1a), (k2, v2)]
    if dup == "num":
        pairs.append((num_key, str(n2)))
    else:
        pairs.append((k1, v1b))
    pairs.append((flag, None))
    rng.shuffle(pairs)
    # первый элемент повторяющегося ключа должен встретиться раньше второго — порядок записи сохраняем как есть
    query = "?" + "&".join(k if v is None else f"{k}={v}" for k, v in pairs)
    params: dict[str, str | None] = {}
    for k, v in pairs:
        params[k] = v
    arith = rng.choice(["concat", "mul", "number"])
    num_val = params[num_key]
    if arith == "concat":
        expr, res = f"params.{num_key} + 1", f"{num_val}1"
        why = f"значение «{num_val}» — строка, поэтому + 1 склеивает: «{res}»"
    elif arith == "mul":
        expr, res = f"params.{num_key} * 1 + 1", str(int(num_val) + 1)
        why = f"* 1 превращает строку «{num_val}» в число, затем + 1: {res}"
    else:
        expr, res = f"Number(params.{num_key}) + 1", str(int(num_val) + 1)
        why = f"Number(«{num_val}») = {num_val}, затем + 1: {res}"
    code = "\n".join([
        f"const query = \"{query}\";",
        "const params = {};",
        "for (const pair of query.slice(1).split(\"&\")) {",
        "  const [key, value] = pair.split(\"=\");",
        "  params[key] = value;",
        "}",
        f"console.log(params.{k1}, params.{flag});",
        "console.log(Object.keys(params).length, " + expr + ");",
    ])
    first = f"{params[k1]} undefined"
    out = first + "\n" + f"{len(params)} {res}"
    dk = num_key if dup == "num" else k1
    dvals = [v for k, v in pairs if k == dk]
    expl = (f"slice(1) убирает «?», split(\"&\") даёт {len(pairs)} пар, split(\"=\") с деструктуризацией — ключ и "
            f"значение. Параметр {dk} встречается дважды ({dvals[0]}, затем {dvals[1]}) — второе присваивание "
            f"перезаписывает первое, поэтому {dk} = {params[dk]}; у «{flag}» нет «=», value = undefined. Ключей "
            f"{len(params)}, а не {len(pairs)}. Значения — строки: {why}. Вывод: «{first}», затем "
            f"«{len(params)} {res}».")
    stem = f"Роутер ({ctx}): программа вручную разбирает строку запроса из адреса страницы в объект параметров."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"query": query, "arith": arith, "dup": dup}, language="javascript")
