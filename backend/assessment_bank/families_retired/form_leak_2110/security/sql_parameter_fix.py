"""Параметры SQLite сохраняют специальные символы как данные."""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng, sql_literal
from assessment_bank.schema import Check
from ._support import CONTEXTS, SOURCES, SQL_NAMES, fix_variant

FAMILY_ID = "security.sql.parameter_fix"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table = rng.choice(CONTEXTS), rng.choice(["records", "entries", "documents", "items"])
    title = rng.choice(SQL_NAMES)
    rid = rng.randint(10, 900)
    head = "def lookup(db, name):\n"
    buggy = head + f'    sql = "SELECT id FROM {table} WHERE label = \'" + name + "\'"\n' \
        + "    return db.execute(sql).fetchall()"
    correct = head + f'    sql = "SELECT id FROM {table} WHERE label = ?"\n' \
        + "    return db.execute(sql, (name,)).fetchall()"
    distractors = [
        head + f'    sql = "SELECT id FROM {table} WHERE label = ?"\n'
        + '    return db.execute(sql, (name.replace("\'", ""),)).fetchall()',
        head + f'    sql = "SELECT id FROM {table} WHERE label = ?"\n'
        + "    return db.execute(sql, (name.strip(),)).fetchall()",
        head + f'''    sql = "SELECT id FROM {table} WHERE label = '?'"\n'''
        + "    return db.execute(sql).fetchall()",
    ]
    labels = [title, "  Черновик  ", "Итог & план", "Скидка 15%", "Обычная запись"]
    rows = [(rid + i, name) for i, name in enumerate(labels)]
    test = f"""import sqlite3
db = sqlite3.connect(':memory:')
db.execute('CREATE TABLE {table} (id INTEGER, label TEXT)')
db.executemany('INSERT INTO {table} VALUES (?, ?)', {rows!r})
for item_id, label in {rows!r}:
    assert lookup(db, label) == [(item_id,)]
assert lookup(db, 'Нет такой записи') == []
db.close()"""
    setup = f"CREATE TABLE {table} (id INTEGER, label TEXT);\n" + "\n".join(
        f"INSERT INTO {table} VALUES ({i}, {sql_literal(t)});" for i, t in rows)
    # sqlite runner дополнительно проверяет SQL с законным названием, содержащим апостроф.
    extra = [Check(name="sqlite_literal_fixture", runner="sqlite", embeds_display_code=False,
                   program=f"SELECT id FROM {table} WHERE label = {sql_literal(title)};",
                   files={"setup.sql": setup}, expect="stdout_equals", expected_stdout=str(rid))]
    stem = (f"{ctx.capitalize()}: поиск должен точно сохранять название, в том числе пробелы "
            f"и апострофы. В записи id={rid} название `{title}`. Таблица `{table}` выбирается "
            "из констант приложения, пользователь передаёт только `name`. Найдите безопасное "
            "исправление для sqlite3: значения нельзя соединять с текстом SQL или изменять.")
    return fix_variant(
        FAMILY_ID, seed, rng, stem=stem, buggy=buggy, correct=correct, distractors=distractors,
        test=test, context=ctx, defect="sql_string_concatenation", extra_checks=extra,
        why="Плейсхолдер ? и отдельный одноэлементный кортеж передают значение как данные. "
            "Удаление апострофов или пробелов и кавычки вокруг ? нарушают точное совпадение.",
        params={"source_urls": [SOURCES["coding"]], "table": table, "rows": rows},
    )
