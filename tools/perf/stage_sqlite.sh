#!/bin/bash
# пробный стенд А12 для e2e: образы :integ + код backend из ветки А12 (монтируется поверх), sqlite, 127.0.0.1:18120
set -u
W=/opt/spectrek_fsp/work/ag_a12
docker rm -f a12-api a12-web >/dev/null 2>&1; docker network create a12stage >/dev/null 2>&1
mkdir -p $W/stage && rm -f $W/stage/s.db; chmod 777 $W/stage
docker run -d --name a12-api --network a12stage --network-alias api --memory 1200m --cpus 1 \
  -v $W/stage:/st -v /opt/spectrek_fsp/data_local:/data_local:ro -v $W/w/backend:/srv/backend \
  -e DATABASE_URL=sqlite:////st/s.db -e LLM_DISABLED=true -e DEV_MODE=true -e MAIL_BACKEND=dev -e API_WORKERS=1 \
  -e FSP_PROTOCOLS_INDEX=/data_local/fsp_protocols/index.json -e TARIFFS_ENABLED=true -e JURY_SPARE_SANDBOXES=2 \
  \
  spectrek_fsp-api:integ sh -c "alembic upgrade head && python -m app.modules.demo.seed >/st/seed.log 2>&1; uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1" >/dev/null
docker run -d --name a12-web --network a12stage -p 127.0.0.1:18120:80 --memory 64m spectrek_fsp-web:integ >/dev/null
for i in $(seq 1 90); do sleep 5; c=$(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:18120/api/meta); [ "$c" = 200 ] && break; done
echo "a12 stage meta: $c after $((i*5))s"; docker logs a12-api 2>&1 | grep -iE "error|Traceback" | tail -5; tail -3 $W/stage/seed.log
