# Встречный — платформа подбора ИТ-специалистов «наоборот»

[![Покрытие тестами бэкенда](docs/badges/coverage.svg)](docs/testing.md) [![Тесты бэкенда](docs/badges/tests.svg)](docs/testing.md)

Прототип для спецтрека ФСП (ЛЦТ 2026). Работодатель сам находит проверенного кандидата по категории
«направление · грейд» и приглашает его с зарплатой. Категория присваивается не по резюме, а по обязательному
пути: опрос → выбор предполагаемого грейда → тест. Факты о кандидате помечены уровнем доказанности
(T0 — самоописание, T1 — подтверждено тестом/зондом, T2 — подтверждено реестром ФСП).

«Встречный» — рабочее название, меняется в `frontend/src/components/Logo.tsx`.

- Развёрнутый прототип: https://fsp.neuropeople.pro
- Доступ к стенду: demo / *** (базовая авторизация nginx; без неё открыты только `/api/*`, `/robots.txt`, манифест PWA, `sw.js`, иконки)
- Для жюри: блок «Для экспертов жюри» на главной — вход в один клик за кандидата (с паспортом ФСП и без), работодателя и эксперта, проводник по сценарию, сброс демо; метрики — страница `/validation`
- Документация API (OpenAPI/Swagger): https://fsp.neuropeople.pro/api/docs
- Архитектура и модель данных: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Интеграции: [антифрод и индекс доверия](docs/ANTIFRAUD.md), [ФСП ID](docs/FSP_INTEGRATION.md), [ATS](docs/ATS.md), [нагрузочный тест](docs/LOAD_TEST.md)

## Состав

| Каталог | Что внутри |
|---|---|
| `backend/` | FastAPI (Python 3.12), SQLAlchemy 2, Alembic, модульный монолит: auth, catalog, profiles, assessment, matching, invitations, fsp, validation, pdf, notifications |
| `backend/assessment_bank/` | Копия пакета банка заданий (чистый Python, без БД); обновляется `tools/sync_bank.py` |
| `frontend/` | React 18 + Vite + TypeScript + Tailwind; главная, регистрация/вход/подтверждение почты, кабинеты кандидата и работодателя |
| `docs/` | Архитектура, модель данных, схема интеграции с ФСП ID (Keycloak) |
| `keycloak/` | Демо-стенд «ФСП ID»: образ Keycloak, генератор realm `fsp` с демо-участниками |
| `docker-compose.yml` | db (PostgreSQL 16) + api + web; Keycloak «ФСП ID (демо)» — профиль `fsp-id` |

## Быстрый старт (Docker)

Нужны Docker 24+ с плагином compose, `make`, `openssl`.

```bash
git clone <адрес репозитория> spectrek && cd spectrek
make up            # создаст .env со случайными секретами, соберёт и запустит db, api, web
```

1. Откройте http://127.0.0.1:8140 — главная страница.
2. Нажмите «Регистрация», выберите роль, введите почту и пароль (буквы и цифры, от 8 символов), отметьте согласие.
3. На экране подтверждения в режиме разработки код показан прямо на странице (и в логе: `make logs`).
4. После ввода кода откроется кабинет кандидата или работодателя.
5. Документация API: http://127.0.0.1:8140/api/docs (кнопка Authorize — вход почтой и паролем).

Остановить: `make down` (данные БД сохраняются в томе `db_data`).

### Почта

По умолчанию работает режим разработки (`DEV_MODE`): код подтверждения пишется в лог API и возвращается
в ответе `/api/auth/register`. Для реальной отправки через Yandex Cloud Postbox (HTTPS API, SESv2-совместимый)
положите ключи в `secrets/postbox.env` (путь задаётся `POSTBOX_ENV_FILE`):

```
POSTBOX_ACCESS_KEY_ID=...
POSTBOX_SECRET_ACCESS_KEY=...
```

Если `DEV_MODE` не задан, он включается автоматически, пока ключей Postbox нет.

## Тесты

```bash
make test        # pytest в контейнере api (SQLite, схема создаётся миграциями Alembic)
make test-pg     # те же тесты на PostgreSQL (база fsp_test в контейнере db)
make coverage    # pytest с покрытием и порогом 80 % (как в CI), обновляет значки docs/badges
make test-bank   # валидатор банка заданий: детерминизм, разнообразие, ключи исполнением кода
make stack-ci && make e2e                  # стек в Docker + сквозные сценарии жюри (Playwright, папка e2e/)
E2E_BASIC_PASSWORD=… make e2e-stand        # те же сценарии против стенда, демо жюри сбрасывается до и после
make validate    # пересчёт метрик страницы /validation (≈ 15–20 мин)
make bench       # бенчмарк подбора со скрытой истиной (200 × 2000), итог — docs/validation/MATCHING_BENCH.md
```

CI (GitHub Actions, `.github/workflows`): `ci.yml` — бэкенд на SQLite с покрытием и на PostgreSQL 16, банк заданий,
фронтенд (типы и сборка), Docker-образы, стек и сквозные сценарии; `e2e.yml` — сценарии против стенда вручную и
по расписанию. Состав тестов, связь с критериями ТЗ, текущие цифры — [docs/testing.md](docs/testing.md).

## Демо-данные

```bash
docker compose exec -T api python -m app.modules.demo.seed           # 150 кандидатов, 10 работодателей, 15 потребностей
docker compose exec -T api python -m app.modules.demo.seed --reset   # пересоздать
docker compose exec -T api python -m app.modules.demo.seed --delete  # удалить только демо-записи
docker compose exec -T api python -m app.integrations.vacancies.demo  # 11 демо-вакансий (одна — «приманка»)
```

Демо-записи помечены `is_demo` (адреса `*@demo.invalid`, компании «Демо: …», паспорта ФСП из демо-реестра);
письма им не отправляются.

Без Docker:

```bash
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

## Локальная разработка без Docker

```bash
# терминал 1 — API на SQLite с автоперезагрузкой (http://localhost:8000/api/docs)
make dev-backend
# терминал 2 — фронтенд Vite (http://localhost:5173), /api проксируется на :8000
make dev-frontend
```

## Переменные окружения

Полный список с пояснениями — в [.env.example](.env.example). Секреты (`POSTGRES_PASSWORD`, `JWT_SECRET`,
ключи Postbox, ключ LLM) в репозиторий не попадают.

LLM: Yandex AI Studio (OpenAI-совместимый API, модели в РФ — данные не покидают РФ). Переменные `LLM_PROVIDER`,
`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_FOLDER_ID`, `LLM_MODEL` задаются в файле `LLM_ENV_FILE`
(на сервере `/opt/spectrek_fsp/secrets/llm.env`). Без них всё работает на словарях и правилах.
Движок теста — `ASSESSMENT_ENGINE` (`bank` — адаптивный тест на банке заданий; `stub` — запасная заглушка).
Банк обновляется командой `python tools/sync_bank.py --commit` (из окружения банка: numpy, scipy, pydantic,
PyYAML); скрипт выкладки вызывает её сам, так что новые семейства из `../bank` попадают на сервер автоматически.
Открытые ответы теста оценивает LLM по рубрике (`LLM_GRADING_MODEL`), без LLM — статус «на проверке».
Название продукта — одна настройка `PRODUCT_NAME` (по умолчанию «Встречный»).

## Развёртывание на сервере

```bash
git clone <репозиторий> /opt/spectrek_fsp/app && cd /opt/spectrek_fsp/app
make env && make up          # порты публикуются только на 127.0.0.1 (WEB_PORT=8140, API_PORT=8141)
```

Внешний nginx проксирует домен на `127.0.0.1:8140` (рабочий пример без секретов —
[infra/nginx/fsp.neuropeople.pro.conf.example](infra/nginx/fsp.neuropeople.pro.conf.example), описание — раздел «Развёртывание» в docs/ARCHITECTURE.md),
сертификат — `certbot certonly --webroot`. Обновление: `git pull && docker compose up -d --build`
(миграции применяются при старте контейнера api).

## Лицензия

MIT — см. [LICENSE](LICENSE). Код открытый, без обфускации.
