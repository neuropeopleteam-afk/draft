"""qa.pytest.shared_state_ob3 — открытая книга: нестабильные тесты из-за общего состояния фикстуры.

Фикстура с ``scope="module"`` возвращает изменяемый объект; один тест его меняет, другой
рассчитывает на пустое состояние. В порядке из файла набор зелёный, но при случайном порядке
(pytest-randomly, xdist, запуск подмножества) — иногда красный.

Шаг 1 — выбрать порядок запуска, воспроизводящий падение (ровно один из четырёх; остальные
три — все зелёные порядки). Шаг 2 — выбрать исправление фикстуры: тесты зелёные при любом
из 6 порядков. Дистракторы: очистка в teardown фикстуры модуля (срабатывает после всех
тестов модуля), область session, функция-фикстура, возвращающая общий объект, поверхностная
копия (общий словарь внутри). Шаг 3 — объяснение при новом условии (параллельный запуск и
общая БД, время, политика перезапусков, общий стенд). Шаги 1–2 проверяются исполнением
(обвязка PYTEST_SHIM повторяет порядок подготовки и завершения фикстур pytest 8).
"""
from __future__ import annotations

import itertools

from assessment_bank.families.qa._shims import PYTEST_SHIM, module_prelude
from assessment_bank.gen_utils import build_variant, make_rng, ob3_steps, rubric_from
from assessment_bank.schema import AnswerKey, Check

from ._qa_utils import balanced_options

FAMILY_ID = "qa.pytest.shared_state_ob3"

# (контекст, модуль, класс, фикстура, add, remove, count, owner, ключи, имена тестов X/Y/Z)
CONTEXTS = [
    ("интернет-магазин", "shop.cart", "Cart", "cart", "add", "remove", "count", "qa_user",
     ("SKU-17", "SKU-99"), ("test_add_two_items", "test_remove_missing_is_noop", "test_owner_is_set")),
    ("уведомления", "notify.inbox", "Inbox", "inbox", "push", "dismiss", "unread", "bot",
     ("welcome", "promo"), ("test_push_counts_unread", "test_dismiss_unknown_is_safe", "test_inbox_owner")),
    ("флаги функций", "flags.registry", "FlagRegistry", "flags", "enable", "disable", "active", "staging",
     ("new_checkout", "dark_mode"), ("test_enable_flag", "test_disable_unknown_flag", "test_registry_env")),
    ("медиатека", "media.playlist", "Playlist", "playlist", "append", "drop", "length", "radio",
     ("track_42", "track_7"), ("test_append_tracks", "test_drop_missing_track", "test_playlist_owner")),
    ("склад", "wms.reserve", "Reservation", "reservation", "reserve", "release", "reserved", "msk_1",
     ("PALLET-3", "PALLET-8"), ("test_reserve_two", "test_release_unknown", "test_reservation_site")),
]


def _impl(c):
    _, _, cls, _, add, rem, cnt, *_ = c
    return (f"class {cls}:\n    def __init__(self, owner):\n        self.owner = owner\n"
            "        self.items = {}\n\n"
            f"    def {add}(self, key, n=1):\n        self.items[key] = self.items.get(key, 0) + n\n\n"
            f"    def {rem}(self, key):\n        self.items.pop(key, None)\n\n"
            f"    def {cnt}(self):\n        return sum(self.items.values())\n\n"
            "    def clear(self):\n        self.items.clear()\n")


def _fixture(kind, c):
    _, _, cls, fx, _, _, _, owner, _, _ = c
    make = f'{cls}(owner="{owner}")'
    if kind in ("good", "module_teardown", "session"):
        deco = {"good": "@pytest.fixture", "module_teardown": '@pytest.fixture(scope="module")',
                "session": '@pytest.fixture(scope="session")'}[kind]
        return "\n".join([deco, f"def {fx}():", f"    obj = {make}", "    yield obj", "    obj.clear()"])
    if kind == "shared":
        return "\n".join([f"_SHARED = {make}", "", "", "@pytest.fixture", f"def {fx}():",
                          "    return _SHARED"])
    if kind == "shallow":
        return "\n".join(["import copy", "", f"_BASE = {make}", "", "", "@pytest.fixture",
                          f"def {fx}():", "    return copy.copy(_BASE)"])
    if kind == "buggy":
        return "\n".join(['@pytest.fixture(scope="module")', f"def {fx}():", f"    return {make}"])
    raise ValueError(kind)


def _tests(c, n_add):
    _, _, _, fx, add, rem, cnt, owner, (k1, k2), (tx, ty, tz) = c
    return {
        tx: [f"def {tx}({fx}):", f"    {fx}.{add}(\"{k1}\", {n_add})", f"    assert {fx}.{cnt}() == {n_add}"],
        ty: [f"def {ty}({fx}):", f"    {fx}.{rem}(\"{k2}\")", f"    assert {fx}.{cnt}() == 0"],
        tz: [f"def {tz}({fx}):", f"    assert {fx}.owner == \"{owner}\""],
    }


def _module(c, fixture_code, file_order, tests):
    _, mod, cls, *_ = c
    out = ["import pytest", f"from {mod} import {cls}", "", "", fixture_code]
    for t in file_order:
        out += ["", ""] + tests[t]
    return "\n".join(out)


def _order_tail(order):
    return ("_bk_res = _bk_run(dict(globals()), order=%r)\n" % list(order)
            + "print(\"RESULT: PASS\" if all(o == \"passed\" for _, o in _bk_res) else \"RESULT: FAIL\")\n")


def _all_orders_tail(names):
    return ("import itertools as _bk_it2\n"
            f"_bk_ok = all(all(o == \"passed\" for _, o in _bk_run(dict(globals()), order=list(_bk_p)))\n"
            f"             for _bk_p in _bk_it2.permutations({list(names)!r}))\n"
            "print(\"RESULT: PASS\" if _bk_ok else \"RESULT: FAIL\")\n")


def _program(code, tail, mods):
    return PYTEST_SHIM + "\n" + module_prelude(mods) + "\n" + code.rstrip() + "\n\n" + tail


def _passes(order, x, y):
    return order.index(y) < order.index(x)


CONDITIONS = {
    "xdist": dict(
        text=("Тесты стали запускать параллельно (pytest-xdist, -n 4), а фикстуры создают "
              "данные в общей тестовой базе стенда. Какие новые причины нестабильности "
              "появятся и как изолировать тесты?"),
        criteria=[("why", "Объясняет: процессы xdist не делят память, но делят внешние "
                          "ресурсы (БД, файлы, очереди, порты); scope=session создаётся в "
                          "каждом процессе отдельно; порядок и состав тестов в процессе "
                          "непредсказуемы", 0.35),
                  ("isolation", "Изоляция данных: уникальные идентификаторы и префиксы на тест "
                                "или процесс (worker_id), транзакция с откатом, отдельная схема "
                                "или база на процесс, очистка по своим меткам", 0.4),
                  ("verify", "Как убедиться: прогон в случайном порядке и параллельно много "
                             "раз, запуск теста в одиночку, поиск скрытых зависимостей", 0.25)],
        strong="""В параллельном режиме каждый процесс xdist получает свою копию фикстур, даже
            session — поэтому общее состояние в памяти пропадает, зато остаётся общее внешнее:
            база стенда, файлы, очереди, фиксированные порты. Тест одного процесса может
            увидеть или удалить данные теста из другого, а проверки вида «в таблице N
            записей» начинают плавать. Изолирую данные: каждый тест создаёт свои записи с
            уникальными ключами (uuid или префикс с worker_id), проверяет только их и только
            их удаляет; для БД — транзакция на тест с откатом или отдельная схема или база на
            процесс (имя по worker_id); временные файлы — через tmp_path; порты — свободные,
            а не фиксированные. Проверяю результат: многократный прогон с -p randomly и -n 4,
            запуск каждого теста в одиночку и в обратном порядке, чтобы выявить оставшиеся
            зависимости.""",
        medium="""При параллельном запуске тесты из разных процессов будут мешать друг другу
            через общую базу. Нужно, чтобы каждый тест создавал свои данные с уникальными
            ключами и удалял их, или использовать транзакцию с откатом.""",
        weak="""Нужно запускать тесты в одном процессе, тогда проблем не будет."""),
    "time": dict(
        text=("Другой тест из этого модуля иногда падает в CI около полуночи по UTC: он "
              "создаёт заказ и проверяет, что дата заказа равна `date.today()`. Как найти "
              "причину и сделать тест стабильным?"),
        criteria=[("cause", "Видит гонку со временем: дата берётся дважды (в коде и в тесте) "
                            "в разные моменты и, возможно, в разных часовых поясах; около "
                            "полуночи они расходятся", 0.4),
                  ("fix", "Управляет временем: внедряет часы/функцию now в код, замораживает "
                          "время (freezegun, time-machine, monkeypatch), явно задаёт "
                          "часовой пояс", 0.35),
                  ("cover", "Добавляет целевые тесты на границы: 23:59:59, 00:00, смена "
                            "часового пояса, переход на летнее время; проверяет, что тест "
                            "детерминирован", 0.25)],
        strong="""Тест берёт «сегодня» отдельно от кода: заказ создаётся в 23:59:59.9, а
            date.today() в проверке вызывается уже в 00:00:00.1 — даты разные. Плюс код может
            считать дату в UTC, а тест — в локальном поясе раннера, и тогда окно падения
            шире. Подтверждаю гипотезу, заморозив время на 23:59:59 и 00:00:00 и запустив тест.
            Исправление: время становится зависимостью — код получает часы (функцию now или
            объект Clock), а тест подставляет фиксированное значение; либо замораживаю время
            freezegun/time-machine или monkeypatch. Часовой пояс задаю явно и в коде, и в
            тесте. Добавляю отдельные тесты на границы суток и смену часового пояса, чтобы
            поведение у полуночи проверялось намеренно, а не случайно.""",
        medium="""Около полуночи дата в коде и в тесте может отличаться, потому что они
            получаются в разное время. Нужно замораживать время в тесте, например через
            freezegun, или передавать текущую дату в функцию.""",
        weak="""Нужно не запускать CI около полуночи или перезапускать упавший тест."""),
    "policy": dict(
        text=("В CI около 3 % прогонов падают из-за нестабильных тестов, и команда включила "
              "автоматический перезапуск упавших тестов до трёх раз. Оцените такой подход и "
              "предложите политику работы с нестабильными тестами."),
        criteria=[("risk", "Видит риски перезапусков: маскируются настоящие гонки и "
                           "регрессии, растёт время сборки, исчезает сигнал о нестабильности", 0.35),
                  ("policy", "Политика: учёт и метрика нестабильности по тестам, карантин с "
                             "владельцем и сроком, перезапуск только как временная мера с "
                             "отчётом, запрет на новые нестабильные тесты", 0.4),
                  ("root", "Разбор причин по категориям (общее состояние, время, порядок, "
                           "асинхронность, внешние сервисы) и воспроизведение в случайном "
                           "порядке/многократном прогоне", 0.25)],
        strong="""Автоматический перезапуск делает сборку зелёной, но скрывает информацию:
            нестабильность может быть симптомом настоящей гонки в продукте, а не в тесте, и
            регрессия, проявляющаяся в 30 % случаев, почти всегда пройдёт с третьей попытки.
            Плюс растёт время сборки. Политика: каждый перезапуск фиксируется, по тестам
            ведётся доля нестабильных прогонов; тест с нестабильностью выше порога уходит в
            карантин — он выполняется, но не блокирует сборку, у него есть владелец и срок
            исправления, после которого тест чинят или удаляют. Перезапуск допустим только
            как временная мера и с отчётом. Новые тесты перед слиянием прогоняются многократно
            и в случайном порядке. Причины разбираю по категориям: общее состояние и порядок,
            время, асинхронность и ожидания, внешние сервисы и данные стенда.""",
        medium="""Перезапуск скрывает проблему и может пропустить настоящую ошибку. Лучше
            собирать статистику нестабильных тестов, переносить их в карантин и
            исправлять причины.""",
        weak="""Подход нормальный: если тест прошёл со второй попытки, значит, ошибки нет."""),
    "stand": dict(
        text=("Тесты API ходят в общий тестовый стенд, где данными пользуются и другие "
              "команды. Тест «у пользователя qa_user ровно 3 заказа» иногда падает. Как "
              "переделать тесты и тестовые данные?"),
        criteria=[("cause", "Объясняет: тест зависит от общих изменяемых данных, которыми "
                            "управляет не он; проверка точного количества хрупкая", 0.3),
                  ("data", "Тест сам создаёт нужные данные (через API или фабрики) с "
                           "уникальными ключами и проверяет только их; очистка за собой; "
                           "выделенные тестовые аккаунты", 0.4),
                  ("env", "Стратегия окружения: эфемерные стенды или контейнеры на прогон, "
                          "заглушки внешних зависимостей, контрактные тесты вместо "
                          "сквозных там, где это возможно", 0.3)],
        strong="""Тест полагается на состояние, которым он не владеет: любая команда может
            создать или удалить заказ qa_user, и проверка точного числа 3 ломается. Тест
            должен сам готовить данные: создаю нового пользователя с уникальным логином (uuid
            в имени), через API создаю ему три заказа и проверяю, что список содержит именно
            эти заказы — по идентификаторам, а не по общему количеству в системе. После
            теста удаляю созданное или помечаю его для фоновой очистки. Для стабильности
            всего набора — эфемерное окружение на прогон (контейнеры с базой и сервисом),
            внешние системы заменяю заглушками, а совместимость с ними проверяю
            контрактными тестами; сквозные тесты на общем стенде оставляю для небольшого
            набора критичных сценариев.""",
        medium="""Тест зависит от общих данных стенда. Лучше, чтобы тест сам создавал
            пользователя и заказы перед проверкой и удалял их после, а проверял только
            свои данные.""",
        weak="""Нужно попросить другие команды не трогать пользователя qa_user."""),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    c = rng.choice(CONTEXTS)
    ctx, mod, cls, fx = c[0], c[1], c[2], c[3]
    tx, ty, tz = c[9]
    n_add = rng.randint(2, 5)
    tests = _tests(c, n_add)
    names = [tx, ty, tz]
    good_orders = [o for o in itertools.permutations(names) if _passes(o, tx, ty)]
    bad_orders = [o for o in itertools.permutations(names) if not _passes(o, tx, ty)]
    file_order = list(rng.choice(good_orders))
    code = _module(c, _fixture("buggy", c), file_order, tests)
    mods = {mod: _impl(c)}
    repro = rng.choice(bad_orders)
    others = list(good_orders)
    fmt_order = lambda o: " → ".join(o)
    opts1, key1 = balanced_options(FAMILY_ID, seed, rng, (fmt_order(repro), None),
                                   [(fmt_order(o), None) for o in others], step=1)
    by_text = {fmt_order(o): o for o in [repro] + others}
    pool = ["module_teardown", "session", "shared", "shallow"]
    chosen = rng.sample(pool, 3)
    opts2, key2 = balanced_options(FAMILY_ID, seed, rng, ("Заменить фикстуру на:", _fixture("good", c)),
                                   [("Заменить фикстуру на:", _fixture(d, c)) for d in chosen],
                                   step=2, salt="step2")
    checks = []
    for o in opts1:
        checks.append(Check(name=f"step1:{o.id}", runner="python",
                            program=_program(code, _order_tail(by_text[o.text]), mods),
                            expect="fail" if o.id == key1 else "pass"))
    for o in opts2:
        prog_code = _module(c, o.code, file_order, tests)
        checks.append(Check(name=f"step2:{o.id}", runner="python", embeds_display_code=False,
                            program=_program(prog_code, _all_orders_tail(names), mods),
                            expect="pass" if o.id == key2 else "fail"))
    checks.append(Check(name="file_order_green", runner="python",
                        program=_program(code, _order_tail(file_order), mods), expect="pass"))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    stem = (f"Модуль тестов ({ctx}) для класса `{cls}` из `{mod}`: у объекта есть владелец "
            f"`owner` и счётчик элементов. Локально и в CI тесты в порядке из файла проходят. "
            f"После подключения pytest-randomly (случайный порядок тестов) сборка стала иногда "
            f"падать, хотя код `{cls}` не менялся.")
    steps = ob3_steps(
        "Шаг 1. При каком порядке запуска тестов модуль упадёт?",
        "Шаг 2. Какое исправление фикстуры делает тесты зелёными при любом порядке запуска?",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    why = {"module_teardown": "очистка в teardown фикстуры модуля выполняется один раз — после "
                              "всех тестов модуля, а не между ними",
           "session": "область session делит объект между всеми тестами сессии — ещё шире, чем module",
           "shared": "фикстура функции возвращает один и тот же объект уровня модуля — состояние общее",
           "shallow": "copy.copy создаёт новый объект, но словарь items внутри общий — изменения "
                      "видны другим тестам"}
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                   explanation=(f"Фикстура `{fx}` с scope=\"module\" создаётся один раз на модуль: "
                                f"`{tx}` оставляет в объекте {n_add} {'элемента' if n_add < 5 else 'элементов'}, и `{ty}`, "
                                f"запущенный после него, видит непустое состояние. Падают порядки, "
                                f"где `{tx}` идёт раньше `{ty}`. Исправление — фикстура области "
                                f"function (новый объект на каждый тест). Дистракторы шага 2: "
                                + "; ".join(why[d] for d in chosen) + f". Шаг 3 — «{cond_name}»."))
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2,
                         answer_key=ak, rubric=rubric, context=ctx, verification="execution",
                         checks=checks, steps=steps, defect_type="shared_fixture_state",
                         display_code_note="Обвязка PYTEST_SHIM повторяет порядок подготовки и "
                                           "завершения фикстур pytest 8; класс подставляется "
                                           "как модуль; показанный код исполняется дословно.",
                         params={"distractors": chosen, "condition": cond_name,
                                 "file_order": file_order, "repro": list(repro)})
