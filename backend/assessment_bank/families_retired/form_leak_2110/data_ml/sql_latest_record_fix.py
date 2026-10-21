"""data_ml.sql.latest_record_fix — choose_fix: «последняя запись в группе» через ROW_NUMBER.

Аналитик хочет текущее значение (тариф, статус, цену) по истории изменений, а запрос с
GROUP BY entity, value возвращает по строке на каждое значение. Из четырёх исправлений ровно
одно верно на любых данных (последняя по времени, при равном времени — с большим id).
Дистракторы: сортировка по возрастанию, RANK при ничьей, неверный разрешитель ничьей,
лишний столбец в PARTITION BY, соединение с MAX(дата) (дубли при ничьей).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, sql_inserts, text_table
from assessment_bank.schema import AnswerKey, Check

from ._dm_utils import balanced_options

FAMILY_ID = "data_ml.sql.latest_record_fix"

# (таблица, сущность, значение, время, значения, «что», контекст)
CONTEXTS = [
    ("plan_changes", "user_id", "plan", "changed_at", ["free", "basic", "pro", "team"],
     "текущий тариф каждого пользователя", "подписочный сервис"),
    ("order_status_log", "order_id", "status", "logged_at", ["created", "paid", "shipped", "returned"],
     "текущий статус каждого заказа", "интернет-магазин"),
    ("price_history", "sku_id", "price", "valid_from", [990, 1190, 1290, 1490],
     "действующую цену каждого товара", "ценообразование"),
    ("segment_history", "client_id", "segment", "assigned_at", ["new", "active", "vip", "sleeping"],
     "текущий сегмент каждого клиента", "CRM-аналитика"),
]
DISTRACTORS = ["asc", "rank", "id_asc", "partition_value", "max_join"]


def _q(kind, T, e, v, ts):
    if kind == "max_join":
        return (f"SELECT h.{e}, h.{v}, h.{ts}\nFROM {T} h\nJOIN (SELECT {e}, MAX({ts}) AS last_ts\n"
                f"      FROM {T} GROUP BY {e}) m\n  ON m.{e} = h.{e} AND m.last_ts = h.{ts}\n"
                f"ORDER BY h.{e};")
    fn = "RANK()" if kind == "rank" else "ROW_NUMBER()"
    part = f"{e}, {v}" if kind == "partition_value" else e
    order = {"asc": f"{ts} ASC, id DESC", "rank": f"{ts} DESC", "id_asc": f"{ts} DESC, id ASC"}.get(
        kind, f"{ts} DESC, id DESC")
    return (f"SELECT {e}, {v}, {ts}\nFROM (\n  SELECT {e}, {v}, {ts},\n"
            f"         {fn} OVER (PARTITION BY {part}\n"
            f"                    ORDER BY {order}) AS rn\n  FROM {T}\n) t\nWHERE rn = 1\n"
            f"ORDER BY {e};")


def _ref(kind, rows):
    """rows = [(id, entity, value, ts)] → строки результата 'entity|value|ts'."""
    out = []
    for ent in sorted({r[1] for r in rows}):
        items = [r for r in rows if r[1] == ent]
        if kind == "partition_value":
            for val in sorted({r[2] for r in items}, key=str):
                best = max((r for r in items if r[2] == val), key=lambda r: (r[3], r[0]))
                out.append(best)
            # порядок внутри одной сущности в SQL не определён: сравниваем как множество
            continue
        if kind in ("rank", "max_join"):
            last = max(r[3] for r in items)
            out.extend(sorted((r for r in items if r[3] == last), key=lambda r: r[0]))
            continue
        if kind == "asc":
            best = min(items, key=lambda r: (r[3], -r[0]))
        elif kind == "id_asc":
            best = max(items, key=lambda r: (r[3], -r[0]))
        else:
            best = max(items, key=lambda r: (r[3], r[0]))
        out.append(best)
    return [f"{r[1]}|{r[2]}|{r[3]}" for r in out]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, e, v, ts, values, what, ctx = rng.choice(CONTEXTS)
    # Калибровка 05.10: разброс объяснялся составом дистракторов (с id_asc 0,40, без него 0,62);
    # состав зафиксирован: «последняя по id, а не по времени» есть всегда.
    chosen = ["id_asc"] + rng.sample([d for d in DISTRACTORS if d != "id_asc"], 2)
    month = rng.randint(1, 12)
    for _ in range(5000):
        rows, rid = [], rng.randint(1, 40)
        ents = sorted(rng.sample(range(100, 400), 3))
        for ent in ents:
            for _ in range(rng.randint(2, 4)):
                rid += rng.randint(1, 4)
                day, hh = rng.randint(1, 28), rng.choice([9, 12, 18])
                rows.append((rid, ent, rng.choice(values), f"2026-{month:02d}-{day:02d} {hh:02d}:00:00"))
        # ничья по времени у последней записи одной из сущностей
        ent = rng.choice(ents)
        mine = [r for r in rows if r[1] == ent]
        last = max(r[3] for r in mine)
        rid += rng.randint(1, 4)
        other = rng.choice([x for x in values if x not in {r[2] for r in mine if r[3] == last}])
        rows.append((rid, ent, other, last))
        good = _ref("good", rows)
        if all(sorted(_ref(d, rows)) != sorted(good) and _ref(d, rows) != good for d in chosen):
            break
    else:
        raise RuntimeError("не удалось подобрать данные")
    rows.sort()
    buggy = (f"SELECT {e}, {v}, MAX({ts}) AS {ts}\nFROM {T}\nGROUP BY {e}, {v}\nORDER BY {e};")
    correct = _q("good", T, e, v, ts)
    # текст варианта — нейтральная подпись, сам запрос показывается один раз (в блоке кода)
    label = "Заменить запрос на:"
    opts, key = balanced_options(FAMILY_ID, seed, rng, (label, correct), [(label, _q(d, T, e, v, ts)) for d in chosen])
    num = isinstance(values[0], int)
    setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, {e} INTEGER NOT NULL, "
             f"{v} {'INTEGER' if num else 'TEXT'} NOT NULL, {ts} TEXT NOT NULL);\n"
             + sql_inserts(T, ["id", e, v, ts], rows) + "\n")
    good_out = "\n".join(_ref("good", rows))
    stem = (f"Для витрины данных ({ctx}) нужно получить {what} по истории `{T}`: значение из "
            f"последней по времени `{ts}` записи; если у последних записей одинаковое время, "
            f"верной считается запись с большим `id`. Результат — одна строка на `{e}`, по "
            f"возрастанию `{e}`. Показанный запрос аналитика возвращает по несколько строк на "
            f"`{e}`. Какой из вариантов решает задачу правильно на любых данных?\n\n"
            f"Пример данных `{T}`:\n{text_table(['id', e, v, ts], rows)}")
    checks = [Check(name="buggy_differs", runner="sqlite", program=buggy, files={"setup.sql": setup},
                    expect="stdout_differs", expected_stdout=good_out)]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="sqlite", program=o.code,
                            files={"setup.sql": setup}, embeds_display_code=False,
                            expect="stdout_equals" if o.id == key else "stdout_differs",
                            expected_stdout=good_out))
    why = {"asc": "сортировка по возрастанию времени берёт первую запись, а не последнюю",
           "rank": "RANK при равном времени даёт обеим записям место 1 — дубли",
           "id_asc": "при ничьей по времени выбирается запись с меньшим id",
           "partition_value": f"PARTITION BY {e}, {v} — по строке на каждое значение, как и в исходном запросе",
           "max_join": "соединение с MAX(время) возвращает все записи с этим временем — дубли при ничьей"}
    ak = AnswerKey(kind="option", value=key,
                   explanation="ROW_NUMBER по сущности с сортировкой по времени и id по убыванию "
                               "и фильтр rn = 1 во внешнем запросе. Ошибки дистракторов: "
                               + "; ".join(why[d] for d in chosen) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="latest_per_group",
                         params={"distractors": chosen})
