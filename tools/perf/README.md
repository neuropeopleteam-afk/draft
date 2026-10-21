# tools/perf — пробные стенды и прогоны на сервере (не на боевом стенде)

- `run_pytest.sh <лог> <аргументы pytest>` — pytest в одноразовом контейнере образа `spectrek_fsp-api:integ` по рабочей копии
  `/opt/spectrek_fsp/work/ag_a12/w` (sqlite, LLM выкл., 1 CPU, 1,2 ГБ); лог — `/opt/spectrek_fsp/work/ag_a12/logs/<лог>.log`.
- `stage_sqlite.sh` — пробный стенд для e2e: образы `:integ` + backend рабочей копии, sqlite, сид демо-данных, 127.0.0.1:18120.
- `stage_pg.sh` — стенд для нагрузки, по составу как боевой: PostgreSQL 16 (320 МиБ, 50 соединений), api 2 воркера uvicorn
  (3072 МиБ, ограничение 2 CPU — боевой стенд работает на том же сервере), nginx-сборка фронтенда, 127.0.0.1:18121.
  Сценарии нагрузки — `tools/loadtest/` (Locust), методика и прежние замеры — `docs/LOAD.md`.
