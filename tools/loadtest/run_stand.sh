#!/usr/bin/env bash
# Нагрузочный тест против стенда (запускает координатор; docs/LOAD_TEST.md). Шаги:
#   1) на сервере: временные учётки loadtest-*@demo.invalid внутри контейнера api → токены в файл (без паролей);
#   2) с машины теста (не с сервера — иначе сеть и CPU теста смешаются с сервером): Locust, N пользователей;
#   3) во время теста — замер docker stats на сервере; 4) на сервере: удалить временные учётки.
#
#   tools/loadtest/run_stand.sh setup   [N=40]     # на сервере, из /opt/spectrek_fsp/app → /tmp/lt_tokens.json
#   tools/loadtest/run_stand.sh run     [U=50] [T=4m] [HOST=https://fsp.neuropeople.pro]   # на машине теста
#   tools/loadtest/run_stand.sh stats   [SEC=300]  # на сервере, параллельно с run → /tmp/lt_docker_stats.txt
#   tools/loadtest/run_stand.sh cleanup            # на сервере
#
# Locust — в отдельном виртуальном окружении (не в окружении приложения): python3.12 -m venv /tmp/lt &&
# /tmp/lt/bin/pip install locust==2.46.0. Сайт стенда закрыт basic auth, но API (/api/…) открыт — Locust ходит только в API.
set -euo pipefail
cd "$(dirname "$0")/../.."
cmd=${1:-}; shift || true
case "$cmd" in
  setup)
    n=${1:-40}
    docker compose exec -T api python - setup "$n" < tools/loadtest/lt_accounts.py > /tmp/lt_tokens.json
    python3 -c "import json; d=json.load(open('/tmp/lt_tokens.json')); print('кандидатов', len(d['candidates']), \
'работодателей', len(d['employers']), 'аналитиков', len(d.get('analysts', [])), 'карточек', len(d['refs']))"
    echo "Токены: /tmp/lt_tokens.json (живут JWT_TTL_MINUTES; скопировать на машину теста, после теста удалить)";;
  run)
    u=${1:-50}; t=${2:-4m}; host=${3:-https://fsp.neuropeople.pro}
    LOCUST=${LOCUST:-/tmp/lt/bin/locust}
    mkdir -p docs/loadtest
    LT_TOKENS=${LT_TOKENS:-/tmp/lt_tokens.json} "$LOCUST" -f tools/loadtest/locustfile.py --host "$host" \
      --headless -u "$u" -r 5 -t "$t" --csv docs/loadtest/run --only-summary;;
  stats)
    sec=${1:-300}; out=/tmp/lt_docker_stats.txt; : > "$out"
    end=$((SECONDS + sec))
    while [ $SECONDS -lt $end ]; do
      { date +%T; docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' | grep spectrek_fsp; uptime; } >> "$out"
      sleep 8
    done
    echo "Замеры: $out";;
  cleanup)
    docker compose exec -T api python - cleanup < tools/loadtest/lt_accounts.py
    rm -f /tmp/lt_tokens.json;;
  *) sed -n '2,13p' "$0"; exit 1;;
esac
