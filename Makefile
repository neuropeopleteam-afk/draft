# Основные команды. Требуется Docker с плагином compose.
COMPOSE ?= docker compose
.DEFAULT_GOAL := help

help: ## Список команд
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

env: ## Создать .env из .env.example со случайными секретами (если .env ещё нет)
	@test -f .env || (cp .env.example .env && \
	  sed -i "s/^POSTGRES_PASSWORD=$$/POSTGRES_PASSWORD=$$(openssl rand -hex 24)/; s/^JWT_SECRET=$$/JWT_SECRET=$$(openssl rand -hex 32)/" .env && \
	  echo ".env создан")

up: env ## Собрать и запустить стек (db, api, web), дождаться готовности, создать демо-данные (NO_SEED=1 — без них)
	$(COMPOSE) up -d --build --wait --wait-timeout 300
	@if [ -z "$$NO_SEED" ]; then $(COMPOSE) exec -T api python -m app.modules.demo.seed; fi
	@echo "Сайт: http://127.0.0.1:$${WEB_PORT:-8140}  API-документация: http://127.0.0.1:$${WEB_PORT:-8140}/api/docs"

llm-local: env ## Стек + открытая модель Qwen на CPU без ключей (профиль llm-local; первый старт скачивает модель 5,7 ГБ)
	LLM_LOCAL_ENV_FILE=./infra/llm-local/llm-local.env $(COMPOSE) --profile llm-local up -d --build
	@echo "Сайт: http://127.0.0.1:$${WEB_PORT:-8140}  Модель: make llm-local-logs (готова, когда /health отвечает ok)"

llm-local-logs: ## Ход загрузки и ответы открытой модели (сервис llm-local)
	$(COMPOSE) --profile llm-local logs -f --tail=50 llm-local

down: ## Остановить стек (данные БД сохраняются)
	$(COMPOSE) --profile llm-local down

ps: ## Состояние контейнеров
	$(COMPOSE) ps

logs: ## Логи API (в DEV_MODE здесь видны коды подтверждения)
	$(COMPOSE) logs -f --tail=100 api

migrate: ## Применить миграции Alembic
	$(COMPOSE) run --rm api alembic upgrade head

test: ## Тесты backend в контейнере (SQLite, миграции Alembic)
	$(COMPOSE) build api
	$(COMPOSE) run --rm --no-deps -e DATABASE_URL=sqlite:////tmp/t.db api python -m pytest

test-pg: ## Те же тесты на PostgreSQL (отдельная база fsp_test)
	$(COMPOSE) up -d db
	@$(COMPOSE) exec -T db sh -c 'psql -U $$POSTGRES_USER -d $$POSTGRES_DB -tc "SELECT 1 FROM pg_database WHERE datname=$$$$fsp_test$$$$" | grep -q 1 || createdb -U $$POSTGRES_USER fsp_test'
	$(COMPOSE) run --rm -e TEST_DATABASE_URL=postgresql+psycopg://$${POSTGRES_USER:-fsp}:$$(grep ^POSTGRES_PASSWORD= .env | cut -d= -f2)@db:5432/fsp_test api python -m pytest

test-local: ## Тесты backend без Docker (нужен Python 3.12+ и зависимости из requirements*.txt)
	cd backend && python -m pytest

validate: ## Пересчёт метрик /validation: K Sympson — Hetter, банк, симуляция теста (до/после), повтор, утечка, подбор (≈ 15–20 мин)
	cd backend && python ../tools/calibrate_exposure.py && python -m app.modules.validation && python -m app.modules.validation.criteria --md ../docs/CRITERIA.md

validate-docker: ## То же в контейнере api (без пересчёта K Sympson — Hetter)
	$(COMPOSE) run --rm --no-deps api python -m app.modules.validation

bench: ## Бенчмарк подбора со скрытой истиной: 200 × 2000, абляции, веса на отложенных данных (≈ 1 мин CPU)
	cd backend && python -m app.modules.validation.matching_bench && python -m app.modules.validation.criteria --md ../docs/CRITERIA.md

grade-above: ## Добор ступенью выше (match-v1.3): бенчмарк со скрытой истиной до/после в малом и большом пуле → docs/validation/grade_above.json (≈ 5 мин CPU)
	cd backend && python ../tools/realdata/grade_above_bench.py

intern-cut: ## Порог грейда «Стажёр»: симуляция теста при 4 порогах-кандидатах, с лёгкими семействами и без (≈ 2 мин CPU)
	cd backend && python -m app.modules.validation.intern_cut

bench-quick: ## Быстрая проверка бенчмарка 40 × 400 без записи результатов
	cd backend && python -m app.modules.validation.matching_bench --quick --no-write

stability: ## Стабильность статуса «Junior (предварительно)» на симуляции теста: до/после, дотестирование (≈ 2 мин)
	cd backend && python -m app.modules.validation.junior_stability

path-retest: ## Test–retest всего пути кандидата (5 × 500, дважды) и D / r_pb семейств → data/path_retest.json (≈ 3 мин CPU)
	cd backend && python -m app.modules.validation.path_retest && python -m app.modules.validation.criteria --md ../docs/CRITERIA.md

partial-credit-sim: ## Частичный балл 0–4 у развёрнутых: «0/1» против «0–4» (5 × 500, 14 вариантов) → data/partial_credit_sim.json, docs/validation/PARTIAL_CREDIT.md
	cd backend && python -m app.modules.validation.partial_credit_sim $(SIM_ARGS)

criteria-doc: ## docs/CRITERIA.md «Критерий ТЗ → что показываем → чем доказано» из того же источника, что /criteria
	cd backend && python -m app.modules.validation.criteria --md ../docs/CRITERIA.md

fsp-regression: ## Парное сравнение рейтинга ФСП v1/v2 на мире бенчмарка (tools/fsp_rating_regression.py, ≈ 1 мин)
	cd backend && python ../tools/fsp_rating_regression.py

dev-backend: ## Локальный backend с автоперезагрузкой (SQLite)
	cd backend && DATABASE_URL=sqlite:///./dev.db DEV_MODE=true alembic upgrade head && \
	  DATABASE_URL=sqlite:///./dev.db DEV_MODE=true uvicorn app.main:app --reload --port 8000

dev-frontend: ## Локальный frontend (Vite, прокси /api → :8000)
	cd frontend && npm install && npm run dev

.PHONY: help env up llm-local llm-local-logs down ps logs migrate test test-pg test-local validate validate-docker dev-backend dev-frontend
grade-sweep: ## Перебор параметров теста ради точности уровня (Парето, два мира σ 0,5 / 0,35) → data/grade_sweep.json, docs/validation/GRADE_ACCURACY.md (≈ 20 мин на 8 ядрах)
	cd backend && python -m app.modules.validation.grade_sweep $(SWEEP_ARGS)

two-stage: ## Двухэтапное подтверждение у границы: «одна сессия / две сессии», Парето по L и длине второго этапа → data/two_stage.json, docs/validation/TWO_STAGE.md (≈ 4 мин на 8 ядрах)
	cd backend && python -m app.modules.validation.two_stage $(TWO_STAGE_ARGS)

grade-compare: ## Точность уровня в сопоставимых условиях (точные параметры, заявили не ниже, короткий тест на уровень выше) → data/grade_compare.json, docs/validation/GRADE_COMPARE.md
	cd backend && python -m app.modules.validation.grade_compare $(COMPARE_ARGS)

grades-ext-sim: ## Путь-повтор с 6 уровнями (Lead, Principal; модельные семейства) → data/grades_ext_sim.json, docs/validation/GRADES_EXT.md (≈ 15 мин на 8 ядрах)
	cd backend && GRADES_EXT_ENABLED=1 python -m app.modules.validation.grades_ext_sim $(SIM_ARGS)

grades-ext-need: ## Что нужно для точности Lead/Principal ≥ 64 %: банк, блок Lead/Principal, частичный балл → data/grades_ext_need.json, docs/validation/GRADES_EXT_NEED.md
	cd backend && GRADES_EXT_ENABLED=1 python -m app.modules.validation.grades_ext_need $(SIM_ARGS)

.PHONY: bench bench-quick stability intern-cut grade-above fsp-regression path-retest grade-sweep two-stage grade-compare grades-ext-sim grades-ext-need partial-credit-sim

# подпись мира у чисел /validation: коммит кода (на сервере проверок .git нет — передавайте GIT_COMMIT=…)
GIT_COMMIT ?= $(shell git rev-parse --short=7 HEAD 2>/dev/null)
export GIT_COMMIT

# --- Проверки CI на своей машине: те же команды, что в .github/workflows (docs/testing.md) ---
PY ?= python

coverage: ## Тесты backend с покрытием и порогом (как в CI) + значки docs/badges
	cd backend && $(PY) -m pytest -p no:cacheprovider --cov=app --cov-report=term:skip-covered \
	  --cov-report=xml:coverage.xml --cov-report=html:htmlcov --junitxml=junit.xml
	$(PY) tools/ci/coverage_report.py --coverage backend/coverage.xml --junit backend/junit.xml \
	  --badge docs/badges/coverage.svg --tests-badge docs/badges/tests.svg

test-bank: ## Валидатор банка заданий, как в CI (≈ 2 мин; нужны node, bash, git)
	cd backend && $(PY) ../tools/ci/check_bank.py --seeds 20 --verify-seeds 3 --out /tmp/bank_report

stack-ci: ## Стек для e2e: сборка образов, запуск, демо-данные, дымовая проверка
	tools/ci/stack.sh up && tools/ci/stack.sh seed && tools/ci/stack.sh smoke

e2e: ## Сквозные сценарии жюри против локального стека (сначала make stack-ci)
	cd e2e && npm ci --no-audit --no-fund && npx playwright install chromium && \
	  E2E_BASE_URL=http://127.0.0.1:$${WEB_PORT:-8140} npx playwright test

e2e-stand: ## Те же сценарии против стенда (E2E_BASIC_PASSWORD — пароль из материалов сдачи)
	cd e2e && E2E_BASE_URL=$${E2E_BASE_URL:-https://fsp.neuropeople.pro} E2E_BASIC_USER=$${E2E_BASIC_USER:-demo} \
	  npx playwright test

openapi: ## Пересобрать docs/api/openapi.json из кода (после любой правки API; тест tests/test_openapi_file.py проверяет актуальность)
	cd backend && $(PY) ../tools/export_openapi.py

openapi-examples: ## Пересъёмка примеров ответов для OpenAPI с демо-мира матрицы прав (≈ 2 мин) → backend/app/core/api_examples.json; затем make openapi
	cd backend && OPENAPI_CAPTURE=1 $(PY) -m pytest -p no:cacheprovider tests/test_openapi_capture.py -k capture -s

openapi-audit: ## Аудит полноты OpenAPI: описания, ошибки по коду, ответы (tools/openapi_audit.py; --raw — без общего обогащения)
	cd backend && $(PY) ../tools/openapi_audit.py

.PHONY: coverage test-bank stack-ci e2e e2e-stand openapi openapi-audit openapi-examples
