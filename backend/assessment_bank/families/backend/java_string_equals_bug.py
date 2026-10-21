"""backend.java.string_equals_bug — find_bug: сравнение строк через `==` вместо `equals`.

Небольшой класс загружает записи «ключ;значение» из текста (как из файла или запроса) и отвечает на вопрос
о значении — роль пользователя, статус заказа, уровень записи журнала. Сравнение `role == "admin"` сравнивает
ссылки: литерал из пула строк и строка, собранная при разборе, — разные объекты, и метод всегда отвечает
`false`, хотя в модульном тесте с литералами всё «работало». Один подтип дефекта; варьируются контекст,
имена, разделитель, порядок методов и служебные строки; строка дефекта не постоянна. Ключ однозначен:
в коде ровно одно сравнение строк.
Проверка исполнением (javac + JVM): данные собираются во время выполнения (разбор строки), проверяются
и положительный, и отрицательный случай — поэтому «всегда true» тоже не проходит.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.java.string_equals_bug"

# (контекст, классы, [имя поля ключа], [имя поля значения], метод-вопрос, искомое значение, прочие значения,
#  описание предиката, примеры ключей)
CONTEXTS = [
    ("права доступа", ["RoleGuard", "AccessTable"], ["login", "user"], ["role", "level"], ["isAdmin", "canManage"],
     "admin", ["viewer", "editor", "guest"], "пользователь с ролью `admin`", ["ivan", "olga", "petr", "anna"]),
    ("статусы заказов", ["OrderBook", "OrderIndex"], ["orderId", "number"], ["status", "state"], ["isPaid", "paid"],
     "paid", ["new", "shipped", "cancelled"], "заказ в статусе `paid`", ["A-17", "A-23", "B-05", "C-41"]),
    ("журнал приложения", ["LogIndex", "LevelTable"], ["source", "logger"], ["level", "severity"], ["isError", "hasErrors"],
     "ERROR", ["INFO", "WARN", "DEBUG"], "источник с уровнем `ERROR`", ["auth", "billing", "search", "mailer"]),
    ("валюты счетов", ["AccountBook", "CurrencyTable"], ["account", "iban"], ["currency", "code"], ["isRub", "inRubles"],
     "RUB", ["USD", "EUR", "KZT"], "счёт в валюте `RUB`", ["acc-1", "acc-7", "acc-9", "acc-12"]),
    ("каналы уведомлений", ["ChannelTable", "NotifyIndex"], ["userId", "member"], ["channel", "transport"],
     ["bySms", "wantsSms"], "sms", ["email", "push", "none"], "пользователь с каналом `sms`", ["u1", "u2", "u7", "u9"]),
]
SEPARATORS = [";", ",", "|"]


def _code(cls: str, kf: str, vf: str, method: str, target: str, sep: str, buggy: bool,
          order: list[str], with_size: bool, with_has: bool, note: str, split_var: str) -> tuple[str, int]:
    cmp = f'return {vf} == "{target}";' if buggy else f'return "{target}".equals({vf});'
    load = [f"    void load(String text) {{",
            f"        for (String line : text.split(\"\\n\")) {{",
            f"            String[] {split_var} = line.split(\"\\\\{sep}\");" if sep == "|" else
            f"            String[] {split_var} = line.split(\"{sep}\");",
            f"            if ({split_var}.length == 2) {{",
            f"                {vf}s.put({split_var}[0].trim(), {split_var}[1].trim());",
            "            }", "        }", "    }", ""]
    ask = [f"    boolean {method}(String {kf}) {{", f"        String {vf} = {vf}s.get({kf});",
           f"        {cmp}", "    }", ""]
    size = [f"    int size() {{", f"        return {vf}s.size();", "    }", ""] if with_size else []
    has = [f"    boolean has(String {kf}) {{", f"        return {vf}s.containsKey({kf});", "    }", ""] if with_has else []
    blocks = {"load": load, "ask": ask, "size": size, "has": has}
    body = [f"    private final Map<String, String> {vf}s = new HashMap<>();", ""]
    for m in order:
        body += blocks[m]
    while body and body[-1] == "":
        body.pop()
    lines = ["import java.util.HashMap;", "import java.util.Map;", ""] + ([note] if note else []) + \
            [f"final class {cls} {{"] + body + ["}"]
    key = next(i for i, l in enumerate(lines, 1) if l.strip() == cmp)
    return "\n".join(lines) + "\n", key


def _harness(code: str, cls: str, method: str, sep: str, rows: list[tuple[str, str]], yes: str, no: str) -> str:
    # данные собираются во время выполнения: строки не из пула литералов, как при чтении файла/запроса
    parts = " + \"\\n\" + ".join(f'"{k}{sep}" + new String("{v}".toCharArray())' for k, v in rows)
    return (code + "\n"
            "public class Main {\n    public static void main(String[] args) {\n"
            f"        {cls} t = new {cls}();\n"
            f"        t.load({parts});\n"
            f"        boolean pass = t.{method}(\"{yes}\") && !t.{method}(\"{no}\");\n"
            "        System.out.println(pass ? \"RESULT: PASS\" : \"RESULT: FAIL\");\n"
            "    }\n}\n")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, classes, kfs, vfs, methods, target, others, pred, keys = rng.choice(CONTEXTS)
    cls, kf, vf, method = rng.choice(classes), rng.choice(kfs), rng.choice(vfs), rng.choice(methods)
    sep = rng.choice(SEPARATORS)
    order = ["load", "ask", "size", "has"]
    rng.shuffle(order)
    with_size, with_has = rng.random() < 0.5, rng.random() < 0.5
    order = [m for m in order if (m != "size" or with_size) and (m != "has" or with_has)]
    split_var = rng.choice(["parts", "cols", "kv", "pair"])
    note = rng.choice(["", f"// {ctx[0].upper() + ctx[1:]}: таблица загружается из файла при старте",
                       "// Записи приходят из внешнего сервиса строками", "// Поиск по ключу, значение — строка"])
    buggy, key = _code(cls, kf, vf, method, target, sep, True, order, with_size, with_has, note, split_var)
    fixed, _ = _code(cls, kf, vf, method, target, sep, False, order, with_size, with_has, note, split_var)
    assert changed_lines(buggy, fixed) == {key}
    ks = rng.sample(keys, 3)
    yes, no = ks[0], ks[1]
    rows = [(yes, target), (no, rng.choice(others)), (ks[2], rng.choice(others))]
    rng.shuffle(rows)
    checks = [Check(name="buggy_fails", runner="java", program=_harness(buggy, cls, method, sep, rows, yes, no),
                    expect="fail"),
              Check(name="fixed_passes", runner="java", program=_harness(fixed, cls, method, sep, rows, yes, no),
                    expect="pass", embeds_display_code=False)]
    stem = (f"Класс `{cls}` ({ctx}) загружает записи вида `{kf}{sep}{vf}` из текста и по `{kf}` отвечает "
            f"на вопрос «это {pred}?» — метод `{method}`. В модульном тесте, где значения заданы литералами в коде, метод "
            f"работал; после загрузки из настоящего файла он возвращает `false` для всех записей, хотя значения "
            f"в файле верные. Укажите номер строки, которую достаточно исправить одной правкой, чтобы ошибка ушла.")
    why = (f"Строка {key}: `==` сравнивает ссылки, а не содержимое. Литерал \"{target}\" лежит в пуле строк, а строка "
           f"из `split`/`trim` создана при разборе — это другой объект, и сравнение всегда ложно (в тесте с литералами "
           f"совпадение ссылок было случайным). Исправление — `\"{target}\".equals({vf})` "
           f"(литерал слева защищает от null).")
    ak = AnswerKey(kind="line", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="string_reference_equality",
                         display_code_note="Показанный класс исполняется дословно вместе с классом Main, который "
                                           "загружает строки, собранные во время выполнения, и проверяет "
                                           "положительный и отрицательный случай.",
                         params={"fixed_code": fixed, "order": order, "sep": sep})
