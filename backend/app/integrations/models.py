"""Модели пакетов интеграций — подключаются к общей metadata в app/models.py."""
from app.integrations.ats.models import AtsConnection, AtsDelivery, AtsLink, AtsSettings, AtsStubRecord  # noqa: F401
from app.integrations.egrul.models import RegistryCheck  # noqa: F401
from app.integrations.fsp_id.models import OidcLoginState  # noqa: F401
from app.integrations.push.models import PushSubscription  # noqa: F401
from app.integrations.sus.models import SusResponse  # noqa: F401
from app.integrations.vacancies.models import Vacancy, VacancyApplication  # noqa: F401
