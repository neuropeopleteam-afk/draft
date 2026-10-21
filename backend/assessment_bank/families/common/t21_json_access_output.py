"""common.json.t21_json_access_output — predict_output (набор t21, порог Стажёр): json.loads небольшого документа
и доступ к вложенным ключам и спискам.

Ответ API (заказ, профиль, тикет, доставка) разбирается json.loads; программа печатает вложенное поле и длину
списка, элемент списка по индексу (в том числе отрицательному) и ``d.get(ключ, "—")`` — по варианту ключа нет
(вернётся «—») или ключ есть со значением null (вернётся None: значение по умолчанию подставляется только при
отсутствии ключа), — а затем имена типов ``type(...).__name__`` (int, str, float, bool, list, dict, NoneType для
null). Ловушки: null → None → NoneType, get при null, отрицательный индекс, JSON-объект → dict, массив → list.
Ключ — независимая модель по словарю, из которого собран документ (без исполнения показанного кода); проверка —
исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

import json

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "common.json.t21_json_access_output"

NAMES = ["Ирина", "Олег", "Мария", "Пётр", "Анна", "Сергей", "Дина", "Глеб"]
CITIES = ["Тула", "Казань", "Омск", "Пермь", "Самара", "Тверь", "Псков"]


def _order(rng):
    items = [{"sku": f"{rng.choice('ABCKMPT')}{rng.randint(10, 99)}", "qty": rng.randint(1, 5)}
             for _ in range(rng.randint(2, 4))]
    doc = {"id": rng.randint(1000, 9999), "status": rng.choice(["paid", "new", "shipped"]),
           "customer": {"name": rng.choice(NAMES), "city": rng.choice(CITIES)},
           "items": items, "coupon": None, "total": rng.choice([1290.5, 799.9, 2450.0, 315.75])}
    return ("заказ интернет-магазина", "API магазина", doc, "customer", ["name", "city"], "items", "sku",
            "coupon", ["comment", "gift", "promo"])


def _profile(rng):
    devices = [{"os": rng.choice(["android", "ios", "web"]), "build": rng.randint(100, 999)}
               for _ in range(rng.randint(2, 4))]
    doc = {"user_id": rng.randint(100, 999), "login": rng.choice(["ira_k", "oleg77", "masha", "petr"]),
           "contacts": {"email": f"user{rng.randint(10, 99)}@example.com", "city": rng.choice(CITIES)},
           "devices": devices, "avatar": None, "verified": rng.choice([True, False])}
    return ("профиль пользователя", "API сервиса профилей", doc, "contacts", ["email", "city"], "devices", "os",
            "avatar", ["phone", "bio", "company"])


def _ticket(rng):
    comments = [{"by": rng.choice(NAMES), "likes": rng.randint(0, 9)} for _ in range(rng.randint(2, 4))]
    doc = {"number": rng.randint(100, 999), "title": rng.choice(["Ошибка оплаты", "Не приходит письмо",
                                                               "Долгая загрузка"]),
           "author": {"name": rng.choice(NAMES), "team": rng.choice(["support", "billing", "mobile"])},
           "comments": comments, "assignee": None, "urgent": rng.choice([True, False])}
    return ("тикет в трекере задач", "API трекера задач", doc, "author", ["name", "team"], "comments", "by",
            "assignee", ["due", "sprint", "parent"])


def _delivery(rng):
    points = [{"city": c, "day": rng.randint(1, 28)} for c in rng.sample(CITIES, rng.randint(2, 4))]
    doc = {"track": rng.randint(10000, 99999), "state": rng.choice(["in_transit", "delivered", "created"]),
           "receiver": {"name": rng.choice(NAMES), "phone": f"+7900{rng.randint(1000000, 9999999)}"},
           "route": points, "courier": None, "weight": rng.choice([1.5, 0.25, 3.75, 12.5])}
    return ("отслеживание доставки", "API сервиса доставки", doc, "receiver", ["name", "phone"], "route", "city",
            "courier", ["note", "insurance", "door_code"])


BUILDERS = [_order, _profile, _ticket, _delivery]


def _type_name(v) -> str:
    if v is None:
        return "NoneType"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    return "dict"


def _show(v) -> str:
    """Как print покажет значение (только для None и строк/чисел из документа)."""
    if v is None:
        return "None"
    return str(v)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, api, doc, nested, nfields, lkey, lfield, nkey, missing = rng.choice(BUILDERS)(rng)
    var = rng.choice(["doc", "data", "resp", "body"])
    nf = rng.choice(nfields)
    idx = rng.choice([0, 1, -1])
    lst = doc[lkey]
    get_kind = rng.choice(["missing", "missing", "null"])
    get_key = rng.choice(missing) if get_kind == "missing" else nkey
    get_val = "—" if get_kind == "missing" else None
    keys = list(doc)
    t1, t2 = rng.sample([k for k in keys if k != nkey], 2)
    if rng.random() < 0.6:
        t2 = nkey                          # null → NoneType чаще всего
    if rng.random() < 0.5:
        t1, t2 = t2, t1
    text = json.dumps(doc, ensure_ascii=False)
    code = ("import json\n"
            f"{var} = json.loads('{text}')\n"
            f'print({var}["{nested}"]["{nf}"], len({var}["{lkey}"]))\n'
            f'print({var}["{lkey}"][{idx}]["{lfield}"], {var}.get("{get_key}", "—"))\n'
            f'print(type({var}["{t1}"]).__name__, type({var}["{t2}"]).__name__)')
    l1 = f"{_show(doc[nested][nf])} {len(lst)}"
    l2 = f"{_show(lst[idx][lfield])} {_show(get_val)}"
    l3 = f"{_type_name(doc[t1])} {_type_name(doc[t2])}"
    out = "\n".join([l1, l2, l3])
    idx_txt = {0: "первый элемент", 1: "второй элемент", -1: "индекс -1 — последний элемент"}[idx]
    get_txt = (f"ключа «{get_key}» в документе нет — get возвращает значение по умолчанию «—»"
               if get_kind == "missing" else
               f"ключ «{get_key}» есть, его значение null, поэтому get возвращает None (значение по умолчанию "
               f"подставляется только при отсутствии ключа)")
    expl = (f"json.loads превращает объект JSON в dict, массив — в list, null — в None. Строка 1: "
            f"{var}[\"{nested}\"][\"{nf}\"] = {_show(doc[nested][nf])}, длина списка «{lkey}» — {len(lst)}. "
            f"Строка 2: {idx_txt} списка → {_show(lst[idx][lfield])}; {get_txt}. Строка 3: типы значений "
            f"«{t1}» и «{t2}» — {_type_name(doc[t1])} и {_type_name(doc[t2])}"
            + (" (null → None, тип NoneType)" if nkey in (t1, t2) else "") + ".")
    stem = f"Интеграция с {api}: программа разбирает JSON-ответ ({ctx}) и печатает несколько полей."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"doc": doc, "nested": [nested, nf], "list": [lkey, idx, lfield],
                                  "get": [get_key, get_kind], "types": [t1, t2]}, language="python")
