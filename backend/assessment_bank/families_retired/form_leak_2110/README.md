# Семейства, выведенные из выдачи 21.10.2026: ключ узнаётся по форме варианта

Решение оркестратора 21.10 (до заморозки банка для итоговых цифр). Причина — атака «решатель без знаний, изучивший открытый код или уже видевший семейство» (`tools/bank_position_attack.py`: обучение на 100 случайных зёрнах из диапазона выдачи, проверка на других): по длине или тексту варианта (цифры заменены на #), отдельно или в паре с буквой и сюжетом. Обычно это choose_fix с одним и тем же правильным исправлением (меняются только числа и имена) и концептуальные mcq с постоянной формулировкой ключа. Универсальное правило без изучения семейства не работает («самый длинный» — 19,6 %, «самый короткий» — 18,6 % при шансе 25 % по всем choose_fix), поэтому это вопрос утечкоустойчивости, а не угадывания.

Реестр читает только `families/*/*.yaml` — эти семейства не попадают ни в тест, ни в симуляцию, ни в валидатор. Генераторы сохранены без правок содержания (изменён только путь `generator:`). План — переделка: несколько верных форм исправления и формулировок на семейство, ранг длины ключа по зерну; затем возврат.

Правило отбора (порог фиксируется до применения, канарейки не трогаются; после каждого раунда атака перемеряется на новых зёрнах другим ключом):
- Раунд 1: `python3 tools/bank_retire_form_leak.py --attack <json> --threshold 0.9` (прогон атаки: `/tmp/pos_after_rp.json`) — выведено 48.
- Раунд 2: `python3 tools/bank_retire_form_leak.py --attack <json> --threshold 0.75` (прогон атаки: `docs/bank/position_attack_2110f_1413.json`) — выведено 9.

Всего выведено: 57.

| Семейство | Формат | Атака | Угадывание | Шанс | Раунд |
|---|---|---|---|---|---|
| `analyst.lead.metric_definition_fix` | choose_fix | текст варианта | 100 % | 25 % | 1 |
| `analyst.sql.join_fanout_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `analyst.sql.retention_cohort_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `backend.db.keyset_pagination_fix` | choose_fix | текст варианта | 100 % | 25 % | 1 |
| `backend.db.transaction_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `backend.django.on_commit_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `backend.go.map_race_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `backend.java.list_remove_loop_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `backend.java.session_registry_leak_fix` | choose_fix | текст варианта | 100 % | 25 % | 1 |
| `backend.kafka.outbox_relay_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `backend.py.money_rounding_fix` | choose_fix | текст варианта | 100 % | 25 % | 1 |
| `backend.time.add_months_fix` | choose_fix | текст варианта | 100 % | 25 % | 1 |
| `common.ds.lru_cache_fix` | choose_fix | текст варианта | 100 % | 25 % | 1 |
| `common.sql.aggregate_filter_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `data_eng.dwh.lead_scd2_merge_fix` | choose_fix | текст варианта | 98 % | 25 % | 1 |
| `data_eng.dwh.scd2_rerun_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `data_eng.etl.partition_overwrite_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `data_eng.etl.upsert_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `data_ml.ml.purged_split_fix` | choose_fix | текст варианта | 97 % | 25 % | 1 |
| `data_ml.sql.latest_record_fix` | choose_fix | текст варианта | 100 % | 25 % | 1 |
| `data_ml.stats.ztest_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `devops.bash.pipefail_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `frontend.forms.int_validation_fix` | choose_fix | текст варианта | 100 % | 25 % | 1 |
| `frontend.js.abort_fetch_fix` | choose_fix | текст варианта | 100 % | 25 % | 1 |
| `frontend.js.async_foreach_fix` | choose_fix | текст варианта | 100 % | 25 % | 1 |
| `frontend.js.listener_leak_fix` | choose_fix | текст варианта | 100 % | 25 % | 1 |
| `frontend.state.optimistic_rollback_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `mobile.js.deeplink_route_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `mobile.js.double_submit_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `mobile.js.offline_queue_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `mobile.js.token_refresh_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `security.auth.password_storage_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `security.sql.parameter_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `security.supply.dependency_patch_fix` | choose_fix | текст варианта | 100 % | 25 % | 1 |
| `security.web.html_escape_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `security.web.ssrf_allowlist_fix` | choose_fix | длина варианта | 100 % | 25 % | 1 |
| `backend.py.concurrency_mcq` | mcq_concept | текст варианта | 100 % | 25 % | 1 |
| `common.git.move_commits_mcq` | mcq_concept | текст варианта | 100 % | 25 % | 1 |
| `common.git.undo_mcq` | mcq_concept | текст × буква | 90 % | 25 % | 1 |
| `data_ml.metrics.invariance_mcq` | mcq_concept | текст варианта | 100 % | 25 % | 1 |
| `mobile.android.state_survival_mcq` | mcq_concept | длина варианта | 90 % | 25 % | 1 |
| `mobile.ios.appearance_mcq` | mcq_concept | текст варианта | 100 % | 25 % | 1 |
| `mobile.push.fcm_message_mcq` | mcq_concept | текст варианта | 100 % | 25 % | 1 |
| `mobile.security.secret_storage_mcq` | mcq_concept | текст варианта | 100 % | 25 % | 1 |
| `qa.load.percentile_merge_mcq` | mcq_concept | длина варианта | 100 % | 25 % | 1 |
| `qa.triage.severity_priority_mcq` | mcq_concept | сюжет × текст | 97 % | 25 % | 1 |
| `security.web.cookie_policy_mcq` | mcq_concept | длина варианта | 100 % | 25 % | 1 |
| `security.web.cors_csrf_mcq` | mcq_concept | текст варианта | 100 % | 25 % | 1 |
| `backend.arch.principal_retry_policy_fix` | choose_fix | текст варианта | 84 % | 25 % | 2 |
| `common.api.rest_idempotent_retry_fix` | choose_fix | буква × длина | 77 % | 25 % | 2 |
| `common.docker.cache_order_fix` | choose_fix | текст варианта | 82 % | 25 % | 2 |
| `data_ml.fe.onehot_serving_fix` | choose_fix | длина варианта | 77 % | 25 % | 2 |
| `qa.sql.reconciliation_fix` | choose_fix | текст варианта | 86 % | 25 % | 2 |
| `analyst.api.idempotency_contract_mcq` | mcq_concept | текст варианта | 88 % | 25 % | 2 |
| `analyst.req.acceptance_scenario_mcq` | mcq_concept | текст варианта | 81 % | 25 % | 2 |
| `mobile.kotlin.flow_lifecycle_mcq` | mcq_concept | текст варианта | 83 % | 25 % | 2 |
| `mobile.principal.rollout_segments_mcq` | mcq_concept | текст варианта | 83 % | 25 % | 2 |
