"""data_ml.py.missing_mean_bug — find_bug: среднее по группам с пропусками в CSV.

Функция читает CSV стандартным модулем ``csv`` и считает среднее значение показателя по
группам, пропуская пустые значения. Подтипы дефекта (в исправлении меняется одна строка):
* ``count_before_skip`` — счётчик увеличивается до проверки на пропуск: пропуски попадают
  в знаменатель, средние занижены;
* ``none_check`` — пропуск проверяется через ``is None``, а ``csv.DictReader`` отдаёт для
  пустой ячейки пустую строку: ``float('')`` падает с ValueError;
* ``na_marker`` — выгрузка помечает пропуски как «NA», а код пропускает только пустую
  строку: ``float('NA')`` падает.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_ml.py.missing_mean_bug"

# (группа, показатель, значения групп, диапазон, контекст)
CONTEXTS = [
    ("region", "revenue", ["msk", "spb", "kzn", "nsk"], (50, 400), "продажи по регионам"),
    ("device", "load_time", ["ios", "android", "web"], (1, 9), "скорость загрузки приложения"),
    ("course", "score", ["python", "sql", "ml", "stats"], (40, 100), "оценки слушателей курсов"),
    ("sensor", "temp", ["s1", "s2", "s3"], (15, 35), "показания датчиков"),
    ("channel", "cac", ["ads", "seo", "email", "partners"], (100, 900), "стоимость привлечения"),
    ("shop", "check", ["a12", "b07", "c33"], (200, 2500), "средний чек магазинов"),
]
SUBTYPES = ["count_before_skip", "none_check", "na_marker"]


HELPERS = [
    ["def top_group(means):", "    return max(means, key=means.get) if means else None"],
    ["def spread(means):", "    vals = list(means.values())", "    return max(vals) - min(vals) if vals else 0.0"],
    ["def as_rows(means):", "    return [(k, v) for k, v in sorted(means.items())]"],
]


def _code(sub: str, fn: str, g: str, v: str, fixed: bool, marker_na: bool,
          helper: list[str], before: bool, norm: bool):
    raw_line = f"        raw = row[\"{v}\"].strip()"
    if sub == "none_check":
        raw_line = f"        raw = row[\"{v}\"]"
    if fixed:
        check = "        if raw in (\"\", \"NA\"):" if marker_na else "        if not raw:"
    elif sub == "none_check":
        check = "        if raw is None:"
    elif sub == "na_marker":
        check = "        if raw == \"\":"
    else:
        check = "        if not raw:"
    if marker_na and sub != "na_marker":
        check = "        if raw in (\"\", \"NA\"):"
    pre = helper + ["", ""] if before else []
    lines = ["import csv", "import io", "", ""] + pre + [
             f"def {fn}(csv_text):",
             "    totals, counts = {}, {}",
             "    for row in csv.DictReader(io.StringIO(csv_text)):",
             (f"        key = row[\"{g}\"].strip().lower()" if norm else f"        key = row[\"{g}\"]"),
             "        totals.setdefault(key, 0.0)",
             "        counts.setdefault(key, 0)",
             raw_line]
    if sub == "count_before_skip" and not fixed:
        lines += ["        counts[key] += 1", check, "            continue",
                  "        totals[key] += float(raw)"]
        key_line = 12 + len(pre)
    else:
        lines += [check, "            continue", "        totals[key] += float(raw)",
                  "        counts[key] += 1"]
        key_line = 12 + len(pre)
    lines.append("    return {k: round(totals[k] / counts[k], 2) for k in sorted(totals) if counts[k]}")
    if not before:
        lines += ["", ""] + helper
    return "\n".join(lines), key_line


def _csv(rows, g, v):
    return "\n".join([f"{g},{v}"] + [f"{a},{b}" for a, b in rows]) + "\n"


def _ref(rows, missing_tokens):
    totals, counts = {}, {}
    for k, raw in rows:
        totals.setdefault(k, 0.0)
        counts.setdefault(k, 0)
        if raw.strip() in missing_tokens:
            continue
        totals[k] += float(raw)
        counts[k] += 1
    return {k: round(totals[k] / counts[k], 2) for k in sorted(totals) if counts[k]}


def _rows(rng, groups, lo, hi, marker):
    for _ in range(1000):
        gs = rng.sample(groups, 3)
        rows = []
        for k in gs:
            for _ in range(rng.randint(2, 3)):
                rows.append((k, str(rng.randint(lo, hi))))
        miss = rng.sample(range(len(rows)), 2)
        for i in miss:
            rows[i] = (rows[i][0], marker)
        rng.shuffle(rows)
        res = _ref(rows, {"", "NA"})
        if len(res) == 3:
            return rows, res
    raise RuntimeError("не удалось подобрать данные")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    g, v, groups, (lo, hi), ctx = rng.choice(CONTEXTS)
    sub = rng.choice(SUBTYPES)
    fn = rng.choice([f"mean_{v}_by_{g}", f"avg_by_{g}", f"{g}_averages"])
    marker_na = sub == "na_marker" or (sub == "count_before_skip" and rng.random() < 0.4)
    marker = "NA" if marker_na else ""
    helper, before, norm = rng.choice(HELPERS), rng.random() < 0.5, rng.random() < 0.5
    buggy, key_line = _code(sub, fn, g, v, False, marker_na, helper, before, norm)
    fixed, _ = _code(sub, fn, g, v, True, marker_na, helper, before, norm)
    assert changed_lines(buggy, fixed) == {key_line}, (sub, changed_lines(buggy, fixed))
    rows, res = _rows(rng, groups, lo, hi, marker)
    t_rows, t_res = _rows(rng, groups, lo, hi, marker)
    test = (f"assert {fn}({_csv(rows, g, v)!r}) == {res!r}\n"
            f"assert {fn}({_csv(t_rows, g, v)!r}) == {t_res!r}")
    checks = [Check(name="buggy_fails", runner="python", program=py_harness(buggy, test), expect="fail"),
              Check(name="fixed_passes", runner="python", program=py_harness(fixed, test),
                    expect="pass", embeds_display_code=False)]
    sample = _csv(rows[:5], g, v).rstrip("\n")
    marker_text = "строкой NA" if marker_na else "пустой ячейкой"
    symptom = ("средние по группам с пропусками получаются заниженными"
               if sub == "count_before_skip" else "функция падает с ValueError на выгрузке с пропусками")
    stem = (f"Функция `{fn}` ({ctx}) считает среднее `{v}` по каждому значению `{g}`; пропуски "
            f"(в выгрузке они обозначены {marker_text}) нужно игнорировать — и в сумме, и в "
            f"числе наблюдений. Начало выгрузки:\n{sample}\n"
            f"На реальных данных {symptom}. Укажите номер строки с ошибкой.")
    why = {"count_before_skip": "счётчик увеличивается до проверки на пропуск, поэтому пропуски "
                                "попадают в знаменатель; увеличивать его нужно после `continue`",
           "none_check": "csv.DictReader отдаёт для пустой ячейки пустую строку, а не None, — "
                         "проверка `is None` не срабатывает и float('') падает",
           "na_marker": "пропуск обозначен строкой NA, а проверка ловит только пустую строку — "
                        "float('NA') падает"}[sub]
    ak = AnswerKey(kind="line", value=key_line, explanation=f"Строка {key_line}: {why}.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="missing_values_handling",
                         params={"fixed_code": fixed, "subtype": sub, "marker_na": marker_na})
