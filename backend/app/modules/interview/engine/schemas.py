"""Схемы движка (контракт engine/CONTRACT.md, раздел 1)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["defense", "interview"]
Channel = Literal["avatar", "voice", "text"]
Kind = Literal["opening", "question", "repeat", "closing"]
Source = Literal["llm", "rules", "stub"]


class TaskContext(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    kind: str | None = None
    title: str = ""
    prompt: str | None = None
    topics: list[str] = Field(default_factory=list)
    answer: str = Field(max_length=6000)
    score: float | None = None
    integrity_flags: list[str] = Field(default_factory=list)


class SkillContext(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    why: str | None = None
    level: str | None = None


class DefenseContext(BaseModel):
    role: str | None = None
    grade: str | None = None
    tasks: list[TaskContext]


class InterviewContext(BaseModel):
    need_title: str = Field(min_length=1, max_length=200)
    need_summary: str | None = None
    confirmed_skills: list[str] = Field(default_factory=list)
    unconfirmed_skills: list[SkillContext]
    format_questions: list[str] = Field(default_factory=list)


class SessionSpec(BaseModel):
    mode: Mode
    candidate_name: str = Field(min_length=1, max_length=60)
    duration_min: int = 0  # 0 — по умолчанию режима (normalize_spec)
    max_questions: int = 0
    jury: bool = False
    context: DefenseContext | InterviewContext
    started_at: datetime | None = None


class PlanItem(BaseModel):
    k: int
    task_id: str | None = None
    skill: str | None = None
    title: str
    angle: str


class Utterance(BaseModel):
    who: Literal["interviewer", "candidate"]
    text: str
    at: datetime
    n: int | None = None
    channel: Channel | None = None
    kind: Kind | None = None
    k: int | None = None


class Transcript(BaseModel):
    items: list[Utterance] = Field(default_factory=list)

    def candidate_items(self) -> list[Utterance]:
        return [u for u in self.items if u.who == "candidate"]

    def questions_asked(self) -> int:
        """Сколько вопросов задано: реплики ведущего вида opening/question (повтор и прощание не считаются)."""
        return sum(1 for u in self.items if u.who == "interviewer" and u.kind in ("opening", "question"))


class TurnInput(BaseModel):
    spec: SessionSpec
    transcript: Transcript
    candidate_text: str | None = None
    channel: Channel = "text"
    repeat: bool = False
    now: datetime | None = None


class TurnOutput(BaseModel):
    text: str
    kind: Kind
    k: int | None
    finished: bool
    transcript: Transcript
    started_at: datetime | None
    source: Source
    llm: dict | None = None
    cost_usd: float = 0.0


class Quote(BaseModel):
    n: int
    text: str


class QuestionVerdict(BaseModel):
    k: int
    task_id: str | None = None
    skill: str | None = None
    question: str
    answer_excerpt: str
    level: str
    level_label: str
    quotes: list[Quote] = Field(default_factory=list)
    reasoning: str = ""
    lowered: bool = False


class Verdict(BaseModel):
    verdict: str
    verdict_label: str
    score: int | None
    summary: str
    questions: list[QuestionVerdict]
    flags: list[str] = Field(default_factory=list)
    coverage: int
    removed_quotes: int = 0
    source: Source
    llm: dict | None = None
    cost_usd: float = 0.0
    raw: dict | None = None


class AudioOut(BaseModel):
    data: bytes
    mime: str
    format: Literal["mp3", "pcm_24000"]
    sample_rate: int | None
    chars: int
    cost_usd: float
    stub: bool = False


class Transcription(BaseModel):
    text: str
    seconds: float
    cost_usd: float
    stub: bool = False


class AvatarToken(BaseModel):
    session_token: str
    max_seconds: int
    ice_servers: list[dict] | None
    relay_only: bool
    persona_name: str


class Cost(BaseModel):
    usd: float
    llm_usd: float = 0.0
    tts_usd: float = 0.0
    stt_usd: float = 0.0
    avatar_usd: float = 0.0
    estimated: bool = True
