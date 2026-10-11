"""Импорт всех моделей — единая metadata для Alembic."""
from app.core.db import Base
from app.modules.assessment.models import (  # noqa: F401
    GradeHistory,
    SandboxTestStart,
    SurveyResponse,
    SurveyStackTag,
    TaskFamily,
    TaskVariant,
    TestAnswer,
    TestSession,
    TestSessionItem,
)
from app.modules.auth.models import Consent, EmailVerification, TwoFactorRecoveryCode, User, UserTwoFactor  # noqa: F401
from app.modules.catalog.models import Category, Direction, Grade, StackTag  # noqa: F401
from app.modules.fsp.models import FspAchievement, FspPassport  # noqa: F401
from app.modules.invitations.models import Invitation, InvitationComplaint, InvitationEvent, Probe  # noqa: F401
from app.modules.matching.models import EmployerNeed, NeedParseJob, SelectionVersion  # noqa: F401
from app.modules.profiles.models import (  # noqa: F401
    CandidateFact,
    CandidateProfile,
    CandidateResume,
    CandidateSpecialization,
    Company,
    EmployerProfile,
)

import app.integrations.models  # noqa: E402,F401 — модели интеграций (день 3Б)
from app.modules.experts.models import ExpertItem, ExpertLabel, ExpertPanelist  # noqa: E402,F401 — экспертная разметка
from app.cup.models import Cup, CupEntry  # noqa: E402,F401 — «Кубок работодателя» (идея 10)
from app.jury_live.models import LiveGuest, LiveRoom  # noqa: E402,F401 — живая демонстрация для жюри (идея 13)
from app.modules.assignments.models import Assignment, AssignmentAttempt, AssignmentPrefs  # noqa: E402,F401 — задания работодателя (И7)
from app.passport.models import GradePassport, PassportKey  # noqa: E402,F401 — подписанный паспорт грейда
from app.modules.contact.models import ContactMessage, InvitationCounter  # noqa: E402,F401 — переписка, встречное (И4)
from app.modules.proctor.models import ProctorEvent, ProctorSession  # noqa: E402,F401 — камера по согласию (И16)
from app.modules.mydata.models import AccountDeletionLog, InterestEvent  # noqa: E402,F401 — «Мои данные», интерес (md01)
from app.modules.hiring.models import HiringInterview, HiringOffer, HiringOutcome  # noqa: E402,F401 — найм (Н8)
from app.modules.subs.models import NeedSubEntry, NeedSubscription, NotifyPrefs, SubsDirty, SubsState, UserNotification  # noqa: E402,F401 — подписки и напоминания (И25)
import app.modules.subs.events  # noqa: E402,F401 — слушатель «кандидат изменился» (И25)
from app.modules.study.models import StudyAnswer, StudyEvent, StudyParticipant  # noqa: E402,F401 — проверка с живыми пользователями (У1)

metadata = Base.metadata
from app.modules.mutual.models import CandidatePreference, OfferFitCheck, SelectionFeedback, SelectionShare, ShareReaction  # noqa: E402,F401 — взаимный подбор (Н9, Н2, Н3)
from app.modules.interview.models import InterviewSession  # noqa: E402,F401 — устная защита и ИИ-интервью (Я15)
from app.modules.tariffs.models import CompanyTariff, DemoInvoice  # noqa: E402,F401 — тарифы работодателя (Я29)
