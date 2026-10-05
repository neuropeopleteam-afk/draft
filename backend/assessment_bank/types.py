"""Контракт банка заданий (общий для backend и авторов семейств)."""
from dataclasses import dataclass, field
from typing import Any, Literal

Direction = Literal["common", "backend", "frontend", "data_ml", "qa", "security"]
Format = Literal["find_bug", "predict_output", "choose_fix", "open_book_3step", "mcq_concept", "open_answer"]


@dataclass(frozen=True)
class Variant:
    variant_id: str  # f"{family_id}:{seed}"
    stem: str  # формулировка на русском
    answer_key: Any  # хранится только на сервере
    code: str | None = None
    options: list[str] | None = None
    rubric: dict[str, str] | None = None  # эталоны strong/medium/weak для open_answer, open_book_3step
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Family:
    family_id: str
    direction: Direction
    skills: list[str]
    target_grades: list[str]
    format: Format
    invariants: dict[str, Any]
    time_limit_s: int
    canary: bool = False
    prior_difficulty: float = 0.0
