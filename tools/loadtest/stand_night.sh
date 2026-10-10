#!/usr/bin/env bash
# Прогон нагрузки на стенде одной командой (docs/LOAD.md, раздел 4). На сервере стенда — только чтение.
#   preflight → prepare (своя песочница жюри) → 100 пользователей (11 мин, всплеск 5 холодных входов на 300-й с) →
#   пауза → 200 пользователей (12 мин) → по каждому прогону сверка с журналом nginx и сводка → cleanup.
# Песочницы прогона удаляются всегда, в том числе при ошибке или остановке (trap). Второй прогон не начинается,
# если /api/health не 200 или доля ошибок первого больше MAX_FAIL.
#
# Запуск отвязанно, лог — в /tmp:
#   export X=<файл с JURY_LINK_1=…> KPY=<SSH-обёртка сервера стенда> LOCUST=/tmp/lt/bin/locust
#   setsid nohup tools/loadtest/stand_night.sh > /tmp/stand_night.log 2>&1 < /dev/null &
# Переменные: H — адрес стенда; RUNS — «тег:пользователей:время …»; PAUSE — секунд между прогонами;
# BURST_AT — секунда всплеска (0 — без); MAX_FAIL — доля ошибок, после которой следующий прогон не идёт;
# WEB — адрес страниц, если не совпадает с H (локальный стенд); PY — python для run_load.py (для KPY нужен paramiko).
# Пароли и токены не печатаются.
set -uo pipefail
cd "$(dirname "$0")/../.."
H=${H:-https://fsp.neuropeople.pro}
X=${X-}
case "$H" in
  http://127.0.0.1*|http://localhost*) ;;  # локальный стенд: страницы без личной ссылки, WEB — адрес сборки
  *) [ -n "$X" ] || { echo "нужен X — файл с JURY_LINK_1=… (личная ссылка эксперта)"; exit 2; } ;;
esac
PY=${PY:-python3}
RUNS=${RUNS:-"stand_100:100:11m stand_200:200:12m"}
PAUSE=${PAUSE:-180}
BURST_AT=${BURST_AT:-300}
MAX_FAIL=${MAX_FAIL:-0.10}
OUT=${LT_OUT:-docs/loadtest}
R=("$PY" tools/loadtest/run_load.py)
ts() { date '+%F %T %Z'; }

echo "[$(ts)] старт: $H; прогоны: $RUNS; пауза $PAUSE с; всплеск на ${BURST_AT}-й с"
"${R[@]}" preflight --host "$H" --xlink-file "$X" || { echo "[$(ts)] preflight не пройден — прогон не начат"; exit 1; }
"${R[@]}" prepare --host "$H" || { echo "[$(ts)] песочница прогона не создана — прогон не начат"; exit 1; }
trap 'exit 130' INT TERM
trap '"${R[@]}" cleanup --host "$H"; echo "[$(ts)] cleanup выполнен"' EXIT

first=1
for spec in $RUNS; do
  IFS=: read -r tag users dur <<< "$spec"
  if [ "$first" -eq 0 ]; then
    echo "[$(ts)] пауза $PAUSE с"
    sleep "$PAUSE"
  fi
  first=0
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 20 "$H/api/health")
  if [ "$code" != 200 ]; then
    echo "[$(ts)] /api/health = $code — следующие прогоны не идут"
    break
  fi
  echo "[$(ts)] прогон $tag: $users пользователей, $dur"
  extra=(); [ "$BURST_AT" -gt 0 ] && extra+=(--burst-at "$BURST_AT" --burst-n 5)
  [ -n "${WEB:-}" ] && extra+=(--web "$WEB")
  "${R[@]}" run --host "$H" -u "$users" -r 2 -t "$dur" --tag "$tag" --xlink-file "$X" --server-stats "${extra[@]}"
  rc=$?
  "${R[@]}" nginx --tag "$tag" || echo "[$(ts)] сверка с nginx не выполнена"
  "${R[@]}" summary --tag "$tag" > "$OUT/${tag}_summary.md" 2>&1 || echo "[$(ts)] сводка не построена"
  echo "[$(ts)] $tag готов: $OUT/${tag}_summary.md"
  if [ "$rc" -ne 0 ]; then
    echo "[$(ts)] прогон $tag завершился с кодом $rc (3 — пользователей после разгона меньше 90 %) — следующие не идут"
    break
  fi
  fail=$("$PY" - "$OUT/${tag}_stats.csv" <<'PY'
import csv, sys
r = next((r for r in csv.DictReader(open(sys.argv[1], encoding="utf-8")) if r["Name"] == "Aggregated"), None)
print(f"{int(r['Failure Count']) / max(1, int(r['Request Count'])):.4f}" if r else "1")
PY
)
  if "$PY" -c "import sys; sys.exit(0 if float('$fail') > float('$MAX_FAIL') else 1)"; then
    echo "[$(ts)] доля ошибок $tag = $fail > $MAX_FAIL — следующие прогоны не идут (разбор по ${tag}_failures.csv и nginx)"
    break
  fi
done
echo "[$(ts)] DONE"
