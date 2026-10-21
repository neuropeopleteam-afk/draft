"""data_ml.features.lag_window_leak_bug — find_bug: «среднее за прошлые дни» включает значение текущего дня.

Порог Junior/Middle. Признак строки t должен считаться только по прошлому (t−w … t−1), а окно берётся после
добавления цели текущей строки в историю — признак содержит саму цель (утечка). Исправление в той же строке —
срез истории без последнего элемента. Ловушки — копия строки, `None` для первой строки, второй признак (день
недели). Один подтип. Проверка исполнением: признак строки t не меняется при изменении цели строки t и равен
среднему предыдущих w значений.
"""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from assessment_bank.families.common._plus_utils import line_bug_variant

FAMILY_ID = "data_ml.features.lag_window_leak_bug"

CONTEXTS = [("прогноз продаж", "sales", "дней"), ("прогноз звонков в поддержку", "calls", "дней"),
            ("прогноз посещаемости сайта", "visits", "дней"), ("прогноз заказов такси", "orders", "часов"),
            ("прогноз выработки электростанции", "kwh", "часов"), ("прогноз возвратов", "returns", "недель")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, target, unit = rng.choice(CONTEXTS)
    w = rng.randint(3, 7)
    fn = rng.choice(["add_features", "make_features", "build_lag_features"])
    feat = rng.choice(["mean_last", "rolling_mean", "avg_prev"])
    hist = rng.choice(["history", "seen", "past"])
    extra = rng.random() < 0.5
    with_doc = rng.random() < 0.5
    with_sort = rng.random() < 0.5
    buggy_line = f"        recent = {hist}[-window:]"
    fixed_line = f"        recent = {hist}[-window - 1:-1]"

    def assemble(line: str) -> str:
        lines = [f"def {fn}(rows, window={w}):"]
        if with_doc:
            lines.append(f'    """Признаки по прошлому; цель — {target}."""')
        if with_sort:
            lines.append('    rows = sorted(rows, key=lambda r: r["t"])')
        lines += ["    out = []", f"    {hist} = []", "    for r in rows:", f'        {hist}.append(r["{target}"])',
                 line, "        f = dict(r)",
                 f'        f["{feat}"] = sum(recent) / len(recent) if recent else None']
        if extra:
            lines.append('        f["dow"] = r["t"] % 7')
        lines += ["        out.append(f)", "    return out"]
        return "\n".join(lines) + "\n"

    buggy, fixed = assemble(buggy_line), assemble(fixed_line)
    vals = [rng.randint(20, 200) for _ in range(w + 6)]
    i = w + rng.randint(1, 4)
    test = f"""
rows = [{{"t": k, "{target}": v}} for k, v in enumerate({vals!r})]
a = {fn}(rows)
rows2 = [dict(r) for r in rows]
rows2[{i}]["{target}"] += 1000
b = {fn}(rows2)
assert a[{i}]["{feat}"] == b[{i}]["{feat}"], "признак зависит от цели своей строки"
prev = {vals!r}[{i} - {w}:{i}]
assert abs(a[{i}]["{feat}"] - sum(prev) / len(prev)) < 1e-9
assert a[0]["{feat}"] is None
"""
    stem = (f"ML ({ctx}). Признак `{feat}` — среднее `{target}` за предыдущие {w} {unit}, и по нему модель "
            f"прогнозирует `{target}` той же строки. На валидации модель почти безошибочна, а на новых данных — "
            f"заметно хуже. Укажите номер строки, которую достаточно исправить одной правкой, чтобы ошибка ушла.")
    why = (f"Цель текущей строки добавляется в `{hist}` до расчёта окна, поэтому `{hist}[-window:]` включает само "
           f"значение `{target}` этой строки — признак содержит цель (утечка). Окно прошлого — `{hist}[-window - 1:-1]` "
           f"(или считать признак до добавления). Копия строки, `None` для первой строки и прочие признаки верны.")
    return line_bug_variant(FAMILY_ID, seed, stem=stem, buggy=buggy, fixed=fixed, test=test, context=ctx,
                            defect="target_in_lag_window", why=why,
                            display_note="После показанного кода признак сравнивается для двух наборов данных, "
                                         "отличающихся только целью одной строки.",
                            params={"window": w, "row": i})
