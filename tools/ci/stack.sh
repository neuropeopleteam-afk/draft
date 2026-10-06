#!/usr/bin/env bash
# Локальный стек (db + api + web из docker-compose.yml) для проверки образов и сквозных тестов.
# Одни и те же команды в CI (.github/workflows/ci.yml, e2e.yml) и на машине разработчика:
#   tools/ci/stack.sh up      # .env со случайными секретами, сборка образов, запуск, ожидание healthcheck
#   tools/ci/stack.sh seed    # демо-данные: 150 кандидатов, 10 работодателей, демо-вакансии
#   tools/ci/stack.sh smoke   # проверка живого стека: сайт, API, миграции, режим жюри, отчёт валидации
#   tools/ci/stack.sh down    # остановить и удалить тома (данные стека не сохраняются)
# Переменные: WEB_PORT (8140), COMPOSE («docker compose»), COMPOSE_FILES (доп. -f, например для локальных
# особенностей сети). Внешние сервисы выключены: ЕГРЮЛ — EGRUL_DISABLED, LLM — нет ключа, почта — DEV_MODE.
set -euo pipefail
cd "$(dirname "$0")/../.."

COMPOSE=${COMPOSE:-docker compose}
# shellcheck disable=SC2206
FILES=(${COMPOSE_FILES:-})
WEB_PORT=${WEB_PORT:-8140}
BASE="http://127.0.0.1:${WEB_PORT}"
dc() { $COMPOSE "${FILES[@]}" "$@"; }

wait_http() {  # wait_http URL [секунд]
  local url=$1 t=${2:-120}
  for _ in $(seq "$t"); do
    if curl -fsS -o /dev/null "$url"; then return 0; fi
    sleep 1
  done
  echo "Нет ответа от $url за $t с" >&2
  return 1
}

case "${1:-}" in
  up)
    make env
    grep -q '^EGRUL_DISABLED=' .env || echo 'EGRUL_DISABLED=true' >> .env
    # демо-ATS (заглушки Talantix, «Поток», Хантфлоу, вебхук) api вызывает сам у себя: изнутри контейнера адрес
    # сайта localhost:8140 недоступен, поэтому — прямой адрес api в контейнере
    grep -q '^ATS_STUB_BASE_URL=' .env || echo 'ATS_STUB_BASE_URL=http://127.0.0.1:8000' >> .env
    t0=$(date +%s)
    dc build
    t1=$(date +%s)
    dc up -d --wait --wait-timeout 300
    wait_http "$BASE/api/health" 120
    echo "Сборка образов: $((t1 - t0)) с; запуск до healthcheck: $(($(date +%s) - t1)) с"
    dc ps
    docker image ls --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep '^spectrek_fsp' || true
    ;;
  seed)
    # --reset: при старте api сразу создаёт учётки жюри (общее демо и запасную песочницу), а они тоже демо —
    # без --reset сид решает, что демо-данные уже есть, и 150 кандидатов не создаёт. Песочницы жюри
    # пересоздадутся при первом входе — уже с подборками по полным демо-данным.
    dc exec -T api python -m app.modules.demo.seed --reset
    dc exec -T api python -m app.integrations.vacancies.demo
    ;;
  smoke)
    set -x
    curl -fsS "$BASE/api/health" | grep -q '"status":"ok"'
    curl -fsS "$BASE/" | grep -q '<div id="root">'
    curl -fsS "$BASE/validation" | grep -q '<div id="root">'          # SPA-маршрут отдаётся nginx
    curl -fsS "$BASE/api/openapi.json" | grep -q '"openapi"'
    curl -fsS "$BASE/api/catalog" | grep -q '"categories"'
    curl -fsS "$BASE/api/jury/status" | grep -q '"available":true'
    curl -fsS "$BASE/api/validation/report" | grep -q '"attacks"'
    dc exec -T api alembic current | grep -q '(head)'                   # миграции применены при старте
    curl -fsS -X POST -H 'content-type: application/json' -d '{"persona":"employer"}' \
      "$BASE/api/jury/login" | grep -q '"access_token"'
    set +x
    echo "Дымовая проверка стека: OK"
    ;;
  down)
    dc down -v --remove-orphans
    ;;
  *)
    echo "использование: $0 up|seed|smoke|down" >&2
    exit 2
    ;;
esac
