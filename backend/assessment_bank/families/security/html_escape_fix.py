"""HTML: учебный текстовый узел, без обработчиков событий и исполняемых вставок."""
from __future__ import annotations

import json
from assessment_bank.gen_utils import make_rng
from ._support import CONTEXTS, SOURCES, fix_variant

FAMILY_ID = "security.web.html_escape_fix"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    tag = rng.choice(["p", "span", "h2", "li"])
    noun = rng.choice(["Отчёт", "План", "Курс", "Заявка", "Архив", "Каталог"])
    number = rng.randint(10, 900)
    sample = f'{noun} {number}: <черновик> & "версия"'
    mapping = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}
    head = "const ESCAPES = " + json.dumps(mapping) + ";\nfunction render(label) {\n"
    tail = f"  return `<{tag}>${{text}}</{tag}>`;\n" + "}"
    buggy = head + "  const text = String(label);\n" + tail
    correct = head + "  const text = String(label).replace(/[&<>\"']/g, c => ESCAPES[c]);\n" + tail
    distractors = [
        head + '  const text = String(label).replace(/[<>"\']/g, c => ESCAPES[c]);\n' + tail,
        head + '  const text = String(label).replace(/[<>"\']/g, c => ESCAPES[c]).replace(/&/g, "&amp;");\n' + tail,
        head + '  const text = String(label).replace(/[&<>"\']/g, c => "");\n' + tail,
    ]
    samples = [sample, "Обычный текст", "&lt;пример&gt;", "Имя 'Редактор'"]
    expected = [f"<{tag}>" + "".join(mapping.get(c, c) for c in s) + f"</{tag}>" for s in samples]
    test = f"""const samples = {json.dumps(samples, ensure_ascii=False)};
const expected = {json.dumps(expected, ensure_ascii=False)};
for (let i = 0; i < samples.length; i++) {{
  __assert(render(samples[i]) === expected[i]);
}}"""
    stem = (f"{ctx.capitalize()}: серверный шаблон выводит пользовательское название "
            f"`{sample}` внутри текстового узла `<{tag}>`, не в URL, скрипте или атрибуте. "
            "Нужно отобразить исходный текст буквально, без удаления символов. "
            "Какое исправление выполняет HTML-экранирование за один проход?")
    return fix_variant(
        FAMILY_ID, seed, rng, stem=stem, buggy=buggy, correct=correct, distractors=distractors,
        test=test, context=ctx, defect="unescaped_html_text", runner="node",
        why="Экранирование зависит от контекста. Для данного текстового узла таблица замен "
            "за один проход сохраняет данные и не экранирует повторно созданные сущности. "
            "В рабочем шаблонизаторе предпочтительно включить встроенное автоэкранирование.",
        params={"source_urls": [SOURCES["coding"]], "tag": tag, "samples": samples},
    )
