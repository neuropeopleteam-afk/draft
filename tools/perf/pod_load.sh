#!/bin/bash
# А12: чистый нагрузочный замер на выделенной машине RunPod (без других стендов).
# Конфигурация как у боевого стенда: PostgreSQL + API uvicorn 2 воркера (Dockerfile, API_WORKERS=2) на 2 ядрах (1,2)
# (как --cpus 2), nginx с frontend/nginx.conf, сборка фронтенда vite. Генератор Locust — на отдельных ядрах.
set -u
D=${D:-/w/a12lt}; O=$D/out; mkdir -p $O; exec > >(tee -a $O/pod.log) 2>&1
echo "== $(date -Is) старт; ядер: $(nproc)"; grep -m1 "model name" /proc/cpuinfo
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null && apt-get install -y -qq postgresql nginx >/dev/null 2>&1; echo "apt: $?"
PGV=$(ls /usr/lib/postgresql | sort -n | tail -1); echo "PostgreSQL $PGV"
PGB=/usr/lib/postgresql/$PGV/bin; PGD=/tmp/pgdata; rm -rf $PGD; mkdir -p $PGD; chown postgres $PGD
su postgres -c "$PGB/initdb -D $PGD -A trust -U postgres" >/dev/null
su postgres -c "taskset -c 3,4 $PGB/pg_ctl -D $PGD -o '-p 5432 -c max_connections=100 -k /tmp' -l /tmp/pg.log start" ; sleep 3
psql -h /tmp -U postgres -c "create database spectrek" >/dev/null
export DATABASE_URL=postgresql+psycopg://postgres@/spectrek?host=/tmp
python3 -m venv /tmp/venv && /tmp/venv/bin/pip install -q -r $D/backend/requirements.txt locust==2.46.0 >$O/pip.log 2>&1; echo "pip: $?"
/tmp/venv/bin/python -c "import psycopg" 2>/dev/null || /tmp/venv/bin/pip install -q "psycopg[binary]"
cd $D/backend
export LLM_DISABLED=true DEV_MODE=true MAIL_BACKEND=dev API_WORKERS=2 TARIFFS_ENABLED=true JURY_SPARE_SANDBOXES=2 PYTHONPATH=$D/backend
export JWT_SECRET=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
/tmp/venv/bin/alembic upgrade head > $O/alembic.log 2>&1; echo "alembic: $?"
/tmp/venv/bin/python -m app.modules.demo.seed > $O/seed.log 2>&1; echo "seed: $?"
taskset -c 1,2 /tmp/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips='*' > $O/api.log 2>&1 &
cd $D/frontend && (npm ci --no-audit --no-fund >$O/npm.log 2>&1 && npm run build >>$O/npm.log 2>&1); echo "build: $? ($(ls dist | wc -l) файлов)"
sed -e 's#listen 80;#listen 18121;#' -e "s#root /usr/share/nginx/html;#root $D/frontend/dist;#" -e 's#http://api:8000#http://127.0.0.1:8000#g' \
    -e 's#resolver 127.0.0.11[^;]*;#resolver 127.0.0.53 valid=30s;#' $D/frontend/nginx.conf > /etc/nginx/conf.d/a12.conf
rm -f /etc/nginx/sites-enabled/default; nginx -t 2>&1 | tail -2
taskset -c 7 nginx || { nginx -s reload; }
for i in $(seq 1 60); do curl -fs -o /dev/null http://127.0.0.1:18121/api/health && break; sleep 2; done
echo "health: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18121/api/health) главная: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18121/)"
H=http://127.0.0.1:18121
for i in $(seq 1 30); do c=$(curl -s -o /dev/null -m 90 -w "%{http_code} %{time_total}" -X POST -H "content-type: application/json" -d '{"persona":"employer","scenario":"new"}' $H/api/jury/login); echo "warm $i $c"; case "$c" in 200*) t=${c#200 }; [ "${t%%.*}" -lt 5 ] && break;; esac; sleep 15; done
cd $D
export LT_OUT=$O LOCUST=/tmp/venv/bin/locust LT_STATE=$O/state.json
( while sleep 5; do echo "$(date +%T) load=$(cut -d' ' -f1-3 /proc/loadavg) api%=$(ps -C uvicorn -o %cpu= | awk '{s+=$1}END{print s}') pg%=$(ps -u postgres -o %cpu= | awk '{s+=$1}END{print s}') locust%=$(ps -C locust -o %cpu= | awk '{s+=$1}END{print s}')"; done ) > $O/cpu.txt &
MON=$!
PY=/tmp/venv/bin/python
for i in 1 2 3; do taskset -c 17-20,23,25,27,30 $PY tools/loadtest/run_load.py prepare --host $H && break; sleep 30; done
for spec in ${SPECS:-20:2:3m 50:3:3m 100:5:4m}; do IFS=: read U R T <<< "$spec"
  echo "== $(date +%T) прогон $U пользователей"
  taskset -c 17-20,23,25,27,30 $PY tools/loadtest/run_load.py run --host $H -u $U -r $R -t $T --tag pod_$U > $O/run_$U.log 2>&1; echo "rc=$?"
  $PY tools/loadtest/run_load.py summary --tag pod_$U > $O/pod_${U}_summary.md 2>&1; grep -E "Всего|доля ошибок" $O/pod_${U}_summary.md
  sleep 20
done
$PY tools/loadtest/run_load.py cleanup --host $H > $O/cleanup.log 2>&1
kill $MON; grep -c Traceback $O/api.log; grep -B2 -A12 Traceback $O/api.log | head -60 > $O/tracebacks.txt
echo "== $(date -Is) конец"
