"""backend.java.list_remove_loop_fix — choose_fix: удаление элементов из ArrayList в цикле по индексу.

Метод удаляет из списка элементы по признаку (нет на складе, выполнено, прочитано) в цикле
`for (int i = 0; i < list.size(); i++) … list.remove(i)`. После удаления элементы сдвигаются влево, индекс
растёт — следующий элемент пропускается: когда подходящие записи идут подряд, часть остаётся в списке.
Симптом тихий (исключения нет), поэтому семейство проверяет понимание механики ArrayList, а не чтение
трассировки. Состав вариантов фиксирован (урок калибровки 05.10–07.10 — ключ должен быть однозначен):
  * верный — Iterator и it.remove();
  * foreach_remove — for-each и list.remove(x): ConcurrentModificationException;
  * remove_by_object — тот же цикл по индексу, но remove(list.get(i)): сдвиг и пропуск остаются;
  * reassign_param — собрать оставшиеся в новый список и присвоить параметру: список вызывающего не меняется.
Проверка исполнением (javac + JVM): каждый вариант запускается на списке, где подходящие элементы идут
подряд; верный даёт ожидаемый остаток, остальные — нет (исключение считается провалом).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.java.list_remove_loop_fix"

# (контекст, класс, метод, запись, поле-признак, «удаляем те, у кого признак = flag», описание признака,
#  шаблон ключа записи)
CONTEXTS = [
    ("корзина магазина", "CartCleaner", "dropOutOfStock", "Line", "inStock", False, "позиции, которых нет на складе", "SKU-{n}"),
    ("список задач", "TaskBoard", "archiveDone", "Task", "done", True, "выполненные задачи", "T-{n}"),
    ("входящие уведомления", "Inbox", "clearRead", "Note", "read", True, "прочитанные уведомления", "n{n}"),
    ("подписки", "Subscriptions", "dropExpired", "Plan", "expired", True, "истёкшие подписки", "plan-{n}"),
    ("очередь загрузок", "DownloadQueue", "removeFailed", "Job", "failed", True, "задания с ошибкой", "job-{n}"),
]
VARS = ["items", "list", "entries", "records"]
LOOP_VARS = ["x", "e", "it", "cur"]


def _cond(rec_var: str, field: str, flag: bool) -> str:
    return f"{rec_var}.{field}()" if flag else f"!{rec_var}.{field}()"


def _method(kind: str, m: str, rec: str, lst: str, field: str, flag: bool, lv: str) -> str:
    """Тело метода (показанный код и варианты ответа) — 5–8 строк."""
    if kind == "buggy":
        return "\n".join([f"    static void {m}(List<{rec}> {lst}) {{",
                          f"        for (int i = 0; i < {lst}.size(); i++) {{",
                          f"            if ({_cond(f'{lst}.get(i)', field, flag)}) {{",
                          f"                {lst}.remove(i);",
                          "            }", "        }", "    }"])
    if kind == "correct":
        return "\n".join([f"    static void {m}(List<{rec}> {lst}) {{",
                          f"        Iterator<{rec}> iter = {lst}.iterator();",
                          "        while (iter.hasNext()) {",
                          f"            if ({_cond('iter.next()', field, flag)}) {{",
                          "                iter.remove();",
                          "            }", "        }", "    }"])
    if kind == "foreach_remove":
        return "\n".join([f"    static void {m}(List<{rec}> {lst}) {{",
                          f"        for ({rec} {lv} : {lst}) {{",
                          f"            if ({_cond(lv, field, flag)}) {{",
                          f"                {lst}.remove({lv});",
                          "            }", "        }", "    }"])
    if kind == "remove_by_object":
        return "\n".join([f"    static void {m}(List<{rec}> {lst}) {{",
                          f"        for (int i = 0; i < {lst}.size(); i++) {{",
                          f"            {rec} {lv} = {lst}.get(i);",
                          f"            if ({_cond(lv, field, flag)}) {{",
                          f"                {lst}.remove({lv});",
                          "            }", "        }", "    }"])
    if kind == "reassign_param":
        return "\n".join([f"    static void {m}(List<{rec}> {lst}) {{",
                          f"        List<{rec}> kept = new ArrayList<>();",
                          f"        for ({rec} {lv} : {lst}) {{",
                          f"            if ({_cond(lv, field, not flag)}) {{",
                          f"                kept.add({lv});",
                          "            }", "        }",
                          f"        {lst} = kept;", "    }"])
    raise ValueError(kind)


def _unit(cls: str, rec: str, field: str, method_src: str) -> str:
    return "\n".join(["import java.util.ArrayList;", "import java.util.Iterator;", "import java.util.List;", "",
                      f"record {rec}(String id, boolean {field}) {{}}", "", f"final class {cls} {{", method_src, "}"]) + "\n"


def _harness(unit: str, cls: str, m: str, rec: str, field: str, rows: list[tuple[str, bool]],
             expected_ids: list[str]) -> str:
    items = ", ".join(f'new {rec}("{i}", {str(f).lower()})' for i, f in rows)
    exp = ", ".join(f'"{i}"' for i in expected_ids)
    return (unit + "\n"
            "public class Main {\n    public static void main(String[] args) {\n"
            f"        List<{rec}> data = new ArrayList<>(List.of({items}));\n"
            f"        List<String> expected = List.of({exp});\n"
            "        try {\n"
            f"            {cls}.{m}(data);\n"
            "        } catch (RuntimeException ex) {\n"
            "            System.out.println(\"RESULT: FAIL \" + ex.getClass().getSimpleName());\n"
            "            return;\n"
            "        }\n"
            "        List<String> ids = new ArrayList<>();\n"
            f"        for ({rec} r : data) ids.add(r.id());\n"
            "        System.out.println(ids.equals(expected) ? \"RESULT: PASS\" : \"RESULT: FAIL \" + ids);\n"
            "    }\n}\n")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, cls, m, rec, field, flag, what, key_tpl = rng.choice(CONTEXTS)
    lst, lv = rng.choice(VARS), rng.choice(LOOP_VARS)
    # данные: 6–8 записей, среди подходящих — хотя бы одна пара подряд (иначе цикл по индексу «случайно» прав)
    n = rng.randint(6, 8)
    while True:
        marks = [rng.random() < 0.5 for _ in range(n)]
        if 2 <= sum(marks) <= n - 2 and any(marks[i] and marks[i + 1] for i in range(n - 1)):
            break
    ids = [key_tpl.format(n=v) for v in sorted(rng.sample(range(10, 99), n))]
    rows = [(i, (mk if flag else not mk)) for i, mk in zip(ids, marks)]  # mk — «удалить»
    expected = [i for i, mk in zip(ids, marks) if not mk]
    names = ["correct", "foreach_remove", "remove_by_object", "reassign_param"]
    labels = {"correct": "Обход через Iterator, удаление iter.remove()",
              "foreach_remove": "Цикл for-each, удаление через " + f"{lst}.remove({lv})",
              "remove_by_object": "Тот же цикл по индексу, удаление по объекту " + f"{lst}.remove({lv})",
              "reassign_param": "Собрать оставшиеся в новый список и присвоить его параметру"}
    srcs = {k: _method(k, m, rec, lst, field, flag, lv) for k in names}
    buggy_m = _method("buggy", m, rec, lst, field, flag, lv)
    opts, key = make_options(rng, (labels["correct"], srcs["correct"]), [(labels[k], srcs[k]) for k in names[1:]])
    by_text = {o.text: o.id for o in opts}
    checks = [Check(name="original_fails", runner="java",
                    program=_harness(_unit(cls, rec, field, buggy_m), cls, m, rec, field, rows, expected), expect="fail")]
    for k in names:
        checks.append(Check(name=f"option:{by_text[labels[k]]}", runner="java",
                            program=_harness(_unit(cls, rec, field, srcs[k]), cls, m, rec, field, rows, expected),
                            expect="pass" if k == "correct" else "fail", embeds_display_code=False))
    code = _unit(cls, rec, field, buggy_m)
    # что оставит показанный цикл по индексу (сдвиг после remove, i++ перешагивает следующий элемент)
    left, i = list(zip(ids, marks)), 0
    while i < len(left):
        if left[i][1]:
            del left[i]
        i += 1
    to_remove = [i_ for i_, mk in zip(ids, marks) if mk]
    stem = (f"Метод `{cls}.{m}` ({ctx}) должен убрать из списка {what}. Исключений нет, но после вызова "
            f"часть таких записей остаётся в списке. Пример: список `{', '.join(ids)}`, убрать нужно "
            f"`{', '.join(to_remove)}`, а после вызова остаётся `{', '.join(i_ for i_, _ in left)}`. Какой вариант "
            f"метода корректен: удаляет все подходящие записи из переданного списка и сохраняет порядок остальных?")
    assert [i_ for i_, _ in left] != expected
    why = ("Верен обход через Iterator с iter.remove(): итератор знает о сдвиге и не пропускает элементы. "
           "В исходном коде после remove(i) элементы сдвигаются влево, а i++ перешагивает следующий — "
           "remove по объекту в том же цикле ничего не меняет. Удаление из списка внутри for-each ломает "
           "итератор — ConcurrentModificationException. Присвоение параметру нового списка меняет только "
           "локальную ссылку: список вызывающего остаётся прежним. Также верны обход с конца или removeIf.")
    ak = AnswerKey(kind="option", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="remove_in_index_loop",
                         display_code_note="Показанный код исполняется дословно вместе с классом Main, который "
                                           "передаёт список с подряд идущими подходящими записями и сравнивает "
                                           "остаток с ожидаемым; исключение считается провалом.",
                         params={"n": n, "n_remove": sum(marks), "flag": flag})
