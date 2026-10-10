"""Эндпоинты «устной защиты» и «ИИ-интервью» (тег interview). Флаг INTERVIEW_ENABLED выключен — 409 interview_disabled
на действиях; чтение состояния отдаёт enabled=false (экраны прячут блоки)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.modules.auth.models import User
from app.modules.interview import port as pt
from app.modules.interview import service as svc

TAGS = [{"name": "interview", "description": "Устная защита развёрнутых ответов теста и ИИ-интервью этапом найма "
                                            "(флаг INTERVIEW_ENABLED). Оценивает модель; грейд не меняется"}]
router = APIRouter(prefix="/api/interview", tags=["interview"])
candidate_router = APIRouter(prefix="/api/candidate", tags=["interview"])
employer_router = APIRouter(prefix="/api/employer", tags=["interview"])
candidate = require_role(UserRole.candidate)
employer = require_role(UserRole.employer)

AUTH = {401: err("Нужен вход"), 403: err("Не та роль")}
OFF = {409: err("Выключено флагом (interview_disabled) или сессия в другом состоянии")}
Channel = Literal["avatar", "voice", "text"]


class QuoteOut(BaseModel):
    text: str


class QuestionOut(BaseModel):
    n: int | None = None
    question: str
    task_id: str | None = None
    task_title: str | None = None
    skill: str | None = None
    level: str = Field(description="defense: confirmed | partial | discrepancy | no_data; interview: strong | medium | "
                                   "weak | no_data")
    level_title: str
    quotes: list[QuoteOut] = Field(description="Только цитаты, сверенные кодом с расшифровкой")
    reasoning: str | None = None
    lowered: bool = False


class TurnOut(BaseModel):
    who: Literal["interviewer", "candidate"]
    text: str
    n: int | None = None


class ChannelsOut(BaseModel):
    avatar: bool
    voice: bool
    text: bool


class ConversationOut(BaseModel):
    n: int | None = None
    question: str | None = None
    asked: int
    max_questions: int
    deadline: datetime | None = None
    channels: ChannelsOut
    engine: Literal["engine", "stub"]
    hint: str | None = Field(None, description="Только заглушка: начало письменного ответа — «подставить» в e2e")


class TaskRef(BaseModel):
    id: str
    title: str | None = None


class SessionOut(BaseModel):
    id: str
    mode: Literal["defense", "interview"]
    status: Literal["invited", "created", "in_progress", "evaluating", "completed", "failed", "expired", "cancelled", "deleted"]
    status_title: str
    verdict: str | None = Field(None, description="defense: confirmed | discrepancies | insufficient; interview: strong | "
                                                  "medium | weak | insufficient. Оценивает модель; грейд не меняется")
    verdict_title: str | None = None
    score: float | None = None
    summary: str | None = None
    questions: list[QuestionOut] = []
    flags: list[str] = []
    coverage: float | None = None
    duration_s: int | None = None
    minutes: int
    max_questions: int
    conversation: ConversationOut | None = None
    created_at: datetime
    completed_at: datetime | None = None
    expires_at: datetime | None = None
    example: bool = Field(description="Готовый пример для жюри (модельный кандидат)")
    example_label: str | None = None
    stub: bool
    jury: bool
    tasks: list[TaskRef] = []
    skills: list[str] = []
    note: str | None = None
    transcript: list[TurnOut] | None = Field(None, description="Только работодателю и только текст")
    result_hidden: bool = False
    return_to: str = Field(description="Куда вернуть кандидата после разговора")
    error: str | None = None


class ConsentOut(BaseModel):
    version: str
    items: list[str]


class JuryOut(BaseModel):
    live_per_hour: int
    max_minutes: int


class DefenseStateOut(BaseModel):
    enabled: bool
    stub: bool
    eligible: bool
    reason: str | None = None
    answers_n: int
    minutes: int
    max_questions: int
    attempts_left: int | None = None
    can_start: bool
    jury: JuryOut | None = None
    name_hint: str
    consent: ConsentOut
    session: SessionOut | None = None
    example: SessionOut | None = None


class StageOut(BaseModel):
    enabled: bool
    stub: bool
    minutes: int
    can_invite: bool
    reason: str | None = None
    skills: list[str] = []
    skills_reason: str | None = None
    name_hint: str | None = None
    consent: ConsentOut | None = None
    session: SessionOut | None = None


class CandidateInterviewOut(BaseModel):
    enabled: bool
    defense: SessionOut | None = None
    interviews: list[SessionOut] = []


class StartIn(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="Как обращаться — одно слово, без фамилии")
    consent: bool


class BeginIn(BaseModel):
    channel: Channel = "text"


class AnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    channel: Channel = "text"


class TranscribeOut(BaseModel):
    text: str


class AvatarOut(BaseModel):
    session_token: str
    ice_servers: list[dict] | None = None


class InviteIn(BaseModel):
    note: str | None = Field(None, max_length=500)
    skills: list[str] | None = Field(None, max_length=8, description="Навыки вручную, если потребности нет")


class DeletedOut(BaseModel):
    deleted: bool


# ------------------------------------------------------------------ кандидат: устная защита

@router.get("/defense/{session_id}", summary="Устная защита попытки: можно ли, текущая сессия, пример для жюри",
            response_model=DefenseStateOut, responses={**AUTH, 404: err("Попытка не найдена")})
def defense_state(session_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    return svc.defense_state(db, user, svc.own_attempt(db, user, session_id))


@router.post("/defense/{session_id}", status_code=201, response_model=SessionOut,
             summary="Начать устную защиту развёрнутых ответов (по желанию; грейд не меняется)",
             responses={**AUTH, **OFF, 404: err("Попытка не найдена"), 422: err("Защищать нечего или нет согласия"),
                        429: err("Лимит сессий (жюри — 1 живой запуск в час на песочницу)")})
def defense_start(session_id: uuid.UUID, body: StartIn, user: User = Depends(candidate),
                  db: Session = Depends(get_db)) -> dict:
    ts = svc.own_attempt(db, user, session_id)
    return svc.view(svc.start_defense(db, user, ts, body.name, body.consent), "candidate")


# ------------------------------------------------------------------ кандидат: разговор

@router.get("/sessions/{session_id}", summary="Сессия кандидата: шаг разговора или итог", response_model=SessionOut,
            responses={**AUTH, 404: err("Сессия не найдена")})
def session_get(session_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    row = svc.own_session(db, user, session_id)
    svc._expire(db, row)
    return svc.view(row, "candidate")


@router.post("/sessions/{session_id}/begin", summary="Начать разговор (первый вопрос)", response_model=SessionOut,
             responses={**AUTH, **OFF, 404: err("Сессия не найдена"), 503: err("Интервьюер недоступен")})
def session_begin(session_id: uuid.UUID, body: BeginIn, user: User = Depends(candidate),
                  db: Session = Depends(get_db)) -> dict:
    row = svc.own_session(db, user, session_id)  # сначала владение (404), потом флаг (409)
    svc.require_enabled()
    return svc.view(svc.begin(db, row, body.channel), "candidate")


@router.post("/sessions/{session_id}/answer", summary="Ответ кандидата (текстом или распознанный) → следующий вопрос",
             response_model=SessionOut, responses={**AUTH, **OFF, 404: err("Сессия не найдена"), 422: err("Пустой ответ")})
def session_answer(session_id: uuid.UUID, body: AnswerIn, tasks: BackgroundTasks, user: User = Depends(candidate),
                   db: Session = Depends(get_db)) -> dict:
    row = svc.own_session(db, user, session_id)
    svc.require_enabled()
    row = svc.answer(db, row, body.text, body.channel)
    if row.status == "evaluating":
        tasks.add_task(svc.evaluate_bg, row.id)
    return svc.view(row, "candidate")


@router.post("/sessions/{session_id}/finish", summary="Закончить разговор досрочно — оценить то, что сказано",
             response_model=SessionOut, responses={**AUTH, **OFF, 404: err("Сессия не найдена")})
def session_finish(session_id: uuid.UUID, tasks: BackgroundTasks, user: User = Depends(candidate),
                   db: Session = Depends(get_db)) -> dict:
    row = svc.own_session(db, user, session_id)
    if row.status == "created":
        row.status = "cancelled"
        db.commit()
    elif row.status == "in_progress":
        svc._close(db, row, inline=pt.is_stub())
        if row.status == "evaluating":
            tasks.add_task(svc.evaluate_bg, row.id)
    return svc.view(row, "candidate")


@router.post("/sessions/{session_id}/transcribe", summary="«Нажми и говори»: запись ответа → текст (кандидат проверяет "
             "и отправляет)", response_model=TranscribeOut,
             responses={**AUTH, **OFF, 404: err("Сессия не найдена"), 413: err("Запись слишком длинная"),
                        503: err("Распознавание недоступно — ответьте текстом")})
async def session_transcribe(session_id: uuid.UUID, request: Request, user: User = Depends(candidate),
                             db: Session = Depends(get_db)) -> dict:
    from app.core.config import get_settings

    row = svc.own_session(db, user, session_id)
    svc.require_enabled()
    if row.status != "in_progress":
        raise api_error(409, "interview_closed", "Разговор не идёт")
    audio = await request.body()
    if len(audio) > get_settings().interview_audio_max_kb * 1024:
        raise api_error(413, "audio_too_large", "Запись слишком длинная — ответьте короче или текстом")
    if not audio:
        raise api_error(422, "empty_audio", "Пустая запись")
    try:
        text, usd = pt.get_port().transcribe(audio, request.headers.get("content-type") or "audio/webm")
    except pt.EngineUnavailable:
        raise api_error(503, "stt_unavailable", "Распознавание речи недоступно — ответьте текстом") from None
    svc.add_cost(row, "stt_usd", usd)  # запись не хранится — только текст и стоимость
    db.commit()
    return {"text": svc._scrub(db, row.candidate_user_id, text)[:3000]}


@router.get("/sessions/{session_id}/speech", summary="Голос интервьюера: текущий вопрос (аудио)",
            responses={**AUTH, 200: {"content": {"audio/mpeg": {}}}, 404: err("Сессия не найдена"),
                       503: err("Голос недоступен — вопрос показан текстом")}, response_class=Response)
def session_speech(session_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> Response:
    row = svc.own_session(db, user, session_id)
    q = (row.state or {}).get("q")
    if row.status != "in_progress" or not q:
        raise api_error(409, "interview_closed", "Разговор не идёт")
    try:
        audio, mime, usd = pt.get_port().speak(q)
    except pt.EngineUnavailable:
        raise api_error(503, "tts_unavailable", "Голос недоступен — вопрос показан текстом") from None
    svc.add_cost(row, "tts_usd", usd)
    db.commit()
    return Response(audio, media_type=mime, headers={"Cache-Control": "no-store"})


@router.post("/sessions/{session_id}/avatar", summary="Токен сессии видео-аватара (Anam JS SDK, на 1 час)",
             response_model=AvatarOut, responses={**AUTH, **OFF, 404: err("Сессия не найдена"),
                                                  503: err("Аватар недоступен — голос или текст")})
def session_avatar(session_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    from app.core.config import get_settings

    row = svc.own_session(db, user, session_id)
    svc.require_enabled()
    if row.status not in ("created", "in_progress"):
        raise api_error(409, "interview_closed", "Разговор не идёт")
    tok = pt.get_port().avatar_token(max_seconds=row.minutes * 60 + 120) if get_settings().interview_avatar else None
    if not tok or not tok.get("session_token"):
        raise api_error(503, "avatar_unavailable", "Видео-аватар недоступен — продолжим голосом или текстом")
    # SDK Anam — npm-зависимость фронтенда (ленивый чанк), внешний CDN не нужен
    return {"session_token": tok["session_token"], "ice_servers": tok.get("ice_servers")}


@router.post("/sessions/{session_id}/channel", summary="Сменить канал (отказ аватара → голос → текст)",
             response_model=SessionOut, responses={**AUTH, 404: err("Сессия не найдена")})
def session_channel(session_id: uuid.UUID, body: BeginIn, user: User = Depends(candidate),
                    db: Session = Depends(get_db)) -> dict:
    row = svc.own_session(db, user, session_id)
    if row.status == "in_progress" and row.channel != body.channel:
        st = dict(row.state or {})
        st["channels_log"] = list(st.get("channels_log") or []) + [body.channel]
        row.state, row.channel = st, body.channel
        db.commit()
    return svc.view(row, "candidate")


@router.delete("/sessions/{session_id}", summary="Удалить запись разговора и результат (ПДн)", response_model=DeletedOut,
               responses={**AUTH, 404: err("Сессия не найдена")})
def session_delete(session_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    row = svc.own_session(db, user, session_id)
    if row.is_example:
        raise api_error(409, "example_readonly", "Пример для жюри не удаляется")
    svc.delete_session(db, row)
    return {"deleted": True}


# ------------------------------------------------------------------ работодатель: карточка

@router.get("/candidates/{ref}", summary="Устная защита и ИИ-интервью кандидата для карточки работодателя",
            response_model=CandidateInterviewOut, responses={**AUTH, 404: err("Кандидат не найден")})
def candidate_interviews(ref: str, direction: Literal["backend", "frontend", "data_ml", "qa", "security"] | None = None,
                         user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    from app.modules.invitations.service import profile_by_ref
    from app.modules.matching.router import my_company
    from app.modules.profiles.facts import load_bundles

    p = profile_by_ref(db, ref)
    c = my_company(db, user)
    b = load_bundles(db, [p.user_id], direction=direction)[p.user_id]
    ts_id = None
    if b.test is not None and (b.test.source_ref or "").startswith("test_session:"):
        try:
            ts_id = uuid.UUID(b.test.source_ref.split(":", 1)[1])
        except ValueError:
            ts_id = None
    return svc.for_candidate_card(db, p.user_id, ts_id, c.id)


# ------------------------------------------------------------------ этап найма «ИИ-интервью»

@employer_router.get("/invitations/{inv_id}/ai-interview", summary="Этап «ИИ-интервью»: можно ли, навыки, итог",
                     response_model=StageOut, responses={**AUTH, 404: err("Приглашение не найдено")})
def stage_employer(inv_id: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    from app.modules.contact.router import _emp_inv

    return svc.stage_state(db, _emp_inv(db, user, inv_id), "employer")


@employer_router.post("/invitations/{inv_id}/ai-interview", status_code=201, response_model=StageOut,
                      summary="Пригласить на ИИ-интервью по навыкам, которые тест не подтвердил",
                      responses={**AUTH, **OFF, 404: err("Приглашение не найдено"),
                                 422: err("Все навыки уже подтверждены — добавьте вручную")})
def stage_invite(inv_id: uuid.UUID, body: InviteIn, user: User = Depends(employer),
                 db: Session = Depends(get_db)) -> dict:
    from app.modules.contact.router import _emp_inv

    inv = _emp_inv(db, user, inv_id)
    svc.invite_interview(db, user, inv, body.note, body.skills)
    return svc.stage_state(db, inv, "employer")


@candidate_router.get("/invitations/{inv_id}/ai-interview", summary="Приглашение на ИИ-интервью (кандидат)",
                      response_model=StageOut, responses={**AUTH, 404: err("Приглашение не найдено")})
def stage_candidate(inv_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    from app.modules.contact.router import _cand_inv

    return svc.stage_state(db, _cand_inv(db, user, inv_id), "candidate")


@candidate_router.post("/invitations/{inv_id}/ai-interview", status_code=201, response_model=SessionOut,
                       summary="Согласиться и начать ИИ-интервью", responses={
                           **AUTH, **OFF, 404: err("Приглашение не найдено"), 422: err("Нет согласия"),
                           429: err("Лимит сессий")})
def stage_start(inv_id: uuid.UUID, body: StartIn, user: User = Depends(candidate),
                db: Session = Depends(get_db)) -> dict:
    from app.modules.contact.router import _cand_inv

    inv = _cand_inv(db, user, inv_id)
    return svc.view(svc.start_interview(db, user, inv, body.name, body.consent), "candidate")
