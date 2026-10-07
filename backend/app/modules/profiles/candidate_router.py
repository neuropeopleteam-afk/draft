"""Кабинет кандидата: опрос после регистрации, согласия 152-ФЗ, приватность, ФСП ID (заглушка),
демо-режим жюри, резюме PDF и стандартизированный PDF-профиль."""
from __future__ import annotations

from datetime import timedelta
import re
import threading
from typing import Literal

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db, utcnow
from app.core.deps import require_role
from app.core.enums import ConsentKind, FactSource, UserRole, WorkFormat
from app.core.errors import api_error, err
from app.core.ratelimit import SlidingWindow, hit
from app.core.legal import CONSENT_VERSION, consent_text
from app.modules.assessment.models import SurveyResponse, SurveyStackTag
from app.modules.auth.models import Consent, User
from app.modules.catalog.dictionary import ROLE_TITLES
from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import DIRECTIONS, STACK
from app.modules.profiles.facts import DEFAULT_PRIVACY, PRIVACY_TITLES, achievement_text, card, load_bundles, refresh_rating, set_t0_facts
from app.modules.profiles.models import CandidateProfile, CandidateResume

router = APIRouter(prefix="/api/me", tags=["candidate"])
# Резюме: попытки (в т. ч. неудачные) — не больше 10 в час на пользователя; одновременно — один разбор на воркер
# (процесс разбора ~40 МБ, предел 256 МБ — укладывается в лимит памяти api в docker-compose.yml)
_resume_attempts = SlidingWindow(10, 3600)
_resume_slots = threading.BoundedSemaphore(1)
legal_router = APIRouter(prefix="/api/legal", tags=["legal"])
AUTH = {401: err("Не выполнен вход"), 403: err("Только для кандидата")}
candidate = require_role(UserRole.candidate)


# ------------------------------------------------------------------ согласия и правовые тексты

@legal_router.get("/consents/{kind}", summary="Текст согласия (152-ФЗ) с реквизитами оператора",
                  responses={404: err("Нет такого согласия")})
def get_consent_text(kind: Literal["processing", "publication"]) -> dict:
    return consent_text(kind)


def _active_consent(db: Session, user_id, kind: ConsentKind) -> Consent | None:
    return db.scalar(select(Consent).where(Consent.user_id == user_id, Consent.kind == kind,
                                           Consent.revoked_at.is_(None)).order_by(Consent.granted_at.desc()).limit(1))


def _grant(db: Session, user_id, kind: ConsentKind) -> None:
    if _active_consent(db, user_id, kind) is None:
        db.add(Consent(user_id=user_id, kind=kind, document_version=CONSENT_VERSION))


def _sync_visibility(db: Session, profile: CandidateProfile) -> None:
    """Профиль виден работодателям, только если есть согласие на публикацию."""
    profile.visible_to_employers = _active_consent(db, profile.user_id, ConsentKind.publication) is not None


@router.get("/consents", summary="Мои согласия", responses=AUTH)
def my_consents(user: User = Depends(candidate), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Consent).where(Consent.user_id == user.id).order_by(Consent.granted_at.desc())).all()
    return [{"kind": c.kind.value, "version": c.document_version, "granted_at": c.granted_at.isoformat(),
             "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None} for c in rows]


@router.post("/consents/{kind}", summary="Дать согласие", status_code=201, responses=AUTH)
def grant_consent(kind: Literal["processing", "publication"], user: User = Depends(candidate),
                  db: Session = Depends(get_db)) -> dict:
    _grant(db, user.id, ConsentKind(kind))
    db.flush()
    _sync_visibility(db, db.get(CandidateProfile, user.id))
    db.commit()
    return {"kind": kind, "granted": True, "version": CONSENT_VERSION}


@router.delete("/consents/{kind}", summary="Отозвать согласие",
               description="Отзыв согласия на публикацию сразу убирает профиль из подборок и поиска. Отзыв согласия на "
                           "обработку означает удаление учётной записи — через обращение к оператору.",
               responses={**AUTH, 409: err("Согласие на обработку отзывается через удаление учётной записи")})
def revoke_consent(kind: Literal["processing", "publication"], user: User = Depends(candidate),
                   db: Session = Depends(get_db)) -> dict:
    if kind == "processing":
        from app.core.legal import OPERATOR

        raise api_error(409, "use_account_deletion",
                        f"Чтобы отозвать согласие на обработку, напишите оператору: {OPERATOR['email']}")
    c = _active_consent(db, user.id, ConsentKind.publication)
    if c:
        c.revoked_at = utcnow()
    db.flush()
    _sync_visibility(db, db.get(CandidateProfile, user.id))
    db.commit()
    return {"kind": kind, "granted": False}


# ------------------------------------------------------------------ опрос после регистрации

class StackItem(BaseModel):
    tag: str
    level: int = Field(2, ge=1, le=3, description="1 — знаком, 2 — работал, 3 — уверенно")


class OnboardingIn(BaseModel):
    direction: Literal["backend", "frontend", "data_ml", "qa", "security"]
    stack: list[StackItem] = Field(default_factory=list, max_length=40)
    experience_years: float = Field(ge=0, le=50)
    roles: list[str] = Field(default_factory=list, max_length=10)
    work_format: WorkFormat = WorkFormat.any
    city: str | None = Field(None, max_length=100)
    relocation: bool = False
    salary_min_hidden: int | None = Field(None, gt=0, le=10_000_000,
                                          description="Скрытый минимум: работодатель его не видит никогда")
    privacy: dict[str, bool] = Field(default_factory=dict, description="Видимость полей карточки (см. GET /onboarding)")
    consent_publication: bool = Field(description="Согласие на показ обезличенного профиля работодателям")
    fsp_id: str | None = Field(None, max_length=64, description="ФСП ID — заглушка до подключения ФСП ID (Keycloak)")

    @field_validator("stack")
    @classmethod
    def _known_tags(cls, v: list[StackItem]) -> list[StackItem]:
        bad = [s.tag for s in v if s.tag not in STACK]
        if bad:
            raise ValueError(f"Неизвестные стек-теги: {', '.join(bad)}")
        return v

    @field_validator("roles")
    @classmethod
    def _known_roles(cls, v: list[str]) -> list[str]:
        bad = [r for r in v if r not in ROLE_TITLES]
        if bad:
            raise ValueError(f"Неизвестные роли: {', '.join(bad)}")
        return v

    @field_validator("fsp_id")
    @classmethod
    def _fsp_format(cls, v: str | None) -> str | None:
        if v and not re.fullmatch(r"[A-Za-z0-9\-_]{4,64}", v.strip()):
            raise ValueError("ФСП ID: латинские буквы, цифры, дефис; 4–64 символа")
        return v.strip() if v else None


def _grade_hint(years: float) -> str:
    return "junior" if years < 1.5 else "middle" if years < 4.5 else "senior"


@router.get("/onboarding", summary="Опрос: текущие ответы и справочники", responses=AUTH)
def get_onboarding(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    p = db.get(CandidateProfile, user.id)
    survey = db.scalar(select(SurveyResponse).where(SurveyResponse.user_id == user.id)
                       .order_by(SurveyResponse.created_at.desc()).limit(1))
    stack = []
    if survey:
        stack = [{"tag": s.stack_tag_id, "level": s.self_level} for s in
                 db.scalars(select(SurveyStackTag).where(SurveyStackTag.survey_id == survey.id)).all()]
    return {
        "completed": p.onboarding_completed_at is not None,
        "answers": {
            "direction": survey.direction_id if survey else None,
            "stack": stack,
            "experience_years": float(p.experience_years) if p.experience_years is not None else None,
            "roles": p.roles or [], "work_format": p.work_format.value, "city": p.city, "relocation": p.relocation,
            "salary_min_hidden": p.salary_min_hidden, "privacy": {**DEFAULT_PRIVACY, **(p.privacy or {})},
            "consent_publication": _active_consent(db, user.id, ConsentKind.publication) is not None,
            "fsp_id": p.fsp_id_claimed,
        },
        "options": {
            "roles": [{"id": k, "title": v} for k, v in ROLE_TITLES.items()],
            "privacy_fields": [{"id": k, "title": v} for k, v in PRIVACY_TITLES.items()],
            "work_formats": [{"id": "remote", "title": "Удалённо"}, {"id": "hybrid", "title": "Гибрид"},
                             {"id": "office", "title": "Офис"}, {"id": "any", "title": "Любой"}],
        },
        "consent_publication_text": consent_text("publication"),
    }


@router.put("/onboarding", summary="Сохранить опрос (каждое сохранение — новая запись в истории опросов)",
            responses={**AUTH, 422: err("Ошибка валидации: неизвестные стек-теги или роли")})
def save_onboarding(data: OnboardingIn, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    p = db.get(CandidateProfile, user.id)
    survey = SurveyResponse(
        user_id=user.id, direction_id=data.direction, claimed_grade_id=_grade_hint(data.experience_years),
        experience_years=data.experience_years,
        answers={"stack": {s.tag: s.level for s in data.stack}, "roles": data.roles,
                 "work_format": data.work_format.value, "city": data.city},
    )
    db.add(survey)
    db.flush()
    for s in data.stack:
        db.add(SurveyStackTag(survey_id=survey.id, stack_tag_id=s.tag, self_level=s.level))
    p.experience_years = data.experience_years
    p.roles = data.roles
    p.work_format = data.work_format
    p.city = data.city
    p.relocation = data.relocation
    p.salary_min_hidden = data.salary_min_hidden
    p.privacy = {k: bool(v) for k, v in {**DEFAULT_PRIVACY, **data.privacy}.items() if k in DEFAULT_PRIVACY}
    p.fsp_id_claimed = data.fsp_id
    p.onboarding_completed_at = p.onboarding_completed_at or utcnow()
    set_t0_facts(db, user.id, FactSource.self_report, stack=[s.tag for s in data.stack], roles=data.roles,
                 experience_years=data.experience_years)
    if data.consent_publication:
        _grant(db, user.id, ConsentKind.publication)
    else:
        c = _active_consent(db, user.id, ConsentKind.publication)
        if c:
            c.revoked_at = utcnow()
    db.flush()
    _sync_visibility(db, p)
    db.commit()
    return {"saved": True, "survey_id": str(survey.id), "suggested_grade": survey.claimed_grade_id,
            "visible_to_employers": p.visible_to_employers}


# ------------------------------------------------------------------ приватность, ФСП, демо-режим жюри

class PrivacyIn(BaseModel):
    privacy: dict[str, bool]


@router.put("/privacy", summary="Видимость полей карточки для работодателя", responses=AUTH)
def set_privacy(data: PrivacyIn, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    p = db.get(CandidateProfile, user.id)
    p.privacy = {k: bool(v) for k, v in {**DEFAULT_PRIVACY, **(p.privacy or {}), **data.privacy}.items()
                 if k in DEFAULT_PRIVACY}
    db.commit()
    return {"privacy": p.privacy}


class JuryIn(BaseModel):
    enabled: bool


@router.put("/jury-mode", summary="Демо-режим жюри: снять правило «смена грейда не чаще раза в 90 дней»",
            description="Только для демо-учёток (вход жюри в один клик, users.is_demo): у живого кандидата правило "
                        "90 дней действует всегда. Число новых тестов в демо-режиме ограничено "
                        "(JURY_MAX_TEST_STARTS_PER_DAY за 24 часа), чтобы перезапусками нельзя было выкачать банк.",
            responses={**AUTH, 403: err("jury_mode_demo_only — не демо-учётка"),
                       409: err("Демо-режим отключён на этом сервере")})
def set_jury_mode(data: JuryIn, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    if not get_settings().jury_mode_available:
        raise api_error(409, "jury_mode_unavailable", "Демо-режим жюри отключён на этом сервере")
    if not user.is_demo:
        raise api_error(403, "jury_mode_demo_only",
                        "Демо-режим жюри доступен только демо-учёткам: для живых кандидатов правило 90 дней действует всегда")
    p = db.get(CandidateProfile, user.id)
    p.jury_mode = data.enabled
    db.commit()
    from app.modules.assessment.service import sandbox_quota

    return {"jury_mode": p.jury_mode, "sandbox_starts": sandbox_quota(db, user.email)}


@router.get("/fsp", summary="Паспорт ФСП: статус связи и достижения (T2)", responses=AUTH)
def my_fsp(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    b = load_bundles(db, [user.id])[user.id]
    c = card(b, {}, include_hidden=True)
    return {
        "fsp_id_claimed": b.profile.fsp_id_claimed,
        "linked": b.passport is not None,
        "link_source": b.passport.link_source.value if b.passport else None,
        "achievements": [{"text": achievement_text(a), "discipline": a.discipline, "verified": a.verified,
                          "event_id": a.event_id, "place": a.place, "date": a.event_date.isoformat() if a.event_date else None,
                          "evsk_code": a.evsk_code, "sport_rank": a.sport_rank, "team": a.team_name,
                          "team_result": a.team_result}
                         for a in b.achievements if a.verified],
        "rating": c["fsp"]["rating"],
        "sport_rank": b.passport.sport_rank if b.passport else None,
        "synced_at": b.passport.synced_at.isoformat() if b.passport and b.passport.synced_at else None,
        "registry": (b.passport.raw or {}).get("registry") if b.passport else None,
        "registry_warning": (b.passport.raw or {}).get("registry_warning") if b.passport else None,
        "identity_linked": bool(user.fsp_subject),
        "registry_sync_available": bool(b.passport and (b.passport.raw or {}).get("fsp_id")),
        "keycloak_ready": bool(get_settings().fsp_oidc_issuer),
        "note": ("Свяжите профиль через ФСП ID (демо-стенд Keycloak, OIDC): достижения придут с уровнем T2. "
                 if get_settings().fsp_oidc_issuer else
                 "Связь через ФСП ID (OIDC, Keycloak) появится после подключения реестра. ")
                + "Без истории ФСП — нейтральное состояние: бонуса нет, штрафа нет.",
    }


@router.post("/fsp/registry-sync", summary="Обновить достижения из API реестра для уже связанного паспорта",
             responses={**AUTH, 409: err("Сначала свяжите ФСП ID"), 503: err("Реестр недоступен")})
def sync_fsp_registry(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    from app.integrations.fsp_id.mapping import apply_claims
    from app.integrations.settings import get_isettings
    from app.modules.fsp.registry import fetch_passport, registry_claims
    from app.core.enums import FspLinkSource

    b = load_bundles(db, [user.id])[user.id]
    raw = b.passport.raw if b.passport else {}
    if not b.passport or not raw.get("fsp_id"):
        raise api_error(409, "fsp_identity_required", "Сначала свяжите ФСП ID: заявленный вручную номер не подтверждает принадлежность")
    if get_isettings().fsp_registry_mode == "claims":
        if b.passport.link_source != FspLinkSource.demo:
            raise api_error(409, "registry_not_configured", "API реестра не настроен; обновите паспорт входом через ФСП ID")
        from app.modules.fsp.registry import mock_passport
        passport = mock_passport(raw["fsp_id"])
    else:
        try:
            passport = fetch_passport(raw["fsp_id"])
        except Exception:
            raise api_error(503, "registry_unavailable", "Реестр временно недоступен. Достижения сохранены, попробуйте позже") from None
    demo = b.passport.link_source == FspLinkSource.demo
    source = b.passport.link_source
    subject = b.passport.fsp_subject
    apply_claims(db, user.id, {"sub": raw.get("oidc_sub") or subject or str(user.id),
                             "iss": raw.get("issuer") or "urn:demo:fsp-registry",
                             **registry_claims(passport),
                             "_registry": {"mode": "mock" if passport.demo else "external", "demo": passport.demo,
                                           "updated_at": passport.updated_at.isoformat()}})
    if demo:
        b.passport.link_source = source
        b.passport.fsp_subject = subject
    db.commit()
    return my_fsp(user, db)


class FspLinkIn(BaseModel):
    fsp_id: str = Field(min_length=4, max_length=64, pattern=r"^[A-Za-z0-9\-_]+$")


@router.post("/fsp/link", summary="Указать ФСП ID (заглушка: сохраняется как заявленный, без проверки реестром)",
             responses=AUTH)
def link_fsp(data: FspLinkIn, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    p = db.get(CandidateProfile, user.id)
    p.fsp_id_claimed = data.fsp_id
    db.commit()
    return {"fsp_id_claimed": p.fsp_id_claimed, "status": "pending_registry",
            "message": "ФСП ID сохранён. Достижения подтянутся из реестра после подключения ФСП ID."}


# ------------------------------------------------------------------ резюме PDF

@router.post(
    "/resume", status_code=201,
    summary="Загрузить PDF-резюме: текст → вырезание ФИО и контактов локально → поля (T0)",
    description="ФИО и контакты вырезаются на сервере (Natasha + регулярные выражения) до любой отправки текста в "
                "LLM. Исходный файл не сохраняется. Найденные контакты возвращаются только кандидату в этом ответе — "
                "чтобы он мог перенести их в профиль.",
    responses={**AUTH, 413: err("Файл больше 5 МБ"), 415: err("Нужен PDF"),
               422: err("Не удалось извлечь текст, больше 20 страниц или разбор дольше 10 с"),
               429: err("Слишком много загрузок"), 503: err("Сервер занят разбором других резюме")},
)
def upload_resume(file: UploadFile = File(...), user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    # Обычная функция (не async): FastAPI выполняет её в пуле потоков — разбор, NER и LLM не блокируют цикл событий
    # воркера. Сам PDF разбирается в отдельном процессе с тайм-аутом и лимитом памяти (pdf_to_text_safe).
    from app.modules.resume.extract import PdfError, extract, pdf_to_text_safe
    from app.modules.resume.pii import redact

    s = get_settings()
    hit(_resume_attempts, str(user.id), "resume_rate", "Слишком много попыток загрузки резюме")
    since = utcnow() - timedelta(hours=1)
    recent = db.scalar(select(func.count()).select_from(CandidateResume)
                       .where(CandidateResume.user_id == user.id, CandidateResume.created_at >= since)) or 0
    if recent >= s.resume_uploads_per_hour:
        raise api_error(429, "resume_rate", f"Не больше {s.resume_uploads_per_hour} загрузок резюме в час. Повторите позже")
    data = file.file.read(s.resume_max_bytes + 1)
    if len(data) > s.resume_max_bytes:
        raise api_error(413, "file_too_large", "Файл больше 5 МБ")
    if not data.startswith(b"%PDF"):
        raise api_error(415, "not_pdf", "Нужен файл PDF")
    if not _resume_slots.acquire(timeout=15):  # разбор длится секунды (тайм-аут 10 с) — очередь дождётся
        raise api_error(503, "resume_busy", "Сервер разбирает другие резюме, повторите через минуту")
    try:
        text, pages = pdf_to_text_safe(data, s.resume_max_pages, s.resume_parse_timeout_s, s.resume_parse_memory_mb)
    except PdfError as e:
        if e.code == "too_many_pages":
            raise api_error(422, "pdf_too_many_pages",
                            f"В PDF {e.pages} страниц — резюме должно быть не длиннее {s.resume_max_pages}") from None
        if e.code == "timeout":
            raise api_error(422, "pdf_timeout", "PDF слишком сложный: разбор не уложился в отведённое время") from None
        raise api_error(422, "pdf_unreadable", "Не удалось прочитать PDF") from None
    finally:
        _resume_slots.release()
    if len(text.strip()) < 30:
        raise api_error(422, "pdf_no_text", "В PDF нет текстового слоя (скан). Заполните профиль вручную")
    red = redact(text)
    fields = extract(red.text)
    r = CandidateResume(user_id=user.id, filename=(file.filename or "resume.pdf")[:255], size_bytes=len(data),
                        page_count=pages, text_redacted=red.text, pii_summary={**red.summary, "ner": red.ner_used},
                        extracted=fields, method=fields.get("method", "rules"))
    db.add(r)
    db.commit()
    found = red.found
    return {
        "id": str(r.id), "filename": r.filename, "pages": pages, "method": r.method,
        "pii_summary": r.pii_summary,
        "pii_found": {  # только в ответе, в БД не сохраняется
            "full_name": (found.get("person") or [None])[0],
            "email": (found.get("email") or [None])[0],
            "phone": (found.get("phone") or [None])[0],
            "telegram": (found.get("telegram") or [None])[0],
        },
        "extracted": fields,
        "text_preview": red.text[:1500],
        "evidence_level": "T0",
    }


@router.get("/resume", summary="Последнее загруженное резюме (текст без ПДн и извлечённые поля)", responses=AUTH)
def last_resume(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict | None:
    r = db.scalar(select(CandidateResume).where(CandidateResume.user_id == user.id)
                  .order_by(CandidateResume.created_at.desc()).limit(1))
    if r is None:
        return None
    return {"id": str(r.id), "filename": r.filename, "pages": r.page_count, "method": r.method,
            "pii_summary": r.pii_summary, "extracted": r.extracted, "text_preview": r.text_redacted[:1500],
            "created_at": r.created_at.isoformat(), "evidence_level": "T0"}


class ApplyIn(BaseModel):
    stack: bool = True
    roles: bool = True
    soft_skills: bool = True
    experience: bool = True


@router.post("/resume/{resume_id}/apply", summary="Перенести поля резюме в профиль (как факты T0)",
             responses={**AUTH, 404: err("Резюме не найдено")})
def apply_resume(resume_id: str, data: ApplyIn, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    import uuid as _uuid

    try:
        r = db.get(CandidateResume, _uuid.UUID(resume_id))
    except ValueError:
        r = None
    if r is None or r.user_id != user.id:
        raise api_error(404, "resume_not_found", "Резюме не найдено")
    ex = r.extracted or {}
    exp = ex.get("experience_years") if data.experience else None
    set_t0_facts(db, user.id, FactSource.resume,
                 stack=[s["tag"] for s in ex.get("stack", [])] if data.stack else [],
                 roles=[x["id"] for x in ex.get("roles", [])] if data.roles else [],
                 soft_skills=[x["id"] for x in ex.get("soft_skills", [])] if data.soft_skills else [],
                 experience_years=exp)
    p = db.get(CandidateProfile, user.id)
    if exp is not None and p.experience_years is None:
        p.experience_years = exp
    if data.roles:
        p.roles = list(dict.fromkeys((p.roles or []) + [x["id"] for x in ex.get("roles", [])]))
    db.commit()
    return {"applied": True}


# ------------------------------------------------------------------ PDF-профиль

def candidate_card_for(db: Session, user_id, *, include_hidden: bool) -> dict:
    b = load_bundles(db, [user_id])[user_id]
    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    return card(b, cats, include_hidden=include_hidden)


@router.get("/profile.pdf", summary="Стандартизированный PDF-профиль (с моими контактами)",
            responses={**AUTH, 200: {"content": {"application/pdf": {}}}}, response_class=Response)
def my_profile_pdf(user: User = Depends(candidate), db: Session = Depends(get_db)) -> Response:
    from app.modules.pdf.profile_pdf import render_profile

    refresh_rating(db, user.id)
    c = candidate_card_for(db, user.id, include_hidden=True)
    p = db.get(CandidateProfile, user.id)
    from app.modules.assessment.feedback import build as build_feedback

    try:
        growth = build_feedback(db, user.id)
    except Exception:  # noqa: BLE001 — блок обратной связи необязателен: PDF важнее
        import logging

        logging.getLogger("pdf").exception("Обратная связь для PDF не собралась")
        growth = None
    pdf = render_profile(c, contacts={"full_name": p.full_name, "email": user.email, "phone": p.phone,
                                      "telegram": p.telegram}, growth=growth)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="profile-{p.public_ref}.pdf"'})


@router.get("/card", summary="Как меня видит работодатель (обезличенная карточка)", responses=AUTH)
def my_card(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    return {**candidate_card_for(db, user.id, include_hidden=False), "directions": DIRECTIONS}
