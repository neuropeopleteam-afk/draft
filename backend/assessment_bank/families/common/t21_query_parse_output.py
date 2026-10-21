"""common.http.t21_query_parse_output — predict_output (набор t21, порог Стажёр): строка запроса в словарь через
``dict(pair.split("=", 1) for pair in raw.split("&"))``.

Строка запроса (без «?») режется по «&», каждая пара — по ПЕРВОМУ «=» (maxsplit=1), и dict() собирает словарь из
пар. Повторный ключ — побеждает последнее значение (а число ключей меньше числа пар); пустое значение «ref=» даёт
пустую строку (длина 0); «=» внутри значения (паддинг base64 у токена или курсора, «a=b» в фильтре) сохраняется
благодаря maxsplit=1. Ловушки: первый или последний из повторов, len(dict) против числа пар, обрезка значения по
второму «=». Отличие от backend.http.t21_query_string_dict_output (цикл и split("=") без maxsplit, порядок ключей):
здесь dict() из пар, maxsplit=1 и пустые значения. Ключ — независимая модель в генераторе; проверка — исполнение
показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "common.http.t21_query_parse_output"

# (сюжет, ключ с «=» в значении, ключи для повтора и обычные, ключ с пустым значением)
CTX = [("эндпоинт GET /search каталога", "cursor", ["page", "sort", "q", "limit"], "ref"),
       ("обработчик OAuth-колбэка", "state", ["code", "lang", "scope", "prompt"], "error"),
       ("эндпоинт GET /orders личного кабинета", "token", ["status", "page", "from", "limit"], "promo"),
       ("сборщик веб-аналитики", "sid", ["utm_source", "utm_medium", "page", "screen"], "ref"),
       ("эндпоинт GET /vacancies поиска работы", "after", ["city", "level", "page", "salary"], "tag")]
VALS = {"page": ["1", "2", "3", "7", "10"], "sort": ["price", "date", "rating"], "q": ["lamp", "sofa", "desk"],
        "limit": ["20", "50", "100"], "code": ["a91f", "x7k2", "q0p3"], "lang": ["ru", "en", "kk"],
        "scope": ["read", "email", "profile"], "prompt": ["none", "login", "consent"],
        "status": ["paid", "new", "done"], "from": ["2026-10-01", "2026-09-15"],
        "utm_source": ["mail", "push", "ads"], "utm_medium": ["cpc", "email", "banner"],
        "screen": ["390x844", "1920x1080"], "city": ["msk", "spb", "kzn"],
        "level": ["junior", "middle", "senior"], "salary": ["90000", "150000"]}
B64 = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0123456789"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, eq_key, keys, empty_key = rng.choice(CTX)
    var = rng.choice(["raw", "query", "qs"])
    others = rng.sample(keys, rng.randint(2, 3))
    rep_key = others[0]
    v_first, v_last = rng.sample(VALS[rep_key], 2)
    eq_val = "".join(rng.choice(B64) for _ in range(rng.randint(4, 8))) + rng.choice(["=", "=="])
    if rng.random() < 0.3:
        eq_val = f"{rng.choice(B64)}{rng.choice(B64)}=" + eq_val
    pairs = [(rep_key, v_first)]
    for k in others[1:]:
        pairs.append((k, rng.choice(VALS[k])))
    pairs.append((eq_key, eq_val))
    pairs.append((empty_key, ""))
    rng.shuffle(pairs)
    # повтор — позже первого вхождения
    first_pos = next(i for i, (k, _) in enumerate(pairs) if k == rep_key)
    pairs.insert(rng.randint(first_pos + 1, len(pairs)), (rep_key, v_last))
    raw = "&".join(f"{k}={v}" for k, v in pairs)
    params: dict[str, str] = {}
    for k, v in pairs:                    # модель: первый «=» отделяет ключ, последнее значение побеждает
        params[k] = v
    style = rng.random() < 0.5
    l1_keys = [rep_key, eq_key] if style else [eq_key, rep_key]
    code = (f'{var} = "{raw}"\n'
            f'params = dict(pair.split("=", 1) for pair in {var}.split("&"))\n'
            f'print(params["{l1_keys[0]}"], params["{l1_keys[1]}"])\n'
            f'print(len(params), len(params["{empty_key}"]))')
    out = f"{params[l1_keys[0]]} {params[l1_keys[1]]}\n{len(params)} 0"
    expl = (f"split(\"&\") даёт {len(pairs)} пар; split(\"=\", 1) режет только по первому «=», поэтому значение "
            f"«{eq_key}» остаётся целиком: {eq_val}. Ключ «{rep_key}» встречается дважды — dict() записывает пары по "
            f"очереди, и побеждает последнее значение {v_last} (а не {v_first}); ключей в словаре {len(params)}, а не "
            f"{len(pairs)}. «{empty_key}=» даёт пустую строку — длина 0.")
    stem = (f"Веб-сервис ({ctx}): обработчик разбирает строку запроса вручную, без библиотек, и печатает "
            f"несколько параметров.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"pairs": [list(p) for p in pairs], "l1": l1_keys}, language="python")
