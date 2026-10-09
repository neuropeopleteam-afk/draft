"""backend.java.session_registry_leak_fix — choose_fix: утечка памяти через долгоживущую Map-реестр.

Версия 2 семейства `backend.java.session_registry_leak_bug` (find_bug, выведено из выдачи 07.10: дефект — пропуск
`remove`, а формат просит «номер строки с ошибкой», поэтому ключ был плохо определён). Теперь формат choose_fix:
показан реестр (сессии, соединения, задания) с методом закрытия, который получает объект через `get`, инвалидирует
его, но из `Map` не удаляет; нужно выбрать исправление поля и метода закрытия. Состав вариантов фиксирован:
  * верный — `remove(id)` вместо `get(id)`: запись исчезает, объект инвалидируется;
  * set_local_null — после инвалидации локальной переменной присваивается `null`: ссылка из Map остаётся;
  * remove_by_object — `map.remove(s)` с объектом вместо ключа: `Map.remove(Object)` компилируется, но ключа-объекта
    нет, запись не удаляется;
  * weak — `WeakHashMap` и прежнее закрытие: значение (сессия) хранит ссылку на свой ключ (`id`), поэтому ключ
    никогда не становится слабо достижимым и запись не очищается (проверено исполнением: после `System.gc()` записи
    остаются).
Проверка исполнением (javac + JVM): открывается N объектов, закрывается первая половина — в реестре остаётся ровно
вторая половина (активные объекты действительны), затем закрывается остальное — реестр пуст, все объекты
инвалидированы. Верный вариант проходит, остальные — нет.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.java.session_registry_leak_fix"

# (контекст, реестр, элемент, поле-владелец, open, close, флаг)
CONTEXTS = [("веб-сервер", "SessionRegistry", "Session", "user", "open", "close", "valid"),
            ("пул соединений", "ConnectionTracker", "Connection", "endpoint", "acquire", "release", "open"),
            ("планировщик", "JobRegistry", "Job", "owner", "submit", "finish", "running"),
            ("чат", "RoomRegistry", "Room", "topic", "create", "dispose", "active"),
            ("загрузки", "UploadTracker", "Upload", "filename", "begin", "complete", "inProgress")]
MAPS = ["HashMap", "ConcurrentHashMap", "LinkedHashMap"]
IMPORTS = "import java.util.*;\nimport java.util.concurrent.*;\n\n"
NAMES = ["good", "set_local_null", "remove_by_object", "weak"]
LABEL = "Заменить поле реестра и метод закрытия на:"


def _item(cls: str, owner: str, flag: str, buf_kb: int) -> list[str]:
    return [f"final class {cls} {{", "    final String id;", f"    final String {owner};",
            f"    private final byte[] buffer = new byte[{buf_kb} * 1024];", f"    private boolean {flag} = true;", "",
            f"    {cls}(String id, String {owner}) {{", "        this.id = id;", f"        this.{owner} = {owner};", "    }", "",
            f"    boolean is{flag[0].upper()}{flag[1:]}() {{", f"        return {flag};", "    }", "",
            "    void invalidate() {", f"        {flag} = false;", "    }", "}", ""]


def _snippet(c, kind: str, map_type: str, counter: bool) -> list[str]:
    """Поле реестра и метод закрытия — то, что показывается в вариантах и подставляется в код реестра."""
    _ctx, _reg, cls, _owner, _op, cl, _flag = c
    fld = cls.lower() + "s"
    mt = "WeakHashMap" if kind == "weak" else map_type
    field = [f"    private final Map<String, {cls}> {fld} = new {mt}<>();"]
    if counter:
        field.append("    private int closedCount = 0;")
    lookup = "remove" if kind == "good" else "get"
    inner = ["            s.invalidate();"]
    if counter:
        inner.append("            closedCount++;")
    if kind == "set_local_null":
        inner.append("            s = null;")
    if kind == "remove_by_object":
        inner.append(f"            {fld}.remove(s);")
    close = [f"    void {cl}(String id) {{", f"        {cls} s = {fld}.{lookup}(id);", "        if (s != null) {"] + inner + \
            ["        }", "    }"]
    return field + [""] + close


def _registry(c, kind: str, map_type: str, counter: bool, finder: bool, order: list[str]) -> str:
    _ctx, reg, cls, owner, op, cl, _flag = c
    fld = cls.lower() + "s"
    snip = _snippet(c, kind, map_type, counter)
    cut = snip.index("")
    fields, close_m = snip[:cut], snip[cut + 1:] + [""]
    open_m = [f"    {cls} {op}(String id, String {owner}) {{", f"        {cls} s = new {cls}(id, {owner});",
              f"        {fld}.put(id, s);", "        return s;", "    }", ""]
    find_m = [f"    {cls} find(String id) {{", f"        return {fld}.get(id);", "    }", ""] if finder else []
    active_m = ["    int active() {", f"        return {fld}.size();", "    }", ""]
    count_m = ["    int closed() {", "        return closedCount;", "    }", ""] if counter else []
    blocks = {"open": open_m, "close": close_m, "find": find_m, "active": active_m, "closed": count_m}
    body = list(fields) + [""]
    for m in order:
        body += blocks[m]
    while body and body[-1] == "":
        body.pop()
    return "\n".join([f"final class {reg} {{"] + body + ["}"]) + "\n"


def _harness(code: str, c, n: int, counter: bool) -> str:
    _ctx, reg, cls, _owner, op, cl, flag = c
    getter = f"is{flag[0].upper()}{flag[1:]}"
    half = n // 2
    extra = f" && r.closed() == {n}" if counter else ""
    return (IMPORTS + code + "\n"
            "public class Main {\n    public static void main(String[] args) {\n"
            f"        {reg} r = new {reg}();\n        List<{cls}> all = new ArrayList<>();\n"
            f"        for (int i = 0; i < {n}; i++) all.add(r.{op}(\"id-\" + i, \"owner-\" + (i % 7)));\n"
            f"        for (int i = 0; i < {half}; i++) r.{cl}(\"id-\" + i);\n"
            f"        boolean half = r.active() == {n - half}\n"
            f"                && all.subList(0, {half}).stream().noneMatch({cls}::{getter})\n"
            f"                && all.subList({half}, {n}).stream().allMatch({cls}::{getter});\n"
            f"        for (int i = {half}; i < {n}; i++) r.{cl}(\"id-\" + i);\n"
            f"        boolean done = r.active() == 0 && all.stream().noneMatch({cls}::{getter}){extra};\n"
            "        System.out.println(half && done ? \"RESULT: PASS\" : \"RESULT: FAIL active=\" + r.active());\n"
            "    }\n}\n")


def _weak_probe(code: str, c, n: int) -> str:
    """Записи WeakHashMap не очищаются: значение держит свой ключ (проверка «запись осталась» — PASS)."""
    _ctx, reg, _cls, _owner, op, _cl, _flag = c
    return (IMPORTS + code + "\n"
            "public class Main {\n    public static void main(String[] args) throws Exception {\n"
            f"        {reg} r = new {reg}();\n"
            f"        for (int i = 0; i < {n}; i++) r.{op}(\"id-\" + i, \"owner-\" + (i % 7));\n"
            "        System.gc();\n        Thread.sleep(200);\n        System.gc();\n"
            f"        System.out.println(r.active() == {n} ? \"RESULT: PASS\" : \"RESULT: FAIL active=\" + r.active());\n"
            "    }\n}\n")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    c = rng.choice(CONTEXTS)
    ctx, reg, cls, owner, op, cl, flag = c
    fld = cls.lower() + "s"
    map_type = rng.choice(MAPS)
    counter = rng.random() < 0.5
    finder = rng.random() < 0.5
    buf_kb = rng.choice([16, 32, 64, 128])
    order = ["open", "close", "find", "active", "closed"]
    rng.shuffle(order)
    order = [m for m in order if (m != "find" or finder) and (m != "closed" or counter)]
    item = _item(cls, owner, flag, buf_kb)
    buggy = IMPORTS + "\n".join(item) + _registry(c, "buggy", map_type, counter, finder, order)
    shown = buggy.replace(IMPORTS, "", 1)
    n = rng.choice([50, 100, 200])
    texts = {k: "\n".join(_snippet(c, k, map_type, counter)) for k in NAMES}
    opts, key = make_options(rng, (LABEL, texts["good"]), [(LABEL, texts[k]) for k in NAMES[1:]])
    kind_of = {o.code: k for k, o in ((k, next(o for o in opts if o.code == texts[k])) for k in NAMES)}
    checks = [Check(name="original_fails", runner="java", program=_harness(shown, c, n, counter), expect="fail",
                    embeds_display_code=False)]
    for o in opts:
        k = kind_of[o.code]
        src = "\n".join(item) + _registry(c, k, map_type, counter, finder, order)
        checks.append(Check(name=f"option:{o.id}", runner="java", program=_harness(src, c, n, counter),
                            expect="pass" if o.id == key else "fail", embeds_display_code=False))
        if k == "weak":
            checks.append(Check(name="weak_entries_stay", runner="java", program=_weak_probe(src, c, n),
                                expect="pass", embeds_display_code=False))
    hours = rng.choice([6, 12, 24, 36])
    stem = (f"Java, {ctx}. Через {hours} ч работы сервис падает с OutOfMemoryError. В heap dump — сотни тысяч объектов "
            f"`{cls}` с `{flag} = false`, все удерживаются полем `{reg}.{fld}`; каждый держит буфер {buf_kb} КБ. "
            f"Какое исправление поля и метода `{cl}` устраняет утечку, если закрытый объект должен стать "
            f"недействительным для всех, кто держит на него ссылку, а записи ещё не закрытых объектов должны остаться "
            f"в реестре?")
    why_other = {"set_local_null": f"`s = null` обнуляет только локальную переменную: запись в `{fld}` остаётся, "
                                   f"объект достижим от реестра",
                 "remove_by_object": f"`Map.remove(Object)` принимает ключ, а не значение: вызов с объектом "
                                     f"`{cls}` компилируется, но записи не находит и ничего не удаляет",
                 "weak": f"в `WeakHashMap` значение хранится жёстко и ссылается на свой ключ (`{cls}.id`), поэтому "
                         f"ключ не становится слабо достижимым — записи остаются, а такой реестр ещё и не "
                         f"потокобезопасен"}
    sel = [k for k in NAMES[1:]]
    why = (f"`{cl}` получает объект через `get`, инвалидирует его, но запись из Map не удаляет: закрытые объекты "
           f"остаются достижимыми от долгоживущего реестра, и сборщик мусора не вправе их освободить. Верно — "
           f"`{fld}.remove(id)`: метод возвращает значение и убирает запись, объект инвалидируется, а остальные записи "
           f"не затрагиваются. Не подходят: " + "; ".join(why_other[k] for k in sel) + ".")
    ak = AnswerKey(kind="option", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=shown, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="collection_leak_get_not_remove",
                         display_code_note="Каждый вариант подставляется в показанные классы и исполняется с классом "
                                           "Main: открывает и закрывает N объектов и проверяет состояние реестра; "
                                           "для WeakHashMap отдельно подтверждено, что записи не очищаются.",
                         params={"map": map_type, "order": order, "distractors": sel})
