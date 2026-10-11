"""API взаимного подбора: работодатель (индикатор, отзывы, новые версии, ссылки), кандидат (интересы, «почему меня
выбрали»), публичная страница руководителя по токену (только чтение, без ПДн)."""
from __future__ import annotations

from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.core.ratelimit import SlidingWindow, client_ip, hit
from app.modules.auth.models import User
from app.modules.catalog.seed_data import known_tag
from app.modules.invitations.models import Invitation
from app.modules.invitations.service import profile_by_ref
from app.modules.jury import scope as jury_scope
from app.modules.matching.router import _own_need, _version_out, my_company
from app.modules.mutual import fit as fitm
from app.modules.mutual import service as svc
from app.modules.mutual.models import CandidatePreference, SelectionShare

TAGS = [{"name": "mutual", "description": "Взаимный подбор (Н9): насколько предложение подходит кандидату; обратная "
                                          "связь по подборке и новые версии (Н2); ссылка для нанимающего "
                                          "руководителя — только чтение, без ПДн, 7 дней (Н3)"}]
employer_router = APIRouter(prefix="/api/employer", tags=["mutual"])
candidate_router = APIRouter(prefix="/api/candidate", tags=["mutual"])
public_router = APIRouter(prefix="/api/share", tags=["mutual"])
employer = require_role(UserRole.employer)
candidate = require_role(UserRole.candidate)
E_AUTH = {401: err("Не выполнен вход"), 403: err("Только для работодателя"), 404: err("Потребность или версия не найдена"),
          409: err("Нет профиля компании")}
C_AUTH = {401: err("Не выполнен вход"), 403: err("Только для кандидата")}
_react_ip = SlidingWindow(60, 600)
_view_ip = SlidingWindow(120, 600)


class FeedbackIn(BaseModel):
    ref: str = Field(min_length=3, max_length=16, description="Обезличенный идентификатор кандидата")
    version: int = Field(ge=1, description="Версия подборки, в которой стоит отметка")
    verdict: Literal["fit", "unfit"]
    reason: Literal["skill", "grade", "format", "salary", "other"] | None = Field(
        None, description="Причина «не подходит»: навык, грейд, формат, зарплата, другое")
    comment: str | None = Field(None, max_length=300)


class SimilarIn(BaseModel):
    ref: str = Field(min_length=3, max_length=16)


class ShareIn(BaseModel):
    version: int | None = Field(None, ge=1, description="Версия подборки; по умолчанию — последняя")
    label: str | None = Field(None, max_length=100, description="Для кого ссылка (видно только рекрутеру и руководителю)")


class OfferCheckIn(BaseModel):
    candidate_ref: str = Field(min_length=3, max_length=16)
    need_id: uuid.UUID | None = None
    salary_from: int | None = Field(None, gt=0, le=10_000_000)
    salary_to: int = Field(gt=0, le=10_000_000, description="Верх вилки — с ним сравнивается скрытый минимум")
    salary_basis: Literal["gross", "net"] = Field("gross", description="Основание вилки: до вычета НДФЛ (gross) или "
                                                                       "на руки (net) — как в приглашении (И4)")

    @model_validator(mode="after")
    def _range(self):
        if self.salary_from and self.salary_from > self.salary_to:
            raise ValueError("Нижняя граница вилки больше верхней")
        return self


class ReactionIn(BaseModel):
    ref: str = Field(min_length=3, max_length=16)
    verdict: Literal["interesting", "no"]
    comment: str | None = Field(None, max_length=500)
    author: str | None = Field(None, max_length=80, description="Как подписать отметку (необязательно)")


class PrefsIn(BaseModel):
    offers_status: Literal["active", "open", "not_looking"] | None = None
    interest_tags: list[str] = Field(default_factory=list, max_length=20)
    interest_tasks: list[str] = Field(default_factory=list, max_length=len(fitm.TASKS))
    salary_signal: bool = True

    @field_validator("interest_tags")
    @classmethod
    def _tags(cls, v):
        bad = [t for t in v if not known_tag(t)]
        if bad:
            raise ValueError(f"Неизвестные технологии: {', '.join(bad[:5])}")
        return v

    @field_validator("interest_tasks")
    @classmethod
    def _tasks(cls, v):
        bad = [t for t in v if t not in fitm.TASKS]
        if bad:
            raise ValueError(f"Неизвестные типы задач: {', '.join(bad[:5])}")
        return v


def _need_version(db: Session, user: User, need_id: uuid.UUID, version: int | None = None):
    company = my_company(db, user)
    need = _own_need(db, company, need_id)
    if version is None:
        from app.modules.matching.models import SelectionVersion
        from sqlalchemy import func

        version = db.scalar(select(func.max(SelectionVersion.version)).where(SelectionVersion.need_id == need.id))
        if not version:
            raise api_error(404, "version_not_found", "У потребности ещё нет подборки")
    return company, need, svc.own_version(db, need, version)


# ------------------------------------------------------------------ работодатель

@employer_router.get("/needs/{need_id}/selections/{version}/mutual", responses=E_AUTH,
                     summary="Взаимный подбор: индикатор для каждого кандидата версии, отзывы и отметки руководителя")
def selection_mutual(need_id: uuid.UUID, version: int, user: User = Depends(employer), db: Session = Depends(get_db)):
    company, need, v = _need_version(db, user, need_id, version)
    return svc.version_mutual(db, company, need, v)


@employer_router.put("/needs/{need_id}/feedback", responses=E_AUTH,
                     summary="Отзыв о кандидате подборки: подходит / не подходит + причина")
def put_feedback(need_id: uuid.UUID, body: FeedbackIn, user: User = Depends(employer), db: Session = Depends(get_db)):
    _, need, v = _need_version(db, user, need_id, body.version)
    return svc.set_feedback(db, user, need, v, body.ref, body.verdict, body.reason, body.comment)


@employer_router.delete("/needs/{need_id}/feedback/{ref}", responses=E_AUTH, status_code=204,
                        summary="Снять отзыв о кандидате")
def delete_feedback(need_id: uuid.UUID, ref: str, user: User = Depends(employer), db: Session = Depends(get_db)):
    need = _own_need(db, my_company(db, user), need_id)
    svc.delete_feedback(db, need, ref)


@employer_router.post("/needs/{need_id}/selections/{version}/refine", responses=E_AUTH, status_code=201,
                      summary="Новая версия по отзывам: без «не подходит», причины — в фильтры (прежняя версия сохраняется)")
def refine(need_id: uuid.UUID, version: int, user: User = Depends(employer), db: Session = Depends(get_db)):
    _, need, v = _need_version(db, user, need_id, version)
    return _version_out(db, svc.refine_by_feedback(db, user, need, v))


@employer_router.post("/needs/{need_id}/selections/{version}/similar", responses=E_AUTH, status_code=201,
                      summary="Ещё похожих на этого кандидата — новой версией подборки")
def similar(need_id: uuid.UUID, version: int, body: SimilarIn, user: User = Depends(employer),
            db: Session = Depends(get_db)):
    _, need, v = _need_version(db, user, need_id, version)
    return _version_out(db, svc.similar(db, user, need, v, body.ref))


@employer_router.post("/needs/{need_id}/shares", responses=E_AUTH, status_code=201,
                      summary="Ссылка на подборку для нанимающего руководителя (токен показывается один раз)")
def create_share(need_id: uuid.UUID, body: ShareIn, user: User = Depends(employer), db: Session = Depends(get_db)):
    _, need, v = _need_version(db, user, need_id, body.version)
    return svc.create_share(db, user, need, v, body.label)


@employer_router.get("/needs/{need_id}/shares", responses=E_AUTH, summary="Ссылки руководителю и их отметки")
def list_shares(need_id: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)):
    need = _own_need(db, my_company(db, user), need_id)
    rows = db.scalars(select(SelectionShare).where(SelectionShare.need_id == need.id)
                      .order_by(SelectionShare.created_at.desc())).all()
    return [svc.share_out(db, s) for s in rows]


@employer_router.post("/needs/{need_id}/shares/{share_id}/revoke", responses=E_AUTH, summary="Отозвать ссылку")
def revoke_share(need_id: uuid.UUID, share_id: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)):
    need = _own_need(db, my_company(db, user), need_id)
    s = db.get(SelectionShare, share_id)
    if s is None or s.need_id != need.id:
        raise api_error(404, "share_not_found", "Ссылка не найдена")
    if not s.revoked_at:
        from app.core.db import utcnow

        s.revoked_at = utcnow()
        db.commit()
    return svc.share_out(db, s)


@employer_router.post("/mutual/offer-check", responses={**E_AUTH, 404: err("Кандидат не найден")},
                      summary="Подсказка в форме приглашения до отправки: подходит ли предложение кандидату")
def offer_check(body: OfferCheckIn, user: User = Depends(employer), db: Session = Depends(get_db)):
    company = my_company(db, user)
    p = profile_by_ref(db, body.candidate_ref)
    owner = db.get(User, p.user_id)
    if not jury_scope.visible(owner.email if owner else None):
        raise api_error(404, "candidate_not_found", "Кандидат не найден")
    need = _own_need(db, company, body.need_id) if body.need_id else None
    return svc.offer_check(db, company, p, body.salary_to, need, body.salary_basis)


# ------------------------------------------------------------------ кандидат

def _prefs_payload(db: Session, user: User) -> dict:
    from app.modules.profiles.facts import load_bundles

    b = load_bundles(db, [user.id]).get(user.id)
    return {"preferences": svc.prefs_dict(db.get(CandidatePreference, user.id)),
            "survey_stack": sorted(b.stack_t0) if b else [],
            "options": {"offers": fitm.OFFERS, "tasks": {k: t for k, (t, _) in fitm.TASKS.items()}},
            "note": "Работодатель видит только итог: «предложение подходит / частично / вероятно, откажет» и строку "
                    "объяснения. Сумма вашего минимума зарплаты не показывается — только «вилка в ожиданиях / ниже "
                    "ожиданий», пока это разрешено (включено по умолчанию, выключается здесь)."}


@candidate_router.get("/preferences", responses=C_AUTH, summary="Мои интересы для взаимного подбора")
def get_prefs(user: User = Depends(candidate), db: Session = Depends(get_db)):
    return _prefs_payload(db, user)


@candidate_router.put("/preferences", responses=C_AUTH, summary="Сохранить интересы: готовность, стек, задачи")
def put_prefs(body: PrefsIn, user: User = Depends(candidate), db: Session = Depends(get_db)):
    svc.save_prefs(db, user.id, body.model_dump())
    return _prefs_payload(db, user)


@candidate_router.get("/invitations/{inv_id}/why", responses={**C_AUTH, 404: err("Приглашение не найдено")},
                      summary="Почему меня выбрали: требования, место в подборке, совпадение условий")
def why(inv_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)):
    inv = db.get(Invitation, inv_id)
    if inv is None or inv.candidate_user_id != user.id:
        raise api_error(404, "invitation_not_found", "Приглашение не найдено")
    return svc.why(db, inv)


# ------------------------------------------------------------------ руководитель по ссылке (без входа)

@public_router.get("/{token}", responses={404: err("Ссылка не найдена"), 410: err("Ссылка отозвана или истекла")},
                   summary="Подборка по ссылке руководителя: только чтение, без ПДн")
def public_share(token: str, request: Request, db: Session = Depends(get_db)):
    hit(_view_ip, client_ip(request), "share_rate_limited", "Слишком много запросов — повторите позже")
    return svc.public_view(db, svc.share_by_token(db, token))


@public_router.post("/{token}/reactions", responses={404: err("Ссылка не найдена"), 410: err("Ссылка отозвана или истекла")},
                    summary="Отметка руководителя: интересно / нет с комментарием — рекрутер увидит")
def public_react(token: str, body: ReactionIn, request: Request, db: Session = Depends(get_db)):
    hit(_react_ip, client_ip(request), "share_rate_limited", "Слишком много отметок с этого адреса — повторите позже")
    return svc.react(db, svc.share_by_token(db, token), body.ref, body.verdict, body.comment, body.author)
