"""Кабинет работодателя: потребности, подборки с версиями, поиск по базе, обезличенная карточка кандидата."""
from __future__ import annotations

from typing import Literal
import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db, release
from app.core.deps import require_role
from app.core.enums import NeedStatus, UserRole
from app.core.errors import api_error, err
from app.core.ratelimit import SlidingWindow, hit
from app.modules.auth.models import User
from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import GRADES, tag_title
from app.modules.invitations.models import Invitation, Probe
from app.modules.invitations.service import (
    INVITATION_COOLDOWN_DAYS,
    candidate_contacts,
    contacts_revealed,
    cooldown_until,
    profile_by_ref,
)
from app.modules.matching import ranking
from app.modules.matching.models import EmployerNeed, SelectionVersion
from app.modules.matching import compare as compare_mod
from app.modules.matching import fast_parse
from app.modules.matching.need_parser import bias_report, normalize, parse_need, text_notes
from app.modules.matching import whatif
from app.modules.mydata import interest  # обезличенная отметка интереса для кандидата (md01)
from app.modules.profiles.facts import card, load_bundles
from app.modules.profiles.models import Company, EmployerProfile
from app.modules.catalog.seed_data import GRADE_ORDER as _GRADE_ORDER

# уровни платформы: 4 (Стажёр–Senior), с флагом GRADES_EXT_ENABLED — 6 (+ Lead, Principal; catalog.levels)
GradeId = Literal[_GRADE_ORDER]  # type: ignore[valid-type]

router = APIRouter(prefix="/api/employer", tags=["employer"])
AUTH = {401: err("Не выполнен вход"), 403: err("Только для работодателя"),
        409: err("company_required — сначала заполните профиль компании")}
employer = require_role(UserRole.employer)


def my_company(db: Session, user: User) -> Company:
    ep = db.get(EmployerProfile, user.id)
    c = db.get(Company, ep.company_id) if ep and ep.company_id else None
    if c is None:
        raise api_error(409, "company_required", "Сначала заполните профиль компании")
    return c


# ------------------------------------------------------------------ схемы

class Evidence(BaseModel):
    """Цитата: фрагмент текста работодателя, на основании которого извлечено требование."""
    quote: str = Field(max_length=300)
    start: int | None = Field(None, ge=0)
    end: int | None = Field(None, ge=0)
    context: str | None = Field(None, max_length=300)
    source: Literal["rules", "llm"] | None = None
    basis: str | None = Field(None, max_length=30)
    model: str | None = Field(None, max_length=60, description="Какая модель нашла цитату (source=llm)")
    confirmed_by: str | None = Field(None, max_length=60, description="Тег словаря подтверждён моделью")


ReviewStatus = Literal["extracted", "confirmed", "edited"]


class UnknownTerm(BaseModel):
    """Требование вне справочника («вне справочника — проверить вручную», И27): в подбор не входит, не теряется."""
    term: str = Field(max_length=80)
    evidence: Evidence | None = None


class StackReq(BaseModel):
    tag: str
    weight: float = Field(1.0, ge=0.05, le=1.0)
    evidence: Evidence | None = None
    status: Literal["extracted", "confirmed", "edited", "manual"] | None = Field(
        None, description="extracted — извлечено, confirmed — подтверждено, edited — изменено, manual — добавлено вручную")


class Requirements(BaseModel):
    direction: Literal["backend", "frontend", "data_ml", "qa", "security"] | None = None
    grade: GradeId | None = None
    stack_required: list[StackReq] = Field(default_factory=list, max_length=20)
    stack_desired: list[StackReq] = Field(default_factory=list, max_length=20)
    experience_years_min: float | None = Field(None, ge=0, le=30)
    work_format: Literal["office", "hybrid", "remote", "any"] | None = None
    work_formats: list[Literal["office", "hybrid", "remote"]] | None = Field(None, max_length=3)
    city: str | None = Field(None, max_length=100)
    salary_from: int | None = Field(None, gt=0)
    salary_to: int | None = Field(None, gt=0)
    evidence: dict[Literal["direction", "grade", "experience_years_min", "work_format", "salary", "city"], Evidence | None] | None = None
    review: dict[Literal["direction", "grade", "experience_years_min", "work_format", "salary", "city"], ReviewStatus] | None = None
    unknown_terms: list[UnknownTerm] | None = Field(None, max_length=20, description="Вне справочника: сохраняются "
                                                    "найденные моделью (source=llm) с цитатой из текста")

    @model_validator(mode="after")
    def _range(self):
        if self.salary_from and self.salary_to and self.salary_from > self.salary_to:
            raise ValueError("Нижняя граница вилки больше верхней")
        return self


class ParseIn(BaseModel):
    text: str = Field(min_length=10, max_length=8000)
    direction: str | None = None
    grade: str | None = None
    mode: Literal["fast", "full"] = Field("fast", description="fast — словарь сразу, модель в фоне (опрос "
                                          "GET /needs/parse/{job_id}); full — прежний синхронный разбор с моделью")


class NeedIn(BaseModel):
    title: str | None = Field(None, max_length=200)
    text: str = Field(min_length=10, max_length=8000)
    requirements: Requirements | None = Field(None, description="Отредактированные требования; если нет — разбор текста")


class NeedPatch(BaseModel):
    title: str | None = Field(None, max_length=200)
    requirements: Requirements | None = None
    status: Literal["draft", "active", "closed"] | None = None


class Filters(BaseModel):
    categories: list[str] | None = Field(None, description="Категории (по умолчанию — точное совпадение)")
    stack_t1: list[str] | None = Field(None, description="Только с подтверждёнными (T1) навыками")
    stack_any: list[str] | None = Field(None, description="Навык заявлен (T0) или подтверждён (T1)")
    fsp_only: bool = False
    confirmed_only: bool = Field(False, description="Только подтверждённый грейд: без «Junior (предварительно)» и без "
                                                    "кандидатов со статусом «грейд не подтверждён»")
    work_format: Literal["office", "hybrid", "remote"] | None = None
    work_formats: list[Literal["office", "hybrid", "remote"]] | None = Field(None, max_length=3)
    city: str | None = Field(None, max_length=100)
    experience_min: float | None = Field(None, ge=0, le=30)
    min_score: float | None = Field(None, ge=0, le=1)
    relaxation: str | None = Field(None, max_length=160, description="Подпись версии, созданной из «Что если» (И18)")
    conditions_off: bool = Field(False, description="Ф2: не применять условия потребности (формат, город) — показать "
                                                    "всех; по умолчанию условия применяются сразу")
    exclude_refs: list[str] | None = Field(None, max_length=200, description="Исключить отмеченных «не подходит» (Н2)")


class SelectionIn(BaseModel):
    filters: Filters = Field(default_factory=Filters)
    parent_version: int | None = None
    requirements: Requirements | None = Field(None, description="Уточнённые требования для новой версии")


# ------------------------------------------------------------------ помощники

def _req_dict(r: Requirements | dict, text: str) -> dict:
    """Требования от клиента → канон. Находки фильтра ст. 64 ТК РФ считаются на сервере по тексту потребности."""
    d = r.model_dump() if isinstance(r, Requirements) else dict(r)
    req = normalize({**d, "stack_required": [dict(x) for x in d.get("stack_required") or []],
                     "stack_desired": [dict(x) for x in d.get("stack_desired") or []]},
                    method=d.get("method", "manual"))
    req["bias"], req["suggested_text"] = bias_report(text, req)
    from app.modules.matching.coverage import coverage

    cov = coverage(text)
    if cov:
        req["coverage"] = cov
    # И18: вне справочника, исключённое отрицанием, вилка не в рублях; И27: найденное моделью вне справочника
    req.update(text_notes(text, req, extra=d.get("unknown_terms")))
    return req


def _own_need(db: Session, company: Company, need_id: uuid.UUID) -> EmployerNeed:
    n = db.get(EmployerNeed, need_id)
    if n is None or n.company_id != company.id:
        raise api_error(404, "need_not_found", "Потребность не найдена")
    return n


def _need_title(req: dict) -> str:
    """Автоимя потребности. Ф6 (В9): не только категория — разные тексты не сливаются в одно «Backend · Middle»:
    категория + до трёх главных обязательных навыков (по весу), а у профессии вне справочника (coverage) — её название
    и ближайшая категория, по которой идёт подбор."""
    direction = {"backend": "Backend", "frontend": "Frontend", "data_ml": "Data/ML", "qa": "QA",
                 "security": "ИБ"}.get(req.get("direction") or "")
    grade = GRADES.get(req.get("grade") or "")
    cov = req.get("coverage") or {}
    if cov.get("title"):
        head = " · ".join(x for x in (cov["title"], grade) if x)
        return f"{head} (ближайшая категория — {direction})" if direction else head
    base = " · ".join(x for x in (direction, grade) if x)
    items = sorted(req.get("stack_required") or [], key=lambda i: -float(i.get("weight") or 0))[:3] \
        or sorted(req.get("stack_desired") or [], key=lambda i: -float(i.get("weight") or 0))[:2]
    skills = ", ".join(tag_title(i["tag"]) for i in items if i.get("tag"))
    return " — ".join(x for x in (base, skills) if x) or "Потребность"


def _make_version(db: Session, need: EmployerNeed, user: User, filters: dict, parent: int | None,
                  req: dict | None = None) -> SelectionVersion:
    last = db.scalar(select(func.max(SelectionVersion.version)).where(SelectionVersion.need_id == need.id)) or 0
    req = req or need.requirements
    sel = ranking.build_selection(db, req, filters)
    # Ф2: снимок версии (категории со счётчиками, условия, «скрыто условиями») — в filters["_meta"]: открытие
    # сохранённой версии отдаёт его без пересчёта
    v = SelectionVersion(need_id=need.id, version=last + 1, parent_version=parent,
                         filters={**filters, META: sel["meta"]}, requirements=req,
                         results=sel["results"], algorithm_version=sel["algorithm"], created_by=user.id)
    db.add(v)
    db.commit()
    interest.record_selection(db, need.company_id, need.id, v.results)  # кандидату — «в M подборках», без названий
    return v


def _result_status(r: dict) -> str:
    """Статус грейда результата подборки (у версий до единой модели статуса — по карточке)."""
    if r.get("grade_status"):
        return r["grade_status"]
    c = r.get("card") or {}
    if (c.get("status") or {}).get("status"):
        return c["status"]["status"]
    return "provisional" if (c.get("category") or {}).get("provisional") else "confirmed"


META = "_meta"


def split_filters(stored: dict | None) -> tuple[dict, dict | None]:
    """Фильтры версии без снимка _meta (Ф2) и сам снимок."""
    f = dict(stored or {})
    return f, f.pop(META, None)


def _version_out(db: Session, v: SelectionVersion) -> dict:
    filters, meta = split_filters(v.filters)
    if meta and meta.get("categories") is not None:
        recs = meta["categories"]  # снимок на момент расчёта версии — без пересчёта пула (Ф2, п. 4)
    else:  # версии до Ф2: считаем и сохраняем снимок, следующие открытия — без пересчёта
        cats = {c.id: c for c in db.scalars(select(Category)).all()}
        (counts, prov), unc = ranking.pool_counts(db), ranking.unconfirmed_counts(db)
        recs = ranking.recommended_categories(v.requirements, counts, cats)
        for r in recs:
            r["provisional"], r["unconfirmed"] = prov.get(r["id"], 0), unc.get(r["id"], 0)
        meta = {**(meta or {}), "categories": recs}
        v.filters = {**filters, META: meta}
        db.commit()
    st = [_result_status(r) for r in v.results]
    return {
        "version": v.version, "parent_version": v.parent_version, "created_at": v.created_at.isoformat(),
        "filters": filters, "requirements": v.requirements, "algorithm": v.algorithm_version,
        # Ф2: условия потребности, применённые к версии, и сколько кандидатов они скрыли (None — версия до Ф2)
        "conditions": meta.get("conditions"), "must_first": meta.get("must_first"),
        "core": meta.get("core"),  # Я1: ядро роли версии (None — у потребности нет ядра или версия до Я1)
        "weights": ranking.WEIGHTS, "levels": ranking.LEVELS, "provisional_penalty": ranking.PROVISIONAL_PENALTY,
        "categories": recs,
        "total": len(v.results), "results": v.results,
        # единая модель статуса: сколько в выдаче подтверждённых / предварительных / не подтверждённых
        "confirmed_matched": sum(1 for x in st if x == "confirmed"),
        "provisional_matched": sum(1 for x in st if x == "provisional"),
        "unconfirmed_matched": sum(1 for x in st if x == "unconfirmed"),
    }


def _need_out(db: Session, n: EmployerNeed) -> dict:
    versions = db.execute(select(SelectionVersion.version, SelectionVersion.parent_version, SelectionVersion.created_at,
                                 SelectionVersion.filters, func.json_array_length(SelectionVersion.results)
                                 if db.bind.dialect.name == "sqlite" else func.jsonb_array_length(SelectionVersion.results))
                          .where(SelectionVersion.need_id == n.id).order_by(SelectionVersion.version)).all()
    return {"id": str(n.id), "title": n.title, "raw_text": n.raw_text, "requirements": n.requirements,
            "status": n.status.value, "created_at": n.created_at.isoformat(),
            "versions": [{"version": a, "parent_version": b, "created_at": c.isoformat(),
                          "filters": split_filters(d)[0], "total": e}
                         for a, b, c, d, e in versions]}


# ------------------------------------------------------------------ потребности

@router.post("/needs/parse", summary="Разобрать потребность из текста (предпросмотр, без сохранения)",
             description="Детерминированный разбор по словарю стек-тегов и правилам работает всегда; при настроенном "
                         "LLM ответ модели уточняет разбор и проходит ту же нормализацию. Контакты из текста "
                         "вырезаются до отправки в LLM. У каждого требования — цитата из текста (evidence: start, "
                         "end, quote); требование LLM без найденной в тексте цитаты отбрасывается. bias — фрагменты, "
                         "нарушающие ст. 64 ТК РФ (возраст, пол, семья, внешность, место жительства…), с предложением "
                         "переписать через навыки; из них требования не извлекаются, в ранжирование они не попадают. "
                         "mode=fast (по умолчанию, И27): ответ словарём сразу, модель — в фоне: parse_job.id для "
                         "опроса GET /needs/parse/{job_id}, llm.pending=true; тот же текст повторно — из кэша "
                         "(llm.cached=true, delta — что добавила модель). mode=full — синхронно, как раньше.",
             responses=AUTH)
def parse(data: ParseIn, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    if data.mode == "full":
        release(db)  # синхронный разбор с моделью — секунды без БД: соединение в пул
        return parse_need(data.text, data.direction, data.grade, full=True)
    return fast_parse.start(db, data.text, data.direction, data.grade, user.id)


@router.get("/needs/parse/{job_id}", summary="Фоновое уточнение разбора моделью: состояние и итог (И27)",
            description="status pending → done | failed. done: result — итоговый разбор (словарь + модель), delta — "
                        "что изменила модель (add_tag, set_scalar, confirm_tag применяются, пока работодатель не "
                        "правил поля; remove_tag и suggest_scalar — только предложения). failed: модель не ответила, "
                        "result — разбор словарём, llm.reason — причина.",
            responses={**AUTH, 404: err("Задача не найдена или устарела")})
def parse_job(job_id: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    out = fast_parse.get(db, job_id, user.id)
    if out is None:
        raise api_error(404, "parse_job_not_found", "Задача разбора не найдена или устарела")
    return out


# Ф5: текст потребности из файла вакансии (PDF, DOCX, TXT) → тот же разбор /needs/parse на клиенте
_need_file_attempts = SlidingWindow(30, 3600)


@router.post("/needs/file", summary="Текст потребности из файла вакансии (PDF, DOCX, TXT), без сохранения",
             description="Тип определяется по содержимому, не по имени. PDF и DOCX разбираются в отдельном процессе с "
                         "тайм-аутом и лимитом памяти (DOCX — stdlib: zipfile + expat, защита от zip-бомб и DTD, файлы "
                         "с макросами отклоняются), TXT — UTF-8/UTF-16/CP1251. Ответ — текст для поля «Кого вы ищете»: "
                         "работодатель видит и правит его, разбор — обычный POST /needs/parse (контакты вырезаются до "
                         "LLM). Файл не сохраняется. Длиннее предела поля — обрезается по абзацу, truncated = true.",
             responses={**AUTH, 413: err("Файл больше 5 МБ"), 415: err("Нужен PDF, DOCX или TXT; DOCX с макросами"),
                        422: err("Не удалось извлечь текст: повреждён, скан, zip-бомба, больше 20 страниц"),
                        429: err("Слишком много загрузок"), 503: err("Сервер занят разбором других файлов")})
def need_from_file(file: UploadFile = File(...), user: User = Depends(employer)) -> dict:
    from app.core.config import get_settings
    from app.modules.resume.files import (
        KIND_TITLES, FileTextError, clean_text, clip, file_to_text, no_text_error, safe_filename,
    )

    s = get_settings()
    hit(_need_file_attempts, str(user.id), "need_file_rate", "Слишком много загрузок файлов")
    limit = next(m.max_length for m in ParseIn.model_fields["text"].metadata if getattr(m, "max_length", None))
    try:
        ft = file_to_text(file.file.read(s.resume_max_bytes + 1), ("pdf", "docx", "txt"), max_bytes=s.resume_max_bytes,
                          max_pages=s.resume_max_pages, timeout_s=s.resume_parse_timeout_s,
                          memory_mb=s.resume_parse_memory_mb)
        text = clean_text(ft.text, headings=True)
        if len(text) < 30:
            raise no_text_error(ft.kind)
    except FileTextError as e:
        raise api_error(e.status, e.code, e.message) from None
    clipped, truncated = clip(text, limit)
    return {"text": clipped, "filename": safe_filename(file.filename, f"vacancy.{ft.kind}"), "kind": ft.kind,
            "kind_title": KIND_TITLES[ft.kind], "pages": ft.pages, "chars": len(clipped), "chars_total": len(text),
            "truncated": truncated, "limit": limit}


@router.post("/needs", status_code=201, summary="Создать потребность и первую версию подборки", responses=AUTH)
def create_need(data: NeedIn, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    if not data.requirements:
        release(db)  # разбор текста (возможно, с моделью) — без БД: соединение в пул
    req = _req_dict(data.requirements, data.text) if data.requirements else parse_need(data.text)
    n = EmployerNeed(company_id=c.id, created_by=user.id, title=(data.title or _need_title(req))[:200],
                     raw_text=data.text, requirements=req, direction_id=req.get("direction"),
                     grade_id=req.get("grade"), salary_from=req.get("salary_from"), salary_to=req.get("salary_to"),
                     status=NeedStatus.active)
    db.add(n)
    db.commit()
    _make_version(db, n, user, {}, None)
    return _need_out(db, n)


@router.get("/needs", summary="Мои потребности", responses=AUTH)
def list_needs(user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    c = my_company(db, user)
    rows = db.scalars(select(EmployerNeed).where(EmployerNeed.company_id == c.id)
                      .order_by(EmployerNeed.created_at.desc())).all()
    return [_need_out(db, n) for n in rows]


@router.get("/needs/{need_id}", summary="Потребность и список версий подборки",
            responses={**AUTH, 404: err("Потребность не найдена")})
def get_need(need_id: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    return _need_out(db, _own_need(db, my_company(db, user), need_id))


@router.patch("/needs/{need_id}", summary="Изменить потребность (подборки прежних версий сохраняются)",
              responses={**AUTH, 404: err("Потребность не найдена"), 422: err("Ошибка валидации")})
def patch_need(need_id: uuid.UUID, data: NeedPatch, user: User = Depends(employer),
               db: Session = Depends(get_db)) -> dict:
    n = _own_need(db, my_company(db, user), need_id)
    if data.title:
        n.title = data.title
    if data.status:
        n.status = NeedStatus(data.status)
    if data.requirements:
        req = _req_dict(data.requirements, n.raw_text)
        n.requirements, n.direction_id, n.grade_id = req, req.get("direction"), req.get("grade")
        n.salary_from, n.salary_to = req.get("salary_from"), req.get("salary_to")
    db.commit()
    return _need_out(db, n)


@router.post("/needs/{need_id}/selections", status_code=201,
             summary="Новая версия подборки (уточнение фильтров или требований без потери прежних версий)",
             responses={**AUTH, 404: err("Потребность или родительская версия не найдены")})
def new_selection(need_id: uuid.UUID, data: SelectionIn, user: User = Depends(employer),
                  db: Session = Depends(get_db)) -> dict:
    n = _own_need(db, my_company(db, user), need_id)
    if data.parent_version is not None and db.scalar(select(SelectionVersion.id).where(
            SelectionVersion.need_id == n.id, SelectionVersion.version == data.parent_version)) is None:
        raise api_error(404, "version_not_found", "Родительская версия подборки не найдена")
    req = _req_dict(data.requirements, n.raw_text) if data.requirements else None
    v = _make_version(db, n, user, data.filters.model_dump(exclude_none=True, exclude_defaults=True),
                      data.parent_version, req)
    return _version_out(db, v)


@router.get("/needs/{need_id}/selections/{version}", summary="Версия подборки: категории, карточки, объяснения",
            responses={**AUTH, 404: err("Версия не найдена")})
def get_selection(need_id: uuid.UUID, version: int, user: User = Depends(employer),
                  db: Session = Depends(get_db)) -> dict:
    n = _own_need(db, my_company(db, user), need_id)
    v = db.scalar(select(SelectionVersion).where(SelectionVersion.need_id == n.id, SelectionVersion.version == version))
    if v is None:
        raise api_error(404, "version_not_found", "Версия подборки не найдена")
    return _version_out(db, v)


@router.get("/needs/{need_id}/selections/{version}/what-if",
            summary="«Что если»: какое требование отсекает больше всего подтверждённых кандидатов",
            description="Полностью подходят — грейд подтверждён (без «предварительно» и «не подтверждён»), каждый "
                        "обязательный навык подтверждён тестом (T1), заявленные формат и город подходят. Для каждого "
                        "требования — сколько подтверждённых оно отсекает и сколько полностью подходящих появится без "
                        "него (только подтверждённые). options[].apply — тело для POST …/selections: новая версия, "
                        "прежние сохраняются. Зарплата не отсекает: ожидания кандидатов скрыты и в подбор не входят. "
                        "Кэш 2 минуты с отметкой свежести данных; порядок выдачи (ярусы обязательного, затем балл) не меняется.",
            responses={**AUTH, 404: err("Версия не найдена")})
def selection_what_if(need_id: uuid.UUID, version: int, user: User = Depends(employer),
                      db: Session = Depends(get_db)) -> dict:
    n = _own_need(db, my_company(db, user), need_id)
    v = db.scalar(select(SelectionVersion).where(SelectionVersion.need_id == n.id, SelectionVersion.version == version))
    if v is None:
        raise api_error(404, "version_not_found", "Версия подборки не найдена")
    return whatif.what_if(db, v.requirements, split_filters(v.filters)[0])


@router.get("/needs/{need_id}/compare", summary="Сравнение 2–3 кандидатов рядом по требованиям потребности",
            description="Строки — требования потребности (с цитатой из текста) и подтверждающие факты: категория и "
                        "грейд, θ ± SE с 95 % интервалом и вероятностью уровня, достоверность результата, навыки "
                        "(T1/T0/нет данных), опыт и формат (T0), паспорт ФСП (T2), зонды (T1), рынок категории, "
                        "итоговое соответствие. Обезличено, как в подборке. Без refs — первые три из версии.",
            responses={**AUTH, 404: err("Потребность, версия или кандидат не найдены"),
                       422: err("Нужно от 2 до 3 разных кандидатов")})
def compare_candidates(need_id: uuid.UUID, refs: list[str] = Query(default_factory=list, max_length=10),
                       version: int | None = Query(None, ge=1), user: User = Depends(employer),
                       db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    n = _own_need(db, c, need_id)
    if version is not None and db.scalar(select(SelectionVersion.id).where(
            SelectionVersion.need_id == n.id, SelectionVersion.version == version)) is None:
        raise api_error(404, "version_not_found", "Версия подборки не найдена")
    refs = list(dict.fromkeys(r.strip() for r in refs if r and r.strip())) or compare_mod.default_refs(db, n, version)
    if not compare_mod.MIN_REFS <= len(refs) <= compare_mod.MAX_REFS:
        raise api_error(422, "compare_refs", "Для сравнения выберите от 2 до 3 кандидатов")
    return compare_mod.compare(db, c, n, refs, version)


# ------------------------------------------------------------------ поиск и карточка

@router.get("/candidates", summary="Поиск по всей базе (только обезличенные карточки)", responses=AUTH)
def search_candidates(
    direction: Literal["backend", "frontend", "data_ml", "qa", "security"] | None = None,
    grade: GradeId | None = None,
    category: str | None = None,
    stack: list[str] = Query(default_factory=list, description="Стек-теги (все должны быть)"),
    stack_level: Literal["any", "t1"] = Query("any", description="any — заявлен или подтверждён; t1 — подтверждён"),
    fsp: bool = Query(False, description="Только с паспортом ФСП"),
    confirmed: bool = Query(False, description="Только подтверждённый грейд: без «Junior (предварительно)» и без "
                                               "«грейд не подтверждён» (по умолчанию они показываются ниже подтверждённых)"),
    limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
    user: User = Depends(employer), db: Session = Depends(get_db),
) -> dict:
    my_company(db, user)
    return ranking.search(db, direction=direction, grade=grade, category=category, stack=stack or None,
                          stack_level=stack_level, fsp_only=fsp, limit=limit, offset=offset, confirmed_only=confirmed)


@router.get("/categories", summary="Категории с числом видимых кандидатов и рыночным диапазоном", responses=AUTH)
def categories(user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    (counts, prov), unc = ranking.pool_counts(db), ranking.unconfirmed_counts(db)  # пул — одной загрузкой
    return [{"id": c.id, "title": c.title, "direction": c.direction_id, "grade": c.grade_id,
             "count": counts.get(c.id, 0), "provisional": prov.get(c.id, 0), "unconfirmed": unc.get(c.id, 0),
             "market_range": ranking._mr(c)}
            for c in db.scalars(select(Category).order_by(Category.direction_id)).all()]


@router.get("/candidates/{ref}", summary="Карточка кандидата: факты с уровнями, история контактов, контакты после принятия",
            responses={**AUTH, 404: err("Кандидат не найден или скрыл профиль")})
def candidate_detail(ref: str, need_id: uuid.UUID | None = None,
                     direction: Literal["backend", "frontend", "data_ml", "qa", "security"] | None = None,
                     user: User = Depends(employer),
                     db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    p = profile_by_ref(db, ref)
    interest.record_card_view(db, c.id, p.user_id)  # кандидату — «карточку посмотрели N работодателей»
    n = _own_need(db, c, need_id) if need_id else None
    selected_direction = (n.requirements or {}).get("direction") if n else direction
    b = load_bundles(db, [p.user_id], direction=selected_direction)[p.user_id]
    cats = {x.id: x for x in db.scalars(select(Category)).all()}
    if b.category_id:
        peers = ranking.visible_pool(db, category_ids=[b.category_id])
        peer_bundles = load_bundles(db, [x.user_id for x in peers], category_ids=[b.category_id])
        rank = 1 + sum(1 for x in peer_bundles.values() if (x.rating or 0) > (b.rating or 0))
        out = card(b, cats, rank=rank, rank_total=len(peers))
    else:  # грейд не подтверждён: места в категории нет
        out = card(b, cats)
    if need_id:
        s, comps, reasons = ranking.score_candidate(b, n.requirements)
        from app.modules.matching import must_have

        # Ф2: «Не хватает обязательного» в шапке; ярус без пула не считается (missing — по самому кандидату)
        must = must_have.assess(b, n.requirements, set(must_have.must_tags(n.requirements)))
        from app.modules.matching import core_skill

        core = core_skill.describe(b, n.requirements)  # Я1: «Основной язык роли — Go: не заявлен»
        if core:
            reasons = reasons[:1] + [core_skill.reason(core)] + reasons[1:]
        out["match"] = {"need_id": str(n.id), "score": s, "components": comps, "reasons": reasons, "must": must,
                        "core": core}
    until = cooldown_until(db, c.id, p.user_id)
    inv = db.scalars(select(Invitation).where(Invitation.company_id == c.id, Invitation.candidate_user_id == p.user_id)
                     .order_by(Invitation.created_at.desc())).all()
    probes = db.scalars(select(Probe).where(Probe.company_id == c.id, Probe.candidate_user_id == p.user_id)
                        .order_by(Probe.created_at.desc())).all()
    revealed = contacts_revealed(db, c.id, p.user_id)
    out.update({
        "can_invite": until is None, "invite_available_at": until.isoformat() if until else None,
        "invitation_cooldown_days": INVITATION_COOLDOWN_DAYS,
        "my_invitations": [{"id": str(i.id), "status": i.status.value, "position_title": i.position_title,
                         "created_at": i.created_at.isoformat()} for i in inv],
        "my_probes": [{"id": str(x.id), "status": x.status.value, "title": x.title, "created_at": x.created_at.isoformat()}
                   for x in probes],
        "contacts": candidate_contacts(db, p.user_id) if revealed else None,
        "contacts_note": None if revealed else "Контакты откроются, когда кандидат примет ваше приглашение",
    })
    if not revealed and any(i.contacts_revoked_at for i in inv):  # кандидат отозвал доступ (app.modules.contact)
        out["contacts_revoked"] = True
        out["contacts_note"] = "Кандидат отозвал доступ к контактам — карточка снова обезличена"
    out["my_invitations"] = [{**x, "contacts_revoked": bool(i.contacts_revoked_at)} for x, i in zip(out["my_invitations"], inv)]
    return out


@router.get("/candidates/{ref}/profile.pdf", summary="Стандартизированный PDF-профиль (контакты — только после принятия)",
            responses={**AUTH, 404: err("Кандидат не найден"), 200: {"content": {"application/pdf": {}}}},
            response_class=Response)
def candidate_pdf(ref: str, user: User = Depends(employer), db: Session = Depends(get_db)) -> Response:
    from app.modules.pdf.profile_pdf import render_profile

    c = my_company(db, user)
    p = profile_by_ref(db, ref)
    interest.record_card_view(db, c.id, p.user_id)
    b = load_bundles(db, [p.user_id])[p.user_id]
    cats = {x.id: x for x in db.scalars(select(Category)).all()}
    contacts = candidate_contacts(db, p.user_id) if contacts_revealed(db, c.id, p.user_id) else None
    from app.passport.service import for_pdf

    pdf = render_profile(card(b, cats), contacts=contacts, audience="employer", passport=for_pdf(db, p.user_id))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="profile-{ref}.pdf"'})
