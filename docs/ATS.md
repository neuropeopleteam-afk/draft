# Интеграция с ATS

Когда кандидат принимает приглашение (или сам откликается на вакансию), работодателю нужен кандидат в его
системе подбора, а не в ещё одном кабинете. Платформа передаёт **верифицированный профиль** — категорию и грейд,
подтверждённые навыки T1, паспорт ФСП T2, вилку оффера, ссылку на PDF-профиль — в:

| Система | API | Что делает адаптер |
|---|---|---|
| **Talantix** (hh.ru) | GraphQL `https://api.talantix.ru/graphql`, OAuth 2.0 (access + refresh) | кандидат с резюме TMS и structuredResume, отклик на вакансию, этап, комментарий |
| **«Поток»** (potok.io) | REST v3 `https://app.potok.io/api/v3`, токен компании | кандидат с резюме на вакансии, этап, комментарий |
| **Хантфлоу** | REST v2 `https://api.huntflow.ru/v2`, токен | кандидат с резюме, на вакансии и этапе |
| **Вебхук** | `POST` JSON с подписью HMAC-SHA256 | любая система, в том числе своя |
| **Экспорт JSON** | `vstrechny.candidate.v1` | ручная загрузка |

У Talantix, «Потока» и Хантфлоу два режима: **демо** (заглушка на нашем сервере повторяет API системы — жюри
видит сценарий без реальных токенов) и **реальный** (токены владельца аккаунта). Код один и тот же, меняется
только адрес.

Код: `backend/app/integrations/ats/` — `providers/` (общий интерфейс и адаптеры), `service.py` (журнал, повторы,
идемпотентность), `router.py` (API), `stub_providers.py` и `stub_router.py` (демо-заглушки), `profile.py`
(профиль для ATS и подписанная ссылка на PDF), `cli.py` (импорт токенов из файла секретов).
Фронтенд: `frontend/src/integrations/Ats.tsx` (кабинет работодателя → «Интеграция с ATS»; кнопки «В ATS» и
«Экспорт JSON» у принятых приглашений и откликов). Схемы из документации систем: `docs/ats/`.

## 1. Правила

- Контакты уходят в ATS **только когда они уже раскрыты** работодателю: приглашение принято или кандидат
  откликнулся сам. Правило ТЗ «контакты после согласия кандидата» сохраняется и за пределами платформы.
- Автоматическая передача — при принятии приглашения и при «Пригласить» по отклику, если включено
  «Передавать автоматически». Вручную — кнопка «В ATS».
- **Без дублей.** Таблица `ats_links`: кандидат платформы → id кандидата в ATS и вакансии, на которые он уже
  добавлен. Id сохраняется сразу после создания, поэтому повтор после сбоя продолжает с того же места. Строка
  связи берётся под короткую блокировку (`lock_until`, 90 с) — авто-передача и двойной клик на двух воркерах не
  создадут двух кандидатов. В Talantix дополнительно ищем кандидата по почте (`persons`, поиск по контактам):
  найден — отклик на вакансию вместо нового кандидата.
- Повтор без `force` — «уже передано»; с `force` — кандидат не создаётся заново, обновляются комментарий и этап.
- До 3 попыток с паузой 0,5 → 2 с (`ATS_MAX_ATTEMPTS`); 400/401/402/403/404/422 не повторяются. Результат,
  шаги, HTTP-код и текст ошибки — в журнале `ats_deliveries` (без ПДн); строку с ошибкой можно «Повторить».
- Токены хранятся зашифрованными (Fernet, `INTEGRATIONS_SECRET_KEY`), в интерфейсе — маска. Новая пара токенов
  Talantix после обновления сохраняется сразу (refresh одноразовый).
- Защита от SSRF: только `https://` и публичные адреса (исключение — наши заглушки).
- Сбой ATS не влияет на принятие приглашения: передача идёт в фоне.

## 2. Профиль для ATS

Общая основа (`profile.build`) из карточки `vstrechny.candidate.v1`:

| Что | Откуда | Уровень |
|---|---|---|
| Фамилия, имя, отчество | раскрытые контакты (разбор «Фамилия Имя Отчество» в любом порядке) | — |
| Почта, телефон, Telegram | раскрытые контакты | — |
| Категория и грейд | «Backend · Middle» | T1 |
| Адаптивный тест | верно из N, θ ± SE, дата, достоверность результата | T1 |
| Подтверждённые навыки | навыки, подтверждённые заданиями теста; зонды работодателя | T1 |
| Паспорт ФСП | привязан ли, источник (реестр / ФСП ID / демо), подтверждённые достижения | T2 |
| Заявлено кандидатом | стек, опыт, формат работы, город | T0 |
| Почему выбран | доказательства из приглашения | T0–T2 |
| Оффер | позиция и вилка «от–до» | — |
| PDF-профиль | `GET /api/ats/profile/{token}.pdf` — подписанная ссылка (JWT, 180 дней) на компанию и кандидата: открывается из ATS без входа; контакты в PDF — только если раскрыты этой компании | — |
| Карточка | ссылка на карточку кандидата в кабинете работодателя | — |

Вилка оффера передаётся текстом (резюме, комментарий), а не в поле «желаемая зарплата» — это предложение
работодателя, а не ожидания кандидата.

## 3. Talantix

Документация: https://api.talantix.ru/docs/. Интроспекция схемы (`POST /graphql/schema`) без токена недоступна
(400), поэтому используемое подмножество схемы взято из справочника документации:
`docs/ats/talantix-schema.subset.graphql`. Тест `test_talantix_queries_match_documented_schema` сверяет каждый
запрос адаптера (поля, аргументы, типы переменных) с этим подмножеством, а `…inputs_match…` — входные объекты.

**Авторизация.** API доступно на тарифе «Оптимальный». Пару токенов выпускает пользователь с ролью
«Администратор» в личном кабинете; ссылка на JSON с токенами живёт 30 дней или до первого обновления.
В настройках вставляется JSON целиком (`access_token`, `refresh_token`, `expires_in`, `refresh_token_expires_in`,
`created_at` в мс) — или access и refresh по отдельности. Access живёт 1 день, refresh — 120 дней, одноразовый.

- `GET /auth_check` → 204 — «Проверить подключение»; 401 `{"type": "invalid_token", "detail": "token_expired"}` —
  токен истёк.
- `POST /oauth/token` (`application/x-www-form-urlencoded`: `grant_type=refresh_token&refresh_token=…`) —
  новая пара. Обновляем заранее (за минуту до `expires_at`) и по 401 с одной повторной попыткой; новая пара
  сразу пишется в БД. `400 invalid_grant` — refresh истёк или уже использован: нужна новая пара.
- Заголовки каждого запроса: `Authorization: Bearer`, `Content-Type: application/json`, обязательный
  `User-Agent` — `Vstrechny-ATS/1.0 (<компания>; <контакт>)`, контакт — `ATS_USER_AGENT_CONTACT`.
- Ответы GraphQL 200 / 210 (INTERNAL) / 269 (EXTERNAL_SYSTEM_ERROR); предметные ошибки — типами в `data`
  (`PersonSaveError` с полями и нарушенными ограничениями → журнал). 403 `insufficient_permissions` — нет тарифа
  или прав. Одно корневое поле на запрос.

**Передача** (`providers/talantix.py`):

1. `persons(filter: {search: <почта>, searchFrom: [CONTACTS]})` — кандидат уже в базе? Да — дубликат не создаём.
2. `personSources(filterByName: "Встречный (ФСП)")`, при отсутствии — `createPersonSource` (один раз, id
   кэшируется в подключении).
3. `dictionaries { areas }` — `areaId` по городу кандидата (если нашёлся; иначе без региона).
4. `createPerson(personCreate: PersonCreateInput)`:

   | Поле Talantix | Значение |
   |---|---|
   | `firstName`, `lastName`, `middleName` | ФИО (нет ФИО — «Кандидат» + код кандидата) |
   | `contacts` | `email`, `cell`, `telegram` |
   | `vacancyIds` | выбранная вакансия |
   | `sourceId` | источник «Встречный (ФСП)» |
   | `areaId` | регион из справочника areas |
   | `customResumes [{type: TMS, text}]` | HTML профиля: все разделы п. 2 с уровнями T0/T1/T2 и ссылками |
   | `structuredResume.title` | «Backend · Middle — <позиция>» |
   | `structuredResume.link` | ссылка на PDF-профиль |
   | `structuredResume.skills` | текст профиля |
   | `structuredResume.keySkills` | подтверждённые навыки (T1) |

   Кандидат из базы или повтор на другую вакансию — `createResponses(personIds, vacancyIds)`.
5. `transferPersonsToWorkflowStatus(personIds, workflowStatusId)` — если выбран этап (идемпотентно).
6. `createPersonComment` на вакансии — вилка оффера, тест и навыки T1, ФСП T2, ссылка на PDF; для кандидата из
   базы — полный профиль (резюме существующего кандидата не перезаписываем).

Вакансии для выбора — `vacancies(first: 200, filter: {vacancyStatus})`, этапы — `vacancy(id) { workflowStatuses }`.

## 4. «Поток»

Документация: https://api-doc.potok.io/ (OpenAPI 3.1: https://api-doc.potok.io/potok-api-v3.yml; подмножество,
которое использует адаптер, — `docs/ats/potok-api-v3.subset.json`; тест сверяет с ним тела запросов).

**Авторизация.** Токен компании: настройки компании в «Потоке» → «Генерация токенов». Передаётся
`Authorization: Bearer <token>`. Частота запросов ограничена (429 при превышении). 402 — подписка просрочена.

**Передача** (`providers/potok.py`):

1. `POST /applicants.json` `{"applicant": {...}}`:

   | Поле «Потока» | Значение |
   |---|---|
   | `first_name`, `last_name`, `middle_name` | ФИО |
   | `emails`, `phones` | почта; телефон цифрами с кодом страны (`79001112233`) |
   | `accounts [{url, icon_id: telegram}]` | Telegram |
   | `source_type`, `source_url` | `sourced`, адрес платформы — источник из «Источники кандидатов» |
   | `resumes[0].cv_params.title` | «Backend · Middle — <позиция>» |
   | `…skills` | HTML профиля (все разделы п. 2) |
   | `…about_me` | оффер и вилка |
   | `…skill_set` | подтверждённые навыки (T1) |
   | `…education.attestation` | адаптивный тест «Встречный» (T1) |
   | `…awards` | достижения ФСП (T2) |
   | `…certificate` | PDF-профиль (ссылка) |
   | `events [{body, type: Event::Comment}]` | комментарий: вилка, T1/T2, ссылка на PDF. Именно список: на объект `{body, type}` (как в опубликованной спецификации) настоящий API отвечает 500 — проверено 07.10.2026; заглушка ведёт себя так же |
   | `ajs_joins [{job_id}]` | сразу на выбранную вакансию |

   Согласие на обработку ПДн (`workflows.personal_data_agreement`) за кандидата не проставляем.
2. Повтор на другую вакансию — `POST /ajs_joins.json` (`job_id`, `applicant_id`, `stage_type: sourced`);
   422 «кандидат на вакансии уже существует» — уже добавлен, не ошибка.
3. `POST /ajs_joins/{id}/change_stage.json` `{stage_id}` — если выбран этап.
4. `POST /events.json` (`Event::Comment`, `job_id`) — комментарий при повторной передаче.

Поиска кандидата по почте в API «Потока» нет, поэтому дубликаты исключает связь `ats_links`. Вакансии и этапы
для выбора — `GET /jobs.json?by_scope=all` (у каждой вакансии `stages`).

## 5. Хантфлоу

В настройках: адрес API (`https://api.huntflow.ru/v2` — облако; для коробки — свой), **токен** (Хантфлоу →
Настройки → API), **id организации** (`account_id`), **id вакансии**, при желании — id этапа.
«Проверить подключение» — `GET /me`, `GET /accounts`, `GET /accounts/{id}/vacancies/statuses`; вакансии для
выбора — `GET /accounts/{id}/vacancies`.

1. `POST /accounts/{account_id}/applicants`: `last_name`, `first_name`, `middle_name`, `email`, `phone`,
   `position` (категория), `money` (вилка), `social` (Telegram), `externals[0].data.body` — текст профиля п. 2.
2. `POST /accounts/{account_id}/applicants/{applicant_id}/vacancy`: `vacancy`, `status` (заданный этап или
   первый), `comment` — оффер. Повтор с `force` вызывает только этот метод (он же меняет этап).

## 6. Универсальный вебхук

`POST <URL>` с телом JSON (схема `vstrechny.candidate.v1`, см. п. 7) и заголовками:

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

## 7. Экспорт JSON (`vstrechny.candidate.v1`)

`GET /api/employer/invitations/{id}/export.json`, `GET /api/employer/applications/{id}/export.json` — то же тело,
что уходит в вебхук:

```json
{
  "schema": "vstrechny.candidate.v1",
  "exported_at": "2026-10-05T15:00:00+00:00",
  "source": {"platform": "Встречный (спецтрек ФСП)", "url": "https://fsp.neuropeople.pro"},
  "company": {"id": "…", "name": "…", "inn": "<реквизит>"},
  "candidate": {
    "ref": "C-7Q2K9M", "category_id": "backend.middle", "category_title": "Backend · Middle",
    "contacts": {"full_name": "…", "email": "…", "phone": "…", "telegram": "…"},
    "card": {"test": {…}, "skills_confirmed": […], "fsp": {"achievements": […]}, "…": "обезличенная карточка"}
  },
  "context": {"type": "invitation", "id": "…", "status": "accepted", "position_title": "…",
              "salary_from": 200000, "salary_to": 280000, "accepted_at": "…", "evidence": […]},
  "links": {"pdf": "https://fsp.neuropeople.pro/api/ats/profile/<token>.pdf",
            "card": "https://fsp.neuropeople.pro/employer/candidates/C-7Q2K9M"},
  "evidence_levels": {"T0": "заявлено кандидатом", "T1": "подтверждено тестом/зондом", "T2": "подтверждено реестром ФСП"}
}
```

Для отклика на вакансию `context.type = "vacancy_application"`, плюс `vacancy_id`, `applied_at`, `cover_letter`.

## 8. Демо-режим (заглушки)

Кнопка «Подключить все демо-ATS» (или «Демо» у отдельной системы) включает заглушки на нашем сервере.
Платформа обращается к ним по настоящему HTTP через публичный адрес — тем же клиентом, что и к реальным системам.

| Заглушка | Адрес | Что повторяет |
|---|---|---|
| Talantix | `/api/ats-stub/talantix/{auth_check, oauth/token, graphql}` | обязательный User-Agent и Bearer, 401 `token_expired`, одноразовый refresh (`invalid_grant`), access живёт 15 минут — автообновление видно в журнале; поля me, vacancies, vacancy, persons, personSources, createPersonSource, createPerson (валидация как `PersonSaveError`), createResponses, transferPersonsToWorkflowStatus, createPersonComment, dictionaries.areas |
| «Поток» | `/api/ats-stub/potok/api/v3/…` | `jobs.json`, `jobs/{id}.json`, `applicants.json` (422 с полями), `applicants/{id}.json`, `ajs_joins.json` (422 при повторе), `change_stage.json`, `events.json`; Bearer или `?token=` |
| Хантфлоу | `/api/ats-stub/huntflow/v2/…` | `/me`, `/accounts`, `/accounts/1/vacancies`, `/accounts/1/vacancies/statuses`, `/accounts/1/applicants`, `/accounts/1/applicants/{id}/vacancy` |
| Вебхук | `/api/ats-stub/webhook/{ключ}` | приём с проверкой подписи |

Вакансии демо: «Backend-разработчик (платежи)», «Python-разработчик (интеграции)», «Frontend-разработчик
(React)», «Аналитик данных» (архив), этапы «Новые → Первичный контакт → Интервью → Оффер → Вышел на работу».
Всё пришедшее видно в блоке «Тестовая ATS: что пришло». У демо-компании жюри все четыре системы подключены
сидом: принятие приглашения Ильёй Сергеевым сразу уходит в Talantix, «Поток», Хантфлоу и вебхук.

## 9. Как подключить реальные системы

**Через кабинет** (рекомендуется): «Интеграция с ATS» → вкладка системы → режим «Реальный» → вставить токены →
«Сохранить» → «Проверить подключение» → «Загрузить вакансии из ATS», выбрать вакансию и этап → «Сохранить».
Демо и реальный режим не смешиваются: при смене режима или адреса прежние связи кандидатов сбрасываются.

**Через файл секретов** (без ввода в браузере): `/opt/spectrek_fsp/secrets/ats.env` на сервере
(подключается docker-compose как `ATS_ENV_FILE`, файл необязательный):

```
TALANTIX_TOKENS_JSON={"access_token":"…","refresh_token":"…","expires_in":86400,"refresh_token_expires_in":10368000,"created_at":…}
TALANTIX_VACANCY_ID=…
POTOK_TOKEN=…
POTOK_VACANCY_ID=…
HUNTFLOW_TOKEN=…
HUNTFLOW_ACCOUNT_ID=…
HUNTFLOW_VACANCY_ID=…
ATS_USER_AGENT_CONTACT=<почта для Talantix>
```

и импорт в компанию работодателя (выводит только маски):

```
docker compose exec api python -m app.integrations.ats.cli import-env --employer-email <почта работодателя>
docker compose exec api python -m app.integrations.ats.cli check --employer-email <почта работодателя>
```

Refresh Talantix одноразовый: после первого обновления пара из файла устаревает, актуальная живёт в БД.
Повторный импорт Talantix без `--force` пропускается. Реальные токены не стоит класть в демо-компанию жюри:
сброс демо-данных жюри (`POST /api/jury/reset`) удаляет компанию вместе с подключениями.

## 10. API

| Метод | Назначение |
|---|---|
| `GET /api/employer/ats/providers` | все системы: режим, включено, маска токена, сроки токенов, вакансия и этап, последняя проверка |
| `PUT /api/employer/ats/providers/{talantix\|potok}` | режим, токены (только запись), адрес, вакансия и этап, сопоставление вакансий платформы |
| `POST /api/employer/ats/providers/{code}/demo` | демо-режим системы |
| `POST /api/employer/ats/providers/{code}/check` | проверить подключение (Talantix — `auth_check`, `me`, вакансии) |
| `GET /api/employer/ats/providers/{code}/vacancies` | вакансии из ATS для выбора |
| `GET /api/employer/ats/providers/{code}/vacancies/{id}/stages` | этапы вакансии |
| `POST /api/employer/ats/demo/connect-all` | подключить все демо-ATS |
| `GET/PUT /api/employer/ats/settings` | Хантфлоу, вебхук, «Передавать автоматически» |
| `GET /api/employer/ats/webhook-secret` | показать секрет вебхука работодателю |
| `POST /api/employer/ats/huntflow/check` | проверить Хантфлоу (совместимость) |
| `POST /api/employer/ats/stub/connect` | подключить заглушки Хантфлоу и вебхука |
| `GET /api/employer/ats/stub/records` | что пришло в заглушки |
| `GET /api/employer/ats/deliveries` | журнал передач (шаги, id в ATS, ошибки) |
| `POST /api/employer/ats/deliveries/{id}/retry` | повторить передачу из журнала |
| `POST /api/employer/ats/push` `{invitation_id \| application_id, target?, ats_vacancy_id?, force?}` | передать вручную; `ats_vacancy_id` — на другую вакансию в ATS |
| `GET /api/ats/profile/{token}.pdf` | PDF-профиль по подписанной ссылке (для ATS) |
| `GET /api/employer/ats/stages` | обратный канал: последний опрос (когда, проверено, изменений, ошибок) и журнал этапов |
| `POST /api/employer/ats/stages/sync` | опросить этапы в «Потоке» сейчас (кнопка «Обновить этапы сейчас») |
| `GET /api/employer/ats/stub/potok/pipeline` | демо-«Поток» глазами рекрутёра: кандидаты на вакансиях и этапы воронки |
| `POST /api/employer/ats/stub/potok/move` `{join_id, stage_id?, decline?}` | демо-«Поток»: рекрутёр переводит кандидата на этап или отклоняет |

## 11. Обратный канал: этап в «Потоке» → этап на платформе

Рекрутёр двигает кандидата по воронке в «Потоке» — платформа узнаёт об этом и показывает этап работодателю и
кандидату. Вебхуков об этапах у «Потока» нет, поэтому платформа опрашивает API v3 (`app/integrations/ats/stages.py`,
клиент — `PotokClient.join_state` в `providers/potok.py`).

**Что опрашивается.** После передачи (п. 4) в `ats_links` лежат id кандидата в «Потоке» и вакансии, на которые он
добавлен. Для каждой пары «кандидат — вакансия»:

1. `GET /jobs/{job_id}/ajs_joins.json?applicant_id=…` → `objects[] {id, job_id, applicant_id, stage: {id, stage_type},
   active}`; `active: false` — кандидат отклонён на вакансии. В примере ответа спецификации вместо объекта `stage`
   стоит `stage_id` — адаптер принимает оба варианта.
2. Если метод компании недоступен (403/404) — `GET /applicants/{id}.json` (этап есть в `ajs_joins[]`, признака отказа
   нет).
3. Названия этапов — `GET /jobs/{id}.json` (`stages`), один запрос на вакансию за опрос.

Оба метода и `POST /jobs/{job_id}/{applicant_id}/decline.json` (отклонение; платформа его не вызывает, он есть в
заглушке, чтобы демо-«Поток» вёл себя как настоящий) описаны в `docs/ats/potok-api-v3.subset.json` по опубликованной
спецификации; тест `test_potok_stub_back_channel_methods_match_spec_subset` сверяет с ней ответы заглушки.

**Тип этапа → этап на платформе.**

| `stage_type` в «Потоке» | Этап на платформе | Статус отклика |
|---|---|---|
| `sourced`, `applied`, `screening` и свои этапы компании | на рассмотрении | не меняется |
| `interview`, `interview_client`, другие `interview_*` | собеседование | «Приглашение на интервью» |
| `offer` | оффер | «Приглашение на интервью» |
| `accepted` | вышел на работу | «Приглашение на интервью» |
| любой при `active: false` | отказ | «Отказ» |

**Что меняется на платформе.**

* Приглашение: статус остаётся «Принято» (контакты уже открыты — правило ТЗ), рядом — этап у работодателя. Работодатель
  видит название этапа из «Потока» (««Поток»: Интервью»), кандидат — этап платформы («Этап у работодателя:
  собеседование»); внутренние названия этапов компании кандидату не показываются.
* Отклик на вакансию: этап и статус (таблица выше); событие попадает в историю отклика, его видят обе стороны.
* Кандидату уходит push при переходе на собеседование, оффер, выход на работу или отказ (на «на рассмотрении» —
  нет: это этап сразу после передачи).
* Каждое изменение и каждая ошибка — в журнале `ats_stage_events` (без ПДн: код кандидата, id в «Потоке», этапы).
  Повторяющаяся ошибка пишется один раз. Ошибка по одной паре (например, 404) не останавливает опрос остальных;
  401, 402, 429 и сбой сети прерывают опрос компании до следующего цикла.

**Когда.** Фоновый опрос раз в `ATS_STAGE_POLL_S` секунд (по умолчанию 300; 0 — только кнопкой). Работают оба воркера
uvicorn, но компанию за один цикл опрашивает один из них (CAS по `ats_connections.stages_synced_at`); за раз — не больше
`ats_stage_poll_batch` (200) пар. Кнопка «Обновить этапы сейчас» в кабинете («Интеграция с ATS» → «Этапы из «Потока»»)
опрашивает сразу.

**Демо.** Демо-«Поток» (заглушка) отвечает тем же API. В блоке «Этапы из «Потока»» работодатель — рекрутёр: кнопки
этапов и «Отклонить» меняют запись в заглушке, как интерфейс «Потока»; платформа узнаёт об этом тем же опросом. В
проводнике жюри это часть шага «Передача в ATS»: перевести Илью на «Интервью» → «Обновить этапы сейчас» → бейдж
««Поток»: Интервью» у приглашения работодателя и «Этап у работодателя: собеседование» у кандидата.

**Реальный «Поток».** На стенде подключена тестовая компания (вакансия 1714909). Передача проверена на настоящем API
07.10.2026; формат ответа `ajs_joins.json` и права токена на этот метод на настоящем API ещё не проверены — если
метод закрыт (403/404), работает запасной путь через `GET /applicants/{id}.json` без признака отказа. Проверка после
выкладки: «Интеграция с ATS» → «Обновить этапы сейчас» (или `POST /api/employer/ats/stages/sync`) от учётки
тестовой компании, затем журнал этапов.

**Дальше.** Хантфлоу — вебхуки `APPLICANT` вместо опроса; Talantix — опрос этапа по сохранённым id из `ats_links`
тем же модулем. Другие ATS (E-Staff, Friend Work) — по интерфейсу `providers/base.Provider`.
