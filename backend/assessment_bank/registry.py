"""Реестр семейств: YAML-описания из ``assessment_bank/families/<блок>/*.yaml``.

Каждое YAML ссылается на модуль-генератор (поле ``generator``), в котором определены
``FAMILY_ID`` и ``generate(seed: int) -> Variant``. Общая точка входа —
:func:`generate(family_id, seed) <generate>`.
"""
from __future__ import annotations

import importlib
from functools import lru_cache
from pathlib import Path
from types import ModuleType

import yaml

from .schema import FamilySpec, Variant, make_variant_id

FAMILIES_DIR = Path(__file__).parent / "families"


class RegistryError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def load_specs() -> dict[str, FamilySpec]:
    specs: dict[str, FamilySpec] = {}
    for path in sorted(FAMILIES_DIR.glob("*/*.yaml")):
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        try:
            spec = FamilySpec(**data)
        except Exception as exc:  # pydantic.ValidationError и ошибки YAML
            raise RegistryError(f"{path.name}: {exc}") from exc
        if spec.family_id in specs:
            raise RegistryError(f"повтор family_id {spec.family_id}")
        if path.parent.name != spec.direction:
            raise RegistryError(f"{path.name}: лежит в {path.parent.name}, а direction={spec.direction}")
        specs[spec.family_id] = spec
    return specs


def get_spec(family_id: str) -> FamilySpec:
    try:
        return load_specs()[family_id]
    except KeyError as exc:
        raise RegistryError(f"нет семейства {family_id}") from exc


def list_families(direction: str | None = None, grade: str | None = None,
                  fmt: str | None = None, canary: bool | None = None) -> list[FamilySpec]:
    out = []
    for spec in load_specs().values():
        if direction and spec.direction != direction:
            continue
        if grade and grade not in spec.target_grades:
            continue
        if fmt and spec.format != fmt:
            continue
        if canary is not None and spec.canary != canary:
            continue
        out.append(spec)
    return out


@lru_cache(maxsize=None)
def _module(family_id: str) -> ModuleType:
    spec = get_spec(family_id)
    mod = importlib.import_module(spec.generator)
    if getattr(mod, "FAMILY_ID", None) != family_id:
        raise RegistryError(f"{spec.generator}.FAMILY_ID != {family_id}")
    if not callable(getattr(mod, "generate", None)):
        raise RegistryError(f"{spec.generator}: нет функции generate(seed)")
    return mod


def generate(family_id: str, seed: int) -> Variant:
    """Сгенерировать вариант семейства по seed (детерминированно)."""
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("seed — неотрицательное целое")
    spec = get_spec(family_id)
    variant = _module(family_id).generate(seed)
    if not isinstance(variant, Variant):
        raise RegistryError(f"{family_id}: generate вернул не Variant")
    m = variant.meta
    if variant.variant_id != make_variant_id(family_id, seed) or m.seed != seed:
        raise RegistryError(f"{family_id}: неверный variant_id/seed")
    if m.family_id != family_id or m.format != spec.format:
        raise RegistryError(f"{family_id}: meta не соответствует YAML")
    return variant


def canary_published_seeds(family_id: str) -> list[int]:
    """Seed, опубликованные «в утечку» (только для канареек): 1..canary_pool_size."""
    spec = get_spec(family_id)
    if not spec.canary:
        return []
    return list(range(1, (spec.canary_pool_size or 0) + 1))
