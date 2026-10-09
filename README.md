# Встречный — платформа подбора ИТ-специалистов «наоборот»

[![Покрытие тестами бэкенда](docs/badges/coverage.svg)](docs/testing.md) [![Тесты бэкенда](docs/badges/tests.svg)](docs/testing.md)

Прототип для спецтрека ФСП (ЛЦТ 2026). Работодатель сам находит проверенного кандидата по категории
«направление · грейд» и приглашает его с зарплатой. Категория присваивается не по резюме, а по обязательному
пути: опрос → выбор предполагаемого грейда → тест. Факты о кандидате помечены уровнем доказанности
(T0 — самоописание, T1 — подтверждено тестом/зондом, T2 — подтверждено реестром ФСП).

«Встречный» — рабочее название, меняется в `frontend/src/components/Logo.tsx`.

- Развёрнутый прототип: https://fsp.neuropeople.pro
- Доступ к стенду: логин и пароль — в материалах сдачи (базовая авторизация nginx; без неё открыты только `/api/*`, `/robots.txt`, манифест PWA, `sw.js`, иконки и страница гостя живой демонстрации `/j/<код>` со статикой `/assets/`, `/recover.js` — QR с телефона эксперта)
- Для жюри: блок «Для экспертов жюри» на главной — вход в один клик за кандидата (с паспортом ФСП и без), работодателя и эксперта, проводник по сценарию, сброс демо; метрики — страница `/validation`
- Документация API (OpenAPI/Swagger): https://fsp.neuropeople.pro/api/docs
- Проверка по критериям ТЗ: страница `/criteria` и [docs/CRITERIA.md](docs/CRITERIA.md) — подпункт ТЗ → что сделать → что увидите → чем доказано
- Архитектура и модель данных: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Интеграции: [антифрод и индекс доверия](docs/ANTIFRAUD.md), [ФСП ID](docs/FSP_INTEGRATION.md), [ATS](docs/ATS.md), [подписка на потребность и напоминания](docs/SUBSCRIPTIONS.md), [нагрузочный тест](docs/LOAD_TEST.md), [задания работодателя: причина, рубрика, свежесть](docs/ASSIGNMENTS.md), [доступность: axe и клавиатура](docs/ACCESSIBILITY.md)

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
make criteria-doc # docs/CRITERIA.md из того же источника, что /criteria (пересобирается и после bench/path-retest/validate)
```

CI (GitHub Actions, `.github/workflows`): `ci.yml` — бэкенд на SQLite с покрытием и на PostgreSQL 16, банк заданий,
фронтенд (типы и сборка), Docker-образы, стек и сквозные сценарии; `e2e.yml` — сценарии против стенда вручную и
по расписанию. Состав тестов, связь с критериями ТЗ, текущие цифры — [docs/testing.md](docs/testing.md).

## Демо-данные

```bash
docker compose exec -T api python -m app.modules.demo.seed           # 500 кандидатов, 10 работодателей, 15 потребностей, 11 демо-вакансий
docker compose exec -T api python -m app.modules.demo.seed --reset   # пересоздать
docker compose exec -T api python -m app.modules.demo.seed --delete  # удалить только демо-записи
docker compose exec -T api python -m app.integrations.vacancies.demo  # 11 демо-вакансий (одна — «приманка»); seed создаёт их сам
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

### Чистая машина: без Docker, без ключей LLM

Свежий клон, Python 3.12 и Node 20+; ключей языковой модели и почты не нужно. Проверено на чистом клоне (проход ниже,
подписи в интерфейсе — в разделе «Что работает без LLM»).

```bash
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
export DATABASE_URL=sqlite:///./dev.db DEV_MODE=true      # SQLite в каталоге backend; ключей LLM и почты нет
export ATS_STUB_BASE_URL=http://127.0.0.1:8000            # тестовая ATS — часть самого API: адрес, по которому он достучится сам до себя
python -m alembic upgrade head                            # схема (до 30 с на первом запуске)
python -m app.modules.demo.seed                           # 500 кандидатов, 10 работодателей, 15 потребностей, 11 демо-вакансий
python -m app.cup.demo                                    # 6 демо-кубков
uvicorn app.main:app --port 8000                          # API, http://localhost:8000/api/docs
# второй терминал
cd frontend && npm install && npm run dev                 # интерфейс, http://localhost:5173 (/api → :8000)
```

Без `ATS_STUB_BASE_URL` передача кандидата в демо-ATS идёт на `http://localhost:8080` и в журнале передач получается ошибка 502;
задавайте переменную до демо-данных — адрес заглушки сохраняется в БД при их создании.
Проверка: `curl -s localhost:8000/api/meta` — в ответе `"llm": {"configured": false, ...}`. На главной блок «Для экспертов
жюри» входит в один клик за любую роль. Демо-данные нужны для подбора (кандидаты) и для кубков/вакансий.

#### Что работает без LLM

Без ключей модели (`/api/meta` → `llm.configured = false`) продукт не ломается: у каждой функции с моделью есть
запасной путь, а интерфейс честно подписывает его.

| Функция | Без LLM | Что видно в интерфейсе |
|---|---|---|
| Разбор потребности работодателя | словарь технологий и правила (`method = rules`), цитаты из текста — те же | чип «разбор по словарю» и подпись, что формулировки вне словаря не распознаются |
| Разбор резюме PDF или DOCX | словари и правила (`method = rules`), ПДн вырезаются локально | «разбор по словарям» и подпись под заголовком «Резюме PDF или DOCX» |
| Потребность из файла вакансии (PDF, DOCX, TXT) | извлечение текста без модели; разбор — как у набранного текста | подпись «Текст из файла …» под полем, docs/FILE_PARSE.md |
| Открытые ответы теста | статус «на проверке», очередь эксперта (`/expert`) | подсказка под полем ответа и в итоге теста: «LLM-оценщик не подключён — ответы проверяет эксперт» |
| Кубок по рубрике | решение остаётся «на оценке», баллы по рубрике ставит работодатель | у работодателя: «LLM-оценщик не подключён: оцените решение по рубрике сами» |
| Оценка ответов пакета разметки | нет оценок модели, ответы оценивает эксперт | сообщение на странице `/validation`: нужен LLM, запасной путь — эксперт |
| Подбор, ранжирование, объяснения, тест на банке заданий, приглашения, ATS, переписка | LLM не используют — работают как обычно | без подписей |

Чтобы включить модель, задайте `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (и `LLM_FOLDER_ID` для Yandex) переменными
окружения или в `backend/.env` (в Docker — файл `LLM_ENV_FILE`, см. ниже); после перезапуска API `llm.configured`
станет `true`, а подписи исчезнут.

## Переменные окружения

Полный список с пояснениями — в [.env.example](.env.example). Секреты (`POSTGRES_PASSWORD`, `JWT_SECRET`,
ключи Postbox, ключ LLM) в репозиторий не попадают.

LLM: цепочка провайдеров `LLM_CHAIN=openrouter,yandex` — Claude Sonnet 5.5 через OpenRouter (зарубежные облачные
модели разрешены организаторами), запасная — YandexGPT (Yandex AI Studio, OpenAI-совместимый API), без ответа
обеих — словари и правила. Данные хранятся на сервере в Москве; в модель уходит только текст для разбора с вырезанными
контактами (то же — в `/api/meta` → `operator.storage`). Ключ OpenRouter и ретранслятор — в `OPENROUTER_ENV_FILE` и `LLM_RELAY_ENV_FILE`;
переменные Yandex (`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_FOLDER_ID`, `LLM_MODEL`) — в `LLM_ENV_FILE`
(на сервере `/opt/spectrek_fsp/secrets/llm.env`). Модели по функциям и настройка — [docs/LLM.md](docs/LLM.md).
Персональные данные вырезаются из текста до обращения к любой модели.
Без ключей и без зарубежных API — своя открытая модель на CPU одной командой `make llm-local`: сервис `llm-local`
(llama.cpp server, Qwen3.5-9B Q4_K_M скачивается при первом старте, около 6,6 ГиБ памяти) и `LLM_CHAIN=local`;
открытые ответы теста оценивает Qwen, разбор вакансий и резюме остаётся за правилами (замер и выбор —
[docs/LLM.md, раздел 9](docs/LLM.md)). Без профиля ничего не меняется.
Движок теста — `ASSESSMENT_ENGINE` (`bank` — адаптивный тест на банке заданий; `stub` — запасная заглушка).
Банк обновляется командой `python tools/sync_bank.py --commit` (из окружения банка: numpy, scipy, pydantic,
PyYAML); скрипт выкладки вызывает её сам, так что новые семейства из `../bank` попадают на сервер автоматически.
Открытые ответы теста оценивает LLM по рубрике (`LLM_GRADING_MODEL`), без LLM — статус «на проверке».
Название продукта — одна настройка `PRODUCT_NAME` (по умолчанию «Встречный»).

Служебные учётки (администратор, аналитик ФСП) через форму регистрации не создаются — только командой
`python -m app.modules.auth add-staff --email admin@company.ru --role admin` (пароль — `STAFF_PASSWORD` или запрос
в терминале). Для них обязателен второй фактор: при первом входе после пароля открывается подключение
приложения-аутентификатора (TOTP, RFC 6238, QR и резервные коды), дальше вход — пароль плюс код. Эксперт панели
подключает код по желанию в разделе «Безопасность входа»; демо-учётки жюри входят в один клик без второго фактора
(в разделе есть пометка, подключить можно для проверки). Потерян телефон — `reset-2fa --email …` или сброс
администратором в том же разделе. Настройки — `TWOFA_*` в [.env.example](.env.example).

## Развёртывание на сервере

```bash
git clone <репозиторий> /opt/spectrek_fsp/app && cd /opt/spectrek_fsp/app
make env && make up          # порты публикуются только на 127.0.0.1 (WEB_PORT=8140, API_PORT=8141)
```

Внешний nginx проксирует домен на `127.0.0.1:8140` (рабочий пример без секретов —
[infra/nginx/fsp.neuropeople.pro.conf.example](infra/nginx/fsp.neuropeople.pro.conf.example), описание — раздел «Развёртывание» в docs/ARCHITECTURE.md),
сертификат — `certbot certonly --webroot`. Обновление: `git pull && docker compose up -d --build`
(миграции применяются при старте контейнера api).
Страница QR без пароля — `sudo bash infra/nginx/apply-public-snippets.sh` (копия файла сайта, `nginx -t`, откат при
ошибке, проверка адресов). Мониторинг с письмом владельцу — раздел 11.1 в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Лицензия

MIT — см. [LICENSE](LICENSE). Код открытый, без обфускации.
