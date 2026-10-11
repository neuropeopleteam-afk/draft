"""analyst.er.cardinality_ddl_fix — choose_fix: кардинальность связи из требования → определение таблицы (DDL).

Требование описывает связь двух сущностей словами («у каждого X ровно один Y», «не больше одного»,
«может быть без», «многие ко многим, пару нельзя связать дважды»). Показано текущее определение таблицы с
ошибкой кардинальности; нужно выбрать определение, которое соответствует требованию. Режимы:
  * one_many — обязательная связь «один ко многим»: внешний ключ NOT NULL REFERENCES;
  * one_one — «один к одному»: внешний ключ NOT NULL UNIQUE REFERENCES;
  * optional — необязательная связь «один ко многим»: внешний ключ без NOT NULL;
  * many_many — «многие ко многим»: таблица связи с составным первичным ключом.
Для каждого режима — четыре типичные ошибки (лишний или пропущенный NOT NULL / UNIQUE / REFERENCES, ключ
по одному столбцу и т. п.); одна показана как текущая, три другие — дистракторы. Ключ проверяется
исполнением: каждое определение создаётся в sqlite3 с PRAGMA foreign_keys = ON и прогоняется через
сценарии вставки, выведенные из требования (что должно проходить и что должно отклоняться).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import balanced_options, cap, py_literal_block

FAMILY_ID = "analyst.er.cardinality_ddl_fix"

# (контекст, родитель: таблица, им., род., дат., дат. мн.; потомок: таблица, им., род., род. мн., столбец, ж. р.)
CTX = [("онлайн-школа", ("courses", "курс", "курса", "курсу", "курсам"),
        ("lessons", "урок", "урока", "уроков", "topic", False)),
       ("служба доставки", ("couriers", "курьер", "курьера", "курьеру", "курьерам"),
        ("orders", "заказ", "заказа", "заказов", "address", False)),
       ("поликлиника", ("doctors", "врач", "врача", "врачу", "врачам"),
        ("visits", "приём", "приёма", "приёмов", "reason", False)),
       ("банк", ("clients", "клиент", "клиента", "клиенту", "клиентам"),
        ("cards", "карта", "карты", "карт", "card_mask", True)),
       ("отдел кадров", ("departments", "отдел", "отдела", "отделу", "отделам"),
        ("employees", "сотрудник", "сотрудника", "сотрудников", "full_name", False)),
       ("библиотека", ("readers", "читатель", "читателя", "читателю", "читателям"),
        ("loans", "выдача книги", "выдачи книги", "выдач книг", "book_title", True)),
       ("склад", ("warehouses", "склад", "склада", "складу", "складам"),
        ("cells", "ячейка", "ячейки", "ячеек", "code", True)),
       ("каршеринг", ("cars", "автомобиль", "автомобиля", "автомобилю", "автомобилям"),
        ("trips", "поездка", "поездки", "поездок", "route", True)),
       ("конференция", ("speakers", "докладчик", "докладчика", "докладчику", "докладчикам"),
        ("talks", "доклад", "доклада", "докладов", "title", False)),
       ("техподдержка", ("engineers", "инженер", "инженера", "инженеру", "инженерам"),
        ("tickets", "заявка", "заявки", "заявок", "subject", True))]

# «один к одному» — пары, где связь по смыслу не больше одной строки на запись родителя
CTX_ONE_ONE = [("отдел кадров", ("employees", "сотрудник", "сотрудника", "сотруднику", "сотрудникам"),
                ("passes", "пропуск", "пропуска", "пропусков", "pass_no", False)),
               ("программа лояльности", ("clients", "клиент", "клиента", "клиенту", "клиентам"),
                ("loyalty_cards", "карта лояльности", "карты лояльности", "карт лояльности", "card_no", True)),
               ("поликлиника", ("patients", "пациент", "пациента", "пациенту", "пациентам"),
                ("med_records", "медкарта", "медкарты", "медкарт", "record_no", True)),
               ("онлайн-касса", ("orders", "заказ", "заказа", "заказу", "заказам"),
                ("receipts", "чек", "чека", "чеков", "fiscal_sign", False)),
               ("служба доставки", ("couriers", "курьер", "курьера", "курьеру", "курьерам"),
                ("terminals", "терминал", "терминала", "терминалов", "serial_no", False)),
               ("управляющая компания", ("flats", "квартира", "квартиры", "квартире", "квартирам"),
                ("accounts", "лицевой счёт", "лицевого счёта", "лицевых счетов", "account_no", False)),
               ("университет", ("students", "студент", "студента", "студенту", "студентам"),
                ("record_books", "зачётная книжка", "зачётной книжки", "зачётных книжек", "book_no", True)),
               ("автопарк", ("cars", "автомобиль", "автомобиля", "автомобилю", "автомобилям"),
                ("trackers", "GPS-трекер", "GPS-трекера", "GPS-трекеров", "imei", False))]

EXTRA = {False: ["created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP", "status TEXT NOT NULL DEFAULT 'new'",
                 "comment TEXT", "priority INTEGER NOT NULL DEFAULT 0", "updated_at TEXT"],
         True: ["role TEXT NOT NULL DEFAULT 'main'", "linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
                "share_pct INTEGER NOT NULL DEFAULT 100", "note TEXT"]}

MODES = ["one_many", "one_one", "optional", "many_many"]

ERRORS = {"one_many": ["nullable", "unique", "noref", "nullable_unique"],
          "one_one": ["no_unique", "nullable", "noref", "bare"],
          "optional": ["notnull", "unique", "noref", "notnull_unique"],
          "many_many": ["pk_one", "unique_other", "no_pk", "noref_other"]}

WHY = {"nullable": "без NOT NULL можно сохранить строку без связи, а требование делает связь обязательной",
       "unique": "UNIQUE запрещает второй строке ссылаться на ту же запись, а требование допускает много",
       "noref": "без REFERENCES можно сослаться на несуществующую запись",
       "nullable_unique": "без NOT NULL связь необязательна, а UNIQUE запрещает вторую строку на ту же запись",
       "no_unique": "без UNIQUE на одну запись могут сослаться две строки, а требование — не больше одной",
       "bare": "нет ни NOT NULL, ни UNIQUE: связь необязательна и не ограничена одной строкой",
       "notnull": "NOT NULL запрещает строку без связи, а требование её допускает",
       "notnull_unique": "NOT NULL запрещает строку без связи, UNIQUE — вторую строку на ту же запись",
       "pk_one": "первичный ключ по одному столбцу не даёт связать одну запись первой таблицы с несколькими записями второй",
       "unique_other": "UNIQUE по второму столбцу разрешает связать его запись только с одной записью первой "
                       "таблицы",
       "no_pk": "без составного ключа одну и ту же пару можно связать дважды",
       "noref_other": "второй столбец без REFERENCES — можно сослаться на несуществующую запись"}

CHECK_SRC = r'''
import sqlite3
con = sqlite3.connect(":memory:")
con.execute("PRAGMA foreign_keys = ON")
con.executescript(SETUP)
try:
    con.executescript(DDL)
    bad = 0
except sqlite3.Error:
    bad = 1
if not bad:
    for sql, must_pass in SCENARIOS:
        try:
            con.execute(sql)
            ok = True
        except sqlite3.Error:
            ok = False
        if ok != must_pass:
            bad += 1
print("RESULT: PASS" if bad == 0 else "RESULT: FAIL")
'''


def _child_ddl(child, txt, fk, parent, kind, mode, extra):
    cons = {"one_many": {"good": "NOT NULL REFERENCES", "nullable": "REFERENCES",
                         "unique": "NOT NULL UNIQUE REFERENCES", "noref": "NOT NULL",
                         "nullable_unique": "UNIQUE REFERENCES"},
            "one_one": {"good": "NOT NULL UNIQUE REFERENCES", "no_unique": "NOT NULL REFERENCES",
                        "nullable": "UNIQUE REFERENCES", "noref": "NOT NULL UNIQUE", "bare": "REFERENCES"},
            "optional": {"good": "REFERENCES", "notnull": "NOT NULL REFERENCES", "unique": "UNIQUE REFERENCES",
                         "noref": "", "notnull_unique": "NOT NULL UNIQUE REFERENCES"}}[mode]
    c = cons[kind]
    ref = f" {parent}(id)" if c.endswith("REFERENCES") else ""
    fk_line = f"  {fk} INTEGER{(' ' + c) if c else ''}{ref}"
    return f"CREATE TABLE {child} (\n  id INTEGER PRIMARY KEY,\n  {txt} TEXT NOT NULL,\n  {extra},\n{fk_line}\n);"


def _link_ddl(link, a, a_fk, b, b_fk, kind, extra):
    a_line = f"  {a_fk} INTEGER NOT NULL REFERENCES {a}(id),"
    b_line = (f"  {b_fk} INTEGER NOT NULL," if kind == "noref_other"
              else f"  {b_fk} INTEGER NOT NULL REFERENCES {b}(id),")
    key = {"good": f"  PRIMARY KEY ({a_fk}, {b_fk})", "pk_one": f"  PRIMARY KEY ({a_fk})",
           "unique_other": f"  UNIQUE ({b_fk})", "no_pk": f"  CHECK ({extra.split()[0]} IS NOT NULL)",
           "noref_other": f"  PRIMARY KEY ({a_fk}, {b_fk})"}[kind]
    return f"CREATE TABLE {link} (\n{a_line}\n{b_line}\n  {extra},\n{key}\n);"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    mode = rng.choice(MODES)
    ctx, (ptab, p_nom, p_gen, p_dat, p_dat_pl), (ctab, c_nom, c_gen, c_gen_pl, txt, fem) = rng.choice(
        CTX_ONE_ONE if mode == "one_one" else CTX)
    each = "Каждая" if fem else "Каждый"
    extra = rng.choice(EXTRA[mode == "many_many"])
    errs = list(ERRORS[mode])
    shown_err = rng.choice(errs)
    dist = [e for e in errs if e != shown_err]
    fk = ptab[:-1] + "_id" if ptab.endswith("s") else ptab + "_id"
    setup = (f"CREATE TABLE {ptab} (id INTEGER PRIMARY KEY, name TEXT NOT NULL);\n"
             f"INSERT INTO {ptab} (id, name) VALUES (1, '{p_nom} 1'), (2, '{p_nom} 2');\n")
    if mode == "many_many":
        link = f"{ptab}_{ctab}"
        a_fk, b_fk = fk, (ctab[:-1] + "_id" if ctab.endswith("s") else ctab + "_id")
        setup += (f"CREATE TABLE {ctab} (id INTEGER PRIMARY KEY, {txt} TEXT NOT NULL);\n"
                  f"INSERT INTO {ctab} (id, {txt}) VALUES (10, 'a'), (11, 'b');\n")
        ins = lambda a_id, b_id: f"INSERT INTO {link} ({a_fk}, {b_fk}) VALUES ({a_id}, {b_id})"  # noqa: E731
        scen = [(ins(1, 10), True), (ins(1, 11), True), (ins(2, 10), True), (ins(1, 10), False),
                (ins(9, 10), False), (ins(1, 99), False)]
        ddl = lambda k: _link_ddl(link, ptab, a_fk, ctab, b_fk, k, extra)  # noqa: E731
        good = ddl("good")
        req = (f"«{'Одна' if fem else 'Один'} {c_nom} может относиться к нескольким {p_dat_pl}, у одного {p_gen} — "
               f"несколько {c_gen_pl}; одну и ту же пару связать дважды нельзя; ссылаться можно только на существующие "
               f"записи обеих таблиц»")
        table_name = link
    else:
        ins = lambda cid, pid: (f"INSERT INTO {ctab} (id, {txt}, {fk}) VALUES "  # noqa: E731
                                f"({cid}, 'x', {'NULL' if pid is None else pid})")
        if mode == "one_many":
            scen = [(ins(10, 1), True), (ins(11, 1), True), (ins(12, 2), True), (ins(13, None), False),
                    (ins(14, 99), False)]
            req = (f"«{each} {c_nom} относится ровно к одному {p_dat}; у одного {p_gen} может быть сколько "
                   f"угодно {c_gen_pl}; ссылаться можно только на существующие записи `{ptab}`»")
        elif mode == "one_one":
            scen = [(ins(10, 1), True), (ins(11, 2), True), (ins(12, 1), False), (ins(13, None), False),
                    (ins(14, 99), False)]
            req = (f"«{each} {c_nom} относится ровно к одному {p_dat}; у {p_gen} — не больше {'одной' if fem else 'одного'} {c_gen} "
                   f"(может не быть ни {'одной' if fem else 'одного'}); ссылаться можно только на существующие записи `{ptab}`»")
        else:
            scen = [(ins(10, 1), True), (ins(11, 1), True), (ins(12, None), True), (ins(13, 99), False)]
            req = (f"«{cap(c_nom)} может быть ещё не {'назначена' if fem else 'назначен'} {p_dat}; у одного {p_gen} "
                   f"может быть сколько угодно {c_gen_pl}; ссылаться можно только на существующие записи `{ptab}`»")
        ddl = lambda k: _child_ddl(ctab, txt, fk, ptab, k, mode, extra)  # noqa: E731
        good = ddl("good")
        table_name = ctab
    shown = ddl(shown_err)
    label = "Заменить определение на:"
    opts, key = balanced_options(FAMILY_ID, seed, rng, (label, good), [(label, ddl(d)) for d in dist])

    def prog(text):
        return (f"SETUP = {setup!r}\n" + py_literal_block("DDL", text) + f"SCENARIOS = {scen!r}\n" + CHECK_SRC)
    checks = [Check(name="shown_violates", runner="python", program=prog(shown), expect="fail")]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="python", program=prog(o.code), embeds_display_code=False,
                            expect="pass" if o.id == key else "fail"))
    stem = (f"Система «{ctx}». В требованиях записано: {req}. Таблица `{ptab}` уже есть (`id INTEGER PRIMARY "
            f"KEY`){', таблица `' + ctab + '` — тоже' if mode == 'many_many' else ''}. Разработчик определил "
            f"таблицу `{table_name}` так, как показано (SQLite, внешние ключи включены). Определение не "
            f"соответствует требованию. Какое определение соответствует ему полностью?")
    ak = AnswerKey(kind="option", value=key,
                   explanation=(f"Сейчас: {WHY[shown_err]}. Верное определение пропускает все допустимые вставки и "
                                f"отклоняет запрещённые требованием. Дистракторы: " +
                                "; ".join(WHY[d] for d in dist) + "."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=shown, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="cardinality", language="sql",
                         display_code_note="Ответ проверяется сценариями вставки в sqlite3, выведенными из требования.",
                         params={"mode": mode, "shown": shown_err, "distractors": dist})
