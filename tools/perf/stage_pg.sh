#!/bin/bash
# стенд А12 для нагрузки: как боевой по составу (PostgreSQL 16, api 2 воркера, лимит 3072 МиБ), но копия:
# образы :integ + backend ветки А12, своя БД, 127.0.0.1:18121; CPU api ограничен 2 ядрами (боевой стенд на том же сервере)
set -u
W=/opt/spectrek_fsp/work/ag_a12
docker rm -f a12lt-api a12lt-web a12lt-db >/dev/null 2>&1; docker network create a12lt >/dev/null 2>&1
PW=$(head -c 18 /dev/urandom | base64 | tr -dc A-Za-z0-9 | head -c 20)
docker run -d --name a12lt-db --network a12lt --network-alias db --memory 320m \
  -e POSTGRES_DB=fsp -e POSTGRES_USER=fsp -e POSTGRES_PASSWORD=$PW \
  postgres:16-alpine postgres -c shared_buffers=128MB -c max_connections=50 -c work_mem=8MB >/dev/null
for i in $(seq 1 30); do sleep 2; docker exec a12lt-db pg_isready -U fsp -d fsp >/dev/null 2>&1 && break; done
docker run -d --name a12lt-api --network a12lt --network-alias api --memory 3072m --cpus 2 \
  -v /opt/spectrek_fsp/data_local:/data_local:ro -v $W/w/backend:/srv/backend \
  -e DATABASE_URL=postgresql+psycopg://fsp:$PW@db:5432/fsp -e LLM_DISABLED=true -e DEV_MODE=true -e MAIL_BACKEND=dev \
  -e API_WORKERS=2 -e FSP_PROTOCOLS_INDEX=/data_local/fsp_protocols/index.json -e TARIFFS_ENABLED=true \
  -e JURY_SPARE_SANDBOXES=2 -e JWT_SECRET=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n') \
  spectrek_fsp-api:integ sh -c "alembic upgrade head && python -m app.modules.demo.seed >/tmp/seed.log 2>&1; uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips=*" >/dev/null
docker run -d --name a12lt-web --network a12lt -p 127.0.0.1:18121:80 --memory 32m spectrek_fsp-web:integ >/dev/null
for i in $(seq 1 120); do sleep 5; c=$(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:18121/api/meta); [ "$c" = 200 ] && break; done
echo "a12lt meta: $c after $((i*5))s"; docker logs a12lt-api 2>&1 | grep -iE "Traceback" | tail -3; docker exec a12lt-api tail -2 /tmp/seed.log
