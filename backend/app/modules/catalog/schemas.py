from datetime import date

from pydantic import BaseModel, ConfigDict


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DirectionOut(_ORM):
    id: str
    title: str
    description: str
    code_language: str
    sort_order: int


class GradeOut(_ORM):
    id: str
    title: str
    level: int
    description: str


class CategoryOut(_ORM):
    id: str
    direction_id: str
    grade_id: str
    title: str
    market_salary_from: int
    market_salary_to: int
    market_salary_median: int | None = None
    market_sample_size: int | None = None
    market_source: str | None = None
    market_as_of: date | None = None


class StackTagOut(_ORM):
    id: str
    title: str
    kind: str
    direction_id: str | None


class FspDisciplineOut(BaseModel):
    id: str
    title: str


class CatalogOut(BaseModel):
    directions: list[DirectionOut]
    grades: list[GradeOut]
    categories: list[CategoryOut]
    stack_tags: list[StackTagOut]
    fsp_disciplines: list[FspDisciplineOut]
