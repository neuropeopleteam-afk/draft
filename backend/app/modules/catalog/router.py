from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.catalog.constants import FSP_DISCIPLINES
from app.modules.catalog.models import Category, Direction, Grade, StackTag
from app.modules.catalog import levels
from app.modules.catalog.schemas import CatalogOut, StackTagOut
from app.modules.catalog.seed_data import EXT_GRADE_ORDER, GRADE_ORDER

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("", response_model=CatalogOut, summary="Справочник: направления, грейды, категории, стек")
def get_catalog(db: Session = Depends(get_db)) -> CatalogOut:
    directions = db.scalars(select(Direction).order_by(Direction.sort_order)).all()
    dir_ids = [d.id for d in directions]
    return CatalogOut(
        directions=directions,
        # уровни платформы (seed_data.GRADE_ORDER): Lead/Principal — только с флагом GRADES_EXT_ENABLED, даже если
        # строки справочника остались в БД после выключения флага; категория Lead/Principal — только в направлении,
        # где эти уровни проверяет банк (catalog.levels)
        grades=[g for g in db.scalars(select(Grade).where(Grade.id.in_(GRADE_ORDER)).order_by(Grade.level)).all()
                if g.id not in EXT_GRADE_ORDER or levels.directions_with(g.id, dir_ids)],
        categories=[c for c in db.scalars(select(Category).where(Category.grade_id.in_(GRADE_ORDER))
                                          .order_by(Category.id)).all()
                    if c.grade_id not in EXT_GRADE_ORDER or levels.is_available(c.direction_id, c.grade_id)],
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
