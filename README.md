# Встречный — платформа подбора ИТ-специалистов «наоборот»

Прототип для спецтрека ФСП (ЛЦТ 2026). Работодатель сам находит проверенного кандидата по категории
«направление · грейд» и приглашает его с зарплатой. Категория присваивается не по резюме, а по обязательному
пути: опрос → выбор предполагаемого грейда → тест. Факты о кандидате помечены уровнем доказанности
(T0 — самоописание, T1 — подтверждено тестом/зондом, T2 — подтверждено реестром ФСП).

«Встречный» — рабочее название, меняется в `frontend/src/components/Logo.tsx`.

- Развёрнутый прототип: https://fsp.neuropeople.pro
- Документация API (OpenAPI/Swagger): https://fsp.neuropeople.pro/api/docs
- Архитектура и модель данных: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Состав

| Каталог | Что внутри |
|---|---|
| `backend/` | FastAPI (Python 3.12), SQLAlchemy 2, Alembic, модульный монолит: auth, catalog, profiles, assessment, matching, invitations, fsp, validation, pdf, notifications |
| `backend/assessment_bank/` | Копия пакета банка заданий (чистый Python, без БД); обновляется `tools/sync_bank.py` |
| `frontend/` | React 18 + Vite + TypeScript + Tailwind; главная, регистрация/вход/подтверждение почты, кабинеты кандидата и работодателя |
| `docs/` | Архитектура, модель данных, схема интеграции с ФСП ID (Keycloak) |
| `docker-compose.yml` | db (PostgreSQL 16) + api + web; Keycloak — отдельный профиль, выключен по умолчанию |

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
make validate    # процедура валидации (пока заготовка, печатает план проверок)
```

Ключевые правила покрыты тестами `backend/tests/test_day2_rules.py` (видимость и обезличивание, лимит приглашений
30 дней, правило 90 дней и демо-режим жюри, обязательная вилка, вырезание ПДн, разбор без LLM) и
`backend/tests/test_ui_contract.py` (сквозной путь кандидат → работодатель → приглашение → контакты).

## Демо-данные

```bash
docker compose exec -T api python -m app.modules.demo.seed           # 150 кандидатов, 10 работодателей, 15 потребностей
docker compose exec -T api python -m app.modules.demo.seed --reset   # пересоздать
docker compose exec -T api python -m app.modules.demo.seed --delete  # удалить только демо-записи
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

Внешний nginx проксирует домен на `127.0.0.1:8140` (пример — раздел «Развёртывание» в docs/ARCHITECTURE.md),
сертификат — `certbot certonly --webroot`. Обновление: `git pull && docker compose up -d --build`
(миграции применяются при старте контейнера api).

## Лицензия

MIT — см. [LICENSE](LICENSE). Код открытый, без обфускации.
