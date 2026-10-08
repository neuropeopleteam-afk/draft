"""backend.java.session_registry_leak_bug — find_bug: утечка памяти через долгоживущую коллекцию.

Реестр (сессии, соединения, задания) хранит объекты в Map. При закрытии объект инвалидируется, но из
Map не удаляется (`get` вместо `remove`) — закрытые объекты остаются достижимыми от корня, GC их не
собирает, heap растёт. Один подтип; варьируются контекст и имена, тип Map (HashMap/ConcurrentHashMap/
LinkedHashMap), наличие счётчика и метода поиска, порядок методов — позиция дефектной строки не постоянна.
Проверка исполнением (javac + JVM): после открытия и закрытия N объектов реестр должен быть пуст, а все
объекты — инвалидированы.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.java.session_registry_leak_bug"

# (контекст, реестр, элемент, поле-владелец, open, close, флаг)
CONTEXTS = [("веб-сервер", "SessionRegistry", "Session", "user", "open", "close", "valid"),
            ("пул соединений", "ConnectionTracker", "Connection", "endpoint", "acquire", "release", "open"),
            ("планировщик", "JobRegistry", "Job", "owner", "submit", "finish", "running"),
            ("чат", "RoomRegistry", "Room", "topic", "create", "dispose", "active"),
            ("загрузки", "UploadTracker", "Upload", "filename", "begin", "complete", "inProgress")]
MAPS = ["HashMap", "ConcurrentHashMap", "LinkedHashMap"]


def _item(cls: str, owner: str, flag: str, buf_kb: int) -> list[str]:
    return [f"final class {cls} {{", "    final String id;", f"    final String {owner};",
            f"    private final byte[] buffer = new byte[{buf_kb} * 1024];", f"    private boolean {flag} = true;", "",
            f"    {cls}(String id, String {owner}) {{", "        this.id = id;", f"        this.{owner} = {owner};", "    }", "",
            f"    boolean is{flag[0].upper()}{flag[1:]}() {{", f"        return {flag};", "    }", "",
            "    void invalidate() {", f"        {flag} = false;", "    }", "}", ""]


def _registry(c, buggy: bool, map_type: str, counter: bool, finder: bool, order: list[str]) -> str:
    _ctx, reg, cls, owner, op, cl, _flag = c
    field_name = cls.lower() + "s"
    fields = [f"    private final Map<String, {cls}> {field_name} = new {map_type}<>();"]
    if counter:
        fields.append("    private int closedCount = 0;")
    fields.append("")
    open_m = [f"    {cls} {op}(String id, String {owner}) {{", f"        {cls} s = new {cls}(id, {owner});",
              f"        {field_name}.put(id, s);", "        return s;", "    }", ""]
    close_m = [f"    void {cl}(String id) {{",
               f"        {cls} s = {field_name}.{'get' if buggy else 'remove'}(id);",
               "        if (s != null) {", "            s.invalidate();"] + \
              (["            closedCount++;"] if counter else []) + ["        }", "    }", ""]
    find_m = [f"    {cls} find(String id) {{", f"        return {field_name}.get(id);", "    }", ""] if finder else []
    active_m = ["    int active() {", f"        return {field_name}.size();", "    }", ""]
    count_m = ["    int closed() {", "        return closedCount;", "    }", ""] if counter else []
    blocks = {"open": open_m, "close": close_m, "find": find_m, "active": active_m, "closed": count_m}
    body = list(fields)
    for m in order:
        body += blocks[m]
    while body and body[-1] == "":
        body.pop()
    return "\n".join([f"final class {reg} {{"] + body + ["}"]) + "\n"


def _harness(code: str, c, n: int, counter: bool) -> str:
    _ctx, reg, cls, _owner, op, cl, flag = c
    getter = f"is{flag[0].upper()}{flag[1:]}"
    extra = f" && r.closed() == {n}" if counter else ""
    return ("import java.util.*;\nimport java.util.concurrent.*;\n\n" + code + "\n"
            "public class Main {\n    public static void main(String[] args) {\n"
            f"        {reg} r = new {reg}();\n        List<{cls}> all = new ArrayList<>();\n"
            f"        for (int i = 0; i < {n}; i++) all.add(r.{op}(\"id-\" + i, \"owner-\" + (i % 7)));\n"
            f"        for (int i = 0; i < {n}; i++) r.{cl}(\"id-\" + i);\n"
            f"        boolean invalidated = all.stream().noneMatch({cls}::{getter});\n"
            f"        boolean pass = invalidated && r.active() == 0{extra};\n"
            "        System.out.println(pass ? \"RESULT: PASS\" : \"RESULT: FAIL active=\" + r.active());\n"
            "    }\n}\n")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    c = rng.choice(CONTEXTS)
    ctx, reg, cls, owner, op, cl, flag = c
    map_type = rng.choice(MAPS)
    counter = rng.random() < 0.5
    finder = rng.random() < 0.5
    buf_kb = rng.choice([16, 32, 64, 128])
    order = ["open", "close", "find", "active", "closed"]
    rng.shuffle(order)
    order = [m for m in order if (m != "find" or finder) and (m != "closed" or counter)]
    item = _item(cls, owner, flag, buf_kb)
    buggy = "import java.util.*;\nimport java.util.concurrent.*;\n\n" + "\n".join(item) + _registry(c, True, map_type, counter, finder, order)
    fixed = "import java.util.*;\nimport java.util.concurrent.*;\n\n" + "\n".join(item) + _registry(c, False, map_type, counter, finder, order)
    ch = changed_lines(buggy, fixed)
    assert len(ch) == 1
    key = next(iter(ch))
    n = rng.choice([50, 100, 200])
    body_b = buggy.replace("import java.util.*;\nimport java.util.concurrent.*;\n\n", "", 1)
    body_f = fixed.replace("import java.util.*;\nimport java.util.concurrent.*;\n\n", "", 1)
    checks = [Check(name="buggy_fails", runner="java", program=_harness(body_b, c, n, counter), expect="fail",
                    embeds_display_code=False),
              Check(name="fixed_passes", runner="java", program=_harness(body_f, c, n, counter), expect="pass",
                    embeds_display_code=False)]
    hours = rng.choice([6, 12, 24, 36])
    stem = (f"Java, {ctx}. Через {hours} ч работы сервис падает с OutOfMemoryError. В heap dump — сотни тысяч объектов "
            f"`{cls}` с `{flag} = false`, все удерживаются полем `{reg}.{cls.lower()}s`; каждый держит буфер "
            f"{buf_kb} КБ. Укажите номер строки с ошибкой.")
    why = (f"Строка {key}: `{cl}` получает объект через `get`, инвалидирует его, но из Map не удаляет. Закрытые "
           f"объекты остаются достижимыми от долгоживущего реестра, и сборщик мусора не вправе их освободить — "
           f"классическая утечка через коллекцию. Нужно `{cls.lower()}s.remove(id)`: ссылка исчезает, объект "
           f"вместе с буфером становится недостижимым.")
    ak = AnswerKey(kind="line", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="collection_leak_get_not_remove",
                         display_code_note="Показанные классы исполняются с классом Main, который открывает и "
                                           "закрывает N объектов и проверяет, что реестр пуст.",
                         params={"fixed_code": fixed, "map": map_type, "order": order})
