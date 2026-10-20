"""Описания семейств направлений волны 20.10 (числовые mcq_concept). Каждое: MODEL (answer, traps, fmt, по желанию
brute), sample, stem, explain, trap_desc; модуль семейства — тонкая обёртка ``generate = make(FAMILY_ID)``.
Генерация и проверки — :func:`assessment_bank.families._w2010_kit.numeric_variant`.
"""
from __future__ import annotations

from math import ceil

from assessment_bank.families._w2010_kit import load_model, num, numeric_variant

DEFS: dict[str, dict] = {}


def define(fid, **kw):
    DEFS[fid] = kw


def make(fid):
    d = DEFS[fid]

    def generate(seed: int):
        return numeric_variant(fid, seed, contexts=d["contexts"], sample=d["sample"], model=d["model"],
                               stem=d["stem"], explain=d["explain"], accept=d.get("accept"), rel=d.get("rel", 0.1),
                               abs_min=d.get("abs_min", 1), trap_first=d.get("trap_first"),
                               trap_desc=d["trap_desc"], n_above_choices=d.get("n_above", (0, 1, 2, 3)))
    return generate


def cap(s: str) -> str:
    return s[0].upper() + s[1:]


def M(src: str):
    return load_model(src)


from assessment_bank.families import _w2010_defs_a  # noqa: E402,F401  — регистрирует описания
from assessment_bank.families import _w2010_defs_b  # noqa: E402,F401
from assessment_bank.families import _w2010_defs_c  # noqa: E402,F401
from assessment_bank.families import _w2010_defs_d  # noqa: E402,F401
