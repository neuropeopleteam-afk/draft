# Основные команды. Требуется Docker с плагином compose.
COMPOSE ?= docker compose
.DEFAULT_GOAL := help

help: ## Список команд
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

env: ## Создать .env из .env.example со случайными секретами (если .env ещё нет)
	@test -f .env || (cp .env.example .env && \
	  sed -i "s/^POSTGRES_PASSWORD=$$/POSTGRES_PASSWORD=$$(openssl rand -hex 24)/; s/^JWT_SECRET=$$/JWT_SECRET=$$(openssl rand -hex 32)/" .env && \
	  echo ".env создан")

up: env ## Собрать и запустить стек (db, api, web)
	$(COMPOSE) up -d --build
	@echo "Сайт: http://127.0.0.1:$${WEB_PORT:-8140}  API-документация: http://127.0.0.1:$${WEB_PORT:-8140}/api/docs"

down: ## Остановить стек (данные БД сохраняются)
	$(COMPOSE) down

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
	cd backend && python ../tools/calibrate_exposure.py && python -m app.modules.validation

validate-docker: ## То же в контейнере api (без пересчёта K Sympson — Hetter)
	$(COMPOSE) run --rm --no-deps api python -m app.modules.validation

bench: ## Бенчмарк подбора со скрытой истиной: 200 × 2000, абляции, веса на отложенных данных (≈ 1 мин CPU)
	cd backend && python -m app.modules.validation.matching_bench

intern-cut: ## Порог грейда «Стажёр»: симуляция теста при 4 порогах-кандидатах, с лёгкими семействами и без (≈ 2 мин CPU)
	cd backend && python -m app.modules.validation.intern_cut

bench-quick: ## Быстрая проверка бенчмарка 40 × 400 без записи результатов
	cd backend && python -m app.modules.validation.matching_bench --quick --no-write

stability: ## Стабильность статуса «Junior (предварительно)» на симуляции теста: до/после, дотестирование (≈ 2 мин)
	cd backend && python -m app.modules.validation.junior_stability

fsp-regression: ## Парное сравнение рейтинга ФСП v1/v2 на мире бенчмарка (tools/fsp_rating_regression.py, ≈ 1 мин)
	cd backend && python ../tools/fsp_rating_regression.py

dev-backend: ## Локальный backend с автоперезагрузкой (SQLite)
	cd backend && DATABASE_URL=sqlite:///./dev.db DEV_MODE=true alembic upgrade head && \
	  DATABASE_URL=sqlite:///./dev.db DEV_MODE=true uvicorn app.main:app --reload --port 8000

dev-frontend: ## Локальный frontend (Vite, прокси /api → :8000)
	cd frontend && npm install && npm run dev

.PHONY: help env up down ps logs migrate test test-pg test-local validate validate-docker dev-backend dev-frontend
.PHONY: bench bench-quick stability intern-cut fsp-regression

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

.PHONY: coverage test-bank stack-ci e2e e2e-stand
