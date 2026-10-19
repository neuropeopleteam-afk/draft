"""Кабинет ФСП (роль fsp_analyst): обезличенная аналитика платформы — только агрегаты, K = 5."""
from __future__ import annotations

import csv
import io
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.fsp_cabinet import analytics as an
from app.modules.auth.models import User

router = APIRouter(prefix="/api/fsp-cabinet", tags=["fsp-cabinet"])
analyst = require_role(UserRole.fsp_analyst, UserRole.admin)
AUTH = {401: err("Не выполнен вход"), 403: err("Только для роли «ФСП» или администратора")}
TAGS = [{"name": "fsp-cabinet", "description": "Кабинет ФСП: спрос работодателей, эффект соревнований ФСП, реальные "
                                               "зарплатные вилки, воронки — только агрегаты (минимальная группа 5)"}]
log = logging.getLogger("app.fsp_cabinet")
Days = Query(None, ge=7, le=730, description="Период, дней (по умолчанию — всё время)")


def _audit(user: User, what: str, days: int | None) -> None:
    log.info("fsp_cabinet access user=%s role=%s section=%s days=%s", user.id, user.role.value, what, days)


@router.get("/report", summary="Вся аналитика кабинета одним ответом", responses=AUTH)
def report(days: int | None = Days, user: User = Depends(analyst), db: Session = Depends(get_db)) -> dict:
    from app.cup import tournament
    from app.modules.jury import scope as jury_scope

    _audit(user, "report", days)
    # Н5: турниры «Компания × ФСП» под вакансии — отдельным списком (платформы и своей песочницы жюри, агрегаты)
    return {**an.report(db, days), "tournaments": tournament.cabinet_list(db, jury_scope.key_of(user.email))}


@router.get("/overview", summary="Ключевые показатели", responses=AUTH)
def overview(days: int | None = Days, user: User = Depends(analyst), db: Session = Depends(get_db)) -> dict:
    _audit(user, "overview", days)
    return an.overview(an.load(db, days))


@router.get("/demand", summary="Спрос работодателей по категориям и навыкам", responses=AUTH)
def demand(days: int | None = Days, user: User = Depends(analyst), db: Session = Depends(get_db)) -> dict:
    _audit(user, "demand", days)
    return an.demand(an.load(db, days))


@router.get("/fsp-effect", summary="Какие дисциплины, разряды и результаты ФСП ведут к приглашениям и принятиям",
            responses=AUTH)
def fsp_effect(days: int | None = Days, user: User = Depends(analyst), db: Session = Depends(get_db)) -> dict:
    _audit(user, "fsp_effect", days)
    return an.fsp_effect(an.load(db, days))


@router.get("/salaries", summary="Реальные зарплатные вилки из приглашений по категориям", responses=AUTH)
def salaries(days: int | None = Days, user: User = Depends(analyst), db: Session = Depends(get_db)) -> dict:
    _audit(user, "salaries", days)
    return an.salaries(an.load(db, days))


@router.get("/funnel", summary="Воронки «соревнование → приглашение → принятие»", responses=AUTH)
def funnel(days: int | None = Days, user: User = Depends(analyst), db: Session = Depends(get_db)) -> dict:
    _audit(user, "funnel", days)
    return an.funnel(an.load(db, days))


@router.get("/cups", summary="Кубки работодателей как мероприятия", responses=AUTH)
def cups(days: int | None = Days, user: User = Depends(analyst), db: Session = Depends(get_db)) -> list[dict]:
    _audit(user, "cups", days)
    return an.cups_section(an.load(db, days), db)


def _cell(v) -> str:
    if v is None:
        return f"<{an.K}"
    return str(v)


EXPORTS = {
    "demand": (lambda r: r["demand"]["categories"],
               ["title", "needs", "companies", "invitations", "invited_candidates", "supply", "invite_rate",
                "accepted_candidates", "accept_rate", "market_median"]),
    "skills": (lambda r: r["demand"]["skills"],
               ["title", "needs_required", "needs_desired", "companies", "supply_confirmed", "invited_with_skill",
                "invite_rate_with_skill"]),
    "fsp": (lambda r: [*r["fsp_effect"]["groups"], *r["fsp_effect"]["disciplines"], *r["fsp_effect"]["ranks"],
                       *r["fsp_effect"]["results"], *r["fsp_effect"]["levels"]],
            ["title", "candidates", "invited", "invite_rate", "accepted", "accept_rate", "lift_vs_no_fsp",
             "adjusted_ratio"]),
    "salaries": (lambda r: r["salaries"]["categories"],
                 ["title", "offers", "from_p25", "from_median", "to_median", "to_p75", "mid_median", "market_from",
                  "market_to", "market_median", "delta_vs_market_pct"]),
}


@router.get("/export/{section}.csv", summary="Выгрузка раздела в CSV (те же агрегаты, малые группы скрыты)",
            responses={**AUTH, 404: err("Нет такого раздела")})
def export(section: str, days: int | None = Days, user: User = Depends(analyst),
           db: Session = Depends(get_db)) -> Response:
    if section not in EXPORTS:
        raise api_error(404, "export_not_found", "Нет такого раздела выгрузки")
    _audit(user, f"export:{section}", days)
    rows_of, cols = EXPORTS[section]
    rep = an.report(db, days)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(cols)
    for row in rows_of(rep):
        if row.get("suppressed") and section == "salaries":
            w.writerow([row.get("title"), _cell(row.get("offers"))] + ["скрыто"] * 5 +
                       [_cell(row.get(c)) for c in cols[7:]])
            continue
        w.writerow([_cell(row.get(c)) for c in cols])
    return Response(content="\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="fsp_{section}.csv"'})
