"""data_eng.dwh.lead_scd2_merge_fix — choose_fix (Lead): загрузка измерения с историей (SCD тип 2) из снимка источника.

Показан текущий скрипт загрузки измерения: он перезаписывает атрибуты на месте (тип 1) — история теряется.
Нужна замена (SQL, sqlite), которая ведёт историю: у изменившихся записей текущая версия закрывается датой
загрузки и добавляется новая; новые ключи добавляются; неизменные не трогаются; ключи, которых нет в снимке
(выгрузка частичная), остаются как есть; повторный запуск той же загрузки ничего не меняет; атрибуты
могут быть NULL.

Варианты (каждый исполняется) построены по схеме 2×2 от верного (UPDATE закрывает текущие версии с отличием
по null-безопасному сравнению IS NOT, затем INSERT для ключей снимка без текущей версии): из пула правил
выбираются два (a, b), варианты — верный, нарушено a, нарушено b, нарушены оба. Пул:
  * null_unsafe — сравнение через «<>»: переход NULL → значение и значение → NULL не замечается;
  * history_match — новая версия вставляется, только если такой комбинации атрибутов нет ни в одной версии
    ключа: при возврате к прежнему значению (A → B → A) B закрывается, а новая версия не появляется;
  * no_valid_to — при закрытии не ставится valid_to: у закрытой версии остаётся '9999-12-31';
  * skip_null — в INSERT отсекаются строки снимка с NULL во втором атрибуте: переход в NULL закрывает версию
    без новой, новый ключ с NULL не добавляется.
Каждый вариант отличается от двух других на одно правило и от третьего — на два; у каждого варианта свои
необязательные комментарии, поэтому ни длина, ни сходство вариантов не выдают ключ.
Данные каждого варианта содержат все случаи (неизменный, простое изменение,
NULL → значение, значение → NULL, возврат к прежнему значению, новый ключ, ключ вне снимка).
Ключ проверяется исполнением: скрипт запускается дважды на sqlite, итог сравнивается с эталоном, который
считает модель на Python (другим путём, чем SQL).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, dedent, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_eng.dwh.lead_scd2_merge_fix"

# контекст, измерение, снимок, ключ, атрибут 1 (значения), атрибут 2 (значения, может быть NULL)
CONTEXTS = [
    ("клиенты интернет-магазина", "dim_customer", "stg_customer", "customer_id",
     ("city", ["Москва", "Казань", "Пермь", "Томск", "Самара"]), ("segment", ["VIP", "B2B", "массовый"])),
    ("поставщики сети магазинов", "dim_supplier", "stg_supplier", "supplier_id",
     ("region", ["Центр", "Урал", "Сибирь", "Юг", "Северо-Запад"]), ("tier", ["A", "B", "C"])),
    ("сотрудники компании", "dim_employee", "stg_employee", "employee_id",
     ("department", ["продажи", "склад", "бухгалтерия", "ИТ", "логистика"]), ("grade", ["G1", "G2", "G3"])),
    ("товары каталога", "dim_product", "stg_product", "product_id",
     ("category", ["обувь", "одежда", "сумки", "часы", "очки"]), ("brand", ["Север", "Полюс", "Восход"])),
    ("торговые точки", "dim_store", "stg_store", "store_id",
     ("format", ["гипермаркет", "у дома", "дискаунтер", "павильон", "склад-магазин"]),
     ("manager", ["Иванова", "Петров", "Сидорова"])),
    ("договоры страхования", "dim_policy", "stg_policy", "policy_id",
     ("product", ["ОСАГО", "КАСКО", "ипотека", "жизнь", "путешествия"]), ("agent", ["агент-1", "агент-2", "агент-3"])),
]

BUGGY = '''
-- загрузка {dim} из снимка {stg} на дату '{d}'
UPDATE {dim}
SET {a1} = (SELECT s.{a1} FROM {stg} s WHERE s.{k} = {dim}.{k}),
    {a2} = (SELECT s.{a2} FROM {stg} s WHERE s.{k} = {dim}.{k})
WHERE EXISTS (SELECT 1 FROM {stg} s WHERE s.{k} = {dim}.{k});

INSERT INTO {dim} ({k}, {a1}, {a2}, valid_from, valid_to, is_current)
SELECT s.{k}, s.{a1}, s.{a2}, '{d}', '9999-12-31', 1
FROM {stg} s
WHERE NOT EXISTS (SELECT 1 FROM {dim} d WHERE d.{k} = s.{k});
'''

SCRIPTS = {
    "good": '''
UPDATE {dim}
SET valid_to = '{d}', is_current = 0
WHERE is_current = 1
  AND EXISTS (SELECT 1 FROM {stg} s
              WHERE s.{k} = {dim}.{k}
                AND (s.{a1} IS NOT {dim}.{a1} OR s.{a2} IS NOT {dim}.{a2}));

INSERT INTO {dim} ({k}, {a1}, {a2}, valid_from, valid_to, is_current)
SELECT s.{k}, s.{a1}, s.{a2}, '{d}', '9999-12-31', 1
FROM {stg} s
WHERE NOT EXISTS (SELECT 1 FROM {dim} d
                  WHERE d.{k} = s.{k} AND d.is_current = 1);
''',
}

# правило -> (фрагмент верного шаблона, замена); фрагменты разных правил не пересекаются
MUTATIONS = {
    "null_unsafe": ("(s.{a1} IS NOT {dim}.{a1} OR s.{a2} IS NOT {dim}.{a2})", "(s.{a1} <> {dim}.{a1} OR s.{a2} <> {dim}.{a2})"),
    "history_match": ("WHERE d.{k} = s.{k} AND d.is_current = 1);",
                      "WHERE d.{k} = s.{k}\n                    AND d.{a1} IS s.{a1} AND d.{a2} IS s.{a2});"),
    "no_valid_to": ("SET valid_to = '{d}', is_current = 0", "SET is_current = 0"),
    "skip_null": ("FROM {stg} s\nWHERE NOT EXISTS", "FROM {stg} s\nWHERE s.{a2} IS NOT NULL\n  AND NOT EXISTS"),
}
PAIRS = [(x, y) for i, x in enumerate(sorted(MUTATIONS)) for y in sorted(MUTATIONS)[i + 1:]]
WHY = {"null_unsafe": "сравнение «<>» не видит переходов NULL ↔ значение",
       "history_match": "поиск совпадения по всей истории ключа: при возврате к прежнему значению (A → B → A) B "
                        "закрывается, а новая версия не появляется — у ключа нет текущей версии",
       "no_valid_to": "у закрытой версии не ставится valid_to — она остаётся с '9999-12-31'",
       "skip_null": "строки снимка с NULL отсекаются в INSERT — переход в NULL закрывает версию без новой, новый ключ "
                    "с NULL не добавляется"}
NOTES = (("-- закрываем текущие версии изменившихся ключей", "-- шаг 1: закрыть изменившиеся версии"),
         ("-- добавляем новые текущие версии", "-- шаг 2: новые версии и новые ключи"))

HARNESS = '''import sqlite3

SETUP = {setup!r}
SCRIPT = r"""
{script}
"""
EXPECTED = {expected!r}
con = sqlite3.connect(":memory:")
con.executescript(SETUP)
con.executescript(SCRIPT)
con.executescript(SCRIPT)          # повторный запуск той же загрузки ничего не меняет
order = lambda r: tuple("" if v is None else str(v) for v in r)  # noqa: E731
got = sorted((tuple(r) for r in con.execute(
    "SELECT {k}, {a1}, {a2}, valid_from, valid_to, is_current FROM {dim}").fetchall()), key=order)
exp = sorted((tuple(r) for r in EXPECTED), key=order)
print("RESULT: PASS" if got == exp else "RESULT: FAIL")
'''


def _lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _reference(dim_rows, stg_rows, d):
    """Эталон SCD2 моделью на Python: словари по ключу, а не SQL."""
    out = [list(r) for r in dim_rows]
    cur = {r[0]: r for r in out if r[5] == 1}
    for k, a1, a2 in stg_rows:
        c = cur.get(k)
        if c is not None and (c[1], c[2]) == (a1, a2):
            continue
        if c is not None:
            c[4], c[5] = d, 0
        out.append([k, a1, a2, d, "9999-12-31", 1])
    return [tuple(r) for r in out]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, dim, stg, k, (a1, v1), (a2, v2) = rng.choice(CONTEXTS)
    year = rng.choice([2024, 2025, 2026])
    d0 = f"{year - 1}-0{rng.randint(1, 9)}-1{rng.randint(0, 9)}"
    d1 = f"{year}-0{rng.randint(1, 6)}-0{rng.randint(1, 9)}"
    d = f"{year}-{rng.choice(['07', '08', '09', '10', '11'])}-{rng.randint(10, 28)}"
    prefix = {"customer_id": "C", "supplier_id": "S", "employee_id": "E", "product_id": "P", "store_id": "T",
              "policy_id": "D"}[k]
    ids = [f"{prefix}{n}" for n in rng.sample(range(100, 999), 9)]
    pick = lambda vals, not_=(): rng.choice([x for x in vals if x not in not_])  # noqa: E731
    dim_rows, stg_rows = [], []
    # 0 — неизменный; 1 — простое изменение a1; 2 — a2: NULL → значение; 3 — a2: значение → NULL;
    # 4 — возврат к прежнему a1 (A → B → A); 5 — неизменный с NULL в a2; 6 — вне снимка; 7, 8 — новые
    cases = list(range(9))
    for case, key in zip(cases, ids):
        x1, x2 = pick(v1), pick(v2)
        if case == 0:
            dim_rows.append((key, x1, x2, d0, "9999-12-31", 1)); stg_rows.append((key, x1, x2))
        elif case == 1:
            dim_rows.append((key, x1, x2, d0, "9999-12-31", 1)); stg_rows.append((key, pick(v1, (x1,)), x2))
        elif case == 2:
            dim_rows.append((key, x1, None, d0, "9999-12-31", 1)); stg_rows.append((key, x1, x2))
        elif case == 3:
            dim_rows.append((key, x1, x2, d0, "9999-12-31", 1)); stg_rows.append((key, x1, None))
        elif case == 4:
            y1 = pick(v1, (x1,))
            dim_rows.append((key, x1, x2, d0, d1, 0)); dim_rows.append((key, y1, x2, d1, "9999-12-31", 1))
            stg_rows.append((key, x1, x2))
        elif case == 5:
            dim_rows.append((key, x1, None, d0, "9999-12-31", 1)); stg_rows.append((key, x1, None))
        elif case == 6:
            dim_rows.append((key, x1, x2, d0, "9999-12-31", 1))
        else:
            stg_rows.append((key, x1, rng.choice([x2, None])))
    rng.shuffle(dim_rows)
    rng.shuffle(stg_rows)
    expected = _reference(dim_rows, stg_rows, d)
    ddl = (f"CREATE TABLE {dim} (sk INTEGER PRIMARY KEY AUTOINCREMENT, {k} TEXT NOT NULL, {a1} TEXT, {a2} TEXT, "
           f"valid_from TEXT NOT NULL, valid_to TEXT NOT NULL, is_current INTEGER NOT NULL);\n"
           f"CREATE TABLE {stg} ({k} TEXT PRIMARY KEY, {a1} TEXT, {a2} TEXT);\n")
    ins = "".join(f"INSERT INTO {dim} ({k}, {a1}, {a2}, valid_from, valid_to, is_current) VALUES ("
                  + ", ".join(_lit(v) for v in r) + ");\n" for r in dim_rows)
    ins += "".join(f"INSERT INTO {stg} ({k}, {a1}, {a2}) VALUES (" + ", ".join(_lit(v) for v in r) + ");\n"
                   for r in stg_rows)
    setup = ddl + ins
    f = dict(dim=dim, stg=stg, k=k, a1=a1, a2=a2, d=d)
    code = dedent(BUGGY.format(**f)) + "\n"
    a, b = rng.choice(PAIRS)
    sets = {"good": [], a: [a], b: [b], f"{a}+{b}": [a, b]}
    style = rng.randrange(2)
    opt_code = {}
    for name, muts in sets.items():      # порядок обращений к rng не зависит от текста
        tpl = SCRIPTS["good"]
        for mname in muts:
            old, new = MUTATIONS[mname]
            if tpl.count(old) != 1:
                raise ValueError(f"фрагмент правила {mname} не найден ровно один раз")
            tpl = tpl.replace(old, new)
        src = dedent(tpl.format(**f))
        if rng.random() < 0.5:
            src = NOTES[0][style] + "\n" + src.lstrip("\n")
        if rng.random() < 0.5:
            src = src.replace("\nINSERT INTO", "\n" + NOTES[1][style] + "\nINSERT INTO", 1)
        opt_code[name] = src
    if len(set(opt_code.values())) != 4:
        raise ValueError("варианты 2×2 совпадают")
    chosen = [a, b, f"{a}+{b}"]
    opts, key = make_options(rng, ("Заменить скрипт загрузки на:", opt_code["good"]),
                             [("Заменить скрипт загрузки на:", opt_code[c]) for c in chosen])
    by_code = {c: n for n, c in opt_code.items()}

    def prog(script: str) -> str:
        return HARNESS.format(setup=setup, script=script, expected=expected, k=k, a1=a1, a2=a2, dim=dim)

    checks = [Check(name="buggy_fails", runner="python", program=prog(code), expect="fail",
                    embeds_display_code=False)]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="python", program=prog(opt_code[by_code[o.code]]),
                            embeds_display_code=False, expect="pass" if o.id == key else "fail"))
    sample = "\n".join(f"  {r[0]} | {r[1]} | {'NULL' if r[2] is None else r[2]} | {r[3]} | {r[4]} | {r[5]}"
                       for r in sorted(dim_rows, key=lambda r: tuple("" if v is None else str(v) for v in r))[:3])
    stem = (f"Хранилище данных: измерение `{dim}` («{ctx}») должно хранить историю атрибутов `{a1}` и `{a2}` "
            f"(медленно меняющееся измерение, тип 2): строка — версия ключа `{k}` с `valid_from`, `valid_to` "
            f"(у текущей — '9999-12-31') и `is_current`. Каждую ночь приходит снимок `{stg}` (ключ и атрибуты; "
            f"выгрузка частичная — ключей, которых нет в снимке, это не касается). Показанный скрипт перезаписывает "
            f"атрибуты на месте — аналитики потеряли историю. Пример строк измерения:\n{sample}\n\n"
            f"Нужна замена скрипта загрузки на дату '{d}', при которой: (1) у ключа с изменившимся атрибутом "
            f"текущая версия закрывается датой загрузки и добавляется новая текущая; (2) новые ключи добавляются; "
            f"(3) неизменные ключи и ключи вне снимка не трогаются; (4) атрибуты могут быть NULL, переход в NULL и "
            f"из NULL — тоже изменение; (5) повторный запуск той же загрузки ничего не меняет; (6) у каждого ключа "
            f"после загрузки ровно одна текущая версия. Какая замена выполняет все требования?")
    return build_variant(
        FAMILY_ID, seed, stem=stem, code=code, options=opts,
        answer_key=AnswerKey(kind="option", value=key, explanation=(
            "Верно: сначала закрыть текущие версии, у которых атрибуты отличаются по null-безопасному сравнению "
            "(IS NOT), затем вставить версию для каждого ключа снимка без текущей версии — это и новые ключи, и "
            "только что закрытые. Остальные нарушают правила: " + f"{WHY[a]}; {WHY[b]}; третий вариант нарушает оба.")),
        context=ctx, verification="execution", checks=checks, defect_type="scd2_load",
        display_code_note=("Ответ проверяется исполнением: скрипт запускается дважды на sqlite, итог сравнивается "
                           "с эталоном, посчитанным моделью на Python."),
        params={"dim": dim, "d": d, "ids": ids, "distractors": chosen})
