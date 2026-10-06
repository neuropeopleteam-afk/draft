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

validate: ## Пересчёт метрик /validation: банк, симуляция теста, повтор, утечка, подбор (≈ 2 мин)
	cd backend && python ../tools/calibrate_exposure.py && python -m app.modules.validation

validate-docker: ## То же в контейнере api (без пересчёта K Sympson — Hetter)
	$(COMPOSE) run --rm --no-deps api python -m app.modules.validation

bench: ## Бенчмарк подбора со скрытой истиной: 200 × 2000, абляции, веса на отложенных данных (≈ 1 мин CPU)
	cd backend && python -m app.modules.validation.matching_bench

bench-quick: ## Быстрая проверка бенчмарка 40 × 400 без записи результатов
	cd backend && python -m app.modules.validation.matching_bench --quick --no-write

dev-backend: ## Локальный backend с автоперезагрузкой (SQLite)
	cd backend && DATABASE_URL=sqlite:///./dev.db DEV_MODE=true alembic upgrade head && \
	  DATABASE_URL=sqlite:///./dev.db DEV_MODE=true uvicorn app.main:app --reload --port 8000

dev-frontend: ## Локальный frontend (Vite, прокси /api → :8000)
	cd frontend && npm install && npm run dev

.PHONY: help env up down ps logs migrate test test-pg test-local validate validate-docker dev-backend dev-frontend
.PHONY: bench bench-quick
