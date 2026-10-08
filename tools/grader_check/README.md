# Проверка оценщика открытых ответов на наборе панели 06.10

Набор: `docs/validation/grader_set_panel_20261006.json.gz` (29 развёрнутых заданий, 319 ответов панели + 87 перефразированных атак,
которые строит `backend/app/modules/validation/grader_check.py`). Пересборка набора из сырых данных панели:

```
/home/user/workspace/spectrek/.venv_bank/bin/python tools/grader_check/build_dataset.py \
  --oldbank /tmp/ig09/oldbank --grading /home/user/workspace/spectrek/panel2_raw/grading \
  --out docs/validation/grader_set_panel_20261006.json.gz
# /tmp/ig09/oldbank — банк на коммите панели: git -C bank archive 1631167 | tar -x -C /tmp/ig09/oldbank
```

## Офлайн-часть (без модели) — уже в `backend/app/modules/validation/data/grader_check.json`

```
cd backend && ../../../.venv/bin/python -m app.modules.validation.grader_check report --dir /tmp/ig09/empty
```

## Прогон на YandexGPT внутри контейнера api (ключ уже там; запускает штаб)

```
bash tools/grader_check/run_in_container.sh                       # полный набор: 232 + 406 запросов + второй вызов
bash tools/grader_check/run_in_container.sh --limit-per-group 10  # дешёвый вариант (≈ 60 + 100 запросов)
DRY=1 bash tools/grader_check/run_in_container.sh                 # только показать команды к серверу
```

Скрипт строит запросы локально, передаёт их в контейнер `spectrek_fsp-api-1` (через `docker exec -i … cat`),
запускает `llm_runner.py` в фоне внутри контейнера с его `LLM_API_KEY`/`LLM_FOLDER_ID`/`LLM_BASE_URL`, раз в минуту
показывает прогресс, забирает ответы, делает второй вызов для сомнительных и пишет отчёт
`backend/app/modules/validation/data/grader_check.json`; временные файлы на сервере и в контейнере удаляет.
Прерванный прогон продолжается повторным запуском. Ниже — прежний ручной вариант с ключом из файла на сервере.

## Прогон на YandexGPT вручную (ключ — только на сервере)

Запросы строятся теми же функциями, что в продукте (`grader.build_messages`), ответы разбираются `parse_reply`,
`doubts`, `combine`. Ключ не покидает сервер: на сервер уходят файлы запросов, обратно — ответы модели.

```
PY=/home/user/workspace/spectrek/.venv/bin/python; K="python3 /home/user/workspace/tools/k.py"; D=/tmp/ig09/run
mkdir -p $D && cd backend
$PY -m app.modules.validation.grader_check build --cond v1 --out $D/v1.jsonl        # 232 запроса, ≈ 0,32 млн токенов
$PY -m app.modules.validation.grader_check build --cond v2 --out $D/v2_1.jsonl      # 406 запросов, ≈ 0,7 млн токенов
#   дешёвый вариант: --limit-per-group 10 (≈ 60 + 100 запросов)
$K cmd 'mkdir -p /tmp/ig09'
for f in v1.jsonl v2_1.jsonl; do $K put $D/$f /tmp/ig09/$f; done
$K put ../tools/grader_check/llm_runner.py /tmp/ig09/llm_runner.py
$K cmd 'cd /tmp/ig09 && (set -a; . /opt/spectrek_fsp/secrets/llm.env; set +a;
  python3 llm_runner.py --requests v1.jsonl --out v1_out.jsonl --model yandexgpt/latest --conc 3 &&
  python3 llm_runner.py --requests v2_1.jsonl --out v2_1_out.jsonl --model yandexgpt/latest --conc 3) | tail -3'
for f in v1_out.jsonl v2_1_out.jsonl; do $K get /tmp/ig09/$f $D/$f; done
$PY -m app.modules.validation.grader_check second --req $D/v2_1.jsonl --res $D/v2_1_out.jsonl --out $D/v2_2.jsonl
$K put $D/v2_2.jsonl /tmp/ig09/v2_2.jsonl
$K cmd 'cd /tmp/ig09 && (set -a; . /opt/spectrek_fsp/secrets/llm.env; set +a;
  python3 llm_runner.py --requests v2_2.jsonl --out v2_2_out.jsonl --model yandexgpt/latest --conc 3) | tail -3'
$K get /tmp/ig09/v2_2_out.jsonl $D/v2_2_out.jsonl
$PY -m app.modules.validation.grader_check report --dir $D    # → data/grader_check.json, раздел /validation#grader
$K cmd 'rm -rf /tmp/ig09'
```

Раннер возобновляет прерванный прогон (уже полученные `req_id` пропускает). Расход токенов — в `tokens` отчёта.
