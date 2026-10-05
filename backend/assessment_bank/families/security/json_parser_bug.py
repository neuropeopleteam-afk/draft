"""Небезопасный выбор формата; тесты содержат только обычные JSON-данные."""
from __future__ import annotations

import json
from assessment_bank.gen_utils import make_rng
from ._support import CONTEXTS, SOURCES, bug_variant

FAMILY_ID = "security.input.json_parser_bug"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, limit = rng.choice(CONTEXTS), rng.choice([2048, 4096, 8192])
    field = rng.choice(["title", "label", "name", "caption"])
    record = {field: f"Черновик {rng.randint(10, 999)}", "count": rng.randint(1, 50)}
    code = f"""import json
import pickle
MAX_BYTES = {limit}

def parse_record(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('size')
    data = pickle.loads(raw)
    if not isinstance(data, dict) or set(data) != {{{field!r}, 'count'}}:
        raise ValueError('fields')
    if not isinstance(data[{field!r}], str) or type(data['count']) is not int:
        raise ValueError('types')
    if not 0 <= data['count'] <= 100:
        raise ValueError('count')
    return data"""
    fixed = code.replace("data = pickle.loads(raw)", "data = json.loads(raw)")
    raw = json.dumps(record, ensure_ascii=False).encode()
    test = f"""assert parse_record({raw!r}) == {record!r}
for invalid in [b'[]', b'{{"extra": 1}}', b'not json', b'x' * (MAX_BYTES + 1)]:
    try:
        parse_record(invalid)
    except (ValueError, UnicodeError):
        continue
    raise AssertionError('invalid record accepted')"""
    stem = (f"{ctx.capitalize()}: публичная форма отправляет UTF-8 JSON с полями `{field}` "
            "и `count`. Ограничения размера и схемы уже предусмотрены. Ревьюер просит не "
            "использовать форматы, восстанавливающие произвольные Python-объекты из внешних "
            f"байтов. Укажите строку, которую нужно заменить; пример законной записи: `{record}`.")
    return bug_variant(
        FAMILY_ID, seed, stem=stem, buggy=code, fixed=fixed, test=test, context=ctx,
        defect="unsafe_deserializer",
        params={"why": "Для внешнего JSON нужен json.loads, а не pickle.loads. Проверка типа "
                "после небезопасного разбора не исправляет выбор десериализатора. "
                "После JSON остаются необходимыми лимит размера и проверка схемы.",
                "source_urls": [SOURCES["pickle"]], "record": record},
    )
