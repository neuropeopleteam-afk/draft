"""Открытая книга: нормализация пути и проверка принадлежности каталогу."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng, ob3_steps, py_harness, rubric_from
from assessment_bank.schema import AnswerKey, Check
from ._support import CONTEXTS, SOURCES

FAMILY_ID = "security.files.path_containment_ob3"

CONDITIONS = {
    "links": {
        "text": "Теперь в дереве разрешены символьные ссылки. Почему простой нормализации "
                "строк недостаточно, как учесть конечную цель ссылки и что остаётся проверить при открытии?",
        "criteria": [("canonical", "Разрешает ссылки и проверяет конечный канонический путь относительно корня", 0.35),
                     ("race", "Учитывает подмену ссылки между проверкой и открытием; предлагает открытие относительно дескриптора каталога с ограничениями ОС", 0.4),
                     ("permissions", "Ограничивает запись в дерево, проверяет права на объект и добавляет тесты ссылок", 0.25)],
        "strong": "Канонизирую и корень, и цель через resolve, затем проверяю принадлежность по "
                  "компонентам пути, а не префиксу. Это обнаруживает ссылки за пределы дерева "
                  "на момент проверки, но не устраняет гонку между проверкой и открытием. "
                  "Для изменяемого дерева нужен платформенный безопасный механизм открытия "
                  "относительно дескриптора корневого каталога, запрещающий выход и нежелательные "
                  "ссылки; одной проверки O_NOFOLLOW только последнего компонента недостаточно. "
                  "Запись в дерево доступна лишь служебной роли. Право чтения конкретного объекта "
                  "проверяется отдельно. Тестирую ссылку внутрь, ссылку наружу и смену цели в пределах "
                  "контролируемого тестового окружения.",
        "medium": "Нужно resolve для корня и файла и relative_to для проверки, а также запрет "
                  "чтения файлов вне каталога. Отдельно проверю владельца файла и добавлю тесты ссылок.",
        "weak": "Достаточно убрать двойные разделители и сравнить первые символы пути.",
    },
    "tenant": {
        "text": "В одном корне теперь хранятся документы нескольких организаций. Достаточно ли "
                "проверки пути? Опишите привязку к организации и безопасную обработку отсутствующего файла.",
        "criteria": [("authorization", "Не смешивает проверку корня и авторизацию; tenant берёт из доверенной сессии", 0.4),
                     ("lookup", "Ищет объект по id вместе с tenant/owner, имя файла берёт из серверных метаданных", 0.35),
                     ("errors", "Не раскрывает чужие пути и наличие объектов; тестирует межорганизационный отказ", 0.25)],
        "strong": "Корень ограничивает файловую область, но не права на документы внутри неё. "
                  "Организацию беру из проверенной сессии, а не из параметра запроса. "
                  "Поиск метаданных ограничиваю парой object_id и tenant_id и необходимой ролью, "
                  "путь получаю из серверного отображения, затем проверяю файловые границы. "
                  "Для чужого и отсутствующего документа выбираю одинаковый внешний ответ "
                  "согласно политике сервиса, без полного пути. Внутренний аудит фиксирует "
                  "категорию отказа без содержимого документа. В тестах разделяю собственный, "
                  "чужой, отсутствующий документ и вложенный допустимый путь.",
        "medium": "Нужно отдельно проверить организацию владельца документа по сессии. "
                  "Проверка общего корня не запрещает читать чужие документы; тест нужен "
                  "для запроса документа другой организации.",
        "weak": "Если путь внутри общего каталога, любой вошедший пользователь может читать файл.",
    },
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    root = f"/demo/{rng.choice(['archive', 'records', 'reports', 'documents'])}_{rng.randint(10, 999)}"
    filename = f"report_{rng.randint(10, 900)}.txt"
    head = f"from pathlib import Path\nROOT = Path({root!r})\n\n"
    bad_body = """def allowed_path(name):
    root = ROOT.resolve()
    target = (root / name).resolve()
    if target == root:
        return None
    if str(target).startswith(str(root)):
        return str(target)
    return None"""
    good_body = """def allowed_path(name):
    root = ROOT.resolve()
    target = (root / name).resolve()
    if target == root:
        return None
    if root in target.parents:
        return str(target)
    return None"""
    wrong_parent = good_body.replace("root in target.parents", "target.parent == root")
    wrong_basename = good_body.replace("(root / name).resolve()", "(root / Path(name).name).resolve()")
    code = head + bad_body
    entries = [
        (root + "_backup/" + filename, None),
        (root + "/./././" + filename, root + "/" + filename),
        (root + "/drafts/" + filename, root + "/drafts/" + filename),
        (root + "/drafts//./" + filename, root + "/drafts/" + filename),
    ]
    text = lambda item: f"Имя: {item[0]!r}"
    opts1, key1 = make_options(rng, (text(entries[0]), None),
                               [(text(e), None) for e in entries[1:]], step=1)
    expected = {text(e): e for e in entries}
    fixes = [good_body, bad_body, wrong_parent, wrong_basename]
    opts2, key2 = make_options(rng, ("Заменить allowed_path:", fixes[0]),
                               [("Заменить allowed_path:", f) for f in fixes[1:]], step=2)
    checks = []
    for o in opts1:
        name, result = expected[o.text]
        checks.append(Check(name=f"step1:{o.id}", runner="python",
                            program=py_harness(code, f"assert allowed_path({name!r}) == {result!r}"),
                            expect="fail" if o.id == key1 else "pass"))
    for o in opts2:
        test = "\n".join(f"assert allowed_path({name!r}) == {result!r}" for name, result in entries)
        test += "\nassert allowed_path('.') is None"
        checks.append(Check(name=f"step2:{o.id}", runner="python",
                            program=py_harness(head + o.code, test), embeds_display_code=False,
                            expect="pass" if o.id == key2 else "fail"))
    condition = rng.choice(sorted(CONDITIONS))
    rubric = rubric_from({**CONDITIONS[condition], "notes": "Шаг 3. Ссылки и гонки обсуждаются "
                          "концептуально; запрещено предлагать реальные воздействия. "
                          "Равноценные защитные архитектуры принимаются. Каждый критерий "
                          "оценивается 0/0.5/1; итог — взвешенная сумма."})
    stem = (f"{ctx.capitalize()}: `allowed_path` возвращает канонический путь только для файла "
            f"внутри `{root}`, включая вложенные папки; сам корень возвращает None. "
            "Это учебное неизменяемое POSIX-дерево без символьных ссылок. Никакие файлы здесь "
            "не открываются. Абсолютные имена допускаются только внутри корня. "
            "Ревью обнаружило сравнение строк вместо компонентов пути.")
    return build_variant(
        FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2, rubric=rubric,
        answer_key=AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                            explanation="Одноимённый соседний каталог не является дочерним. "
                            "После resolve проверяется настоящий предок; basename теряет "
                            "вложенную папку, проверка parent отвергает допустимую вложенность."),
        context=ctx, verification="execution", checks=checks, defect_type="path_string_prefix",
        steps=ob3_steps("Шаг 1. Какое законное имя файла обнаруживает ошибку контракта?",
                        "Шаг 2. Выберите исправление, сохраняющее вложенные имена.",
                        "Шаг 3. " + CONDITIONS[condition]["text"] + " Ответьте в 5–10 предложениях."),
        params={"condition": condition, "root": root, "source_urls": [SOURCES["coding"]]},
    )
