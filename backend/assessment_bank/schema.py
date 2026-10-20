"""Схема банка заданий: описание семейства (YAML) и варианта (Variant).

Поля строго по брифу разработки («Формат банка заданий»):

* семейство: family_id, direction, skills[], target_grades[], format, invariants
  (размер кода, число операций, тип дефекта), time_limit_s, canary, prior_difficulty;
* вариант: variant_id (family_id + seed), stem, code, options, answer_key, rubric, meta.

Всё, что нужно только серверу (ключ, рубрика, проверки исполнением, параметры
шаблона), отделено от того, что видит кандидат: см. :meth:`Variant.public_view`.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Direction = Literal["common", "backend", "frontend", "data_ml", "qa", "security",
                    "devops", "data_eng", "mobile", "analyst"]  # 4 новых направления — волна 7 (каталог А, 10.10)
# intern — грейд «Стажёр» ниже Junior: информационная метка для лёгких семейств (b ≲ −1); CAT её не использует
Grade = Literal["intern", "junior", "middle", "senior", "lead", "principal"]  # lead, principal — волна 7 (6 уровней, решение владельца 10.10)
Format = Literal[
    "find_bug", "predict_output", "choose_fix", "open_book_3step", "mcq_concept", "open_answer",
    "incident_sim",
]
Language = Literal[
    "python", "javascript", "typescript", "sql", "bash", "text", "go", "java", "dockerfile", "yaml",
    "kotlin", "swift"]  # kotlin, swift — волна 7 (mobile): только чтение кода, ключ — моделью на Python
Runner = Literal["python", "node", "bash", "git", "sqlite", "go", "java", "django"]
Verification = Literal["execution", "reference_table", "rubric_only"]

GRADES: tuple[str, ...] = ("intern", "junior", "middle", "senior", "lead", "principal")
FORMATS: tuple[str, ...] = (
    "find_bug", "predict_output", "choose_fix", "open_book_3step", "mcq_concept", "open_answer",
    "incident_sim",
)
OPTION_FORMATS = {"choose_fix", "mcq_concept"}
RUBRIC_FORMATS = {"open_answer", "open_book_3step", "incident_sim"}
STEP_FORMATS = {"open_book_3step", "incident_sim"}
AUTO_SCORED_FORMATS = {"find_bug", "predict_output", "choose_fix", "mcq_concept"}

FAMILY_ID_RE = re.compile(
    r"^(common|backend|frontend|data_ml|qa|security|devops|data_eng|mobile|analyst)(\.[a-z0-9_]+){2,}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- семейство
class Invariants(_Strict):
    """Инварианты семейства: то, что одинаково у всех изоморфных вариантов."""

    code_lines: tuple[int, int] | None = Field(
        default=None, description="Диапазон числа непустых строк кода [min, max]")
    operations: tuple[int, int] | None = Field(
        default=None, description="Диапазон числа операций (см. metrics.count_operations)")
    defect_type: str | None = Field(default=None, description="Тип дефекта (один на семейство)")
    n_options: int | None = Field(default=None, ge=2, le=6, description="Число вариантов ответа")
    extra: dict[str, Any] = Field(default_factory=dict, description="Доп. инварианты семейства")

    @field_validator("code_lines", "operations")
    @classmethod
    def _range_ok(cls, v: tuple[int, int] | None) -> tuple[int, int] | None:
        if v is not None and not (0 <= v[0] <= v[1]):
            raise ValueError("диапазон должен быть [min, max], 0 <= min <= max")
        return v


class PriorDifficulty(_Strict):
    """Предкалибровка: априорные параметры по признакам шаблона (не по ответам людей!).

    b — трудность (логиты, шкала θ ~ N(0, 1)), a — дискриминативность,
    sigma_variant — ожидаемый разброс трудности между вариантами семейства,
    step_offsets — сдвиги трудности шагов для open_book_3step.
    """

    b: float = Field(ge=-4, le=4)
    a: float = Field(default=1.0, ge=0.2, le=3.0)
    sigma_variant: float = Field(default=0.3, ge=0.0, le=1.5)
    step_offsets: list[float] | None = None
    basis: str = Field(min_length=10, description="Из каких признаков получена оценка")


class FamilySpec(_Strict):
    family_id: str
    title: str = Field(min_length=3)
    direction: Direction
    skills: list[str] = Field(min_length=1)
    target_grades: list[Grade] = Field(min_length=1)
    format: Format
    language: Language
    invariants: Invariants
    time_limit_s: int = Field(ge=15, le=3600)
    canary: bool = False
    canary_pool_size: int | None = Field(
        default=None, ge=5, le=500,
        description="Для канарейки: сколько вариантов (seed 1..N) намеренно опубликовано")
    prior_difficulty: PriorDifficulty
    generator: str = Field(description="Модуль с функцией generate(seed) -> Variant")
    version: int = 1
    description: str = ""

    @field_validator("family_id")
    @classmethod
    def _fid(cls, v: str) -> str:
        if not FAMILY_ID_RE.match(v):
            raise ValueError(f"family_id '{v}' не соответствует шаблону direction.area.name")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> "FamilySpec":
        if not self.family_id.startswith(self.direction + "."):
            raise ValueError("family_id должен начинаться с direction")
        if self.canary and not self.canary_pool_size:
            raise ValueError("канарейке нужен canary_pool_size (число опубликованных вариантов)")
        if not self.canary and self.canary_pool_size:
            raise ValueError("canary_pool_size задаётся только для канареек")
        if self.format in STEP_FORMATS:
            so = self.prior_difficulty.step_offsets
            if not so or len(so) != 3:
                raise ValueError(f"{self.format}: нужны step_offsets из трёх чисел")
        elif self.prior_difficulty.step_offsets:
            raise ValueError("step_offsets допустимы только для open_book_3step и incident_sim")
        if self.format in OPTION_FORMATS and not self.invariants.n_options:
            raise ValueError(f"{self.format}: нужен invariants.n_options")
        if len(set(self.target_grades)) != len(self.target_grades):
            raise ValueError("target_grades содержит повторы")
        return self

    @property
    def block(self) -> str:
        """Блок теста: общий или направление."""
        return "common" if self.direction == "common" else self.direction

    @property
    def n_parts(self) -> int:
        """Число независимо оцениваемых частей (для open_book_3step и incident_sim — три шага)."""
        return 3 if self.format in STEP_FORMATS else 1


# --------------------------------------------------------------------------- вариант
class Option(_Strict):
    id: str = Field(pattern=r"^[A-F]$")
    text: str = Field(min_length=1)
    code: str | None = None
    step: int | None = Field(default=None, ge=1, le=3, description="Шаг open_book_3step")


class RubricCriterion(_Strict):
    id: str
    description: str = Field(min_length=10)
    weight: float = Field(gt=0, le=1)


class Rubric(_Strict):
    """Рубрика открытого ответа: критерии с весами и эталоны трёх уровней."""

    criteria: list[RubricCriterion] = Field(min_length=2)
    strong: str = Field(min_length=80, description="Эталон сильного ответа")
    medium: str = Field(min_length=40, description="Эталон среднего ответа")
    weak: str = Field(min_length=15, description="Эталон слабого ответа")
    scoring_notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "Rubric":
        total = sum(c.weight for c in self.criteria)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"сумма весов критериев должна быть 1, сейчас {total:.3f}")
        if len({self.strong, self.medium, self.weak}) != 3:
            raise ValueError("эталоны сильного/среднего/слабого ответа должны различаться")
        if len({c.id for c in self.criteria}) != len(self.criteria):
            raise ValueError("id критериев повторяются")
        return self


class AnswerKey(_Strict):
    kind: Literal["option", "line", "output", "steps", "rubric"]
    value: Any
    accept: list[str] = Field(default_factory=list, description="Равноценные формы ответа")
    explanation: str = Field(min_length=10, description="Разбор для эксперта")


class Check(_Strict):
    """Проверка ключа исполнением НАШЕГО кода в песочнице (код кандидата не исполняется)."""

    name: str
    runner: Runner
    program: str
    files: dict[str, str] = Field(default_factory=dict)
    # stdout_equals / stdout_differs — сравнение нормализованного вывода с expected_stdout;
    # pass / fail — тестовая обвязка печатает последней строкой «RESULT: PASS|FAIL».
    expect: Literal["stdout_equals", "stdout_differs", "pass", "fail"]
    expected_stdout: str | None = None
    # Показанный кандидату код входит в программу дословно (проверяем ровно то, что показали)
    embeds_display_code: bool = True

    @model_validator(mode="after")
    def _exp(self) -> "Check":
        if self.expect in ("stdout_equals", "stdout_differs") and self.expected_stdout is None:
            raise ValueError(f"{self.expect} требует expected_stdout")
        return self


class StepPrompt(_Strict):
    step: int = Field(ge=1, le=3)
    kind: Literal["reproduce", "fix", "explain"]
    prompt: str = Field(min_length=10)


class VariantMeta(_Strict):
    family_id: str
    seed: int
    format: Format
    language: Language
    generator_version: int = 1
    context: str = Field(description="Предметная область варианта (для контроля разнообразия)")
    code_lines: int | None = None
    operations: int | None = None
    defect_type: str | None = None
    steps: list[StepPrompt] | None = None
    verification: Verification
    checks: list[Check] = Field(default_factory=list)
    display_code_note: str | None = Field(
        default=None, description="Если исполняется не дословно показанный код — почему")
    params: dict[str, Any] = Field(default_factory=dict, description="Параметры шаблона")


SECRET_META_FIELDS = {"checks", "params", "defect_type", "verification", "display_code_note"}


class Variant(_Strict):
    variant_id: str
    stem: str = Field(min_length=20)
    code: str | None = None
    options: list[Option] | None = None
    answer_key: AnswerKey
    rubric: Rubric | None = None
    meta: VariantMeta

    @model_validator(mode="after")
    def _format_rules(self) -> "Variant":
        fmt = self.meta.format
        if self.variant_id != make_variant_id(self.meta.family_id, self.meta.seed):
            raise ValueError("variant_id должен быть family_id:seed")
        if fmt in RUBRIC_FORMATS and self.rubric is None:
            raise ValueError(f"{fmt}: нужна рубрика с эталонами")
        if fmt in OPTION_FORMATS:
            if not self.options:
                raise ValueError(f"{fmt}: нужны варианты ответа")
            if self.answer_key.kind != "option":
                raise ValueError(f"{fmt}: ключ должен быть option")
            if self.answer_key.value not in {o.id for o in self.options}:
                raise ValueError("ключ не совпадает ни с одним вариантом")
        if self.options:
            ids = [(o.step, o.id) for o in self.options]
            if len(set(ids)) != len(ids):
                raise ValueError("id вариантов ответа повторяются")
        if fmt == "find_bug" and self.answer_key.kind != "line":
            raise ValueError("find_bug: ключ — номер строки")
        if fmt == "predict_output" and self.answer_key.kind != "output":
            raise ValueError("predict_output: ключ — вывод программы")
        if fmt == "open_answer" and self.answer_key.kind != "rubric":
            raise ValueError("open_answer: ключ — рубрика")
        if fmt in STEP_FORMATS:
            if self.answer_key.kind != "steps":
                raise ValueError(f"{fmt}: ключ — по шагам")
            if not self.meta.steps or [s.kind for s in self.meta.steps] != [
                    "reproduce", "fix", "explain"]:
                raise ValueError(f"{fmt}: шаги reproduce → fix → explain")
            if not self.options:
                raise ValueError(f"{fmt}: нужны варианты для шагов 1 и 2")
            for st in (1, 2):
                st_ids = {o.id for o in self.options if o.step == st}
                if self.answer_key.value.get(str(st)) not in st_ids:
                    raise ValueError(f"{fmt}: ключ шага {st} не найден")
        return self

    # ---- представления
    def public_view(self) -> dict[str, Any]:
        """То, что можно отправить кандидату: без ключа, рубрики и служебных данных."""
        meta = self.meta.model_dump(exclude=SECRET_META_FIELDS)
        opts = None
        if self.options:
            opts = [o.model_dump(exclude_none=True) for o in self.options]
        out: dict[str, Any] = {
            "variant_id": self.variant_id, "stem": self.stem, "code": self.code,
            "options": opts, "meta": meta,
        }
        inc = (self.meta.params or {}).get("incident")
        if inc is not None:
            out["incident"] = inc
        return out

    def fingerprint(self) -> str:
        """Хэш видимого кандидату содержания (для уникальности вариантов)."""
        pv = self.public_view()
        payload = json.dumps({k: pv[k] for k in ("stem", "code", "options")},
                             ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def canonical_hash(self) -> str:
        """Хэш полного содержания варианта (для проверки детерминизма)."""
        payload = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def public_text(self) -> str:
        parts = [self.stem, self.code or ""]
        for o in self.options or []:
            parts.append(o.text)
            parts.append(o.code or "")
        for s in self.meta.steps or []:
            parts.append(s.prompt)
        return "\n".join(parts)


def make_variant_id(family_id: str, seed: int) -> str:
    return f"{family_id}:{seed}"
