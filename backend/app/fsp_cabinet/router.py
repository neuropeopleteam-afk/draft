"""Кабинет ФСП (роль fsp_analyst): обезличенная аналитика платформы — только агрегаты, K = 5."""
from __future__ import annotations

import csv
import io
import logging

from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
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
    from app.fsp_cabinet.regions import build_regions_map
    from app.modules.jury import scope as jury_scope

    _audit(user, "report", days)
    # Н5: турниры «Компания × ФСП» под вакансии — отдельным списком (платформы и своей песочницы жюри, агрегаты)
    return {
        **an.report(db, days),
        "regions_map": build_regions_map(db, days),
        "tournaments": tournament.cabinet_list(db, jury_scope.key_of(user.email)),
    }


@router.get("/regions", summary="Карта талантов по регионам и федеральным округам РФ", responses=AUTH)
def regions(days: int | None = Days, user: User = Depends(analyst), db: Session = Depends(get_db)) -> dict:
    from app.fsp_cabinet.regions import build_regions_map

    _audit(user, "regions", days)
    return build_regions_map(db, days)


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


class ProtocolClaimDecideIn(BaseModel):
    action: Literal["approve", "reject"]
    note: str | None = Field(None, max_length=500)


@router.get("/protocol-claims", summary="Очередь заявок кандидатов на подтверждение достижений по официальным протоколам ФСП",
            responses=AUTH)
def list_protocol_claims(
    status: Literal["all", "pending_fsp", "verified"] = Query("all"),
    user: User = Depends(analyst),
    db: Session = Depends(get_db),
) -> dict:
    from app.modules.catalog.constants import FSP_DISCIPLINES
    from app.modules.fsp.models import FspAchievement, FspPassport
    from app.modules.profiles.facts import achievement_text
    from app.modules.profiles.models import CandidateProfile

    _audit(user, "protocol-claims", None)
    disc_titles = {d["id"]: d["title"] for d in FSP_DISCIPLINES}
    rows = db.scalars(
        select(FspAchievement)
        .where(
            or_(
                FspAchievement.source_ref.like("protocol:%"),
                FspAchievement.protocol_status.in_(("pending_fsp", "verified")),
            )
        )
        .order_by(FspAchievement.created_at.desc())
    ).all()
    pids = list({r.passport_id for r in rows})
    passports = {p.id: p for p in db.scalars(select(FspPassport).where(FspPassport.id.in_(pids))).all()} if pids else {}
    uids = list({p.user_id for p in passports.values()})
    profiles = {p.user_id: p for p in db.scalars(select(CandidateProfile).where(CandidateProfile.user_id.in_(uids))).all()} if uids else {}

    items = []
    pending_cnt = 0
    verified_cnt = 0
    for a in rows:
        tr = a.team_result or {}
        pref = a.protocol_ref or {}
        st = a.protocol_status or tr.get("protocol_status") or ("verified" if tr.get("protocol_verified") else "pending_fsp")
        if st == "pending_fsp":
            pending_cnt += 1
        elif st == "verified":
            verified_cnt += 1
        if status != "all" and st != status:
            continue
        pp = passports.get(a.passport_id)
        prof = profiles.get(pp.user_id) if pp else None
        ekp_no = a.ekp_no or pref.get("ekp_no") or tr.get("ekp_no")
        evsk_rank = a.evsk_rank or tr.get("evsk_rank") or a.sport_rank
        evsk_basis = a.evsk_basis or tr.get("evsk_basis")
        pdf_url = pref.get("url") or tr.get("pdf_url")
        page = pref.get("page") or tr.get("page")
        doc_id = pref.get("doc_id") or tr.get("doc_id") or a.event_id
        items.append({
            "id": str(a.id),
            "candidate_ref": prof.public_ref if prof else None,
            "event_name": a.event_name,
            "event_date": a.event_date.isoformat() if a.event_date else None,
            "discipline": a.discipline,
            "discipline_title": disc_titles.get(a.discipline, a.discipline),
            "place": a.place,
            "result_title": a.result_title,
            "team_name": a.team_name,
            "region": tr.get("region"),
            "ekp_no": ekp_no,
            "evsk_rank": evsk_rank,
            "evsk_basis": evsk_basis,
            "protocol_ref": {"doc_id": doc_id, "ekp_no": ekp_no, "page": page, "url": pdf_url},
            "pdf_url": pdf_url,
            "page": page,
            "protocol_status": st,
            "status_title": (
                "Подтверждено протоколом ФСП" if st == "verified"
                else "Найдено в протоколе — ожидает подтверждения ФСП" if st == "pending_fsp"
                else tr.get("status_title") or "Отклонено"
            ),
            "fsp_note": tr.get("fsp_note"),
            "formatted_text": achievement_text(a),
            "created_at": a.created_at.isoformat() if a.created_at else None,
        })
    items.sort(key=lambda x: (0 if x["protocol_status"] == "pending_fsp" else 1))
    return {
        "counts": {"pending_fsp": pending_cnt, "verified": verified_cnt, "total": len(rows)},
        "items": items,
    }


@router.post("/protocol-claims/{achievement_id}/decide",
             summary="Подтвердить или отклонить заявку кандидата по официальному протоколу ФСП",
             responses={**AUTH, 404: err("Заявка не найдена")})
def decide_protocol_claim(
    achievement_id: uuid.UUID,
    data: ProtocolClaimDecideIn,
    user: User = Depends(analyst),
    db: Session = Depends(get_db),
) -> dict:
    from app.modules.fsp.models import FspAchievement, FspPassport
    from app.modules.notifications import service as notif_svc
    from app.modules.profiles.facts import achievement_text, refresh_rating

    a = db.get(FspAchievement, achievement_id)
    if a is None:
        raise api_error(404, "claim_not_found", "Заявка на подтверждение протокола не найдена")
    pp = db.get(FspPassport, a.passport_id)
    tr = dict(a.team_result or {})
    if data.action == "approve":
        a.protocol_status = "verified"
        a.verified = True
        tr["protocol_verified"] = True
        tr["protocol_status"] = "verified"
        tr["status_title"] = "Подтверждено представителем ФСП по официальному протоколу"
        if data.note:
            tr["fsp_note"] = data.note
        a.team_result = tr
        if a.evsk_rank and pp and not pp.sport_rank:
            pp.sport_rank = a.evsk_rank
    else:
        a.protocol_status = "none"
        a.verified = False
        tr["protocol_verified"] = False
        tr["protocol_status"] = "rejected"
        tr["status_title"] = "Отклонено представителем ФСП"
        if data.note:
            tr["fsp_note"] = data.note
        a.team_result = tr
    db.flush()
    if pp is not None:
        refresh_rating(db, pp.user_id)
        try:
            notif_svc.notify(
                db,
                pp.user_id,
                kind="fsp_protocol_decided",
                title=(
                    "Достижение подтверждено представителем ФСП"
                    if data.action == "approve"
                    else "Заявка по протоколу ФСП отклонена"
                ),
                body=achievement_text(a) + (f" · Комментарий ФСП: {data.note}" if data.note else ""),
                link="/candidate/profile",
            )
        except Exception:  # noqa: BLE001
            pass
    db.commit()
    return {
        "id": str(a.id),
        "protocol_status": a.protocol_status,
        "verified": a.verified,
        "status_title": tr.get("status_title"),
        "formatted_text": achievement_text(a),
    }
