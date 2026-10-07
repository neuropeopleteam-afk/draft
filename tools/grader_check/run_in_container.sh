#!/usr/bin/env bash
# Прогон проверки оценщика открытых ответов (раздел /validation#grader) на YandexGPT внутри контейнера api
# сервера «Москва». Ключ уже в окружении контейнера (LLM_API_KEY, LLM_FOLDER_ID, LLM_BASE_URL) и не покидает его:
# в контейнер уходят файлы запросов (их строят те же функции, что в продукте — grader.build_messages), обратно —
# ответы модели. Раннер — только стандартная библиотека Python, возобновляет прерванный прогон.
#
# Запуск — штаб, из рабочего дерева с этой веткой (на машине разработки, не на сервере):
#   bash tools/grader_check/run_in_container.sh                       # полный набор: 232 + 406 + второй вызов
#   bash tools/grader_check/run_in_container.sh --limit-per-group 10  # дешёвый вариант (≈ 60 + 100 запросов)
#   DRY=1 bash tools/grader_check/run_in_container.sh                 # только показать команды к серверу
# Итог: backend/app/modules/validation/data/grader_check.json (закоммитить), временные файлы удаляются.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PY=${PY:-/srv/work/srv/work/spectrek/.venv/bin/python}
C=${C:-spectrek_fsp-api-1}       # контейнер api
D=${D:-/tmp/ig09/run}            # локальная папка прогона
R=/tmp/ig09                      # папка на сервере и в контейнере
MODEL=${MODEL:-yandexgpt/latest} # та же модель, что в продукте (LLM_MODEL контейнера)
POLL=${POLL:-60}

K() { if [ -n "${DRY:-}" ]; then printf 'k.py %s\n' "$*" >&2; echo ready; else python3 /srv/work/srv/work/tools/k.py "$@"; fi; }
L() { if [ -n "${DRY:-}" ]; then printf 'локально: %s\n' "$*" >&2; else "$@"; fi; }  # шаги по ответам модели
to_c() { for f in "$@"; do K put "$D/$f" "$R/$f" >/dev/null; K cmd "docker exec -i $C sh -c 'cat > $R/$f' < $R/$f"; done; }
from_c() { for f in "$@"; do K cmd "docker exec $C cat $R/$f > $R/$f"; K get "$R/$f" "$D/$f" >/dev/null; done; }
run_c() {  # $1 — флаг готовности, дальше пары «запросы:ответы»; прогон в фоне внутри контейнера
  local flag=$1 cmds=""; shift
  for p in "$@"; do
    cmds+="python llm_runner.py --requests ${p%%:*} --out ${p##*:} --model $MODEL --conc 3 >> runner.log 2>&1 && "
  done
  K cmd "docker exec -d $C sh -c 'cd $R && rm -f $flag && ${cmds}echo ok > $flag || echo fail > $flag'"
  until K cmd "docker exec $C cat $R/$flag 2>/dev/null" | grep -Eq 'ok|fail|ready'; do
    K cmd "docker exec $C sh -c 'cd $R && wc -l *_out.jsonl 2>/dev/null | tail -1 && tail -1 runner.log'" || true
    sleep "$POLL"
  done
  if K cmd "docker exec $C cat $R/$flag" | grep -q fail; then
    K cmd "docker exec $C tail -5 $R/runner.log"
    echo "Прогон прервался; повторный запуск скрипта продолжит с места остановки" >&2; exit 1
  fi
}

mkdir -p "$D"; cd "$ROOT/backend"
echo "== запросы (локально, без ключа)"
"$PY" -m app.modules.validation.grader_check build --cond v1 --out "$D/v1.jsonl" "$@"
"$PY" -m app.modules.validation.grader_check build --cond v2 --out "$D/v2_1.jsonl" "$@"
cp "$ROOT/tools/grader_check/llm_runner.py" "$D/llm_runner.py"
echo "== в контейнер $C"
K cmd "mkdir -p $R && docker exec $C mkdir -p $R"
to_c v1.jsonl v2_1.jsonl llm_runner.py
echo "== первый вызов модели (v1, v2)"
run_c step1.flag v1.jsonl:v1_out.jsonl v2_1.jsonl:v2_1_out.jsonl
from_c v1_out.jsonl v2_1_out.jsonl
echo "== второй вызов для сомнительных (v2)"
L "$PY" -m app.modules.validation.grader_check second --req "$D/v2_1.jsonl" --res "$D/v2_1_out.jsonl" --out "$D/v2_2.jsonl"
[ -n "${DRY:-}" ] && touch "$D/v2_2.jsonl"
to_c v2_2.jsonl
run_c step2.flag v2_2.jsonl:v2_2_out.jsonl
from_c v2_2_out.jsonl
echo "== отчёт → app/modules/validation/data/grader_check.json"
L "$PY" -m app.modules.validation.grader_check report --dir "$D"
K cmd "docker exec $C rm -rf $R; rm -rf $R"
echo "Готово: проверьте git diff backend/app/modules/validation/data/grader_check.json и /validation#grader"
