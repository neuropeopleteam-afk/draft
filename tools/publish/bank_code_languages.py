#!/usr/bin/env python3
"""Языки кода в семействах банка по направлениям (для docs/validation/LIMITATIONS.md).

Запуск из корня: python3 tools/publish/bank_code_languages.py [backend common ...] → JSON в stdout.
Считает поле language семейства (YAML `language:` и генераторы `language="…"`); text — задание без кода.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "backend" / "assessment_bank" / "families"
PAT = re.compile(r'language(?:: ?|=")([a-z]+)')


def count(direction: str) -> dict:
    c = Counter()
    for p in sorted((ROOT / direction).rglob("*")):
        if p.suffix in (".yaml", ".yml", ".py") and p.is_file():
            c.update(PAT.findall(p.read_text(encoding="utf-8", errors="ignore")))
    return dict(c.most_common())


if __name__ == "__main__":
    dirs = sys.argv[1:] or ["backend", "common"]
    print(json.dumps({d: count(d) for d in dirs}, ensure_ascii=False, indent=1))
