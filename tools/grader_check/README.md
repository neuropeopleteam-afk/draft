# Проверка оценщика открытых ответов на наборе панели 06.10

Набор: `docs/validation/grader_set_panel_20261006.json.gz` (29 развёрнутых заданий, 319 ответов панели + 87 перефразированных атак,
которые строит `backend/app/modules/validation/grader_check.py`). Пересборка набора из сырых данных панели:

```
python tools/grader_check/build_dataset.py \
  --oldbank /tmp/ig09/oldbank --grading $PRIVATE_DATA/panel2_raw/grading \
  --out docs/validation/grader_set_panel_20261006.json.gz
# /tmp/ig09/oldbank — банк на коммите панели: git -C bank archive 1631167 | tar -x -C /tmp/ig09/oldbank
```

## Офлайн-часть (без модели) — уже в `backend/app/modules/validation/data/grader_check.json`

```
cd backend && ../../../.venv/bin/python -m app.modules.validation.grader_check report --dir /tmp/ig09/empty
```

## Прогон на YandexGPT внутри контейнера api (ключ уже там; запускает руководитель проекта)

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
PY=python; K="python3 $K_PY"; D=/tmp/ig09/run
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

## Офлайн: параметрические вариации атак (фильтры до модели)

`injection_variants.py` — 116 атак панели (4 приёма × 29 заданий) × 10 преобразований нагрузки (исходная, в начале
ответа, ПРОПИСНЫМИ, цитата, HTML-комментарий, комментарий в коде, перенос строк, перевод на английский, синонимы,
гомоглифы + символы нулевой ширины) = 1 160 вариаций (320 различных текстов). Проверяются только
`injection_signals` и `strip_meta`, модель не вызывается — это не число «пробитий» оценщика.

```bash
cd backend && python ../tools/grader_check/injection_variants.py   # → data/grader_variants.json
```

Прогон 20.10: перехвачено 841 из 1 160; не перехвачены все вариации «английский» и «гомоглифы» (по 116) и 87 из 116
«синонимы». Чтобы заявлять «0 из 1 160 пробитий», эти вариации нужно прогнать через полную цепочку на LLM
(build → llm_runner → second → report, как выше).
