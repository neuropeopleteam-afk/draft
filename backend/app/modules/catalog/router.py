from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.catalog.constants import FSP_DISCIPLINES
from app.modules.catalog.models import Category, Direction, Grade, StackTag
from app.modules.catalog.schemas import CatalogOut, StackTagOut
from app.modules.catalog.seed_data import GRADE_ORDER

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("", response_model=CatalogOut, summary="Справочник: направления, грейды, категории, стек")
def get_catalog(db: Session = Depends(get_db)) -> CatalogOut:
    return CatalogOut(
        directions=db.scalars(select(Direction).order_by(Direction.sort_order)).all(),
        # уровни платформы (seed_data.GRADE_ORDER): Lead/Principal — только с флагом GRADES_EXT_ENABLED, даже если
        # строки справочника остались в БД после выключения флага
        grades=db.scalars(select(Grade).where(Grade.id.in_(GRADE_ORDER)).order_by(Grade.level)).all(),
        categories=db.scalars(select(Category).where(Category.grade_id.in_(GRADE_ORDER)).order_by(Category.id)).all(),
        stack_tags=db.scalars(select(StackTag).order_by(StackTag.direction_id, StackTag.sort_order)).all(),
        fsp_disciplines=FSP_DISCIPLINES,
    )


@router.get("/stack-tags", response_model=list[StackTagOut], summary="Стек-теги для опроса")
def get_stack_tags(
    direction: str | None = Query(None, description="Направление; общий блок возвращается всегда"),
    db: Session = Depends(get_db),
) -> list[StackTag]:
    q = select(StackTag).order_by(StackTag.direction_id, StackTag.sort_order)
    if direction:
        q = q.where((StackTag.direction_id == direction) | (StackTag.direction_id.is_(None)))
    return list(db.scalars(q).all())
