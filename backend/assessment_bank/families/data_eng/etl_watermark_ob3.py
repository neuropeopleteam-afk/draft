"""data_eng.etl.watermark_ob3 — open_book_3step: инкрементальная выгрузка по водяному знаку updated_at.

Выгрузка берёт строки источника с `updated_at > wm` и сдвигает wm на максимум пакета; результат дописывается в журнал
версий хранилища (каждая версия строки (id, updated_at) должна попасть туда ровно один раз). Отметки времени — с
точностью до секунды. Дефект: если в той же секунде, что и максимум прошлого пакета, ещё одна транзакция
зафиксировалась ПОСЛЕ запуска, её строка имеет updated_at = wm и строгим сравнением отбрасывается навсегда.
Шаг 1 — сценарий из двух запусков, где это происходит (остальные: новая строка позже границы, изменение уже
выгруженной строки, новых строк нет). Шаг 2 — исправление: верное — `>=` и пропуск уже выгруженных пар
(id, updated_at); почти верные фиксированного состава — `>=` без защиты от повторов (повторы граничных строк),
пропуск по id (теряются новые версии уже выгруженных строк), память только о парах последнего пакета (повторы на
третьем запуске). Шаг 3 — перенос: поздняя фиксация долгих транзакций, удаления, повторная загрузка периода.
Проверка шагов 1–2 — исполнение показанного кода в песочнице Python на сценариях запусков.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng, ob3_steps, rubric_from
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_eng.etl.watermark_ob3"

CTX = [("заказы интернет-магазина", "orders"), ("платежи", "payments"), ("остатки склада", "stock"),
       ("заявки на доставку", "deliveries"), ("профили клиентов", "customers"), ("тарифы и цены", "prices")]

FILTER = {
    None: ['    batch = [r for r in source if r["updated_at"] > wm]'],
    "pairs": ['    loaded = state.setdefault("loaded", set())',
              '    batch = [r for r in source',
              '             if r["updated_at"] >= wm and (r["id"], r["updated_at"]) not in loaded]',
              '    loaded |= {(r["id"], r["updated_at"]) for r in batch}'],
    "ge": ['    batch = [r for r in source if r["updated_at"] >= wm]'],
    "ids": ['    ids = state.setdefault("ids", set())',
            '    batch = [r for r in source if r["updated_at"] >= wm and r["id"] not in ids]',
            '    ids |= {r["id"] for r in batch}'],
    "last": ['    last = state.get("last", set())',
             '    batch = [r for r in source',
             '             if r["updated_at"] >= wm and (r["id"], r["updated_at"]) not in last]',
             '    state["last"] = {(r["id"], r["updated_at"]) for r in batch}'],
}
LABEL = {"pairs": "Сравнивать `>=` и пропускать уже выгруженные пары (id, updated_at):",
         "ge": "Сравнивать `>=` вместо `>`:",
         "ids": "Сравнивать `>=` и пропускать строки с уже выгруженными id:",
         "last": "Сравнивать `>=` и пропускать пары (id, updated_at) из предыдущего пакета:"}


def _code(fix=None):
    return "\n".join(["def extract(source, state):",
                      '    wm = state.get("wm", "")',
                      *FILTER[fix],
                      "    if batch:",
                      '        state["wm"] = max(r["updated_at"] for r in batch)',
                      "    return batch"])


RUNNER = '''

RUNS = {runs!r}
state, out = {{}}, []
for snapshot in RUNS:
    out += [(r["id"], r["updated_at"]) for r in extract([dict(r) for r in snapshot], state)]
for pair in sorted(out):
    print(*pair)
'''


def _prog(code, runs):
    return code + RUNNER.format(runs=runs)


def _ref(runs):
    pairs = sorted({(r["id"], r["updated_at"]) for snap in runs for r in snap})
    return "\n".join(f"{i} {t}" for i, t in pairs)


def _sim(fix, runs):
    ns: dict = {}
    exec(_code(fix), ns)  # noqa: S102 — собственный код генератора, для отбора сценариев
    state, out = {}, []
    for snap in runs:
        out += [(r["id"], r["updated_at"]) for r in ns["extract"]([dict(r) for r in snap], state)]
    return "\n".join(f"{i} {t}" for i, t in sorted(out))


CONDITIONS = {
    "late_commit": dict(
        text=("В источнике (PostgreSQL) updated_at заполняется триггером через now() — это время НАЧАЛА транзакции. "
              "Часть транзакций пакетной загрузки идёт до 5 минут. Почему ваше исправление шага 2 всё равно может "
              "терять строки и как сделать выгрузку надёжной?"),
        criteria=[("cause", "Строка фиксируется позже, чем выгрузка сдвинула водяной знак, а её updated_at — время "
                            "начала транзакции, то есть меньше знака; `>=` её уже не видит", 0.35),
                  ("fix", "Окно перекрытия: выгружать с wm − максимальная длительность транзакции (с запасом) и "
                          "убирать повторы по (id, updated_at) или идемпотентным MERGE; либо выгрузка по журналу "
                          "(логическая репликация/Debezium) вместо запроса по updated_at", 0.4),
                  ("control", "Контроль: сверка числа строк/контрольных сумм источника и хранилища за период, "
                              "алерт на расхождение, мониторинг длительности транзакций", 0.25)],
        strong="""now() в PostgreSQL возвращает время начала транзакции, поэтому строка с updated_at = 10:00:03 может
            стать видимой в 10:05, когда водяной знак уже ушёл на 10:04 — ни `>`, ни `>=` её не возьмут. Делаю окно
            перекрытия: каждый запуск читает с wm − 10 минут (больше самой долгой транзакции, с запасом), а повторы
            убираю по (id, updated_at) или загружаю через идемпотентный MERGE по ключу. Надёжнее перейти на выгрузку
            из журнала изменений (логическая репликация, Debezium): там порядок задаёт LSN фиксации, а не время в
            строке. Контроль — ежедневная сверка числа строк и контрольных сумм по периодам между источником и
            хранилищем с алертом и мониторинг длительности транзакций.""",
        medium="""Нужно брать строки с небольшим запасом по времени назад и удалять дубли при загрузке.""",
        weak="""Нужно запускать выгрузку чаще, тогда строки не будут теряться."""),
    "deletes": dict(
        text=("Из источника строки иногда физически удаляют (DELETE). Увидит ли это выгрузка по updated_at, что от "
              "этого сломается в хранилище и как это исправить?"),
        criteria=[("cause", "Удалённой строки нет в выборке, updated_at не меняется — выгрузка удаление не видит, "
                            "в хранилище строка остаётся «живой»", 0.35),
                  ("options", "Варианты: мягкое удаление (флаг deleted_at, который меняет updated_at), выгрузка по "
                              "журналу (CDC с событием удаления), периодическая сверка ключей источника и хранилища "
                              "с пометкой удалённых", 0.4),
                  ("tradeoffs", "Компромиссы: изменения в источнике и приложениях, нагрузка полной сверки, хранение "
                                "истории (SCD2, отметка удаления вместо удаления в хранилище)", 0.25)],
        strong="""Выгрузка по updated_at удаление не видит: строки просто нет в выборке, и в хранилище она остаётся
            активной — витрины считают удалённые заказы. Варианты: мягкое удаление в источнике (deleted_at, который
            обновляет updated_at, — выгрузка заберёт его как изменение); выгрузка по журналу изменений (Debezium
            даёт событие удаления); если менять источник нельзя — периодическая сверка множества ключей источника и
            хранилища с пометкой отсутствующих как удалённых. В хранилище удаление отражаю отметкой (is_deleted,
            valid_to в SCD2), а не физическим удалением, чтобы не терять историю. Компромиссы: мягкое удаление
            требует правок приложений, полная сверка нагружает источник — делаю её по партициям ночью.""",
        medium="""Удаления не попадут в выгрузку. Можно сделать мягкое удаление с флагом.""",
        weak="""Удаления не важны для хранилища, их можно игнорировать."""),
    "backfill": dict(
        text=("В трансформации нашли ошибку, и данные за прошлую неделю нужно перезагрузить из источника. Как "
              "провести повторную загрузку периода, не сломав состояние инкрементальной выгрузки и не создав "
              "дублей?"),
        criteria=[("state", "Повторная загрузка — отдельный запуск по явному диапазону дат, не трогающий "
                            "водяной знак ежедневной выгрузки (или знак восстанавливается после)", 0.35),
                  ("idempotency", "Идемпотентная запись: перезапись партиций периода целиком или MERGE по ключу, "
                                  "чтобы повторный запуск давал тот же результат", 0.4),
                  ("ops", "Проверка: сверка числа строк и сумм до/после, запуск по частям, предупреждение "
                          "потребителей витрин", 0.25)],
        strong="""Повторную загрузку запускаю как отдельную задачу с явным диапазоном (с понедельника по
            воскресенье) — она читает источник по updated_at в этих границах и НЕ меняет водяной знак ежедневной
            выгрузки, иначе следующий обычный запуск либо пропустит, либо повторит данные. Запись идемпотентная:
            перезаписываю партиции периода целиком (или MERGE по ключу и версии), поэтому повторный запуск даёт тот
            же результат. Перед запуском сохраняю контрольные числа (строки, суммы по дням), после — сверяю;
            загружаю по дню, чтобы откатить частично; потребителей витрин предупреждаю о пересчёте.""",
        medium="""Сбросить водяной знак на начало недели и запустить выгрузку заново, дубли удалить.""",
        weak="""Запустить обычную выгрузку ещё раз — она сама подтянет нужные данные."""),
}


def _ts(day, sec):
    return f"2026-10-{day:02d} {10 + sec // 3600:02d}:{(sec // 60) % 60:02d}:{sec % 60:02d}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, _tbl = rng.choice(CTX)
    code = _code(None)
    for _ in range(2000):
        day = rng.randint(1, 10)
        s0 = rng.randint(0, 3000)
        ids = rng.sample(range(10, 99), 4)
        a, b, c, d = ids
        t1, t2, t3 = _ts(day, s0), _ts(day, s0 + rng.randint(2, 40)), _ts(day, s0 + rng.randint(60, 200))
        r1 = [{"id": a, "updated_at": t1}, {"id": b, "updated_at": t2}]
        bug = [r1, r1 + [{"id": c, "updated_at": t2}]]
        later = [r1, r1 + [{"id": c, "updated_at": t3}]]
        upd = [r1, [{"id": a, "updated_at": t3}, {"id": b, "updated_at": t2}]]
        same = [r1, r1]
        three = [r1, r1 + [{"id": c, "updated_at": t2}], r1 + [{"id": c, "updated_at": t2}, {"id": d, "updated_at": t3}]]
        scen = [bug, later, upd, same]
        if _sim(None, bug) == _ref(bug) or any(_sim(None, s) != _ref(s) for s in scen[1:]):
            continue
        t2set = scen + [three]
        if all(_sim("pairs", s) == _ref(s) for s in t2set) and \
                all(any(_sim(f, s) != _ref(s) for s in t2set) for f in ("ge", "ids", "last")):
            break

    def txt(name, s):
        def rows(snap):
            return ", ".join(f"id {r['id']} ({r['updated_at'][11:]})" for r in snap)
        base = f"1-й запуск видит: {rows(s[0])}. 2-й запуск видит: {rows(s[1])}"
        return base + {"bug": f" — строку id {c} зафиксировали после 1-го запуска",
                       "later": f" — строку id {c} зафиксировали после 1-го запуска",
                       "upd": f" — строку id {a} изменили после 1-го запуска", "same": " — новых изменений нет"}[name]
    names = ["bug", "later", "upd", "same"]
    texts = [txt(n, s) for n, s in zip(names, scen)]
    opts1, key1 = make_options(rng, (texts[0], None), [(t, None) for t in texts[1:]], step=1)
    by_text = dict(zip(texts, scen))
    checks = []
    for o in opts1:
        sc = by_text[o.text]
        checks.append(Check(name=f"step1:{o.id}", runner="python", program=_prog(code, sc),
                            expect="stdout_differs" if o.id == key1 else "stdout_equals", expected_stdout=_ref(sc)))
    opts2, key2 = make_options(rng, (LABEL["pairs"], _code("pairs")),
                               [(LABEL[k], _code(k)) for k in ("ge", "ids", "last")], step=2)
    for o in opts2:
        # каждый сценарий — отдельная программа: состояние не должно переходить между ними
        prog = "\n".join([f"# сценарий {i + 1}\n" + _prog(o.code, s) for i, s in enumerate(t2set)])
        checks.append(Check(name=f"step2:{o.id}", runner="python", program=prog,
                            expect="stdout_equals" if o.id == key2 else "stdout_differs",
                            expected_stdout="\n".join(_ref(s) for s in t2set), embeds_display_code=False))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    stem = (f"Ежечасная инкрементальная выгрузка «{ctx}» берёт из источника строки, изменённые после прошлого "
            "запуска, и дописывает их в журнал версий хранилища: каждая версия строки (id, updated_at) должна "
            "попасть туда ровно один раз. updated_at хранится с точностью до секунды; состояние `state` сохраняется "
            "между запусками. Сверка показала, что часть версий в хранилище так и не появилась.")
    steps = ob3_steps(
        "Шаг 1. Воспроизведите дефект: в каком сценарии из двух запусков версия строки будет потеряна?",
        "Шаг 2. Выберите исправление, после которого каждая версия попадает в хранилище ровно один раз при любой "
        "последовательности запусков (новые фиксации получают updated_at не меньше водяного знака).",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    expl = (f"После 1-го запуска wm = {t2}. Строка id {c} с тем же updated_at зафиксирована позже и строгим `>` "
            "отбрасывается навсегда. `>=` без защиты повторяет граничные строки на каждом запуске; пропуск по id "
            "теряет новые версии уже выгруженных строк; память только о последнем пакете снова выгружает граничные "
            f"строки на третьем запуске. Шаг 3 — «{cond_name}».")
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"}, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2, answer_key=ak,
                         rubric=rubric, context=ctx, verification="execution", checks=checks, steps=steps,
                         defect_type="strict_watermark_boundary", params={"condition": cond_name, "t2": t2})
