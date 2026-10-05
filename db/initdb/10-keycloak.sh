#!/bin/sh
# Отдельная база для Keycloak (ФСП ID, демо) в нашем PostgreSQL. Выполняется только при создании тома db_data;
# на существующей установке: docker compose exec db createdb -U "$POSTGRES_USER" keycloak
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c "CREATE DATABASE keycloak"
