"""Эндпоинты «устной защиты» и «ИИ-интервью» (тег interview). Флаг INTERVIEW_ENABLED выключен — 409 interview_disabled
на действиях; чтение состояния отдаёт enabled=false (экраны прячут блоки)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
import uuid

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, WebSocket
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.modules.auth.models import User
from app.modules.catalog.ext import DirectionId
from app.modules.interview import port as pt
from app.modules.interview import service as svc

TAGS = [{"name": "interview", "description": "Устная защита развёрнутых ответов теста и ИИ-интервью этапом найма "
                                            "(флаг INTERVIEW_ENABLED). Оценивает модель; грейд не меняется"}]
log = logging.getLogger("interview.concierge")

router = APIRouter(prefix="/api/interview", tags=["interview"])
candidate_router = APIRouter(prefix="/api/candidate", tags=["interview"])
employer_router = APIRouter(prefix="/api/employer", tags=["interview"])
candidate = require_role(UserRole.candidate)
employer = require_role(UserRole.employer)

AUTH = {401: err("Нужен вход"), 403: err("Не та роль")}
OFF = {409: err("Выключено флагом (interview_disabled) или сессия в другом состоянии")}
Channel = Literal["voice", "text"]


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
    voice: bool = Field(description="Голос ведущего (синтез речи, mp3)")
    stt: bool = Field(description="«Нажми и говори»: запись ответа → распознанный текст")
    text: bool
    avatar: bool = Field(False, description="Живой аватар (Anam, наше сгенерированное лицо, голос наш): токен — POST /sessions/{id}/avatar-token; "
                                            "при любом сбое экран показывает свой портрет")


class AvatarTokenOut(BaseModel):
    """Параметры подключения к потоку живого аватара (Anam, JS SDK). Ключей нет — одноразовый токен сессии; реплики ведущей
    клиент берёт у нас (/speech?format=pcm, наш голос) и передаёт в поток для движения губ (режим передачи звука)."""
    session_token: str
    max_seconds: int = Field(description="Потолок длительности сессии у поставщика")
    ice_servers: list[dict] | None = Field(None, description="Наш TURN (временные учётные данные) или null — ICE поставщика")
    relay_only: bool = False
    persona_name: str = "Интервьюер"


class ConversationOut(BaseModel):
    n: int | None = None
    question: str | None = None
    asked: int
    max_questions: int
    deadline: datetime | None = None
    channels: ChannelsOut
    engine: Literal["engine", "stub"]
    hint: str | None = Field(None, description="Только заглушка: начало письменного ответа — «подставить» в e2e")
    context: str | None = Field(None, description="Защита: 1–2 строки письменного ответа кандидата, по которому вопрос")


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


class InterviewConsentOut(BaseModel):
    version: str
    items: list[str]


class JuryOut(BaseModel):
    live_per_hour: int
    max_minutes: int


class DefenseFallbackOut(BaseModel):
    """Д2: жюри без развёрнутых ответов — живой разговор по защищаемому примеру (example) или последнему заданию."""
    source: str
    title: str


class IntegrityContourOut(BaseModel):
    """Контур паспорта честности (KF2): prior — канарейки и предзнание, fit — индекс l_z, origin — ИИ-метка,
    screen — экран и клавиатура, live — камера / устная защита."""
    id: str
    status: str = Field(description="ok / warn / na / checked (кандидату вне демо-режима) / recommended (контур live)")
    value: str | None = None


class IntegrityPassportOut(BaseModel):
    """Паспорт честности попытки (IntegrityBadge): итог по 5 контурам."""
    level: str | None = None
    title: str | None = None
    verdict: str = Field(description="clean / attention / recommended / confirmed / discrepancies")
    verdict_title: str
    recommended: bool
    why: str | None = None
    detailed: bool
    contours: list[IntegrityContourOut]


class DefenseStatusOut(BaseModel):
    status: str = Field(description="recommended / confirmed / discrepancies / insufficient / none")
    title: str


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
    consent: InterviewConsentOut
    session: SessionOut | None = None
    example: SessionOut | None = None
    fallback: DefenseFallbackOut | None = None
    # KF2: мост «подозрение античита → 3-минутная устная защита с видеоаватаром»
    recommended: bool = False
    why: str | None = None
    basis: str = Field("answers", description="answers — развёрнутые ответы; code — код и выбранные решения (KF2)")
    defense_status: DefenseStatusOut | None = None
    integrity: IntegrityPassportOut | None = None


class StageOut(BaseModel):
    enabled: bool
    stub: bool
    minutes: int
    can_invite: bool
    reason: str | None = None
    skills: list[str] = []
    skills_reason: str | None = None
    name_hint: str | None = None
    consent: InterviewConsentOut | None = None
    session: SessionOut | None = None


class CandidateInterviewOut(BaseModel):
    enabled: bool
    defense: SessionOut | None = None
    interviews: list[SessionOut] = []
    # KF2: «Устная защита: рекомендована / пройдена: подтверждено / не подтверждено» и паспорт честности
    recommended: bool = False
    why: str | None = None
    defense_status: DefenseStatusOut | None = None
    integrity: IntegrityPassportOut | None = None


class StartIn(BaseModel):
    name: str = Field("", max_length=60, description="Как обращаться — одно слово, без фамилии (по желанию)")
    consent: bool


class BeginIn(BaseModel):
    channel: Channel = "text"


class AnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    channel: Channel = "text"


class TranscribeOut(BaseModel):
    text: str
    stub: bool = Field(False, description="Заглушка распознавания (только e2e/демо): подставлено начало письменного ответа")


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


@router.post("/quick-defense", status_code=201, response_model=SessionOut,
             summary="Живой разговор с ИИ-интервьюером в один клик (последняя попытка теста, сразу голосом)",
             responses={**AUTH, **OFF, 404: err("Завершённых попыток нет"), 422: err("Защищать нечего"),
                        429: err("Лимит сессий")})
def quick_defense_start(user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    return svc.view(svc.quick_defense(db, user), "candidate")


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
    port = pt.get_port()
    st = row.state or {}
    hint = port.hint(st.get("engine") or {}, int(st.get("n") or 0)) if port.is_stub() and st.get("engine") else None
    try:
        text, usd, stub = port.transcribe(audio, request.headers.get("content-type") or "audio/webm", stub_text=hint)
    except pt.EngineUnavailable:
        raise api_error(503, "stt_unavailable", "Распознавание речи недоступно — ответьте текстом") from None
    svc.add_cost(row, "stt_usd", usd)  # запись не хранится — только текст и стоимость
    db.commit()
    return {"text": svc._scrub(db, row.candidate_user_id, text)[:3000], "stub": stub}


@router.get("/sessions/{session_id}/speech", summary="Голос интервьюера: текущий вопрос (аудио)",
            responses={**AUTH, 200: {"content": {"audio/mpeg": {}}}, 404: err("Сессия не найдена"),
                       503: err("Голос недоступен — вопрос показан текстом")}, response_class=Response)
def session_speech(session_id: uuid.UUID, format: Literal["mp3", "pcm", "pcm24"] = "mp3", user: User = Depends(candidate),
                   db: Session = Depends(get_db)) -> Response:
    """format=pcm — pcm_s16le 16 кГц моно (audio/pcm) для живого аватара (Anam, передача звука); по умолчанию mp3.
    format=pcm24 — PCM 24 кГц потоком (первый звук ≈ 0,7 с): живой разговор без пауз, тот же голос, что у проводника."""
    row = svc.own_session(db, user, session_id)
    st = row.state or {}
    # идёт разговор — текущий вопрос; только что закрыт (время вышло, «Закончить») — прощание ведущей
    q = st.get("q") if row.status == "in_progress" else st.get("closing") if row.status in ("evaluating", "completed") else None
    if not q:
        raise api_error(409, "interview_closed", "Разговор не идёт")
    if format == "pcm24":
        from app.modules.interview import concierge as cg
        from app.modules.interview.engine.cost import estimate_cost

        gen = cg.synth_stream(q, "pcm24")
        try:
            first = next(gen)
        except StopIteration:
            first = b""
        except cg.TtsError:
            raise api_error(503, "tts_unavailable", "Голос недоступен — вопрос показан текстом") from None
        try:
            svc.add_cost(row, "tts_usd", estimate_cost("tts", len(q)))
            db.commit()
        except Exception:  # noqa: BLE001 — учёт расхода не должен ронять голос
            db.rollback()

        def body_iter():
            if first:
                yield first
            try:
                yield from gen
            except cg.TtsError:
                return

        return StreamingResponse(body_iter(), media_type="audio/pcm",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "X-Voice-Rate": "24000"})
    try:
        audio, mime, usd = pt.get_port().speak(q, "pcm_16000" if format == "pcm" else "mp3")
    except pt.EngineUnavailable:
        raise api_error(503, "tts_unavailable", "Голос недоступен — вопрос показан текстом") from None
    svc.add_cost(row, "tts_usd", usd)
    db.commit()
    return Response(audio, media_type=mime, headers={"Cache-Control": "no-store"})


@router.post("/sessions/{session_id}/avatar-token", summary="Живой аватар: токен сессии видеопотока (INTERVIEW_ANAM_ENABLED)",
             response_model=AvatarTokenOut,
             responses={**AUTH, **OFF, 404: err("Сессия не найдена"), 503: err("Аватар недоступен — экран показывает свой портрет")})
def session_avatar_token(session_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    """Лицо — наш сгенерированный портрет (frontend/public/avatar/PROVENANCE.md), загруженный в Anam как собственный аватар
    (ANAM_AVATAR_ID); модель Anam только рисует лицо и губы под наш звук (/speech?format=pcm), её LLM и голос не
    используются. Флаг по умолчанию выключен → 503, клиент тихо остаётся на портрете и голосе mp3."""
    row = svc.own_session(db, user, session_id)
    if row.status not in ("created", "in_progress"):
        raise api_error(409, "interview_closed", "Разговор не идёт")
    try:
        t = pt.get_port().avatar_token()
    except pt.EngineUnavailable:
        raise api_error(503, "avatar_unavailable", "Аватар недоступен — доступны каналы «голос» и «текст»") from None
    from app.modules.interview.engine.settings import get_interview_settings
    # учёт: сессия поставщика тарифицируется по времени; оценка — длительность разговора, не больше потолка сессии
    minutes = max(1, min(int(t.get("max_seconds") or 0) // 60 or 1, int(getattr(row, "minutes", 0) or 0) or 10))
    svc.add_cost(row, "avatar_usd", minutes * float(getattr(get_interview_settings(), "interview_price_avatar_min", 0) or 0))
    db.commit()
    return t


@router.post("/sessions/{session_id}/channel", summary="Сменить канал (отказ голоса → текст)",
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
def candidate_interviews(ref: str, direction: DirectionId | None = None,
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


# ------------------------------------------------------------------ живой ИИ-проводник Настя (главная и все кабинеты)

class ConciergeSpeechIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    # pcm24 — PCM 24 кГц потоком (живой аватар и запасной голос проводника); pcm — 16 кГц целиком (советник, стенд)
    format: Literal["mp3", "pcm", "pcm24"] = "mp3"


class ConciergeChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1500)
    user_name: str | None = Field(None, max_length=60)
    user_role: str | None = Field(None, max_length=32)
    current_path: str = Field("/", max_length=200)
    step_index: int = Field(0, ge=0, le=50)
    history: list[dict] = Field(default_factory=list, max_length=20)


class ConciergeChatOut(BaseModel):
    reply: str
    user_name: str | None = None
    detected_role: Literal["all", "candidate", "employer", "fsp"] = "all"
    start_tour: bool = True
    jump_to_step: int | None = None


@router.post("/concierge/avatar-token", response_model=AvatarTokenOut,
             summary="Живой аватар ИИ-проводника Насти: токен сессии видеопотока с движением губ")
def concierge_avatar_token(request: Request, sid: str | None = Query(None, max_length=64)) -> dict:
    # У Насти — своё лицо (у интервьюера защиты — прежнее). Минуты видеопотока стоят денег: лимиты в сутки на всех,
    # на один адрес и на один разговор (concierge_budget); сверх лимита — 429, браузер переходит на голос без видео.
    from app.modules.interview import concierge as cg
    from app.modules.interview import concierge_budget as budget

    ip = budget.client_ip(request)
    if not budget.burst_ok(ip, 5):
        raise api_error(429, "too_many_requests", "Слишком много запросов — попробуйте через минуту")
    ok, why = budget.take("sessions", ip, 1, conv=sid)
    if not ok:
        log.info("concierge avatar-token: лимит %s (ip %s)", why, ip)
        raise api_error(429, "avatar_budget", "Видеопоток на сегодня исчерпан — включён голосовой режим")
    try:
        from app.modules.interview.engine.providers import avatar as av

        t = av.avatar_token(persona_name="Настя", director_notes=cg.anam_director_notes(),
                            avatar_id=cg.ANAM_AVATAR_ID or None)
        return t.model_dump(mode="json") if hasattr(t, "model_dump") else dict(t)
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 — недоступен поставщик/ключ: тот же ответ, что и у порта
        raise api_error(503, "avatar_unavailable", "Живой видеопоток временно недоступен — включён голосовой режим") from None
    try:
        return pt.get_port().avatar_token()
    except pt.EngineUnavailable:
        raise api_error(503, "avatar_unavailable", "Живой видеопоток временно недоступен — включён голосовой режим") from None


@router.post("/concierge/speech", summary="Голос ИИ-проводника Насти (mp3 или PCM для живого аватара)",
             response_class=Response)
def concierge_speech(body: ConciergeSpeechIn, request: Request) -> Response:
    from app.modules.interview import concierge as cg
    from app.modules.interview import concierge_budget as budget

    text = body.text.strip()
    ip = budget.client_ip(request)
    if not budget.burst_ok(ip):
        raise api_error(429, "too_many_requests", "Слишком много запросов — попробуйте через минуту")
    if body.format == "pcm24":
        hit = cg.cached(text, "pcm24")
        if hit:
            return Response(hit, media_type="audio/pcm", headers={"Cache-Control": "public, max-age=86400", "X-Voice-Rate": "24000"})
        # синтез вне кэша стоит знаков — считаем (постоянные фразы сценария уже в кэше и бесплатны)
        ok, why = budget.take("tts", ip, len(text))
        if not ok:
            raise api_error(429, "tts_budget", "Синтез речи на сегодня исчерпан")
        gen = cg.synth_stream(text, "pcm24")
        try:
            first = next(gen)
        except StopIteration:
            first = b""
        except cg.TtsError:
            raise api_error(503, "tts_unavailable", "Синтез речи временно недоступен") from None

        def body_iter():
            if first:
                yield first
            try:
                yield from gen
            except cg.TtsError:
                return

        return StreamingResponse(body_iter(), media_type="audio/pcm",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "X-Voice-Rate": "24000"})
    fmt = "pcm" if body.format == "pcm" else "mp3"
    if not cg.cached(text, fmt):
        ok, why = budget.take("tts", ip, len(text))
        if not ok:
            raise api_error(429, "tts_budget", "Синтез речи на сегодня исчерпан")
    try:
        audio, mime = cg.cached_speak(text, "pcm_16000" if body.format == "pcm" else "mp3")
    except pt.EngineUnavailable:
        raise api_error(503, "tts_unavailable", "Синтез речи временно недоступен") from None
    return Response(audio, media_type=mime, headers={"Cache-Control": "public, max-age=3600"})


class ConciergeTurnIn(BaseModel):
    message: str = Field(min_length=1, max_length=1500)
    user_name: str | None = Field(None, max_length=60)
    role: str | None = Field(None, max_length=32)
    current_path: str = Field("/", max_length=200)
    step_id: str | None = Field(None, max_length=40)
    touring: bool = False
    paused: bool = False
    history: list[dict] = Field(default_factory=list, max_length=20)
    session_id: str | None = Field(None, max_length=64)
    # что сейчас на экране: заголовок и видимые кнопки/заголовки (Настя отвечает «по экрану» и может показать элемент)
    screen: dict | None = None
    last_said: str = Field("", max_length=600)
    # чего ждёт Настя после своей реплики: checkin | continue | detour | start | answer
    awaiting: str | None = Field(None, max_length=16)


class ConciergeEventIn(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)
    type: Literal["open", "say", "step", "close", "mic", "point"]
    text: str = Field("", max_length=1200)
    step: str | None = Field(None, max_length=40)
    path: str | None = Field(None, max_length=200)
    name: str | None = Field(None, max_length=60)
    role: str | None = Field(None, max_length=32)


@router.post("/concierge/turn", summary="Ход живого разговора с Настей: решение и голос ответа одним потоком (NDJSON)",
             response_class=StreamingResponse)
def concierge_turn(body: ConciergeTurnIn, request: Request) -> StreamingResponse:
    from app.modules.interview import concierge as cg
    from app.modules.interview import concierge_budget as budget

    ip = budget.client_ip(request)
    if not budget.burst_ok(ip, 2):
        raise api_error(429, "too_many_requests", "Слишком много запросов — попробуйте через минуту")
    ok, why = budget.take("turns", ip, 1)
    if not ok:
        log.info("concierge turn: лимит %s (ip %s) — без модели", why, ip)
    screen = None
    if isinstance(body.screen, dict):
        items = body.screen.get("items")
        screen = {"title": str(body.screen.get("title") or "")[:160],
                  "items": [str(x)[:80] for x in (items if isinstance(items, list) else [])][:40]}
    gen = cg.turn_stream(body.message, user_name=(body.user_name or None), role=body.role, current_path=body.current_path,
                         step_id=body.step_id, touring=body.touring, paused=body.paused, history=body.history,
                         session_id=body.session_id, screen=screen, last_said=body.last_said,
                         awaiting=body.awaiting if body.awaiting in ("checkin", "continue", "detour", "start", "answer") else None,
                         no_llm=not ok)
    return StreamingResponse(gen, media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/concierge/event", status_code=204, response_class=Response,
             summary="Событие разговора с Настей для стенограммы: открытие, реплика обзора, шаг, закрытие")
def concierge_event(body: ConciergeEventIn, request: Request) -> Response:
    from app.modules.interview import concierge_brain as brain
    from app.modules.interview import concierge_budget as budget

    if not budget.burst_ok(budget.client_ip(request)):
        return Response(status_code=204)
    brain.event(body.session_id, body.type, text=body.text, step=body.step, path=body.path, name=body.name, role=body.role)
    return Response(status_code=204)


@router.get("/concierge/script", summary="Сценарий обзора Насти: приветствие, реплики шагов, связки (голос — из кэша)")
def concierge_script(name: str | None = Query(None, max_length=40)) -> dict:
    from app.modules.interview import concierge as cg

    cg.warm_async()
    return cg.script(name)


@router.get("/concierge/budget", summary="Сегодняшние расходы проводника Насти и лимиты (для владельца)")
def concierge_budget_usage() -> dict:
    from app.modules.interview import concierge_budget as budget

    return budget.usage()


@router.websocket("/live/stt")
async def live_stt(ws: WebSocket) -> None:
    """Живое распознавание речи (разговор «как по видеосвязи»): PCM 16 кГц от браузера → события распознавания."""
    from app.modules.interview import live_stt as ls

    await ls.bridge(ws)


@router.post("/concierge/transcribe", response_model=TranscribeOut,
             summary="Распознавание голоса собеседника для ИИ-проводника Насти")
async def concierge_transcribe(request: Request) -> dict:
    from app.core.config import get_settings

    audio = await request.body()
    if len(audio) > get_settings().interview_audio_max_kb * 1024:
        raise api_error(413, "audio_too_large", "Запись слишком длинная — скажите короче или напишите")
    if not audio:
        raise api_error(422, "empty_audio", "Пустая запись")
    try:
        text, _usd, stub = pt.get_port().transcribe(audio, request.headers.get("content-type") or "audio/webm")
    except pt.EngineUnavailable:
        raise api_error(503, "stt_unavailable", "Распознавание речи временно недоступно") from None
    return {"text": (text or "").strip()[:1500], "stub": stub}


@router.post("/concierge/chat", response_model=ConciergeChatOut,
             summary="Живой диалог с ИИ-проводником Настей: знакомство по имени, выбор роли и ответы на вопросы")
def concierge_chat(body: ConciergeChatIn) -> dict:
    from app.modules.interview import concierge as cg

    return cg.reply_chat(
        body.message,
        user_name=body.user_name,
        user_role=body.user_role,
        current_path=body.current_path,
        step_index=body.step_index,
        history=body.history,
    )

