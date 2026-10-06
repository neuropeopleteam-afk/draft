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
from app.modules.auth.models import Consent, EmailVerification, User  # noqa: F401
from app.modules.catalog.models import Category, Direction, Grade, StackTag  # noqa: F401
from app.modules.fsp.models import FspAchievement, FspPassport  # noqa: F401
from app.modules.invitations.models import Invitation, InvitationEvent, Probe  # noqa: F401
from app.modules.matching.models import EmployerNeed, SelectionVersion  # noqa: F401
from app.modules.profiles.models import (  # noqa: F401
    CandidateFact,
    CandidateProfile,
    CandidateResume,
    Company,
    EmployerProfile,
)

import app.integrations.models  # noqa: E402,F401 — модели интеграций (день 3Б)

metadata = Base.metadata
