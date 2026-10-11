"""API тарифов (Я29): публичный список тарифов, тариф и лимит своей компании, демо-счёт, заявка «Партнёр ФСП»;
кабинет ФСП — метка партнёра и блок «Польза для ФСП» с CSV.

Без TARIFFS_ENABLED все методы отвечают 404 ``tariffs_disabled`` (интерфейс раздел не показывает: /api/meta → tariffs).
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.fsp_cabinet import benefit as benefit_mod
from app.modules.auth.models import User
from app.modules.matching.router import my_company
from app.modules.profiles.models import Company
from app.modules.tariffs import plans as P
from app.modules.tariffs import service as svc

public_router = APIRouter(prefix="/api/tariffs", tags=["tariffs"])
employer_router = APIRouter(prefix="/api/employer/tariff", tags=["tariffs"])
fsp_router = APIRouter(prefix="/api/fsp-cabinet", tags=["fsp-cabinet"])
employer = require_role(UserRole.employer)
analyst = require_role(UserRole.fsp_analyst, UserRole.admin)
TAGS = [{"name": "tariffs", "description": "Тарифы работодателя: «Старт» (бесплатно), «Найм» (цена по запросу, демо-счёт "
                                           "без суммы), «Партнёр ФСП» (выдаёт ФСП); лимит приглашений в месяц. Кандидатам "
                                           "всегда бесплатно. Без TARIFFS_ENABLED — 404 tariffs_disabled."}]
OFF = {404: err("Тарифы не включены на сервере (tariffs_disabled)")}
E_AUTH = {401: err("Не выполнен вход"), 403: err("Только для работодателя"), 409: err("Нет профиля компании"), **OFF}
F_AUTH = {401: err("Не выполнен вход"), 403: err("Только для роли «ФСП» или администратора"), **OFF}
Days = Query(None, ge=7, le=730, description="Период, дней (по умолчанию — всё время)")
log = logging.getLogger("app.tariffs")


class ChooseIn(BaseModel):
    plan: Literal["start", "hire", "partner"] = Field(description="start — «Старт», hire — «Найм» (демо-счёт); "
                                                                  "partner выдаёт только ФСП → 409 partner_by_fsp")


class PartnerRequestIn(BaseModel):
    note: str | None = Field(None, max_length=500, description="Чем компания хочет помочь ФСП (необязательно)")


class PartnerSetIn(BaseModel):
    action: Literal["grant", "revoke"]
    note: str | None = Field(None, max_length=300, description="Основание: спонсорский пакет, договор (необязательно)")


# ------------------------------------------------------------------ публично

@public_router.get("", summary="Тарифы работодателя: цены, лимиты, функции (публично)", responses=OFF)
def plans() -> dict:
    svc.need_on()
    return {"plans": P.public_plans(), "features": [{"key": k, "title": t} for k, t in P.FEATURES.items()],
            "price_is_stub": P.PRICE_IS_STUB, "candidates_free": True,
            "market_references": P.MARKET_REFERENCES, "market_note": P.MARKET_NOTE,
            "notes": ["Кандидатам — всегда бесплатно: тест, категория, приглашения, паспорт ФСП.",
                      "Цена «Найма» — по запросу. Оплаты на прототипе нет: при выборе «Найма» выставляется "
                      "демонстрационный счёт без суммы, тариф подключается сразу.",
                      "«Партнёр ФСП» входит в спонсорский пакет федерации; отборочные задачи компаний проводит ФСП "
                      "на своих соревнованиях."]}


# ------------------------------------------------------------------ работодатель

@employer_router.get("", summary="Тариф моей компании: лимит и остаток приглашений в месяц, демо-счета", responses=E_AUTH)
def my_tariff(user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    svc.need_on()
    return svc.state(db, my_company(db, user))


@employer_router.post("", summary="Сменить тариф: «Старт» или «Найм» (демонстрационный счёт, без оплаты)",
                      responses={**E_AUTH, 409: err("plan_same — тариф уже действует; partner_by_fsp — «Партнёр ФСП» "
                                                    "выдаёт ФСП; partner_active — уже партнёр ФСП")})
def choose(data: ChooseIn, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    svc.need_on()
    c = my_company(db, user)
    out = svc.choose(db, c, user, data.plan)
    log.info("tariff change company=%s plan=%s by=%s", c.id, data.plan, user.id)
    return out


@employer_router.post("/partner-request", summary="Заявка «Стать партнёром ФСП» (решает федерация в своём кабинете)",
                      responses={**E_AUTH, 409: err("partner_already — компания уже партнёр ФСП")})
def partner_request(data: PartnerRequestIn, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    svc.need_on()
    return svc.request_partner(db, my_company(db, user), data.note)


# ------------------------------------------------------------------ кабинет ФСП

@fsp_router.get("/partners", summary="Партнёры ФСП и заявки компаний на партнёрство", responses=F_AUTH)
def partners(user: User = Depends(analyst), db: Session = Depends(get_db)) -> dict:
    svc.need_on()
    return svc.partners_overview(db, user)


@fsp_router.get("/partners/search", summary="Найти компанию по названию или ИНН, чтобы выдать метку партнёра",
                responses=F_AUTH)
def partners_search(q: str = Query(min_length=3, max_length=100), user: User = Depends(analyst),
                    db: Session = Depends(get_db)) -> list[dict]:
    svc.need_on()
    return svc.search_companies(db, user, q)


@fsp_router.post("/partners/{company_id}", summary="Выдать или снять метку «Партнёр ФСП»",
                 responses={**F_AUTH, 403: err("Только для роли «ФСП» или администратора; partner_scope — компания "
                                               "чужой песочницы жюри"),
                            404: err("Компания не найдена или тарифы выключены")})
def partners_set(company_id: uuid.UUID, data: PartnerSetIn, user: User = Depends(analyst),
                 db: Session = Depends(get_db)) -> dict:
    svc.need_on()
    c = db.get(Company, company_id)
    if c is None:
        raise api_error(404, "company_not_found", "Компания не найдена")
    svc.set_partner(db, user, c, data.action == "grant", data.note)
    log.info("fsp partner %s company=%s by=%s role=%s", data.action, c.id, user.id, user.role.value)
    return svc.company_brief(db, c, user)


@fsp_router.get("/benefit", summary="«Польза для ФСП»: приглашения и наймы участников ФСП по регионам и направлениям, "
                                    "вклад партнёров, доля приглашений с ФСП-бонусом (агрегаты, K = 5)", responses=F_AUTH)
def benefit(days: int | None = Days, user: User = Depends(analyst), db: Session = Depends(get_db)) -> dict:
    svc.need_on()
    log.info("fsp_cabinet access user=%s role=%s section=benefit days=%s", user.id, user.role.value, days)
    return benefit_mod.compute(db, days)


@fsp_router.get("/benefit/export.csv", summary="«Польза для ФСП» в CSV (те же агрегаты, малые группы скрыты)",
                responses=F_AUTH)
def benefit_csv(days: int | None = Days, user: User = Depends(analyst), db: Session = Depends(get_db)) -> Response:
    svc.need_on()
    log.info("fsp_cabinet access user=%s role=%s section=export:benefit days=%s", user.id, user.role.value, days)
    rep = benefit_mod.compute(db, days)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(benefit_mod.CSV_COLS)
    for row in benefit_mod.csv_rows(rep):
        w.writerow(row)
    return Response(content="\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="fsp_benefit.csv"'})
