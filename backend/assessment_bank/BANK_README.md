# assessment_bank — банк заданий и психометрика спецтрека ФСП (ЛЦТ 2026)

Пакет на чистом Python 3.12 без БД: семейства изоморфных заданий, генерация вариантов по
seed, валидатор с проверкой ключей исполнением в песочнице, модели Раша/2PL, иерархия
семейств, адаптивный тест с контролем показа, грейды, детектор предзнания и симуляция.
Бэкенд импортирует пакет как библиотеку. Лицензия MIT.

## Установка и запуск

```bash
make install            # venv + зависимости с фиксированными версиями (requirements.txt)
make list               # список семейств
make test-fast          # pytest без долгих тестов (~1 мин)
make validate           # валидатор на 200 seed + симуляция → reports/
make validate SEEDS=50 N=300   # быстрее
make validate VENV=../.venv_bank   # если venv лежит вне проекта
```

CLI: `python -m assessment_bank {list|generate FID SEED [--public]|validate|simulate|canary-leak}`.

```python
from assessment_bank import generate, list_families
v = generate("backend.py.rate_limiter_ob3", 1000017)
v.public_view()      # то, что видит кандидат: без ключа, рубрики, проверок и параметров
v.answer_key, v.rubric
```

Зависимости (все с открытыми лицензиями): numpy 2.1.3 (BSD), scipy 1.14.1 (BSD),
pydantic 2.9.2 (MIT), PyYAML 6.0.2 (MIT), pytest 9.1.1 (MIT), Django 5.2.17 (BSD — только для
проверки ключей семейств `backend.django.*`). Для проверок ключей нужны `node` (≥ 18), `bash`, `git`;
`sqlite3` — из стандартной библиотеки Python; для семейств Go и Java — `go` (≥ 1.22) и JDK (≥ 17,
с модулем `jdk.compiler`): пути задаются переменными `BANK_GO_BIN` / `BANK_JAVA_BIN` или берутся из
PATH. Без них соответствующие проверки помечаются «нет исполнителя» (WARN, не FAIL).

## Формат банка

Семейство = YAML-описание + модуль Python с функцией `generate(seed) -> Variant`.
Файлы лежат в `assessment_bank/families/<direction>/<name>.yaml|.py`, каталог совпадает
с `direction`.

| Поле YAML | Смысл |
|---|---|
| `family_id` | `направление.область.имя`, например `common.sql.left_join_count` |
| `direction` | common, backend, frontend, data_ml, qa, security; с волны 7 — devops, data_eng, mobile, analyst |
| `skills`, `target_grades` | навыки (теги, которые платформа сводит к своему каталогу); intern / junior / middle / senior — `intern` («Стажёр») помечает лёгкие семейства у порога Junior (b ≲ −1) и в CAT не участвует |
| `language` | python, javascript, typescript, sql, bash, text, go, java, dockerfile, yaml |
| `format` | find_bug, predict_output, choose_fix, open_book_3step, mcq_concept, open_answer |
| `invariants` | `code_lines`, `operations` (диапазоны), `defect_type`, `n_options`, `extra` |
| `time_limit_s`, `canary`, `canary_pool_size` | лимит времени; канарейка и число опубликованных seed |
| `prior_difficulty` | `b`, `a`, `sigma_variant`, `step_offsets` (для трёх шагов), `basis` — обоснование |

Вариант (`schema.Variant`): `variant_id = family_id:seed`, `stem` (по-русски), `code`,
`options`, `answer_key` (`option | line | output | steps | rubric`), `rubric`
(критерии с весами + эталоны сильного/среднего/слабого ответа), `meta` (контекст,
измеренные `code_lines`/`operations`, шаги, способ проверки ключа, проверки исполнением).

Форматы:
* `find_bug` — номер строки с дефектом; генератор отдаёт исправленный код, валидатор
  проверяет, что исправление меняет ровно эту строку, дефектный код падает, исправленный проходит;
* `predict_output` — точный вывод; ключ считается независимой моделью и сверяется с
  исполнением показанного кода;
* `choose_fix` — 4 исправления, ровно одно верно на тестах, остальные падают;
* `open_book_3step` — «экзамен с открытой книгой»: шаг 1 — выбрать вход, воспроизводящий
  дефект; шаг 2 — исправление; шаг 3 — развёрнутое объяснение при новом условии
  (оценка по рубрике); шаги 1–2 проверяются исполнением;
* `mcq_concept` — концептуальный вопрос; ключ исполнением, где возможно, иначе по
  справочной таблице (отмечается предупреждением);
* `open_answer` — проектное решение, рубрика из 3 критериев с эталонами.

## Как добавить семейство

1. Скопируйте ближайшее по формату семейство (`families/<dir>/*.py|.yaml`).
2. В `.py`: `FAMILY_ID = "..."`, весь случайный выбор — только через
   `make_rng(FAMILY_ID, seed)`; никаких `random.*`, времени, `hash()` строк. Соберите
   вариант через `build_variant(...)` и опишите проверки `Check` (runner `python | node |
   bash | git | sqlite | go | java | django`), соблюдая соглашения валидатора: `option:X` для choose_fix,
   `step1:X`/`step2:X` для open_book_3step, `stdout_equals` с ключом для predict_output.
3. В YAML задайте инварианты и `prior_difficulty` с обоснованием `basis`.
4. Отладка: `python tools/dev_family.py FAMILY_ID 200 --show 2` — пример варианта и сводка
   валидатора; затем `pytest -q tests/test_families_quick.py -k имя`.

Правила, подтверждённые калибровкой 05.10 (панель LLM, `calibration/panel_20261005/report.md`):

* **Один подтип дефекта на семейство.** Варьируется поверхность (контекст, имена, данные,
  порядок блоков), а не суть ошибки; разные подтипы — разные семейства с общим генератором
  (`_generate(seed, family_id, subtypes)` в исходном модуле, тонкий модуль-обёртка рядом).
* **Состав дистракторов фиксирован**, если от него зависит трудность (σ вариантов > 0,5).
* **Нет подсказок в условии**: условие задаёт цель или симптом, а не перечень мер; верный
  вариант не должен быть единственным «другой формы» (длина, подзапрос, ключевое слово) —
  нужен хотя бы один почти верный дистрактор.
* **Строка дефекта не постоянна** по вариантам (служебные строки, порядок функций).
* Если в find_bug две строки равноценно исправляют дефект, вторая указывается в
  `answer_key.accept`, её исправление — в `params.alt_fixes[str(строка)]` и проверяется
  исполнением (`Check(name="alt_fix:<строка>", expect="pass")`).

### Senior-семейства общего блока (добавлены 06.10)

| Семейство | Формат | Что проверяет | Проверка ключа |
|---|---|---|---|
| `common.dist.fencing_token_bug` | find_bug | fencing-токен не растёт при перехвате истёкшей чужой аренды — устаревший держатель после паузы перезаписывает данные | сценарий «пауза дольше TTL» исполняется на дефектном и исправленном коде |
| `common.perf.fanout_tail_mcq` | mcq_concept | доля медленных запросов при fan-out на N бэкендов: 1 − (1 − q)^N | точный расчёт (Fraction) сверяется с вариантами |
| `common.dist.outbox_fix` | choose_fix | двойная запись «БД + брокер», transactional outbox и at-least-once relay | модель БД/брокера, падение в каждой точке, перезапуск relay, инвариант «без потерь и призраков» |

Также по итогам калибровки выделены семейства по подтипам: `backend.cache.key_params_bug`,
`frontend.sec.replace_global_bug`, `data_ml.sql.rolling_partition_bug`,
`frontend.ts.typeof_null_guard_bug`, `data_ml.metrics.auc_pairwise_ties_bug`,
`backend.py.idempotency_coarse_ob3`, `common.git.move_commits_mcq`; `security.crypto.aead_mcq`
переписано как расчётная задача (период ротации ключа AES-GCM, NIST SP 800-38D §8.3).

### Исполнители go, java, django (добавлены 06.10)

* `go` — программы пакета собираются одним `go build -race` и исполняются по очереди (детектор гонок
  включён, паника и отчёт гонки — «тест не пройден»);
* `java` — один процесс JVM на пакет: каждая программа (`public class Main`) компилируется
  `javax.tools` в свой каталог и исполняется в своём загрузчике классов;
* `django` — как python, но без `-S`: Django берётся из окружения банка, каждая программа исполняется
  в `isolate_apps("bankapp")` на своей SQLite-базе в памяти.

Где настоящий исполнитель невозможен или недетерминирован (кэш слоёв Docker, сеть compose, брокер
Kafka, сборщик мусора JVM), ключ проверяется исполнением *модели* на Python — программа описана в
`display_code_note` варианта, а показанный код либо исполняется дословно (`embeds_display_code`), либо
модель повторяет его операции (отмечено в докстринге семейства).

### Семейства по стекам (06.10–07.10)

Семейства с навыками `go*`, `java*`, `django*`, `kafka*`, `docker*` платформа выдаёт только кандидатам,
указавшим этот стек в анкете (фильтр по стеку, `skill_map.STACK_GATED`). Заявленный стек выбирает
вопросы, но не ранжирует.

| Семейство | Формат | Что проверяет | Проверка ключа |
|---|---|---|---|
| `backend.go.slice_append_output`, `go_defer_recover_output` | predict_output | семантика срезов и append; defer/recover | настоящий Go |
| `backend.go.map_race_fix` | choose_fix | гонка на map, sync.Mutex/RWMutex | Go с `-race` |
| `backend.go.context_background_bug` | find_bug | контекст запроса потерян (Background) | Go |
| `backend.java.hashcode_bug` | find_bug | hashCode не согласован с equals | JVM: HashSet/HashMap |
| `backend.java.stream_lazy_output`, `future_exception_output` | predict_output | ленивость Stream; исключения в CompletableFuture | JVM |
| `backend.java.session_registry_leak_fix` (08.10, вместо `session_registry_leak_bug`) | choose_fix | утечка через долгоживущую коллекцию (`get` вместо `remove`); дистракторы — локальный `null`, `Map.remove(Object)` с объектом, `WeakHashMap` (значение держит свой ключ) | JVM: закрыта половина объектов — остаётся вторая половина, затем реестр пуст; для WeakHashMap подтверждено, что записи не очищаются после `System.gc()`. Версия 1 (find_bug) выведена 07.10 (ключ плохо определён; p 0,03) и переделана 08.10 |
| `backend.java.string_equals_bug` (07.10) | find_bug | `==` вместо `equals` для строк, собранных при разборе | JVM: строки создаются во время выполнения, положительный и отрицательный случай |
| `backend.java.list_remove_loop_fix` (07.10) | choose_fix | удаление из ArrayList в цикле по индексу (сдвиг и пропуск); дистракторы — for-each + remove (CME), remove по объекту, присвоение параметру | JVM: все четыре варианта на списке с подряд идущими подходящими записями |
| `backend.django.n_plus_one_output` | predict_output | число запросов при select_related | настоящий Django |
| `backend.django.form_fields_bug`, `on_commit_fix` | find_bug, choose_fix | `fields="__all__"`; `transaction.on_commit` | настоящий Django |
| `backend.django.signals_output` | predict_output | какие операции ORM посылают post_save | настоящий Django |
| `backend.django.migration_default_bug` | find_bug | `default=timezone.now()` — константа в миграции | настоящий Django: две записи с паузой |
| `backend.kafka.consumer_group_mcq` | mcq_concept | партиции и потребители группы | модель |
| `backend.kafka.partition_key_bug` | find_bug | ключ по статусу вместо id — порядок в партиции | модель клиента (murmur2, как в Java-клиенте и kafka-python) |
| `backend.kafka.offset_commit_mcq` | mcq_concept | commitSync после пачки, падение, дубли | модель потребителя |
| `backend.kafka.outbox_relay_fix` | choose_fix | relay outbox помечает строки до подтверждения send() | модель брокера, отвергающего часть сообщений |
| `common.docker.layer_cache_output` | predict_output | какие слои пересоберутся при повторной сборке | модель кэша слоёв (COPY по контрольной сумме, RUN по тексту, каскад) |
| `common.docker.cache_order_fix` | choose_fix | порядок COPY и установки зависимостей | модель кэша: две сборки подряд |
| `common.docker.compose_port_bug` | find_bug | опубликованный порт вместо порта контейнера в сети compose | модель сети compose по показанному YAML |

### Лёгкие семейства у порога Junior (грейд «Стажёр», 07.10)

`target_grades: [intern, junior]`, prior b от −1,2 до −1,5; по одному семейству в каждом направлении:
`common.sql.count_nulls_output` (COUNT(*) / COUNT(col) / COUNT(DISTINCT) при NULL),
`common.linux.relative_path_output` (`..` и `.` в относительном пути), `backend.py.dict_get_default_output`
(`dict.get` с умолчанием), `frontend.js.loose_equality_output` (`==` против `===`),
`data_ml.stats.mean_median_output` (среднее и медиана с выбросом), `qa.pytest.float_assert_bug`
(точное сравнение float, `pytest.approx`), `security.logging.password_in_log_bug` (пароль в журнале).

### Добор у порогов Junior/Middle и Middle/Senior (10.10)

Цель — точность теста, а не число заданий: у порогов Junior/Middle (θ = 0) и Middle/Senior (θ = 1) по калибровке
панели (модель, не люди) мало семейств с высокой различающей способностью (у порога M/S в security — ни одного).
Слабые семейства (низкая дискриминация, ответы на уровне угадывания, разброс между вариантами) собраны
`tools/weak_families.py` в `reports/weak_families.{md,json}` — это список-кандидат на исключение из адаптивного пула.
Различимость вариантов любого семейства проверяет `tools/check_family_variants.py`.

Добавлено 17 семейств, все с ключом, проверяемым исполнением, одним подтипом дефекта и фиксированным составом
дистракторов; prior a = 1,3, b — у своей границы (обоснование в `basis`). Калибровка — отдельным прогоном панели.

| Семейство | Формат | Порог | Проверка ключа |
|---|---|---|---|
| `security.web.ssrf_allowlist_fix` | choose_fix | M/S | законные и атакующие URL (userinfo, суффикс домена, схема) |
| `security.session.fixation_bug` | find_bug | J/M | подставленный идентификатор сессии после входа не даёт доступа |
| `security.crypto.hmac_canonical_bug` | find_bug | M/S | подпись не подходит к сообщению со сдвинутой границей полей |
| `security.access.bulk_owner_check_bug` | find_bug | J/M | пакет «свой + чужой» отклоняется целиком |
| `security.auth.token_audience_bug` | find_bug | M/S | токен без `aud`, с чужим `aud`, истёкший, чужого издателя — отклонены |
| `frontend.state.optimistic_rollback_fix` | choose_fix | M/S | Node: откат после подтверждённых изменений |
| `frontend.js.object_key_order_output` | predict_output | M/S | Node и модель порядка ключей объекта |
| `data_ml.ml.purged_split_fix` | choose_fix | M/S | разрыв перед тестовым блоком на разных (n, k, H) |
| `data_ml.metrics.pooled_rate_bug` | find_bug | J/M | итоговая доля — отношение сумм |
| `data_ml.features.lag_window_leak_bug` | find_bug | J/M | признак не зависит от цели своей строки |
| `data_ml.features.target_encoding_oof_fix` | choose_fix | M/S | независимость от цели своего фолда и эталонный расчёт |
| `qa.mock.called_once_bug` | find_bug | J/M | обвязка pytest: исправленный тест ловит мутанта |
| `qa.mutation.survivors_output` | predict_output | M/S | прогон тестов на мутантах |
| `qa.pytest.fixture_scope_state_bug` | find_bug | M/S | тесты по одному и во всех порядках |
| `qa.pytest.raises_too_broad_bug` | find_bug | J/M | правильная реализация и мутант с другим исключением |
| `backend.cache.stampede_fix` | choose_fix | M/S | asyncio: N одновременных промахов — одна загрузка; ошибка не кэшируется |
| `common.sql.window_range_ties_output` | predict_output | M/S | SQLite и модель рамки RANGE по умолчанию |

Тесты добора — `tests/test_bank_core_plus.py`; счётчик в `tests/test_bankfix.py` считает только шесть исходных
направлений (165 + добор), новые направления проверяются своими тестами.

### Мобильная разработка и аналитик (волна 7, 10–11.10)

Направления `mobile` («Мобильная разработка») и `analyst` («Системный / бизнес-аналитик») — 22 и 19 семейств
уровней intern–senior (плюс Lead/Principal — отдельные семейства с префиксом `lead_`/`principal_`). Каждое — параметрический
генератор с ≥ 20 различимыми вариантами (`tools/check_family_variants.py --direction mobile --direction analyst`).
Kotlin и Swift в песочнице не исполняются: для них «найди ошибку» с ключом от модели на Python (поток выполнения,
владение ссылками, потоки UI), концептуальные вопросы — с моделью жизненного цикла или справочной таблицей. JS/TS —
исполняется в Node. Текстовые модели аналитика (машины состояний UML, BPMN, таблицы решений, контракты API, JSON
Schema, процессы) вкладываются в программу проверки дословно и разбираются ею — ключ считается по показанному тексту.

| Семейства | Формат | Уровни | Проверка ключа |
|---|---|---|---|
| `mobile.js.*` (token_refresh, offline_queue, double_submit, deeplink_route, cursor_pagination, background_timer, version_gate, retry_backoff) | choose_fix / find_bug / predict_output | I–S | Node: модели сервера, сети, таймеров |
| `mobile.kotlin.*`, `mobile.swift.*` | find_bug / mcq_concept | J–S | модель на Python (главный поток, retain cycle, Flow и жизненный цикл) |
| `mobile.android.*`, `mobile.ios.*`, `mobile.push.*`, `mobile.security.*` | mcq_concept | I–S | модель жизненного цикла / справочная таблица |
| `mobile.storage.sqlite_migration_bug` | find_bug | I/J | sqlite: миграция схемы |
| `mobile.perf.frame_budget_mcq`, `mobile.perf.cold_start_mcq` | mcq_concept | J–S | бюджет кадра; критический путь холодного старта |
| `mobile.arch.offline_sync_open`, `mobile.release.release_quality_open` | open_answer | S | рубрика |
| `analyst.sql.*` (null_aggregate, funnel_distinct, not_in_null, join_fanout, retention_cohort) | predict_output / find_bug / choose_fix | I–S | sqlite |
| `analyst.er.cardinality_ddl_fix` | choose_fix | J/M | sqlite с внешними ключами: сценарии вставки из требования |
| `analyst.uml.state_machine_output`, `analyst.uml.state_rule_bug` | predict_output / find_bug | I–M | разбор машины состояний (16 контекстов) |
| `analyst.bpmn.gateway_trace_output`, `analyst.bpmn.join_mismatch_bug` | predict_output / find_bug | I–S | путь через XOR; игра фишек на Python |
| `analyst.req.acceptance_scenario_mcq`, `analyst.req.decision_table_mcq`, `analyst.req.rice_priority_mcq` | mcq_concept | I–M | разбор сценариев Gherkin; перебор комбинаций таблицы; RICE по таблице |
| `analyst.api.json_schema_validate_output` | predict_output | I/J | мини-валидатор подмножества JSON Schema |
| `analyst.api.breaking_change_mcq`, `analyst.api.idempotency_contract_mcq` | mcq_concept | M/S | модель совместимости контракта; событийная модель повторов |
| `analyst.process.bottleneck_capacity_output` | predict_output | M/S | мощность шагов с долей XOR и циклом доработки (Fraction) |
| `analyst.req.nfr_open`, `analyst.arch.integration_open` | open_answer | S | рубрика |

Имена навыков (`skills`) — из словаря каталога платформы (направления mobile/analyst, `skill_map`); тесты потока —
`tests/test_wave7_mobile_analyst.py` (состав, покрытие уровней, трудность против уровней, различимость, данные
машин состояний). prior_difficulty — априорная, до калибровки панелью.

### Уровни Lead и Principal: common, backend, frontend, data_ml, devops, data_eng (волна 7, 11.10)

46 семейств уровней Lead и Principal: common — 11 (7 Lead, 4 Principal), backend, frontend, data_ml, devops,
data_eng — по 7 (на направление ≥ 4 Lead и ≥ 2 Principal). Соглашения:

- `target_grades` — только `[lead]` или `[principal]` (без senior): продукт скрывает их одним условием, пока
  расширение грейдов выключено; в счёт 165 семейств прежних направлений они не входят.
- `prior_difficulty.b`: Lead 1,6–2,0, Principal 2,5–2,8 (диапазон карточки 1,6–3,2); `basis` начинается с
  «Априорная трудность (не по людям)» и объясняет, где проходит граница Senior/Lead или Lead/Principal.
- В devops и data_eng имена файлов — с префиксом `lead_`/`principal_`.
- Открытые ответы (`open_answer`) — кейсы с числами в условии: ответ без расчёта по этим числам не получает
  высших баллов. Рубрика — 4–6 критериев с весами (сумма 1,0), шкала 0–4 по каждому критерию, оценка требует
  цитат из ответа; эталоны сильного, среднего и слабого ответа — в варианте.
- `choose_fix` — по схеме 2×2: из пула правил выбираются два, варианты — верный, нарушено первое, нарушено второе,
  нарушены оба; у вариантов свои локальные имена и необязательные строки. Ключ проверяется исполнением
  (python, node, sqlite) на сценариях, где каждое нарушение даёт неверный итог.
- `mcq_concept` — числовые и «стратегические» вопросы, ключ которых считает программа (`numeric_mcq`: модель
  очереди, событий, лет-сценариев и т. п., не формула генератора); ответ-пара (`lead_burn_rate_mcq`) и политики
  хранения (`principal_tiering_mcq`) — по схеме 2×2.
- Ключ не угадывается по форме вариантов: самый длинный, самый короткий, «центральный», «краевой» и «ни разу
  не крайний» дают ≤ 0,45 при случайном 0,25 (тест). У расчётных вопросов с числом в подписи ключ не угадывается
  и по месту числа среди четырёх: ловушки берутся из пула ошибок с обеих сторон от верного значения (завышающие
  и занижающие), сколько их ниже ключа — равновероятно, подписи одной длины (три значащие цифры, двузначные
  числа) — тест `test_key_not_guessable_by_value_rank`, ≤ 0,45.

| Направление | Lead | Principal | Проверка ключа |
|---|---|---|---|
| common | `arch.design_review_open`, `incident.postmortem_open`, `arch.capacity_design_open`, `arch.consistency_tradeoff_open` (open); `arch.availability_chain_mcq`, `arch.retry_amplification_mcq`, `arch.queue_workers_mcq` (mcq) | `strategy.tech_strategy_open`, `process.tech_debt_portfolio_open` (open); `strategy.migration_plan_mcq`, `strategy.tco_horizon_mcq` (mcq) | рубрика; программы: цепочка доступности, усиление повторов, очередь, план миграции, TCO по годам |
| backend | `arch.single_flight_fix`, `arch.outbox_relay_fix` (choose_fix); `review.pr_lead_open`, `arch.idempotent_payments_open` (open) | `strategy.monolith_split_open`, `strategy.sharding_plan_open` (open); `strategy.blast_radius_mcq` (mcq) | asyncio-тест; модель базы и брокера с падением в каждой точке; исходы событий с весами |
| frontend | `arch.optimistic_update_fix` (choose_fix, node); `arch.perf_budget_mcq` (mcq); `review.client_arch_open`, `arch.rendering_strategy_open`, `arch.realtime_collab_open` (open) | `strategy.legacy_migration_open`, `strategy.design_system_platform_open` (open) | поддельный API с порядком ответов и отказами; критический путь загрузки |
| data_ml | `exp.duration_cuped_mcq`, `serving.lead_batching_mcq` (mcq); `review.ml_system_open`, `arch.recsys_serving_open`, `eval.llm_eval_open` (open) | `strategy.ml_platform_open`, `strategy.llm_adoption_open` (open) | длительность теста с CUPED; очередь GPU с динамическим пакетированием |
| devops | `sre.lead_burn_rate_mcq`, `k8s.lead_rollout_capacity_mcq` (mcq); `mon.lead_observability_open`, `ci.lead_cicd_platform_open` (open) | `strategy.principal_dr_open`, `strategy.principal_platform_eng_open` (open); `strategy.principal_dr_cost_mcq` (mcq) | поминутный расход бюджета SLO; ёмкость при выкатке; годы-сценарии DR |
| data_eng | `stream.lead_watermark_mcq` (mcq); `dwh.lead_scd2_merge_fix` (choose_fix, sqlite); `review.lead_pipeline_review_open`, `etl.lead_cdc_design_open` (open) | `strategy.principal_platform_open`, `strategy.principal_governance_open` (open); `strategy.principal_tiering_mcq` (mcq) | события с водяным знаком; два запуска SCD2 на sqlite против модели на Python; помесячный проигрыш уровней хранения |

Тест потока — `tests/test_lead_principal_a.py` (состав, уровни, трудность, пометка в обосновании, рубрики,
≥ 20 различимых вариантов, префиксы, угадывание по форме и по месту числа, вне счёта 165). prior_difficulty — априорная, до
калибровки панелью.

### Правки по флагам панели 06.10 (версии 2)

`qa.js.brittle_render_fix` и `common.text.utf8_truncate_fix` — фиксированный состав дистракторов;
`qa.triage.severity_priority_mcq` — только квадранты, где серьёзность и приоритет расходятся;
`qa.load.percentile_merge_mcq` — выбор метода вместо многошагового расчёта. Перекалибровка 07.10
(`panel_20261007_ext3`): `percentile_merge_mcq` — флагов нет (b −0,53, a 1,78); `severity_priority_mcq` —
лучше, но σ 0,59 остаётся; `brittle_render_fix` и `utf8_truncate_fix` флаги не сняли.

### Переделка по итогам вычитки и панели ext4 (08.10)

Ветка `feat/bank-fix`, перекалибровка — `calibration/panel_20261008_ext4` и `panel_20261008_ext4b`.
* `backend.kafka.outbox_relay_fix` (v2): дистрактор с несуществующим параметром kafka-python заменён на правдоподобный,
  но неверный (`add_errback` только пишет в журнал; строка помечается сразу); `django_migration_default_bug` (v2):
  точная формулировка («все записи после запуска приложения получают одно значение — момент запуска»).
* Выровнены длины вариантов (верный вариант не самый длинный и не самый короткий): `percentile_merge_mcq`, `git.undo_mcq`
  (дистракторы зависят от формы верной команды), `tx_isolation_mcq`, `cors_csrf_mcq`, `cookie_policy_mcq` (v3, фиксированный
  состав дистракторов), `js_listener_leak_fix`, `sql_reconciliation_fix`, `kafka.offset_commit_mcq`, `fe_onehot_serving_fix`,
  `focus_trap_ob3`, `docker.cache_order_fix`. Не правились (отношение длин 1,03 и 0,99): `security.supply.dependency_patch_fix`,
  `common.db.index_plan_mcq`.
* Лимиты канареек: `common.alg.heap_trace` 150 → 180 с, `common.linux.umask_chmod` 90 → 120 с.
* Пул песочницы (`sandbox.run_checks`) ограничен 24 потоками: на хосте со 192 ядрами `os.cpu_count()` давал 768 потоков
  и «Too many open files» при проверках git/оболочки.
* Правила калибровки (`calibration/rerun_new.py`): задание MCQ/choose_fix, на которое вся панель отвечает на уровне
  угадывания (p ≤ 0,29, r(x,θ) < 0,15), считается неинформативным — остаётся prior, оценка панели в `b_panel`/`a_panel`.

### Выведены из выдачи 07.10 по итогам калибровки; `session_registry_leak_fix` возвращён 08.10, `gc_reachability_mcq` выведен повторно 09.10

Четыре семейства были перенесены в `assessment_bank/families_retired/` (реестр их не читает; после переноса в
выдаче осталось 162 семейства): `backend.java.session_registry_leak_bug` (ключ плохо определён для формата
find_bug: дефект — пропуск `remove`; p 0,03, отрицательная дискриминация), `backend.java.gc_reachability_mcq`
(p 0,23 ≈ шанс, σ между вариантами 1,88), `common.text.utf8_truncate_fix` (вторая панель подряд: b 3,69, a 0,44),
`qa.js.brittle_render_fix` (решается «в лоб», σ 1,04, 3B лучше 32B). Продукт выдаёт задания по
`prior_difficulty` из YAML, где эти семейства стояли у порогов Junior/Middle с a ≈ 1 — то есть CAT выбирал их
как самые информативные, а по данным они шум. Покрытие Java: 5 → 3 семейства (одно уровня Junior); тем же днём
добавлены два простых Java-семейства с бесспорным ключом — `backend.java.string_equals_bug` (Стажёр/Junior,
find_bug) и `backend.java.list_remove_loop_fix` (Junior/Middle, choose_fix с исполнением всех вариантов) — итого
**164** семейства в выдаче, Java — 5.

08.10 (ветка `feat/bank-fix`) оба Java-семейства переделаны по решению консилиума и возвращены в `families/`:
`session_registry_leak_bug` → **`backend.java.session_registry_leak_fix`** (choose_fix: `remove(id)` против
локального `null`, `Map.remove(Object)` и `WeakHashMap`; все варианты исполняются на JVM), `gc_reachability_mcq`
(тот же ID, версия 2: фиксированный сценарий — 4 объекта, 6 переназначений, одна схема дистракторов). В выдаче
снова **166** семейств, Java — 7.

09.10 (ветка `feat/bank-fix`, решение руководителя проекта по итогам панели ext4) `backend.java.gc_reachability_mcq` (версия 3) **повторно выведено**
в `families_retired/backend/`: ключ однозначен и варианты изоморфны (σ 0,00, χ² p_hom 0,58), но вся панель отвечает на уровне
угадывания (p 0,23 при шансе 0,25, a 0,36, r 0,04), то есть задание не различает уровни, а CAT по prior (b 0,3, a 1,0) выбирал бы
его как информативное. Оценки трудности для людей нет; вернуть можно после пилота с людьми. Теперь в выдаче **165** семейств
(backend 44, common 34, frontend 26, data_ml 23, qa 19, security 19), Java — 6 (`hashcode_bug`, `string_equals_bug`,
`list_remove_loop_fix`, `session_registry_leak_fix`, `stream_lazy_output`, `future_exception_output`); в `families_retired/` —
`gc_reachability_mcq`, `utf8_truncate_fix` и `brittle_render_fix`. Код и YAML перенесены `git mv` без содержательных правок
(изменён только путь `generator:`); запись об измерениях в `params_current.json` сохранена как история. Регрессионный тест
фиксированного сценария (`tests/test_bankfix.py`) исполняет генератор из `families_retired/` напрямую.
Цифры, причины и план переделки — `assessment_bank/families_retired/README.md`; перекалибровка
переделанных семейств — `calibration/panel_20261008_ext4/` (запись об измерениях 07.10 в `params_current.json`
заменена новой оценкой, история — в отчётах панелей).

Правила текста (вычитка 08.10, `tests/test_proofread.py`):

* **Числительные склоняются через `gen_utils.plural(n, «один», «два», «пять»)`**, а не
  формой «раз(а)» или фиксированным множественным числом: числа в шаблонах меняются, и
  «5 часа», «4 месяцев», «2 партиций» недопустимы.
* **Единая терминология:** «хэш», «сэмплирование», «таймаут», «кэш».
* **В подписи варианта не дублируется код:** если у варианта есть `code`, текст — нейтральная
  подпись («Заменить запрос на:»), иначе в интерфейсе текст и код показываются дважды и
  подпись подсказывает ответ.
* **Контекст — предметная область, а не «сервис»:** в условии он подставляется как
  «Сервис (…)», поэтому в самом контексте слово «сервис» не повторяется.
* **Правка только текста не меняет порядок обращений к `rng`**: иначе меняются ключи и
  параметры вариантов, и калибровка семейства теряет силу.

### Уровни Lead и Principal: qa, security, mobile, analyst (волна 7)

28 семейств — по 7 на направление (4 Lead, 3 Principal), файлы `<направление>/lead_*.py` и `principal_*.py`,
`target_grades` — ровно один из `lead`, `principal`. Трудность — априорная (`prior_difficulty` с `basis`): Lead
b 1,7–2,0, Principal b 2,5–2,6, a 1,1–1,3; калибровка — общим прогоном панели. Без флага уровней Lead/Principal
продукт эти семейства не выдаёт.

Форматы и проверка:
* **mcq_concept с расчётом** — ключ печатает программа по тем же числам, что видит кандидат (перебор, точные дроби,
  целочисленный поиск); дистракторы — модели типичных ошибок, числа подобраны так, что каждая ошибка даёт другой
  ответ, а приближённый расчёт — тот же ключ.
* **choose_fix на модуле целиком** — каждая замена исполняется в составе модуля на одних и тех же сценариях
  (Python, Node, SQLite).
* **open_answer** — рубрика 0–4 по критериям, каждый балл подтверждается дословной цитатой из ответа (доказательная
  оценка); ревью документов — в выдержку вставлены 3 проблемы из пула 7 среди верных разделов, критерии — по
  вставленным проблемам и приоритизация.
* **Защита от угадывания по форме** — дистракторы choose_fix и двухчастных ответов строятся по схеме 2×2
  (`factorial_distractors`: нарушено одно правило, другое, оба), у числовых ответов ранг верного по seed
  равномерен, у выбора из фиксированных решений ключ по seed распределён поровну. Тест
  `test_key_not_guessable_by_option_form`: самый длинный / короткий / «центральный» / «краевой» вариант угадывает
  ключ не чаще 0,45 (случайный выбор — 0,25).

| Семейство | Формат | Уровень | Содержание | Проверка ключа |
|---|---|---|---|---|
| `qa.lead.retry_gate_fix` | choose_fix | Lead | политика перезапусков и карантина в конвейере MR | Python, 8 сценариев |
| `qa.lead.retry_tradeoff_mcq` | mcq_concept | Lead | повторы упавших тестов: ложные красные против пропуска нестабильности | расчёт |
| `qa.lead.quality_investment_mcq` | mcq_concept | Lead | одно вложение в качество по полным затратам на релиз | модель этапов |
| `qa.lead.test_plan_review_open` | open_answer | Lead | ревью плана тестирования | рубрика 0–4 |
| `qa.principal.test_budget_mcq` | mcq_concept | Principal | регрессия в бюджет: транзитивное влияние, перекрытие | перебор подмножеств |
| `qa.principal.quality_program_review_open` | open_answer | Principal | ревью программы качества организации | рубрика 0–4 |
| `qa.principal.quality_strategy_open` | open_answer | Principal | стратегия качества | рубрика 0–4 |
| `security.lead.authz_policy_fix` | choose_fix | Lead | политика доступа с делегированием и блокировками | Python, сценарии |
| `security.lead.key_rotation_mcq` | mcq_concept | Lead | ротация ключа подписи токенов без отказов | модель кэшей |
| `security.lead.token_length_mcq` | mcq_concept | Lead | длина токена против распределённого многоцелевого подбора | целочисленный поиск |
| `security.lead.design_review_open` | open_answer | Lead | ревью дизайна обмена документами | рубрика 0–4 |
| `security.principal.fix_order_mcq` | mcq_concept | Principal | очерёдность исправления по ожидаемому ущербу | перебор 120 порядков |
| `security.principal.architecture_review_open` | open_answer | Principal | ревью многоарендной платформы | рубрика 0–4 |
| `security.principal.security_strategy_open` | open_answer | Principal | стратегия безопасности | рубрика 0–4 |
| `mobile.lead.sync_rebase_fix` | choose_fix | Lead | офлайн-синхронизация, конфликты по полям | Node, 8 сценариев |
| `mobile.lead.api_sunset_mcq` | mcq_concept | Lead | отключение старого API при хвосте версий | расчёт |
| `mobile.lead.startup_path_mcq` | mcq_concept | Lead | холодный старт: критический путь до первого кадра | граф зависимостей |
| `mobile.lead.design_review_open` | open_answer | Lead | ревью дизайна ленты | рубрика 0–4 |
| `mobile.principal.rollout_segments_mcq` | mcq_concept | Principal | выкатка по сегментам: интервал доли сбоев против порога | интервал Уилсона |
| `mobile.principal.architecture_review_open` | open_answer | Principal | ревью мультибрендового приложения | рубрика 0–4 |
| `mobile.principal.mobile_strategy_open` | open_answer | Principal | мобильная стратегия | рубрика 0–4 |
| `analyst.lead.state_model_bug` | find_bug | Lead | модель состояний: обход повторного одобрения | модель на Python |
| `analyst.lead.metric_definition_fix` | choose_fix | Lead | определение конверсии когорты в запросе дашборда | SQLite |
| `analyst.lead.sla_chain_mcq` | mcq_concept | Lead | доступность операции по цепочке, самое дешёвое достаточное | расчёт |
| `analyst.lead.spec_review_open` | open_answer | Lead | ревью спецификации интеграции | рубрика 0–4 |
| `analyst.principal.launch_effect_mcq` | mcq_concept | Principal | эффект запуска: разность разностей внутри сегментов | точные дроби |
| `analyst.principal.target_architecture_review_open` | open_answer | Principal | ревью целевой архитектуры единого профиля | рубрика 0–4 |
| `analyst.principal.analyst_strategy_open` | open_answer | Principal | стратегия системного анализа | рубрика 0–4 |

Тесты — `tests/test_lead_principal_b.py` (состав, имена и уровни, диапазон b, рубрики 0–4 с цитатами, ≥ 20
различимых вариантов, защита от угадывания по форме).

### Короткие Principal: qa, security, mobile, analyst (волна 10, 11.10)

19 семейств — qa 5, security 4, mobile 5, analyst 5; файлы `<направление>/principal_*_mcq.py`, `target_grades: [principal]`,
формат `mcq_concept`, `time_limit_s` ≤ 420 (короткое задание для блока Principal). Трудность — априорная
(`prior_difficulty.basis` «Априорная трудность (не по людям)…»): b 2,5–2,6, a 1,3–1,4; калибровки нет — уточнится
общим прогоном панели. Общий помощник — `families/_principal_c_utils.py` (форматы подписей, подбор ловушек по
обе стороны ключа, обёртки над `_lead_b_utils.computed_mcq`).

* **Числовые** — ключ печатает программа по тем же числам, что видит кандидат (точные дроби, перебор,
  численное интегрирование); дистракторы — модели типичных ошибок, сколько ловушек меньше ключа — по seed
  равновероятно, подписи одной длины и формы, значения не у границы округления, отрыв от ключа ≥ 3–10 %.
* **Выбор решения** (`gate_threshold`, `min_os`, `hotfix_policy`, `pilot_value`, `delay_order`) — программа
  перебирает решения и печатает лучшее; какое решение верное — по seed поровну (числа подбираются под него),
  отрыв от второго не меньше 5 %.

| Семейство | Содержание | Проверка ключа |
|---|---|---|
| `qa.principal.escape_origin_mcq` | доля дефектов, дошедших до эксплуатации, после усиления одного этапа конвейера | точные дроби по этапам |
| `qa.principal.release_evidence_mcq` | сколько релизов без инцидента подтверждают цель с заданной уверенностью | целочисленный поиск |
| `qa.principal.gate_threshold_mcq` | порог остановки выкатки по числу упавших нестабильных тестов | перебор порогов |
| `qa.principal.scaleout_nodes_mcq` | число узлов под пик по нагрузочному тесту (модель Амдала из измерений) | бисекция + перебор N |
| `qa.principal.hidden_defects_mcq` | сколько дефектов ещё не найдено: две независимые команды, слои с разной находимостью | множества по слоям, точные дроби |
| `security.principal.attack_path_shift_mcq` | вероятность успеха атакующего после закрытия одного пути в дереве атак | обход дерева, точные дроби |
| `security.principal.control_overlap_mcq` | чистая выгода пакета мер поверх действующей при перекрывающемся покрытии атак | точные дроби по исходам |
| `security.principal.log_retention_mcq` | минимальный срок хранения журналов под нужную долю расследуемых вторжений | интегрирование (Симпсон) |
| `security.principal.patch_waves_mcq` | ожидаемое число взломанных серверов при выкатке исправления волнами | интегрирование (Симпсон) |
| `mobile.principal.crash_users_mcq` | доля пользователей без сбоев при цели по сессиям и неоднородной активности | точные дроби по сегментам |
| `mobile.principal.min_os_mcq` | до какой версии ОС поднять минимальную поддерживаемую | перебор версий |
| `mobile.principal.sync_conflict_mcq` | ожидаемое число конфликтов офлайн-синхронизации в сутки | ряд Тейлора, точные дроби |
| `mobile.principal.hotfix_policy_mcq` | политика выпусков: частота поезда и срочные выпуски по стоимости в месяц | расчёт по политикам |
| `mobile.principal.kill_switch_mcq` | за сколько часов флаг аварийного отключения дойдёт до доли пользователей (кэш + запуски) | Симпсон + бисекция |
| `analyst.principal.delay_order_mcq` | порядок инициатив одной команды по стоимости задержки | перебор 24 порядков |
| `analyst.principal.metric_tree_mcq` | общий прирост выручки от инициатив на разных ветвях дерева метрик | точные дроби по сегментам |
| `analyst.principal.payback_cohort_mcq` | месяц окупаемости привлечения по кривой удержания когорты | помесячная модель когорты |
| `analyst.principal.pilot_value_mcq` | запуск сразу, пилот или закрытие — ценность информации | дерево решений, точные дроби |
| `analyst.principal.profile_merge_mcq` | уникальные клиенты в едином профиле: дубли, точность и полнота сопоставления | точные дроби |

Тесты — `tests/test_principal_c.py` (состав по направлениям, спецификация и короткий лимит, ключ исполнением,
≥ 20 различимых вариантов, защита от угадывания по форме и по рангу значения, нет пересечения с исходными 165);
семейства попадают и в общие проверки `tests/test_lead_principal_b.py`.

## Что проверяет валидатор

На каждом семействе (по умолчанию 200 seed): детерминизм (повторная генерация и отдельный
процесс с другим `PYTHONHASHSEED`); уникальность вариантов (FAIL < 90 %, WARN < 98 %;
для open_answer — не меньше 40 различных формулировок); поверхностное разнообразие
(средняя дистанция Жаккара, число контекстов, доля самого частого); равномерность позиции
правильного ответа (χ²); соблюдение инвариантов (`code_lines`, `operations`,
`defect_type`, число вариантов ответа); структурные правила форматов (для find_bug —
исправление меняет ровно строку ключа, строки из `accept` подтверждены `alt_fixes`); проверку ключа
исполнением нашего кода в песочнице. Отчёт — `reports/validation_report.{md,json}`.

Песочница: отдельные процессы с лимитами CPU/памяти/файлов/дескрипторов, своя группа
процессов, таймаут, временный каталог; для Python — аудит-хук, запрещающий сеть,
запуск процессов и удаление файлов; для Node — отдельные `vm`-контексты; git запускается
в одноразовом репозитории с фиксированными автором и датами. Исполняется только код
генераторов банка; код и ответы кандидатов не исполняются никогда.

## Психометрика (`assessment_bank.psychometrics`)

* `irt` — Раш и 2PL: оценка параметров по матрице ответов (MML-EM с априорными), θ и SE
  (EAP/MAP/MLE), информация, согласие (infit/outfit, точечно-бисериальная корреляция);
* `hierarchical` — параметры семейства (μ, a) + разброс вариантов σ; эффективный наклон
  нового варианта `a/√(1+(aσ/1.702)²)`; флаг неизоморфности при σ > 0,5;
* `cat` — выбор следующего задания по максимуму информации, баланс общего блока (40 %),
  Sympson–Hetter, субпулы (змейкой по трудности), канарейки на позициях 2, 6, 10,
  остановка по SE ≤ 0,35 (мин. 8, макс. 20 заданий, лимит 90 мин) — по умолчанию; по выбору — классификация по
  грейду (`stop_rule="classification"`: стоп, когда ни один порог не в θ̂ ± z·SE; `select_at="cut"` — информация в
  неопределённом пороге) и дотестирование у ближайшего порога (`ext_items`, `ext_time_s`, `ext_own_first`;
  `exclude_ext` — семейства прошлой попытки, `blocked_subpools` — карантин);
* `grading` — пороги θ (предварительно: Junior −1,0; Middle 0,0; Senior 1,0),
  подтверждение заявленного грейда при P(θ ≥ порога) ≥ 0,8, без принудительного понижения;
* `preknowledge` — модель времени (лог-нормальная) и детектор: аномально быстрые и
  верные ответы на канарейках; порог калибруется по честной популяции под заданный FPR;
* `serving.SeedServer` — ротация субпулов, не более 3 показов варианта, карантин;
  канарейки выдаются только из опубликованных seed.

## Симуляция (`assessment_bank.simulation`, `make simulate`)

Синтетическая популяция θ ~ N(0, 1) и синтетическая «истина» параметров (предкалибровка + сдвиг эксперта σ = 0,5):
проверка механики теста (оценивание, остановка, калибровка на пилоте, детектор, ротация), не людей.
`python -m assessment_bank simulate --n 1000 --seed 20261005 --worlds 10 --jobs 4 --out reports`.

* **Потоки случайных чисел по ключу (с 09.10, `rng: keyed-v1` в отчёте).** Истина семейства — из потока
  `(seed, "truth", family_id)`, популяция, пилот и каждый кандидат каждого сценария — из своих потоков. Добавление или
  вывод семейства меняет только его самого; семейства backend не двигают frontend (тест `test_simulation_streams.py`).
  До 09.10 весь прогон шёл одним генератором по порядку: вставка `backend.java.session_registry_leak_fix` и новые
  лимиты времени трёх семейств common (08.10) перетасовали истину следующих семейств, популяции и пилот frontend
  (backend идёт первым и расходует тот же генератор), и «решение верно» frontend/calibrated_cat в отчёте
  упало 0,783 → 0,709 без единой правки во frontend (бисекция по входам симуляции 09.10: в том мире среднее θ
  пилота frontend было +0,142, калибровка сдвинула трудности на −0,145, смещение θ̂ −0,142).
* **Разброс по мирам (`--worlds`).** Таблицы отчёта — один мир (seed). Отдельная таблица — среднее, SD, мин и макс
  prior_cat и calibrated_cat по независимым мирам (своя истина, популяция и пилот N = 300). Главный источник разброса
  calibrated_cat — масштаб пилота: среднее θ 300 участников отклоняется от 0 на ±0,06 (SE), калибровка переносит это
  в смещение θ̂, а правило подтверждения P(θ ≥ порога) ≥ 0,8 — в долю ложных отказов. Разница версий банка в одном
  мире меньше двух SD разброса миров — не свойство банка.
* Параметры `calibration/params_current.json` симуляция не читает: пул строится по `prior_difficulty` из YAML
  (как и выдача платформы), калиброванный пул — по синтетическому пилоту.

## Модель угроз и ограничения

* Код банка открыт (MIT): генераторы и шаблоны известны всем. Защита держится на
  числе вариантов, ротации субпулов, квоте показа и детекторе, а не на секретности кода.
* `predict_output` уязвим к запуску кода и к подсказкам языковых моделей; поэтому вес
  таких заданий ограничен, а Senior-грейд опирается на open_book_3step и open_answer.
* Канарейки опубликованы намеренно; их ответы в грейд не входят.
* Параметры трудности — экспертная предкалибровка; до калибровки на пилоте грейды
  предварительные. Пороги грейдов требуют процедуры установления (standard setting).
