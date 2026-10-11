from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.catalog import ext
from app.modules.catalog.constants import FSP_DISCIPLINES
from app.modules.catalog.models import Category, Direction, Grade, StackTag
from app.modules.catalog import levels
from app.modules.catalog.schemas import CatalogOut, StackTagOut
from app.modules.catalog.seed_data import EXT_GRADE_ORDER, GRADE_ORDER

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


def _hidden() -> set[str]:
    """Скрытые сейчас направления расширения каталога (флаг CATALOG_EXT_ENABLED выключен или банк не проверен)."""
    return set(ext.hidden_ext())


@router.get("", response_model=CatalogOut, summary="Справочник: направления, грейды, категории, стек")
def get_catalog(db: Session = Depends(get_db)) -> CatalogOut:
    hidden = _hidden()
    directions = [d for d in db.scalars(select(Direction).order_by(Direction.sort_order)).all() if d.id not in hidden]
    dir_ids = [d.id for d in directions]
    return CatalogOut(
        directions=directions,
        # уровни платформы (seed_data.GRADE_ORDER): Lead/Principal — только с флагом GRADES_EXT_ENABLED, даже если
        # строки справочника остались в БД после выключения флага; категория Lead/Principal — только в направлении,
        # где эти уровни проверяет банк (catalog.levels); направления расширения каталога — только видимые (ext.py)
        grades=[g for g in db.scalars(select(Grade).where(Grade.id.in_(GRADE_ORDER)).order_by(Grade.level)).all()
                if g.id not in EXT_GRADE_ORDER or levels.directions_with(g.id, dir_ids)],
        categories=[c for c in db.scalars(select(Category).where(Category.grade_id.in_(GRADE_ORDER))
                                          .order_by(Category.id)).all()
                    if c.direction_id not in hidden
                    and (c.grade_id not in EXT_GRADE_ORDER or levels.is_available(c.direction_id, c.grade_id))],
        stack_tags=[t for t in db.scalars(select(StackTag).order_by(StackTag.direction_id, StackTag.sort_order)).all()
                    if t.direction_id not in hidden],
        fsp_disciplines=FSP_DISCIPLINES,
    )


@router.get("/stack-tags", response_model=list[StackTagOut], summary="Стек-теги для опроса")
def get_stack_tags(
    direction: str | None = Query(None, description="Направление; общий блок возвращается всегда. У направлений "
                                                    "расширения каталога — ещё связанные теги других направлений "
                                                    "(инженеру данных — Spark и Airflow и т. п.)"),
    db: Session = Depends(get_db),
) -> list[StackTag]:
    hidden = _hidden()
    q = select(StackTag).order_by(StackTag.direction_id, StackTag.sort_order)
    if direction:
        related = list(ext.EXT_RELATED_TAGS.get(direction, ())) if direction not in hidden else []
        conds = [StackTag.direction_id == direction, StackTag.direction_id.is_(None)]
        if related:
            conds.append(StackTag.id.in_(related))
        q = q.where(or_(*conds))
    rows = [t for t in db.scalars(q).all() if t.direction_id not in hidden]
    if direction in ext.EXT_RELATED_TAGS and direction not in hidden:
        # свои теги направления — первыми, затем связанные (в порядке EXT_RELATED_TAGS), затем общий блок
        order = {t: i for i, t in enumerate(ext.EXT_RELATED_TAGS[direction])}
        rows.sort(key=lambda t: (0 if t.direction_id == direction else 1 if t.id in order else 2,
                                 order.get(t.id, 0), t.sort_order))
    return rows
