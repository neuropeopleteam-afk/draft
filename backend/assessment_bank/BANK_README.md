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
pydantic 2.9.2 (MIT), PyYAML 6.0.2 (MIT), pytest 8.3.3 (MIT), Django 5.2.17 (BSD — только для
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
| `direction` | common, backend, frontend, data_ml, qa, security |
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
| `backend.java.session_registry_leak_bug` | find_bug | утечка через долгоживущую коллекцию (`get` вместо `remove`) | JVM: реестр пуст после закрытия. **Выведено из выдачи 07.10 по калибровке** (ключ плохо определён для формата find_bug; p 0,03, a 0,62) — см. `families_retired/README.md` |
| `backend.java.gc_reachability_mcq` | mcq_concept | сколько объектов доступны для сборки мусора | модель достижимости (обход ссылок от переменных). **Выведено из выдачи 07.10 по калибровке** (p 0,23 ≈ шанс, σ 1,88) — см. `families_retired/README.md` |
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

### Правки по флагам панели 06.10 (версии 2)

`qa.js.brittle_render_fix` и `common.text.utf8_truncate_fix` — фиксированный состав дистракторов;
`qa.triage.severity_priority_mcq` — только квадранты, где серьёзность и приоритет расходятся;
`qa.load.percentile_merge_mcq` — выбор метода вместо многошагового расчёта. Перекалибровка 07.10
(`panel_20261007_ext3`): `percentile_merge_mcq` — флагов нет (b −0,53, a 1,78); `severity_priority_mcq` —
лучше, но σ 0,59 остаётся; `brittle_render_fix` и `utf8_truncate_fix` флаги не сняли.

### Выведены из выдачи 07.10 по итогам калибровки

Четыре семейства перенесены в `assessment_bank/families_retired/` (реестр их не читает; после переноса в выдаче
осталось 162 семейства): `backend.java.session_registry_leak_bug` (ключ плохо определён для формата find_bug: дефект —
пропуск `remove`; p 0,03, отрицательная дискриминация), `backend.java.gc_reachability_mcq` (p 0,23 ≈ шанс,
σ между вариантами 1,88), `common.text.utf8_truncate_fix` (вторая панель подряд: b 3,69, a 0,44),
`qa.js.brittle_render_fix` (решается «в лоб», σ 1,04, 3B лучше 32B). Продукт выдаёт задания по
`prior_difficulty` из YAML, где эти семейства стояли у порогов Junior/Middle с a ≈ 1 — то есть CAT выбирал их
как самые информативные, а по данным они шум. Покрытие Java: 5 → 3 семейства (одно уровня Junior); тем же днём
добавлены два простых Java-семейства с бесспорным ключом — `backend.java.string_equals_bug` (Стажёр/Junior, find_bug)
и `backend.java.list_remove_loop_fix` (Junior/Middle, choose_fix с исполнением всех вариантов) — итого **164** семейства
в выдаче, Java — 5. Новые семейства выдаются по prior из YAML до перекалибровки (`calibration/rerun_new.py`).
Цифры, причины и план переделки — `assessment_bank/families_retired/README.md`;
`calibration/params_current.json` не менялся (история измерений).

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

## Модель угроз и ограничения

* Код банка открыт (MIT): генераторы и шаблоны известны всем. Защита держится на
  числе вариантов, ротации субпулов, квоте показа и детекторе, а не на секретности кода.
* `predict_output` уязвим к запуску кода и к подсказкам языковых моделей; поэтому вес
  таких заданий ограничен, а Senior-грейд опирается на open_book_3step и open_answer.
* Канарейки опубликованы намеренно; их ответы в грейд не входят.
* Параметры трудности — экспертная предкалибровка; до калибровки на пилоте грейды
  предварительные. Пороги грейдов требуют процедуры установления (standard setting).
