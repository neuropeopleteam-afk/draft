# Интеграция с ATS

Когда кандидат принимает приглашение (или сам откликается на вакансию), работодателю нужен кандидат в его
системе подбора, а не в ещё одном кабинете. Платформа передаёт карточку тремя способами: **Хантфлоу (API v2)**,
**универсальный вебхук** с подписью HMAC и **экспорт JSON**. Для демо есть **тестовая ATS** на нашем сервере.

Код: `backend/app/integrations/ats/`, фронтенд `frontend/src/integrations/Ats.tsx`
(кабинет работодателя → «Интеграция с ATS»; кнопки «В ATS» и «Экспорт JSON» у принятых приглашений и откликов).

## 1. Правила

- Контакты уходят в ATS **только когда они уже раскрыты** работодателю: приглашение принято или кандидат
  откликнулся сам. Правило ТЗ «контакты после согласия кандидата» сохраняется и за пределами платформы.
- Автоматическая передача — при принятии приглашения, если включено «Передавать автоматически».
  Вручную — кнопка «В ATS» (приглашение или отклик).
- До 3 попыток с паузой 0,5 → 2 с (`ATS_MAX_ATTEMPTS`); результат, HTTP-код и текст ошибки — в журнале
  `ats_deliveries` (без ПДн), журнал виден работодателю.
- Токен Хантфлоу и секрет вебхука хранятся зашифрованными (Fernet, `INTEGRATIONS_SECRET_KEY`), в интерфейсе — маска.
- Защита от SSRF: только `https://` и публичные адреса; адреса во внутренней сети отклоняются
  (исключение — наша тестовая ATS).
- Сбой ATS не влияет на принятие приглашения: передача идёт в фоне.

## 2. Хантфлоу (публичный API v2)

Работодатель в настройках компании задаёт: адрес API (`https://api.huntflow.ru/v2` — облако; для коробочной
версии — свой), **токен** (Хантфлоу → Настройки → API), **id организации** (`account_id`), **id вакансии**
и, при желании, id этапа. Кнопка «Проверить связь» вызывает `GET /me`, `GET /accounts` и
`GET /accounts/{account_id}/vacancies/statuses`.

Вызовы при передаче (заголовок `Authorization: Bearer <токен>`):

1. `POST /accounts/{account_id}/applicants` — создать кандидата:

   | Поле Хантфлоу | Откуда |
   |---|---|
   | `last_name`, `first_name`, `middle_name` | ФИО кандидата (разбор «Фамилия Имя Отчество» в любом порядке) |
   | `email`, `phone` | раскрытые контакты |
   | `position` | категория кандидата («Backend · Middle») |
   | `money` | вилка предложения |
   | `social` | Telegram, если указан |
   | `externals[0].data.body` | текст резюме: категория, вилка, доказательства T1/T2 (тест, навыки, ФСП), ссылка на карточку |

2. `POST /accounts/{account_id}/applicants/{applicant_id}/vacancy` — закрепить на вакансии:
   `vacancy`, `status` (заданный этап или первый активный этап подбора), `comment` («Принял приглашение на
   платформе „Встречный“…»).

Если вакансия не задана — кандидат только добавляется в базу.

## 3. Универсальный вебхук

`POST <URL>` с телом JSON (схема `vstrechny.candidate.v1`, см. п. 4) и заголовками:

| Заголовок | Значение |
|---|---|
| `X-Vstrechny-Event` | `candidate.accepted_invitation` или `candidate.applied` |
| `X-Vstrechny-Delivery` | id доставки (для идемпотентности на стороне получателя) |
| `X-Vstrechny-Timestamp` | Unix-время отправки |
| `X-Vstrechny-Signature` | `t=<timestamp>,v1=<hex HMAC-SHA256(secret, "<timestamp>." + тело)>` |

Проверка на стороне получателя (Python):

```python
import hmac, hashlib, time

def verify(secret: str, body: bytes, header: str, tolerance_s: int = 300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    ts = int(parts["t"])
    if abs(time.time() - ts) > tolerance_s:
        return False  # защита от повтора
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, parts["v1"])
```

Ответ 2xx — доставлено; иначе повтор.

## 4. Экспорт JSON (`vstrechny.candidate.v1`)

`GET /api/employer/invitations/{id}/export.json`, `GET /api/employer/applications/{id}/export.json` — то же тело,
что уходит в вебхук:

```json
{
  "schema": "vstrechny.candidate.v1",
  "exported_at": "2026-10-05T15:00:00+00:00",
  "source": {"platform": "Встречный (спецтрек ФСП)", "url": "https://fsp.neuropeople.pro"},
  "company": {"id": "…", "name": "…", "inn": "9701316954"},
  "candidate": {
    "ref": "C-7Q2K9M", "category_id": "backend.middle", "category_title": "Backend · Middle",
    "contacts": {"full_name": "…", "email": "…", "phone": "…", "telegram": "…"},
    "card": {"test": {…}, "skills_confirmed": […], "fsp": {"achievements": […]}, "…": "обезличенная карточка"}
  },
  "context": {"type": "invitation", "id": "…", "status": "accepted", "position_title": "…",
              "salary_from": 200000, "salary_to": 280000, "accepted_at": "…", "evidence": […]},
  "evidence_levels": {"T0": "заявлено кандидатом", "T1": "подтверждено тестом/зондом", "T2": "подтверждено реестром ФСП"}
}
```

Для отклика на вакансию `context.type = "vacancy_application"`, плюс `vacancy_id`, `applied_at`, `cover_letter`.

## 5. Тестовая ATS (для демо)

Кнопка «Подключить тестовую ATS» включает обе интеграции с адресами нашей заглушки:

- `…/api/ats-stub/huntflow/v2/…` — те же методы, что у Хантфлоу (`/me`, `/accounts`, `/accounts/1/vacancies/statuses`,
  `/accounts/1/applicants`, `/accounts/1/applicants/{id}/vacancy`), токен — персональный ключ компании;
- `…/api/ats-stub/webhook/{ключ}` — приём вебхука с проверкой подписи.

Всё пришедшее видно в блоке «Тестовая ATS: что пришло» (кандидат, вакансия и этап, подпись верна/неверна, тело
JSON). Записи заглушки привязаны к компании и видны только её сотрудникам.

## 6. API

| Метод | Назначение |
|---|---|
| `GET/PUT /api/employer/ats/settings` | настройки (токен и секрет — только запись) |
| `GET /api/employer/ats/webhook-secret` | показать секрет вебхука работодателю |
| `POST /api/employer/ats/huntflow/check` | проверить токен и организацию |
| `POST /api/employer/ats/stub/connect` | подключить тестовую ATS |
| `GET /api/employer/ats/stub/records` | что пришло в тестовую ATS |
| `GET /api/employer/ats/deliveries` | журнал передач |
| `POST /api/employer/ats/push` `{invitation_id | application_id, target?}` | передать вручную |

## 7. Дальше

Другие ATS (Talantix, E-Staff, Potok) — через их API по тому же шаблону `clients.py`; встречный канал
(статус кандидата в ATS → статус на платформе) — через вебхуки Хантфлоу (`APPLICANT` события).
