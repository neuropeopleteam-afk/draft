"""mobile.storage.sqlite_migration_bug — find_bug: миграция локальной SQLite-базы приложения при обновлении.

Приложение хранит данные в SQLite на устройстве (Room / SQLDelight / Core Data поверх SQLite). Скрипт миграции
версии N → N+1 добавляет несколько столбцов; один из них объявлен `NOT NULL` без `DEFAULT` — SQLite отклоняет
`ALTER TABLE … ADD COLUMN … NOT NULL` без значения по умолчанию, миграция прерывается у всех, кто обновляет
приложение (на чистой установке схема создаётся сразу новой, и ошибки нет). Один подтип дефекта; варьируются
предметная область, столбцы, порядок операторов и служебные строки (индекс, PRAGMA user_version, UPDATE).
Ключ проверяется исполнением: показанный скрипт дословно выполняется в sqlite3 на базе версии N с данными;
исправленный скрипт проходит (версия схемы повышена, строки сохранены, значения по умолчанию верны).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "mobile.storage.sqlite_migration_bug"

# (контекст, таблица, базовые столбцы, строки, [(новый столбец, тип, значение по умолчанию, смысл)])
DOMAINS = [
    ("заметки", "notes", "id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT",
     [(1, "Список покупок", "молоко"), (2, "Идеи", None), (3, "Пароль от Wi-Fi", "на роутере")],
     [("pinned", "INTEGER", "0", "закреплена ли заметка"), ("color", "INTEGER", "0", "цвет карточки"),
      ("sort_order", "INTEGER", "0", "ручной порядок")]),
    ("трекер привычек", "habits", "id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT",
     [(1, "Вода", "2026-09-01"), (2, "Зарядка", "2026-09-03")],
     [("streak", "INTEGER", "0", "серия дней"), ("archived", "INTEGER", "0", "в архиве"),
      ("reminder_min", "INTEGER", "540", "время напоминания, минуты от полуночи")]),
    ("офлайн-корзина магазина", "cart_items", "id INTEGER PRIMARY KEY, sku TEXT NOT NULL, qty INTEGER NOT NULL",
     [(1, "A-100", 2), (2, "B-205", 1), (3, "C-310", 4)],
     [("price_cents", "INTEGER", "0", "цена на момент добавления"), ("selected", "INTEGER", "1", "отмечен к оплате"),
      ("gift", "INTEGER", "0", "подарочная упаковка")]),
    ("кэш сообщений мессенджера", "messages", "id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, text TEXT",
     [(1, 10, "привет"), (2, 10, "как дела?"), (3, 11, None)],
     [("status", "INTEGER", "0", "статус доставки"), ("edited", "INTEGER", "0", "сообщение изменено"),
      ("reactions", "INTEGER", "0", "число реакций")]),
    ("история тренировок", "workouts", "id INTEGER PRIMARY KEY, kind TEXT NOT NULL, minutes INTEGER",
     [(1, "бег", 30), (2, "йога", 45)],
     [("calories", "INTEGER", "0", "сожжённые калории"), ("synced", "INTEGER", "0", "отправлено на сервер"),
      ("heart_avg", "INTEGER", "0", "средний пульс")]),
]
NULLABLE = {"notes": ("remote_id", "TEXT"), "habits": ("icon", "TEXT"), "cart_items": ("promo_code", "TEXT"),
            "messages": ("reply_to", "INTEGER"), "workouts": ("route_json", "TEXT")}

PROGRAM = """import sqlite3

{migration}
SETUP = {setup!r}
con = sqlite3.connect(':memory:')
con.executescript(SETUP)
ok = True
try:
    con.executescript(MIGRATION)
except sqlite3.Error as e:
    ok = False
    print('migration error:', type(e).__name__)
if ok:
    ver = con.execute('PRAGMA user_version').fetchone()[0]
    rows = con.execute('SELECT id, {cols} FROM {table} ORDER BY id').fetchall()
    ok = ver == {new_ver} and rows == {expected!r}
print('RESULT: PASS' if ok else 'RESULT: FAIL')
"""


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table, base_cols, rows, newcols = rng.choice(DOMAINS)
    ver = rng.randint(2, 9)
    cols = rng.sample(newcols, 2)
    nul = NULLABLE[table]
    bad_i = rng.randrange(2)
    order = [("col", 0), ("col", 1), ("null", None)]
    rng.shuffle(order)
    good_lines, bad_lines = [], []
    for kind, i in order:
        if kind == "null":
            ln = f"ALTER TABLE {table} ADD COLUMN {nul[0]} {nul[1]};"
            good_lines.append(ln)
            bad_lines.append(ln)
            continue
        name, typ, dflt, _ = cols[i]
        good = f"ALTER TABLE {table} ADD COLUMN {name} {typ} NOT NULL DEFAULT {dflt};"
        good_lines.append(good)
        bad_lines.append(f"ALTER TABLE {table} ADD COLUMN {name} {typ} NOT NULL;" if i == bad_i else good)
    idx_col = cols[rng.randrange(2)][0]
    tail = [f"CREATE INDEX IF NOT EXISTS idx_{table}_{idx_col} ON {table}({idx_col});"]
    if rng.random() < 0.5:
        tail.append(f"UPDATE {table} SET {nul[0]} = NULL WHERE {nul[0]} = '';")
    rng.shuffle(tail)
    head = [f"-- Миграция локальной базы: версия {ver} → {ver + 1} ({ctx})", "BEGIN;"]
    end = [f"PRAGMA user_version = {ver + 1};", "COMMIT;"]
    buggy = "\n".join(head + bad_lines + tail + end)
    fixed = "\n".join(head + good_lines + tail + end)
    diff = changed_lines(buggy, fixed)
    assert len(diff) == 1
    key_line = next(iter(diff))
    n_base = len(base_cols.split(", "))
    vals = ", ".join("(" + ", ".join("NULL" if x is None else (str(x) if isinstance(x, int) else f"'{x}'")
                                     for x in r) + ")" for r in rows)
    setup = (f"CREATE TABLE {table} ({base_cols});\n"
             f"INSERT INTO {table} VALUES {vals};\nPRAGMA user_version = {ver};")
    assert n_base == len(rows[0])
    names = [c[0] for c in cols]
    expected = [(r[0], *[int(c[2]) for c in cols]) for r in rows]
    prog = lambda sql: PROGRAM.format(migration=f'MIGRATION = """\n{sql}\n"""\n', setup=setup,
                                      cols=", ".join(names), table=table, new_ver=ver + 1, expected=expected)
    checks = [Check(name="buggy_fails", runner="python", program=prog(buggy), expect="fail"),
              Check(name="fixed_passes", runner="python", program=prog(fixed), expect="pass",
                    embeds_display_code=False)]
    bad_name, _, bad_default, meaning = cols[bad_i]
    n_rows = len(rows)
    stem = (f"Мобильное приложение ({ctx}) хранит данные в SQLite на устройстве. В новой версии добавлен скрипт "
            f"миграции схемы {ver} → {ver + 1}. На чистой установке всё работает, но у пользователей, обновивших "
            f"приложение со старой версии, миграция прерывается при первом запуске, и приложение не открывает "
            f"локальные данные. Укажите номер строки, которую достаточно исправить одной правкой, чтобы ошибка ушла.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=(f"Строка {key_line}: столбец `{bad_name}` ({meaning}) объявлен NOT NULL без DEFAULT. "
                                f"SQLite не добавляет такой столбец через ALTER TABLE: существующим строкам "
                                f"(в таблице их {n_rows}) нечего записать. Исправление — `NOT NULL DEFAULT "
                                f"{bad_default}`; на чистой установке таблица создаётся сразу новой схемой, "
                                f"поэтому ошибка видна только при обновлении."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="add_not_null_no_default",
                         params={"fixed_code": fixed, "bad_column": bad_name, "from_version": ver})
