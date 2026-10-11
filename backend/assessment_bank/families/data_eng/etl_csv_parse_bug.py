"""data_eng.etl.csv_parse_bug — find_bug: строки CSV разбираются split(","), а поля в кавычках содержат запятые.

Заголовок разбирается модулем csv, а строки данных — `line.split(",")`; поле в кавычках с запятой внутри
(«Иванов, Иван») сдвигает столбцы, а zip молча обрезает лишнее. Исправление — `next(csv.reader([line]))`
в той же строке. Проверка — исполнение показанного кода в песочнице Python на выгрузке с такими полями:
дефектный разбор даёт неверный итог, исправленный — верный.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_eng.etl.csv_parse_bug"

CTX = [("выгрузка клиентов из CRM", "client", "amount", ["Иванов, Иван", "ООО \"Ромашка\", склад", "Петров П."]),
       ("отчёт по заказам маркетплейса", "buyer", "total", ["Смирнова, А.", "ИП Козлов", "Сидоров, Пётр"]),
       ("реестр платежей", "payer", "sum", ["АО \"Вектор\", филиал 2", "Орлова Е.", "Белов, Б."]),
       ("список поставок", "supplier", "cost", ["ООО \"Берег\", Пермь", "Лес и К", "Зайцев, З."])]
FN = [("load_rows", "total_by"), ("parse_export", "sum_by"), ("read_report", "aggregate"),
      ("read_csv_rows", "group_sum")]
GROUP = [("region", ["Москва", "Казань", "Омск", "Тверь"]), ("city", ["Самара", "Пермь", "Томск", "Уфа"]),
         ("branch", ["север", "юг", "центр", "запад"])]


def _code(fn, agg, money, fixed, skip_empty, cast, strip_cr=False):
    parse = "        values = next(csv.reader([line]))" if fixed else '        values = line.split(",")'
    lines = ["import csv", "", "", f"def {fn}(text):", "    lines = text.strip().splitlines()",
             "    header = next(csv.reader([lines[0]]))", "    rows = []", "    for line in lines[1:]:"]
    if strip_cr:
        lines += ["        line = line.rstrip(\"\\r\")"]
    if skip_empty:
        lines += ["        if not line.strip():", "            continue"]
    lines += [parse, "        rows.append(dict(zip(header, values)))", "    return rows", "", "",
              f"def {agg}(rows, key):", "    out = {}", "    for r in rows:",
              f"        out[r[key]] = out.get(r[key], 0) + {cast}(r[\"{money}\"])", "    return out"]
    return "\n".join(lines)


def _csv_line(vals):
    out = []
    for v in vals:
        s = str(v)
        out.append('"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s)
    return ",".join(out)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, who, money, names = rng.choice(CTX)
    fn, agg = rng.choice(FN)
    skip_empty = rng.random() < 0.5
    cast = rng.choice(["int", "float"])
    strip_cr = rng.random() < 0.5
    code = _code(fn, agg, money, False, skip_empty, cast, strip_cr)
    fixed = _code(fn, agg, money, True, skip_empty, cast, strip_cr)
    ch = changed_lines(code, fixed)
    assert len(ch) == 1
    key = next(iter(ch))
    gcol, region = rng.choice(GROUP)
    n_rows = rng.randint(4, 6)
    start_id = rng.choice([1, 101, 501, 1001])
    data = [(start_id + i, rng.choice(names), rng.choice(region[:3]), rng.choice([100, 250, 400, 900, 1200, 75]))
            for i in range(n_rows)]
    if not any("," in d[1] for d in data):
        data[0] = (start_id, names[0], data[0][2], data[0][3])
    header = ["id", who, gcol, money]
    text = "\n".join([",".join(header)] + [_csv_line(d) for d in data])
    exp = {}
    for d in data:
        exp[d[2]] = exp.get(d[2], 0) + (int(d[3]) if cast == "int" else float(d[3]))
    test = (f"\n\n\nTEXT = {text!r}\ntry:\n    got = {agg}({fn}(TEXT), {gcol!r})\nexcept Exception:\n"
            f"    got = None\nprint(\"RESULT: PASS\" if got == {exp!r} else \"RESULT: FAIL\")\n")
    checks = [Check(name="buggy_fails", runner="python", program=code + test, expect="fail"),
              Check(name="fixed_passes", runner="python", program=fixed + test, expect="pass",
                    embeds_display_code=False)]
    comma_name = next(d[1] for d in data if "," in d[1])
    stem = (f"Скрипт разбирает файл «{ctx}» (CSV с заголовком; поля с запятыми — в кавычках, как пишет модуль csv) "
            f"и считает сумму `{money}` по `{gcol}`. На выгрузке ниже, где {who} — «{comma_name}», итог по `{gcol}` "
            f"неверный или скрипт падает.\nВыгрузка:\n{text}\nУкажите номер строки с ошибкой.")
    ak = AnswerKey(kind="line", value=key,
                   explanation=f"Строка {key}: split(\",\") режет поле в кавычках по запятой внутри, столбцы "
                               "сдвигаются (zip молча обрезает лишнее). Заголовок уже разбирается csv.reader — "
                               "строки данных нужно разбирать так же: next(csv.reader([line])).")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="naive_csv_split",
                         params={"fixed_code": fixed, "skip_empty": skip_empty, "cast": cast, "strip_cr": strip_cr})
