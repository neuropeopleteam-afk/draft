"""Слой выдачи вариантов: пулы seed по субпулам, частота показа вариантов, карантин.

* Субпул s семейства — диапазон seed [SUBPOOL_BASE·(s+1), SUBPOOL_BASE·(s+1) + pool_size).
  Активный субпул меняется по расписанию (ротация); вышедшие из ротации варианты не
  выдаются, пока не пройдёт карантин.
* Каждый вариант показывается не более max_uses раз, затем уходит в карантин.
* Канарейки выдаются только из опубликованных seed 1..canary_pool_size.

Состояние (счётчики) хранится в памяти; бэкенд может сохранять его в БД через
``to_state()/from_state()``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .registry import canary_published_seeds, get_spec

SUBPOOL_BASE = 1_000_000


@dataclass
class SeedServer:
    pool_size: int = 200
    max_uses: int = 3
    uses: dict[str, int] = field(default_factory=dict)
    quarantined: set[str] = field(default_factory=set)

    def seeds_for(self, family_id: str, subpool: int) -> list[int]:
        spec = get_spec(family_id)
        if spec.canary:
            return canary_published_seeds(family_id)
        start = SUBPOOL_BASE * (subpool + 1)
        return list(range(start, start + self.pool_size))

    def draw(self, family_id: str, subpool: int, rng: np.random.Generator) -> int:
        seeds = self.seeds_for(family_id, subpool)
        if get_spec(family_id).canary:
            return int(seeds[int(rng.integers(len(seeds)))])
        free = [s for s in seeds if f"{family_id}:{s}" not in self.quarantined]
        if not free:
            raise RuntimeError(f"{family_id}: субпул {subpool} исчерпан — нужна ротация")
        least = min(self.uses.get(f"{family_id}:{s}", 0) for s in free)
        cands = [s for s in free if self.uses.get(f"{family_id}:{s}", 0) == least]
        seed = int(cands[int(rng.integers(len(cands)))])
        vid = f"{family_id}:{seed}"
        self.uses[vid] = self.uses.get(vid, 0) + 1
        if self.uses[vid] >= self.max_uses:
            self.quarantined.add(vid)
        return seed

    def to_state(self) -> dict:
        return {"uses": dict(self.uses), "quarantined": sorted(self.quarantined)}

    @classmethod
    def from_state(cls, state: dict, **kw) -> "SeedServer":
        s = cls(**kw)
        s.uses = dict(state.get("uses", {}))
        s.quarantined = set(state.get("quarantined", []))
        return s


def export_canary_leak(family_ids: list[str] | None = None) -> list[dict]:
    """«Утечка» канареек: опубликованные варианты с ответами (для демонстрации детектора)."""
    from .registry import generate, list_families

    out = []
    fids = family_ids or [s.family_id for s in list_families(canary=True)]
    for fid in fids:
        for seed in canary_published_seeds(fid):
            v = generate(fid, seed)
            out.append({"variant_id": v.variant_id, "stem": v.stem, "code": v.code,
                        "options": [o.model_dump(exclude_none=True) for o in v.options or []],
                        "answer": v.answer_key.value})
    return out
