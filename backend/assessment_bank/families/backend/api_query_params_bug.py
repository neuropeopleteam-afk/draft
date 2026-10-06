"""backend.api.query_params_bug — find_bug: разбор параметров строки запроса.

Значения из строки запроса приходят строками. Одна из строк разбора нарушает требования:
`bool("false")` истинно, `"".split(",")` даёт `[""]`, ограничение сверху/снизу записано
через `max`/`min` наоборот. Остальные строки разбора написаны правильно.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.api.query_params_bug"

CONTEXTS = [
    dict(res="products", ctx="каталог товаров", flag="in_stock", lst="categories",
         sorts=("price", "rating", "created_at"), vals=["books", "toys", "garden", "sport"]),
    dict(res="orders", ctx="кабинет продавца", flag="only_paid", lst="statuses",
         sorts=("created_at", "total", "updated_at"), vals=["new", "paid", "shipped", "returned"]),
    dict(res="vacancies", ctx="поиск вакансий", flag="remote", lst="skills",
         sorts=("salary", "published_at", "relevance"), vals=["python", "sql", "docker", "kafka"]),
    dict(res="articles", ctx="блог-платформа", flag="published", lst="tags",
         sorts=("views", "published_at", "title"), vals=["go", "ml", "devops", "security"]),
    dict(res="tickets", ctx="служба поддержки", flag="unassigned", lst="priorities",
         sorts=("created_at", "priority", "sla"), vals=["low", "high", "urgent", "normal"]),
    dict(res="events", ctx="афиша мероприятий", flag="free_only", lst="cities",
         sorts=("starts_at", "price", "popularity"), vals=["msk", "spb", "kzn", "nsk"]),
]
SUBTYPES = ["bool_cast", "empty_split", "limit_clamp", "offset_clamp"]
FN_NAMES = ["parse_query", "parse_filters", "parse_list_params", "read_query"]


def _lines(c: dict, bug: str | None) -> dict[str, str]:
    f, l = c["flag"], c["lst"]
    good = {
        "limit": 'limit = min(int(query.get("limit", "20")), 100)',
        "offset": 'offset = max(int(query.get("offset", "0")), 0)',
        "flag": f'{f} = query.get("{f}", "false").lower() == "true"',
        "list": f'{l} = [x for x in query.get("{l}", "").split(",") if x]',
    }
    bad = {
        "bool_cast": ("flag", f'{f} = bool(query.get("{f}", "false"))'),
        "empty_split": ("list", f'{l} = query.get("{l}", "").split(",")'),
        "limit_clamp": ("limit", 'limit = max(int(query.get("limit", "20")), 100)'),
        "offset_clamp": ("offset", 'offset = min(int(query.get("offset", "0")), 0)'),
    }
    if bug:
        k, line = bad[bug]
        good = {**good, k: line}
    return good


def _code(c: dict, fn: str, order: list[str], bug: str | None, ret_order: list[str]) -> str:
    ls = _lines(c, bug)
    names = {"limit": "limit", "offset": "offset", "flag": c["flag"], "list": c["lst"]}
    ret = ", ".join(f'"{names[k]}": {names[k]}' for k in ret_order)
    out = [f"ALLOWED_SORT = {c['sorts']!r}", "", "",
           f"def {fn}(query: dict) -> dict:",
           f'    """Параметры запроса GET /api/{c["res"]}; значения приходят строками."""']
    out += ["    " + ls[k] for k in order]
    out += [f'    sort = query.get("sort", "{c["sorts"][0]}")',
            "    if sort not in ALLOWED_SORT:",
            '        raise ValueError("unsupported sort")',
            f'    return {{{ret}, "sort": sort}}']
    return "\n".join(out)


def _ref(c: dict, q: dict) -> dict:
    """Независимая модель требований."""
    limit = int(q.get("limit", "20"))
    offset = int(q.get("offset", "0"))
    return {"limit": limit if limit < 100 else 100, "offset": offset if offset > 0 else 0,
            c["flag"]: q.get(c["flag"], "false").lower() == "true",
            c["lst"]: [x for x in q.get(c["lst"], "").split(",") if x],
            "sort": q.get("sort", c["sorts"][0])}


def _qs(q: dict) -> str:
    return "&".join(f"{k}={v}" for k, v in q.items())


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    c = rng.choice(CONTEXTS)
    fn = rng.choice(FN_NAMES)
    # Калибровка 05.10: подтип empty_split (''.split(",") → ['']) не решила ни одна модель (0,00 против
    # 0,32–0,55) — это знание частного поведения str.split, а не разбора параметров; исключён.
    bug = rng.choice([b for b in SUBTYPES if b != "empty_split"])
    order = rng.sample(["limit", "offset", "flag", "list"], 4)
    ret_order = rng.sample(["limit", "offset", "flag", "list"], 4)
    f, l = c["flag"], c["lst"]
    picks = rng.sample(c["vals"], 2)
    sort = rng.choice(c["sorts"][1:])
    # запрос из сообщения тестировщика: всегда несколько параметров, среди них — «спусковой»
    q: dict[str, str] = {}
    if bug == "bool_cast":
        q = {"limit": str(rng.choice([10, 25, 50])), f: "false", l: ",".join(picks), "sort": sort}
    elif bug == "empty_split":
        q = {"limit": str(rng.choice([10, 30, 60])), "offset": str(rng.choice([20, 40, 80])),
             f: rng.choice(["true", "false"]), "sort": sort}
    elif bug == "limit_clamp":
        q = {"limit": str(rng.choice([15, 30, 45, 70])), f: "true", l: picks[0], "sort": sort}
    else:
        q = {"limit": str(rng.choice([10, 20, 50])), "offset": str(rng.choice([20, 40, 100])),
             l: ",".join(picks), "sort": sort}
    keys = list(q)
    rng.shuffle(keys)
    q = {k: q[k] for k in keys}
    buggy = _code(c, fn, order, bug, ret_order)
    fixed = _code(c, fn, order, None, ret_order)
    key_line = 6 + order.index({"bool_cast": "flag", "empty_split": "list", "limit_clamp": "limit",
                                "offset_clamp": "offset"}[bug])
    assert changed_lines(buggy, fixed) == {key_line}
    extra = [{}, {"limit": "500", "offset": "-5", f: "TRUE", l: ",".join(c["vals"][:3])},
             {"limit": "7", "offset": "14", f: "false", "sort": c["sorts"][2]}]
    cases = [q] + extra
    test = "\n".join(f"assert {fn}({qq!r}) == {_ref(c, qq)!r}" for qq in cases)
    checks = [Check(name="buggy_fails", runner="python", program=py_harness(buggy, test), expect="fail"),
              Check(name="fixed_passes", runner="python", program=py_harness(fixed, test),
                    expect="pass", embeds_display_code=False)]
    stem = (f"Функция `{fn}` ({c['ctx']}) разбирает строку запроса `GET /api/{c['res']}`. "
            f"Требования: `limit` — по умолчанию 20 и не больше 100; `offset` — по умолчанию 0 и "
            f"не меньше 0; `{f}` — `true` или `false` (регистр не важен), по умолчанию `false`; "
            f"`{l}` — значения через запятую, без параметра — пустой список; `sort` — одно из "
            f"допустимых полей. Тестировщик сообщает: на запрос `?{_qs(q)}` функция возвращает "
            f"результат, который не соответствует требованиям. Укажите номер строки с ошибкой.")
    why = {"bool_cast": f"`bool()` от любой непустой строки, в том числе \"false\", даёт True; "
                        f"нужно сравнивать текст: `.lower() == \"true\"`",
           "empty_split": f"`\"\".split(\",\")` возвращает `['']`, а не пустой список; пустые "
                          f"элементы нужно отфильтровать",
           "limit_clamp": "`max(x, 100)` даёт не меньше 100; ограничение сверху — `min(x, 100)`",
           "offset_clamp": "`min(x, 0)` даёт не больше 0, любой положительный offset теряется; "
                           "ограничение снизу — `max(x, 0)`"}[bug]
    ak = AnswerKey(kind="line", value=key_line, explanation=f"Строка {key_line}: {why}.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=c["ctx"],
                         verification="execution", checks=checks, defect_type="query_param_parsing",
                         params={"fixed_code": fixed, "subtype": bug, "query": q})
