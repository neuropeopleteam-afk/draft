# Направление data_eng — Инженер данных

Семейства направления «Инженер данных»: SQL-аналитика (фильтры, агрегаты, окна, сессии, SCD2), ETL/ELT (upsert,
перезапись партиций, инкрементальная выгрузка по водяному знаку, CDC), качество данных, оркестрация (Airflow:
правила запуска, catchup), потоковая обработка (окна по времени события, отставание группы Kafka, гарантии доставки),
проектирование конвейеров.

Семейств уровней Стажёр–Senior: **22**. Покрытие уровней (семейство может целиться в два соседних): Стажёр — 4, Junior — 14, Middle — 15, Senior — 8.
Семейства уровней Lead/Principal (файлы с префиксами `lead_`/`principal_`, 6 шт.) — отдельный набор,
проверяется `tests/test_lead_principal_a.py`.

## Как устроены семейства
- Каждое семейство — параметрический генератор: контекст, данные, имена и числа меняются от seed; не меньше 20
  различимых вариантов (`tools/check_family_variants.py`, расстояние Жаккара по словам видимого текста ≥ 0,05).
- Ключ закрытых форматов проверяется исполнением в песочнице; у open_book_3step шаги 1–2 исполняются, шаг 3 и
  open_answer оцениваются по рубрике из трёх критериев с весами и эталонами «сильный/средний/слабый».
- SQL исполняется в sqlite (раннер `sqlite` или обвязка на Python с `sqlite3`). Код DAG Airflow исполняется дословно с
  заглушками модулей airflow (собирают граф, правила и расписание) и моделью планировщика по документации Airflow 2.
  Потоковые задачи — упрощённые обработчики на Python, исполняемые как показаны; код потребителя Kafka → БД
  исполняется с заглушками потребителя и БД (транзакция применяется только без исключения) и внедрённым падением.
- Дистракторы — фиксированный состав типовых ошибок (одна главная ловушка на семейство), чтобы задание различало
  соседние уровни, а не случайно усложнялось.
- `prior_difficulty` — априорная трудность (не по людям) с обоснованием `basis`; калибровка — общим прогоном панели.
- Навыки (`skills`) — из словаря каталога направлений (снимок в `tests/test_devops_de.py`).

## Семейства

| семейство | формат | уровни | b | что проверяет | ключ |
|---|---|---|---|---|---|
| `data_eng.design.pipeline_open` | open_answer | Senior | +1.3 | Проектирование конвейера данных — источники, гарантии, модель хранения и эксплуатация | рубрика |
| `data_eng.dq.uniqueness_check_bug` | find_bug | Junior, Middle | -0.4 | Качество данных — проверка уникальности по неполному составному ключу | исполнение: python |
| `data_eng.dwh.scd2_rerun_fix` | choose_fix | Middle, Senior | +0.8 | Загрузка измерения SCD2 — повторный запуск за ту же дату создаёт вторую текущую версию | исполнение: python |
| `data_eng.etl.cdc_apply_output` | predict_output | Middle, Senior | +0.6 | CDC — итоговое состояние таблицы после применения событий не по порядку (повторы, устаревшие, удаление) | исполнение: python |
| `data_eng.etl.csv_parse_bug` | find_bug | Стажёр, Junior | -0.8 | ETL — разбор CSV через split(",") при полях с запятыми | исполнение: python |
| `data_eng.etl.partition_overwrite_fix` | choose_fix | Middle, Senior | +0.5 | ETL — идемпотентный перезапуск дневной загрузки (перезапись партиции в транзакции) | исполнение: python |
| `data_eng.etl.tz_partition_bug` | find_bug | Junior, Middle | -0.3 | ETL — дата партиции из UTC вместо местной даты | исполнение: python |
| `data_eng.etl.upsert_fix` | choose_fix | Junior, Middle | +0.1 | ETL — загрузка изменений через INSERT OR REPLACE затирает created_at (upsert) | исполнение: python |
| `data_eng.etl.watermark_ob3` | open_book_3step | Middle, Senior | +0.9 | Инкрементальная выгрузка по водяному знаку updated_at теряет строки на границе (открытая книга) | шаги 1–2 — исполнение (python), шаг 3 — рубрика |
| `data_eng.orch.catchup_runs_mcq` | mcq_concept | Junior, Middle | -0.1 | Оркестрация (Airflow) — сколько запусков создаст catchup и какая у них logical_date | исполнение: python |
| `data_eng.orch.trigger_rule_output` | predict_output | Junior, Middle | +0.3 | Оркестрация (Airflow) — состояния задач после падения одной (trigger_rule) | исполнение: python |
| `data_eng.sql.and_or_precedence_output` | predict_output | Стажёр, Junior | -1.3 | SQL — приоритет AND над OR в WHERE | исполнение: sqlite |
| `data_eng.sql.date_between_output` | predict_output | Стажёр, Junior | -0.9 | SQL — фильтр по датам через BETWEEN по столбцу с датой и временем | исполнение: sqlite |
| `data_eng.sql.group_by_having_output` | predict_output | Стажёр, Junior | -1.1 | SQL — WHERE до группировки и HAVING после | исполнение: sqlite |
| `data_eng.sql.left_join_filter_bug` | find_bug | Junior, Middle | -0.3 | SQL — условие на правую таблицу в WHERE ломает LEFT JOIN | исполнение: python |
| `data_eng.sql.null_agg_canary` | predict_output | Junior | -1.0 | SQL — агрегаты и NULL (канарейка) | исполнение: sqlite |
| `data_eng.sql.scd2_asof_output` | predict_output | Junior, Middle | +0.0 | SQL — факты и измерение SCD2 по интервалу действия версии | исполнение: sqlite |
| `data_eng.sql.sessionization_output` | predict_output | Middle, Senior | +0.8 | SQL — сессионизация событий через LAG и порог паузы | исполнение: sqlite |
| `data_eng.sql.window_rank_output` | predict_output | Junior, Middle | +0.0 | SQL — топ-k по группе: ROW_NUMBER, RANK, DENSE_RANK при равных значениях | исполнение: sqlite |
| `data_eng.stream.consumer_lag_mcq` | mcq_concept | Junior, Middle | -0.3 | Kafka — отставание группы потребителей и время, за которое она догонит поток | исполнение: python |
| `data_eng.stream.delivery_semantics_mcq` | mcq_concept | Senior | +1.1 | Kafka → БД — гарантии доставки по коду потребителя и итог после падения | исполнение: python |
| `data_eng.stream.tumbling_window_output` | predict_output | Middle, Senior | +0.9 | Потоковая обработка — окна по времени события, водяной знак и опоздавшие события | исполнение: python |

## Проверки
```bash
make test-fast                                              # быстрые тесты, включая tests/test_devops_de.py
python tools/dev_family.py <family_id> 200 --show 1         # одно семейство: 200 seed, пример варианта
python tools/check_family_variants.py --direction data_eng   # ≥ 20 различимых вариантов
python -m assessment_bank validate --seeds 200 --out reports
```
