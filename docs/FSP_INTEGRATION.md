# Интеграция с ФСП ID

В прототипе «ФСП ID (демо)» — это Keycloak 26 (официальный образ `quay.io/keycloak/keycloak`) с realm `fsp`,
который играет роль единой учётной записи участника соревнований ФСП. Платформа подключается к нему как обычный
OIDC-клиент, поэтому замена демо-стенда на настоящий ФСП ID — это смена адреса, client_id и секрета, без
изменения кода (если ФСП ID отдаёт те же claims; иначе меняется только `mapping.py`).

Код: `backend/app/integrations/fsp_id/` (OIDC, маппинг, API), `keycloak/` (образ, генератор realm),
фронтенд `frontend/src/integrations/FspId.tsx`.

## 1. Развёртывание

| Что | Как |
|---|---|
| Сервис | `keycloak` в `docker-compose.yml`, профиль `fsp-id` (`COMPOSE_PROFILES=fsp-id`) |
| Адрес | тот же домен, путь `/auth` (`KC_HTTP_RELATIVE_PATH=/auth`), nginx контейнера `web` проксирует `/auth/` |
| Закрыто снаружи | `/auth/admin/` и `/auth/realms/master/` → 403; админка доступна только с сервера на `127.0.0.1:8142` |
| Хранилище | отдельная база `keycloak` в нашем PostgreSQL (создаётся скриптом `db/initdb/10-keycloak.sh`) |
| Память | лимит контейнера 640 МБ, `MaxRAMPercentage=40`, `TieredStopAtLevel=1`, локальный кэш; на сервере ≈ 330–400 МБ |
| Realm | `keycloak/realm-fsp.json` генерирует `keycloak/make_realm.py`; импорт при старте (`--import-realm`, существующий realm не перезаписывается) |
| Секреты | `FSP_OIDC_CLIENT_SECRET`, `FSP_DEMO_PASSWORD` — `secrets/fsp_id.env`; пароль администратора — `secrets/keycloak.env`; вне репозитория, `chmod 600` |

## 2. Поток входа (Authorization Code + PKCE, backend-for-frontend)

```
Браузер                Платформа (api)                         Keycloak realm fsp
  │ «Войти через ФСП ID»   │                                        │
  ├─ POST /api/fsp-id/start ─▶ state, nonce, code_verifier → БД     │
  │◀── authorize_url ──────┤  (code_challenge = S256)               │
  ├────────────────────────────── GET /auth/realms/fsp/…/auth ─────▶│ логин и пароль
  │◀────────────── 302 /api/fsp-id/callback?code&state ─────────────┤
  ├─ GET /api/fsp-id/callback ─▶ POST token (code + code_verifier) ─▶│
  │                        │  проверка id_token по JWKS: подпись RS256, iss, aud, exp, nonce
  │                        │  claims → одноразовый билет (5 мин)
  │◀── 303 /fsp-id/done?ticket=… ┤
  ├─ POST /api/fsp-id/exchange ─▶ JWT платформы (известный пользователь)
  │                        │  или consent_required + превью паспорта (новый)
  ├─ POST /api/fsp-id/complete (согласие 152-ФЗ) ─▶ кабинет кандидата + JWT
```

- Токены Keycloak в браузер не попадают; браузер получает только JWT платформы.
- Новая учётная запись создаётся **только после согласия** на обработку ПДн; почта считается подтверждённой, если ФСП ID передал `email_verified=true`.
- Если почта уже занята аккаунтом с паролем — автоматической склейки нет: пользователь входит паролем и
  связывает ФСП ID в разделе «Паспорт ФСП» (`intent=link`, повторный ввод пароля в Keycloak — `prompt=login`).
- Обращение к Keycloak с сервера идёт по внутренней сети (`FSP_OIDC_INTERNAL_BASE=http://keycloak:8080/auth/realms/fsp`),
  а `iss` проверяется по публичному адресу (`FSP_OIDC_ISSUER`). Keycloak с `KC_HOSTNAME_BACKCHANNEL_DYNAMIC`
  выдаёт одинаковый `iss` для обоих путей.

## 3. Claims и паспорт ФСП

Клиент `spectrek-platform` (confidential, PKCE S256, redirect `…/api/fsp-id/callback`) содержит мапперы
пользовательских атрибутов в id_token, access_token и userinfo:

| Claim | Тип | Пример | Куда в платформе |
|---|---|---|---|
| `sub` | строка | UUID Keycloak | `users.fsp_subject`, `fsp_passports.fsp_subject` (уникально) |
| `email`, `email_verified` | строка, bool | `champion@demo.fsp-id.example` | почта новой учётной записи |
| `fsp_id` | строка | `FSP-770012` | номер в паспорте, `candidate_profiles.fsp_id_claimed` (подтверждён) |
| `fsp_rank` | строка | `КМС` | `fsp_passports.sport_rank` — разряд по ЕВСК |
| `fsp_disciplines` | массив | `["product", "algorithmic"]` | дисциплины ЕВСК (справочник `FSP_DISCIPLINES`) |
| `fsp_achievements` | массив JSON | `{"discipline":"product","event":"…","level":"national","date":"2025-11-22","place":1,"result":"победитель"}` | `fsp_achievements`, `verified=true` |

- Уровень доказанности всех фактов из ФСП ID — **T2** («подтверждено реестром»); они участвуют в бонусе рейтинга.
- Неизвестные дисциплины и уровни (`school | regional | interregional | national | international`) отбрасываются.
- ФИО из ФСП ID не копируется в карточку — обезличенность сохраняется, контакты раскрываются по правилам платформы.
- Пользователь без claims `fsp_*` получает связанный паспорт без достижений — нейтрально: бонуса нет, штрафа нет.

Демо-пользователи realm `fsp` (пароль — в подсказке на странице входа, на сервере задан в `secrets/fsp_id.env`):

| Логин | Профиль |
|---|---|
| `fsp-champion` | КМС, продуктовое и алгоритмическое программирование, 3 достижения (в т. ч. всероссийский уровень) |
| `fsp-prizer` | II разряд, программирование систем ИБ, призёр |
| `fsp-newcomer` | нет истории соревнований ФСП |

## 4. API платформы

| Метод | Назначение |
|---|---|
| `GET /api/fsp-id/config` | включён ли вход, подпись кнопки, демо-учётки |
| `POST /api/fsp-id/start` `{intent: login|link}` | начать вход или связку → `authorize_url` |
| `GET /api/fsp-id/callback` | redirect_uri для Keycloak |
| `POST /api/fsp-id/exchange` `{ticket}` | билет → JWT или запрос согласия |
| `POST /api/fsp-id/complete` `{ticket, consent_processing, consent_publication}` | создать кандидата после согласия |

## 5. Как подключить настоящий ФСП ID

1. Зарегистрировать платформу как OIDC-клиента ФСП ID: тип confidential, Authorization Code + PKCE (S256),
   redirect URI `https://<домен>/api/fsp-id/callback`, scopes `openid email profile` и scope с атрибутами паспорта.
2. Согласовать состав claims с ФСП. Если имена отличаются (например, `evsk_rank` вместо `fsp_rank`) —
   поправить словарь в `backend/app/integrations/fsp_id/mapping.py`; остальной код не меняется.
   Если реестр достижений отдаётся отдельным API, а не в токене, — вызвать его в `apply_claims` по `sub`
   (access_token уже есть в callback).
3. Задать переменные: `FSP_OIDC_ISSUER` (issuer ФСП ID), `FSP_OIDC_INTERNAL_BASE` — пусто,
   `FSP_OIDC_CLIENT_ID`, `FSP_OIDC_CLIENT_SECRET` (в `secrets/fsp_id.env`), `FSP_DEMO_ACCOUNTS=` и
   `FSP_DEMO_PASSWORD=` — пусто (подсказка с демо-учётками скрывается).
4. Убрать профиль `fsp-id` из `COMPOSE_PROFILES` — демо-Keycloak больше не запускается.
5. Проверить: `/.well-known/openid-configuration` ФСП ID доступен с сервера; вход тестовым участником;
   в паспорте появились достижения с отметкой T2.

Для production дополнительно: refresh-токены не храним (данные паспорта обновляются при каждом входе);
периодическая синхронизация достижений и отзыв связки при удалении учётной записи в ФСП ID — следующий этап.
