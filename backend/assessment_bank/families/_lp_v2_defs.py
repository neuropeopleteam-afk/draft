"""Содержательные семейства старших грейдов (Senior / Lead / Principal) — волна LP-v2 (320 семейств, 0 % MCQ).

Для каждого из 10 направлений определены 32 параметрических семейства:
* 6 семейств ``find_bug`` (поиск тонкого дефекта конкурентности/консистентности/кворума/водяных знаков в коде);
* 8 семейств ``choose_fix`` (выбор корректного патча из 4 вариантов кода с проверкой в песочнице);
* 6 семейств ``predict_output`` (предсказание результата работы распределённого/транзакционного алгоритма);
* 4 семейства ``open_book_3step`` (3 шага: воспроизведение сбоя → выбор исправления → архитектурный разбор по рубрике);
* 4 семейства ``incident_sim`` (интерактивный симулятор инцидента с телеметрией, логами и 3 оцениваемыми шагами);
* 4 семейства ``open_answer`` (архитектурный RFC / разбор компромиссов с многокритериальной рубрикой).

Все кодовые и трёхшаговые семейства проверяются исполнением (``verification="execution"``) в песочнице Python.
Априорная дискриминативность: ``a = 1.3``, ``basis = "Априорная, до калибровки на людях: ..."``.
"""
from __future__ import annotations

from typing import Any

from assessment_bank.gen_utils import (
    LETTERS,
    build_variant,
    changed_lines,
    make_rng,
    ob3_steps,
    py_harness,
    rubric_from,
)
from assessment_bank.schema import AnswerKey, Check, Option, Variant


def _stratified_options(
    rng,
    slot_idx: int,
    seed: int,
    correct: tuple[str, str | None],
    distractors: list[tuple[str, str | None]],
    step: int | None = None,
) -> tuple[list[Option], str]:
    n_tot = 1 + len(distractors)
    key_idx = (slot_idx * 3 + seed + (step or 0) * 2) % n_tot
    dists = list(distractors)
    rng.shuffle(dists)
    opts: list[Option] = []
    di = 0
    for i in range(n_tot):
        if i == key_idx:
            opts.append(Option(id=LETTERS[i], text=correct[0], code=correct[1], step=step))
        else:
            t, c = dists[di]
            di += 1
            opts.append(Option(id=LETTERS[i], text=t, code=c, step=step))
    return opts, LETTERS[key_idx]


_IDENT_POOLS = [
    ("store_map", "rec_item", "cur_ver", "batch_seq", "node_alpha", "основной контур"),
    ("ledger_tbl", "slot_row", "epoch_id", "window_id", "replica_west", "ядро обработки"),
    ("state_dict", "entry_val", "fence_num", "frame_idx", "shard_north", "контур шлюза"),
    ("registry_db", "item_rec", "token_gen", "slice_no", "worker_east", "узел агрегации"),
    ("cache_index", "bucket_el", "term_no", "step_seq", "broker_south", "сегмент витрины"),
    ("journal_map", "tx_record", "stamp_ver", "round_id", "cell_prime", "модуль маршрутизации"),
    ("vault_table", "claim_row", "seq_fence", "tick_num", "node_delta", "кластер синхронизации"),
    ("buffer_hash", "lease_obj", "gen_clock", "wave_idx", "peer_omega", "тракт репликации"),
]

DIRECTIONS: tuple[str, ...] = (
    "common", "backend", "frontend", "data_ml", "data_eng",
    "devops", "qa", "security", "mobile", "analyst",
)

DIR_META: dict[str, dict[str, Any]] = {
    "common": {
        "ru": "Общеинженерный контур",
        "skills": ["algorithms", "sql", "http", "python", "asyncio"],
        "services": [
            ("платформа расчётов", "core-ledger", "транзакции клиринга"),
            ("шлюз событий", "event-router", "пакеты телеметрии"),
            ("сервис квот", "quota-guard", "лимиты вызовов API"),
            ("диспетчер задач", "job-scheduler", "фоновые воркеры"),
            ("реестр конфигураций", "config-hub", "снимки настроек"),
            ("контур сверки", "reconcile-svc", "проводки за сутки"),
            ("агрегатор метрик", "metrics-rollup", "временные ряды"),
            ("оркестратор пайплайнов", "flow-engine", "шаги графа задач"),
            ("кэш метаданных", "meta-cache", "ключи маршрутизации"),
            ("шлюз вебхуков", "webhook-edge", "входящие уведомления"),
        ],
    },
    "backend": {
        "ru": "Backend-разработка",
        "skills": ["fastapi", "postgresql", "asyncio", "rest_api", "caching", "distributed_systems", "reliability"],
        "services": [
            ("биллинг подписок", "billing-api", "списания по картам"),
            ("сервис заказов", "order-core", "резервы склада"),
            ("шлюз выплат СБП", "payout-gw", "переводы мерчантам"),
            ("сервис корзины", "cart-engine", "позиции заказа"),
            ("процессинг возвратов", "refund-worker", "обратные транзакции"),
            ("сервис тарификации", "tariff-calc", "квоты клиентов"),
            ("каталог остатков", "inventory-svc", "остатки по дарксторам"),
            ("сервис уведомлений", "notify-hub", "очередь писем и пушей"),
            ("контур бронирования", "booking-api", "слоты расписания"),
            ("сервис лояльности", "bonus-ledger", "начисления баллов"),
        ],
    },
    "frontend": {
        "ru": "Frontend-разработка",
        "skills": ["javascript", "typescript", "react", "state_management", "web_performance", "accessibility"],
        "services": [
            ("веб-терминал торгов", "trade-ui", "котировки стакана"),
            ("редактор дашбордов", "canvas-app", "виджеты аналитики"),
            ("витрина маркетплейса", "catalog-spa", "фильтры выдачи"),
            ("личный кабинет банка", "ib-portal", "история операций"),
            ("система видеозвонков", "meet-client", "потоки участников"),
            ("конструктор форм", "form-studio", "шаги анкеты"),
            ("карта курьерской доставки", "fleet-map", "треки курьеров"),
            ("клиент мессенджера", "chat-web", "лента сообщений"),
            ("панель мониторинга", "ops-console", "графики алертов"),
            ("витрина авиабилетов", "travel-search", "варианты перелётов"),
        ],
    },
    "data_ml": {
        "ru": "Аналитика данных и ML",
        "skills": ["statistics", "pandas", "scikit-learn", "cross_validation", "mlops", "data_drift", "rag"],
        "services": [
            ("антифрод-скоринг", "fraud-scorer", "признаки транзакций"),
            ("ранжирование поиска", "ranker-srv", "векторы запросов"),
            ("прогноз спроса", "demand-ml", "ряды продаж"),
            ("кредитный конвейер", "credit-risk", "анкеты заёмщиков"),
            ("динамическое ценообразование", "surge-price", "коэффициенты спроса"),
            ("рекомендательная лента", "recsys-api", "эмбеддинги товаров"),
            ("RAG-ассистент поддержки", "rag-router", "чанки базы знаний"),
            ("модель оттока клиентов", "churn-eval", "когорты удержания"),
            ("платформа A/B-экспериментов", "ab-stats", "метрики вариантов"),
            ("детектор дрейфа признаков", "drift-watch", "распределения фичей"),
        ],
    },
    "data_eng": {
        "ru": "Инженерия данных",
        "skills": ["etl", "dwh", "spark", "airflow", "streaming", "clickhouse", "data_quality"],
        "services": [
            ("CDC-репликация заказов", "cdc-ingest", "события binlog"),
            ("стриминг кликстрима", "click-stream", "сессии пользователей"),
            ("витрина финансовой сверки", "fin-mart", "проводки главной книги"),
            ("конвейер телеметрии IoT", "iot-lake", "пакеты датчиков"),
            ("агрегатор рекламных показов", "ad-attribution", "события конверсий"),
            ("хранилище feature store", "feast-sync", "срезы признаков"),
            ("компакция Iceberg-таблиц", "lake-compact", "паркет-сегменты"),
            ("оркестратор ночных витрин", "dwh-dag", "инкрементальные батчи"),
            ("контроль качества данных", "dq-gate", "правила полноты"),
            ("индексатор логов безопасности", "siem-etl", "партиции ClickHouse"),
        ],
    },
    "devops": {
        "ru": "DevOps и SRE",
        "skills": ["kubernetes", "sre", "monitoring", "terraform", "ci_cd", "nginx", "networking"],
        "services": [
            ("ingress-контур кластера", "edge-ingress", "маршруты апстримов"),
            ("контроллер автоскейлинга", "hpa-controller", "реплики подов"),
            ("агент сбора метрик", "prom-scraper", "таргеты телеметрии"),
            ("оператор баз данных", "pg-operator", "реплики кластера"),
            ("конвейер канарских выкладок", "argo-rollout", "веса трафика"),
            ("балансировщик межсетевого трафика", "l4-lb", "пулы узлов"),
            ("система ротации секретов", "vault-sync", "динамические токены"),
            ("контроллер квот неймспейсов", "ns-quota", "лимиты CPU и памяти"),
            ("агрегатор распределённых трейсов", "otel-collector", "спаны запросов"),
            ("оркестратор резервных копий", "velero-backup", "снимки томов"),
        ],
    },
    "qa": {
        "ru": "Обеспечение качества (QA)",
        "skills": ["test_design", "pytest", "api_testing", "load_testing", "test_architecture", "contract_testing"],
        "services": [
            ("стенд контрактного тестирования", "pact-verifier", "схемы потребителей"),
            ("генератор нагрузочного профиля", "k6-runner", "виртуальные пользователи"),
            ("оркестратор регрессионных прогонов", "test-grid", "шарды тестового набора"),
            ("детектор нестабильных тестов", "flaky-guard", "история перезапусков"),
            ("сервис синтетических транзакций", "synth-probe", "проверки сценариев"),
            ("валидатор миграций схемы", "schema-check", "дампы совместимости"),
            ("прокси записи моков", "wiremock-hub", "снимки ответов API"),
            ("анализатор покрытия ветвей", "cov-gate", "диффы пул-реквестов"),
            ("ферма мобильных эмуляторов", "device-farm", "сессии автотестов"),
            ("аудитор SLA ответов", "sla-assert", "квантили латентности"),
        ],
    },
    "security": {
        "ru": "Информационная безопасность",
        "skills": ["secure_code_review", "authorization", "aead", "token_validation", "incident_response", "threat_modeling"],
        "services": [
            ("шлюз проверки JWT-токенов", "auth-verify", "ключи подписи JWKS"),
            ("сервис отзыва сессий", "revoke-list", "идентификаторы токенов"),
            ("WAF-фильтр API", "waf-inspect", "правила сигнатур"),
            ("менеджер ключей шифрования", "kms-rotator", "версии мастер-ключей"),
            ("аудитор прав доступа RBAC", "IAM-policy", "матрицы разрешений"),
            ("детектор брутфорс-атак", "rate-shield", "счётчики попыток входа"),
            ("валидатор вебхук-подписей", "hmac-guard", "заголовки времени и nonce"),
            ("коррелятор инцидентов SIEM", "soc-engine", "цепочки событий"),
            ("шлюз изоляции тенантов", "tenant-fence", "контексты организаций"),
            ("сканер секретов в артефактах", "secret-scan", "слои контейнеров"),
        ],
    },
    "mobile": {
        "ru": "Мобильная разработка",
        "skills": ["architecture", "kotlin_coroutines", "swift_concurrency", "offline_first", "ui_threading", "networking"],
        "services": [
            ("модуль офлайн-синхронизации", "sync-engine", "очередь локальных мутаций"),
            ("менеджер фоновой загрузки", "bg-transfer", "чанки медиафайлов"),
            ("кэш изображений ленты", "image- pipeline", "кадры предпросмотра"),
            ("координатор навигации", "nav-router", "диплинки экранов"),
            ("обновление токена сессии", "token-refresh", "параллельные запросы API"),
            ("локальное хранилище профиля", "room-store", "миграции схемы БД"),
            ("трекер геопозиции курьера", "geo-tracker", "пакеты координат"),
            ("обработчик push-уведомлений", "push-handler", "идемпотентные события"),
            ("плеер потокового видео", "media-buffer", "сегменты предзагрузки"),
            ("витрина каталога с пагинацией", "paged-feed", "страницы курсора"),
        ],
    },
    "analyst": {
        "ru": "Системный и бизнес-анализ",
        "skills": ["requirements", "api_contracts", "bpmn", "er_modeling", "state_machines", "product_analytics"],
        "services": [
            ("конечный автомат заявки на кредит", "loan-fsm", "переходы статусов"),
            ("контракт межсистемного обмена", "order-contract", "версии схемы событий"),
            ("матрица бизнес-правил скидок", "promo-rules", "условия комбинирования"),
            ("оркестратор BPMN-процесса возврата", "refund-bpmn", "компенсирующие задачи"),
            ("модель расчёта SLA поддержки", "sla-calendar", "рабочие окна эскалации"),
            ("реестр согласий 152-ФЗ", "consent-model", "цели обработки данных"),
            ("контур сверки взаиморасчётов", "clearing-spec", "акты расхождений"),
            ("спецификация лимитов антифрода", "limit-matrix", "пороги операций"),
            ("воронка онбординга мерчантов", "kyc-funnel", "шаги верификации"),
            ("модель квотирования ресурсов", "quota-spec", "приоритеты тарифов"),
        ],
    },
}

# 32 слота на каждое направление:
# (slot_idx, slug, format, target_grades, b_base, time_limit_s, defect_or_topic, title_ru)
SLOT_SPECS: list[tuple[int, str, str, list[str], float, int, str, str]] = [
    # 0..5: find_bug (6)
    (0, "cas_epoch_fence_bug", "find_bug", ["senior", "lead"], 1.72, 360, "stale_epoch_boundary",
     "Потеря монотонности fencing-токена при оптимистичной записи"),
    (1, "sliding_budget_evict_bug", "find_bug", ["senior", "lead"], 1.84, 360, "window_eviction_leak",
     "Утечка веса при вытеснении устаревших событий из скользящего окна"),
    (2, "quorum_ack_dedup_bug", "find_bug", ["lead"], 1.98, 420, "duplicate_quorum_ack",
     "Ложный кворум из-за подсчёта повторных подтверждений от одного узла"),
    (3, "half_open_probe_gate_bug", "find_bug", ["lead"], 2.14, 420, "half_open_race",
     "Лавина пробных запросов в полуоткрытом состоянии предохранителя"),
    (4, "saga_lifo_compensate_bug", "find_bug", ["principal"], 2.78, 420, "compensation_order",
     "Нарушение обратного порядка компенсаций при откате распределённой саги"),
    (5, "watermark_late_admission_bug", "find_bug", ["principal"], 3.08, 420, "watermark_off_by_one",
     "Потеря граничного события на стыке водяного знака и допустимого опоздания"),

    # 6..13: choose_fix (8)
    (6, "idempotent_claim_lease_fix", "choose_fix", ["senior", "lead"], 1.76, 360, "idempotency_lease_race",
     "Атомарный захват ключа идемпотентности с перехватом просроченного лиза"),
    (7, "capped_backoff_budget_fix", "choose_fix", ["senior", "lead"], 1.88, 360, "retry_budget_overflow",
     "Ограничение экспоненциальной паузы повторов с контролем общего дедлайна"),
    (8, "consistent_ring_wrap_fix", "choose_fix", ["lead"], 2.04, 420, "ring_wraparound",
     "Замыкание кольца консистентного хэширования с пропуском выведенных узлов"),
    (9, "keyset_tiebreaker_cursor_fix", "choose_fix", ["lead"], 2.20, 420, "cursor_tie_loss",
     "Курсорная пагинация без потери записей с совпадающей меткой времени"),
    (10, "singleflight_stale_fallback_fix", "choose_fix", ["lead", "principal"], 2.52, 420, "cache_stampede_fallback",
     "Подавление шторма пересчёта кэша с возвратом устаревшего значения при сбое"),
    (11, "outbox_atomic_reclaim_fix", "choose_fix", ["principal"], 2.84, 420, "outbox_stuck_lease",
     "Повторный захват зависших сообщений transactional outbox без дублей"),
    (12, "causal_vector_barrier_fix", "choose_fix", ["principal"], 3.02, 420, "causal_order_violation",
     "Проверка причинной готовности сообщения по векторным часам от всех узлов"),
    (13, "hierarchical_tenant_quota_fix", "choose_fix", ["principal"], 3.22, 420, "priority_quota_starvation",
     "Двухуровневое квотирование: лимит тенанта и защищённый резерв критичного трафика"),

    # 14..19: predict_output (6)
    (14, "token_bucket_refill_trace_out", "predict_output", ["senior", "lead"], 1.80, 360, "token_bucket_state",
     "Трассировка корзины токенов с дробным пополнением и потолком всплеска"),
    (15, "mvcc_snapshot_visibility_out", "predict_output", ["lead"], 1.96, 420, "mvcc_visibility",
     "Видимость версий строк при чтении снимка MVCC с активными транзакциями"),
    (16, "lsm_tombstone_compaction_out", "predict_output", ["lead"], 2.16, 420, "lsm_compaction",
     "Слияние уровней LSM-дерева с удержанием маркеров удаления до горизонта снимка"),
    (17, "raft_election_quorum_out", "predict_output", ["lead", "principal"], 2.56, 420, "raft_log_completeness",
     "Отбор лидера по актуальности журнала (term, длина) и подсчёт кворума голосов"),
    (18, "p2c_latency_ewma_dispatch_out", "predict_output", ["principal"], 2.88, 420, "load_balancing_ewma",
     "Балансировка по эффективной цене узла (активные запросы × штраф латентности)"),
    (19, "ssi_rw_conflict_abort_out", "predict_output", ["principal"], 3.16, 420, "ssi_rw_cycle",
     "Детектирование цикла rw-антизависимостей при сериализуемой изоляции снимков"),

    # 20..23: open_book_3step (4)
    (20, "split_brain_lease_ob3", "open_book_3step", ["lead"], 2.02, 600, "lease_split_brain",
     "Рассинхронизация лидера при паузе процесса и истечении аренды (3 шага)"),
    (21, "dual_write_outbox_drift_ob3", "open_book_3step", ["lead"], 2.24, 600, "dual_write_anomaly",
     "Развал консистентности при двойной записи в БД и брокер без outbox (3 шага)"),
    (22, "read_repair_monotonic_ob3", "open_book_3step", ["principal"], 2.82, 720, "non_monotonic_quorum_read",
     "Немонотонное чтение при неполном кворуме и гонке read-repair (3 шага)"),
    (23, "shard_rebalance_epoch_ob3", "open_book_3step", ["principal"], 3.12, 720, "rebalance_epoch_routing",
     "Потеря обновлений во время онлайн-миграции шарда между эпохами (3 шага)"),

    # 24..27: open_book_3step с интерактивным симулятором инцидента (incident_sim: true в invariants.extra и pv["incident"])
    (24, "pool_starvation_cascade_inc", "open_book_3step", ["senior", "lead"], 1.86, 540, "pool_exhaustion_in_tx",
     "Инцидент: исчерпание пула соединений из-за внешнего вызова внутри транзакции"),
    (25, "retry_storm_amplification_inc", "open_book_3step", ["lead"], 2.12, 600, "cascading_retry_storm",
     "Инцидент: каскадный шторм повторов между слоями без бюджета ретраев"),
    (26, "hot_partition_skew_stall_inc", "open_book_3step", ["lead", "principal"], 2.58, 660, "partition_hotkey_skew",
     "Инцидент: деградация p99 из-за перекоса горячего ключа и блокировки очереди"),
    (27, "stale_cache_poison_rollout_inc", "open_book_3step", ["principal"], 2.98, 780, "schema_rollout_cache_poison",
     "Инцидент: отравление общего кэша несовместимой схемой при канарской выкладке"),

    # 28..31: open_answer (4)
    (28, "multi_region_active_active_oa", "open_answer", ["lead"], 2.08, 600, "multi_region_consistency",
     "Архитектурный выбор: перевод контура в геораспределённый режим Active-Active"),
    (29, "zero_downtime_contract_mig_oa", "open_answer", ["lead"], 2.28, 600, "expand_contract_migration",
     "План миграции схемы и контрактов под нагрузкой без окна простоя (Expand-Contract)"),
    (30, "tail_latency_slo_budget_oa", "open_answer", ["principal"], 2.92, 780, "tail_latency_architecture",
     "Системная архитектура удержания p99 в жёстком SLO при десятикратных пиках"),
    (31, "cross_domain_isolation_blast_oa", "open_answer", ["principal"], 3.24, 780, "blast_radius_isolation",
     "Ограничение радиуса поражения (cell-based архитектура и сброс нагрузки)"),
]


def family_id_for(direction: str, slot_idx: int) -> str:
    _, slug, _, grades, *_ = SLOT_SPECS[slot_idx]
    top_g = "principal" if "principal" in grades else "lead"
    return f"{direction}.{top_g}_v2.{slug}"


def module_name_for(slot_idx: int) -> str:
    _, slug, *_ = SLOT_SPECS[slot_idx]
    return f"lp2_{slot_idx:02d}_{slug}"


def yaml_spec_for(direction: str, slot_idx: int) -> dict[str, Any]:
    _, slug, fmt, grades, b_base, tm, defect, title_ru = SLOT_SPECS[slot_idx]
    dm = DIR_META[direction]
    fid = family_id_for(direction, slot_idx)
    mod = module_name_for(slot_idx)
    dir_idx = DIRECTIONS.index(direction)
    b = round(b_base + (dir_idx - 4.5) * 0.015, 2)
    inv: dict[str, Any] = {
        "defect_type": defect,
        "extra": {
            "wave": "LP-v2",
            "slot": slot_idx,
            "direction_ru": dm["ru"],
            **({"incident_sim": True} if 24 <= slot_idx <= 27 else {}),
        },
    }
    if fmt == "choose_fix":
        inv["n_options"] = 4
    elif fmt in ("open_book_3step", "incident_sim"):
        inv["n_options"] = 4
    pr: dict[str, Any] = {
        "b": b,
        "a": 1.3,
        "sigma_variant": 0.25,
        "basis": (
            f"Априорная, до калибровки на людях (a = 1,3, σ = 0,25). "
            f"{dm['ru']}: {title_ru.lower()}; формат {fmt}, целевые грейды {', '.join(grades)} "
            f"(b = {str(b).replace('.', ',')} у порога старшего грейда)."
        ),
    }
    if fmt in ("open_book_3step", "incident_sim"):
        pr["step_offsets"] = [-0.35, 0.0, 0.35]
    lang = "text" if fmt == "open_answer" else "python"
    return {
        "family_id": fid,
        "title": f"{dm['ru']}: {title_ru}",
        "direction": direction,
        "skills": list(dm["skills"][:5]),
        "target_grades": list(grades),
        "format": fmt,
        "language": lang,
        "invariants": inv,
        "time_limit_s": tm,
        "canary": False,
        "prior_difficulty": pr,
        "generator": f"assessment_bank.families.{direction}.{mod}",
        "version": 1,
        "description": f"{dm['ru']} ({', '.join(grades)}): {title_ru}. Проверка исполнением и рубрикой.",
    }


# --------------------------------------------------------------------------- Генераторы по форматам
def _gen_find_bug(fid: str, direction: str, slot_idx: int, seed: int) -> Variant:
    _, slug, _, _grades, _b, _tm, defect, title_ru = SLOT_SPECS[slot_idx]
    dm = DIR_META[direction]
    rng = make_rng(fid, seed)
    svc_ru, svc_id, entity_ru = dm["services"][seed % len(dm["services"])]
    id_p = _IDENT_POOLS[(seed // 2 + slot_idx) % len(_IDENT_POOLS)]
    k = slot_idx  # 0..5
    v_a = 12 + (seed % 113) * 3 + rng.randint(0, 2)
    v_b = 60 + (seed % 127) * 4 + rng.randint(0, 3)
    v_c = rng.randint(3, 9)

    if k == 0:
        buggy = (
            f"def apply_versioned_update(state: dict, key: str, val: int, epoch: int) -> bool:\n"
            f"    cur_val, cur_epoch = state.get(key, (0, {v_a}))\n"
            f"    if epoch < cur_epoch:\n"
            f"        return False\n"
            f"    state[key] = (val, epoch)\n"
            f"    return True"
        )
        fixed = buggy.replace("if epoch < cur_epoch:", "if epoch <= cur_epoch:")
        tests = (
            f"s = {{'k1': (100, {v_b})}}\n"
            f"assert apply_versioned_update(s, 'k1', 200, {v_b}) is False\n"
            f"assert s['k1'] == (100, {v_b})\n"
            f"assert apply_versioned_update(s, 'k1', 300, {v_b + 1}) is True\n"
            f"assert s['k1'] == (300, {v_b + 1})"
        )
        stem = (
            f"В контуре «{svc_ru}» (`{svc_id}`) обновления объекта «{entity_ru}» защищены монотонно растущим "
            f"номером эпохи (`epoch`). Повторная или запоздавшая доставка с уже обработанной эпохой (`epoch <= cur_epoch`) "
            f"должна отклоняться, не перезаписывая состояние. Найдите строку с дефектом."
        )
        expl = "Строка 3 проверяет `epoch < cur_epoch` вместо `epoch <= cur_epoch`, из-за чего пакет с той же эпохой перезаписывает значение."
    elif k == 1:
        buggy = (
            f"def sliding_window_load(events: list[tuple[int, int]], now: int, window: int = {v_b}) -> int:\n"
            f"    active_sum = 0\n"
            f"    cutoff = now - window\n"
            f"    for ts, weight in events:\n"
            f"        if ts >= cutoff and ts <= now:\n"
            f"            active_sum += weight\n"
            f"        elif ts < cutoff:\n"
            f"            active_sum = max(0, active_sum - weight)\n"
            f"    return active_sum"
        )
        fixed = buggy.replace("active_sum = max(0, active_sum - weight)", "continue")
        tests = (
            f"ev = [(10, {v_a}), ({v_b + 20}, {v_c * 10}), (15, {v_a * 2})]\n"
            f"assert sliding_window_load(ev, {v_b + 30}, {v_b}) == {v_c * 10}"
        )
        stem = (
            f"В сервисе «{svc_ru}» (`{svc_id}`) функция считает суммарный вес событий «{entity_ru}», попавших "
            f"в окно `[now - window, now]`. События приходят не по порядку, а старые события (`ts < cutoff`) должны "
            f"просто игнорироваться, не уменьшая накопленную сумму окна. Укажите строку с ошибкой."
        )
        expl = "В строке 8 устаревшее событие, пришедшее после свежего, ошибочно вычитает свой вес из суммы актуального окна вместо пропуска (`continue`)."
    elif k == 2:
        buggy = (
            f"def has_quorum_commit(acks: list[tuple[str, str]], tx_id: str, quorum: int = {v_c}) -> bool:\n"
            f"    matching = [node for node, tid in acks if tid == tx_id]\n"
            f"    if len(matching) >= quorum:\n"
            f"        return True\n"
            f"    return False"
        )
        fixed = buggy.replace("if len(matching) >= quorum:", "if len(set(matching)) >= quorum:")
        tests = (
            f"acks = [('n1', 'tx-{v_a}')] * {v_c} + [('n2', 'tx-{v_a}')]\n"
            f"assert has_quorum_commit(acks, 'tx-{v_a}', {v_c}) is False\n"
            f"acks_ok = [(f'n{{i}}', 'tx-{v_a}') for i in range({v_c})]\n"
            f"assert has_quorum_commit(acks_ok, 'tx-{v_a}', {v_c}) is True"
        )
        stem = (
            f"Координатор «{svc_ru}» (`{svc_id}`) фиксирует операцию «{entity_ru}» при получении подтверждений "
            f"от не менее чем `quorum = {v_c}` различных узлов. При сетевых повторах один узел может прислать "
            f"несколько дублей одного подтверждения. Найдите строку с ошибкой."
        )
        expl = "Строка 3 считает `len(matching)` с учётом дублей от одного и того же узла вместо `len(set(matching))` уникальных узлов."
    elif k == 3:
        buggy = (
            f"def allow_half_open_probe(state: dict, max_probes: int = {v_c}) -> bool:\n"
            f"    if state.get('mode') != 'half_open':\n"
            f"        return state.get('mode') == 'closed'\n"
            f"    in_flight = state.get('probes', 0)\n"
            f"    if in_flight > max_probes:\n"
            f"        return False\n"
            f"    state['probes'] = in_flight + 1\n"
            f"    return True"
        )
        fixed = buggy.replace("if in_flight > max_probes:", "if in_flight >= max_probes:")
        tests = (
            f"st = {{'mode': 'half_open', 'probes': {v_c}}}\n"
            f"assert allow_half_open_probe(st, {v_c}) is False\n"
            f"assert st['probes'] == {v_c}\n"
            f"st2 = {{'mode': 'half_open', 'probes': {v_c - 1}}}\n"
            f"assert allow_half_open_probe(st2, {v_c}) is True"
        )
        stem = (
            f"Предохранитель (Circuit Breaker) в «{svc_ru}» (`{svc_id}`) для защиты «{entity_ru}» в режиме "
            f"`half_open` должен пропускать не более `max_probes = {v_c}` пробных вызовов. Найдите строку, "
            f"из-за которой пропускается лишний `({v_c + 1})`-й вызов."
        )
        expl = "Строка 5 использует строгое `in_flight > max_probes` вместо `in_flight >= max_probes`, пропуская `max_probes + 1` проб."
    elif k == 4:
        buggy = (
            f"def rollback_saga(completed_steps: list[tuple[str, int]], base_val: int = {v_b}) -> list[str]:\n"
            f"    log: list[str] = []\n"
            f"    cur = base_val\n"
            f"    for step_name, delta in completed_steps:\n"
            f"        cur -= delta\n"
            f"        log.append(f'{{step_name}}:{{cur}}')\n"
            f"    return log"
        )
        fixed = buggy.replace("for step_name, delta in completed_steps:", "for step_name, delta in reversed(completed_steps):")
        tests = (
            f"steps = [('reserve', {v_a}), ('charge', {v_c * 5}), ('notify', {v_c})]\n"
            f"res = rollback_saga(steps, {v_b})\n"
            f"assert [x.split(':')[0] for x in res] == ['notify', 'charge', 'reserve']"
        )
        stem = (
            f"Оркестратор распределённой саги в «{svc_ru}» (`{svc_id}`) при сбое на шаге обработки «{entity_ru}» "
            f"должен выполнить компенсирующие транзакции строго в обратном порядке (LIFO) относительно выполненных шагов. "
            f"Укажите строку с дефектом."
        )
        expl = "В строке 4 обход `completed_steps` идёт в прямом порядке (FIFO) вместо обратного `reversed(completed_steps)` (LIFO)."
    else:
        buggy = (
            f"def ingest_stream_batch(records: list[tuple[int, int]], watermark: int, allowed_lateness: int = {v_a}) -> tuple[int, int]:\n"
            f"    accepted_sum = 0\n"
            f"    wm = watermark\n"
            f"    for ev_ts, val in records:\n"
            f"        wm = max(wm, ev_ts)\n"
            f"        if ev_ts >= wm - allowed_lateness:\n"
            f"            accepted_sum += val\n"
            f"    return accepted_sum, wm"
        )
        fixed = buggy.replace(
            "        wm = max(wm, ev_ts)\n        if ev_ts >= wm - allowed_lateness:",
            "        if ev_ts >= watermark - allowed_lateness:\n            accepted_sum += val\n        wm = max(wm, ev_ts)\n        if False:",
        )
        # Cleaner 1-line fix: keep watermark advancement per batch, bug is comparing against mutated wm instead of watermark
        buggy = (
            f"def ingest_stream_batch(records: list[tuple[int, int]], watermark: int, allowed_lateness: int = {v_a}) -> int:\n"
            f"    accepted_sum = 0\n"
            f"    max_seen = watermark\n"
            f"    for ev_ts, val in records:\n"
            f"        max_seen = max(max_seen, ev_ts)\n"
            f"        if ev_ts >= max_seen - allowed_lateness:\n"
            f"            accepted_sum += val\n"
            f"    return accepted_sum"
        )
        fixed = buggy.replace("if ev_ts >= max_seen - allowed_lateness:", "if ev_ts >= watermark - allowed_lateness:")
        tests = (
            f"batch = [({v_b + 100}, 10), ({v_b - v_a + 5}, 25)]\n"
            f"assert ingest_stream_batch(batch, {v_b}, {v_a}) == 35\n"
            f"assert ingest_stream_batch([({v_b - v_a - 1}, 50)], {v_b}, {v_a}) == 0"
        )
        stem = (
            f"Потоковый оператор в «{svc_ru}» (`{svc_id}`) принимает микробатч «{entity_ru}» относительно "
            f"зафиксированного на входе батча водяного знака `watermark` (допустимое опоздание — `allowed_lateness = {v_a}`). "
            f"Внутри одного микробатча порядок записей произвольный, поэтому проверка опоздания должна выполняться "
            f"относительно входного `watermark` батча, а не максимума внутри текущего микробатча. Найдите строку с ошибкой."
        )
        expl = "Строка 6 сравнивает `ev_ts` с `max_seen - allowed_lateness` (уже сдвинутым свежим событием внутри того же батча) вместо входного `watermark - allowed_lateness`."

    ch = changed_lines(buggy, fixed)
    assert len(ch) == 1, (fid, ch)
    line_no = next(iter(ch))
    checks = [
        Check(name="buggy_fails", runner="python", program=py_harness(buggy, tests), expect="fail"),
        Check(name="fixed_passes", runner="python", program=py_harness(fixed, tests), expect="pass", embeds_display_code=False),
    ]
    return build_variant(
        fid, seed,
        stem=f"{dm['ru']} · уровень {'/'.join(_grades)} · {title_ru} [{id_p[5]}, ревизия {v_a}] — " + stem,
        code=buggy,
        answer_key=AnswerKey(kind="line", value=line_no, explanation=expl),
        context=svc_ru,
        verification="execution",
        checks=checks,
        defect_type=defect,
        params={"fixed_code": fixed, "bug_line": line_no, "svc": svc_id, "v_a": v_a, "v_b": v_b},
    )


def _gen_choose_fix(fid: str, direction: str, slot_idx: int, seed: int) -> Variant:
    _, slug, _, _grades, _b, _tm, defect, title_ru = SLOT_SPECS[slot_idx]
    dm = DIR_META[direction]
    rng = make_rng(fid, seed)
    svc_ru, svc_id, entity_ru = dm["services"][seed % len(dm["services"])]
    id_p = _IDENT_POOLS[(seed // 2 + slot_idx) % len(_IDENT_POOLS)]
    k = slot_idx - 6  # 0..7
    ttl = 20 + (seed % 109) * 2 + rng.randint(0, 1)
    cap_v = 80 + (seed % 131) * 3 + rng.randint(0, 2)
    lim_v = rng.randint(4, 12)

    if k == 0:
        buggy = (
            f"def claim_idempotency(store: dict, key: str, now: int, lease_ttl: int = {ttl}) -> bool:\n"
            f"    rec = store.get(key)\n"
            f"    if rec is not None:\n"
            f"        return False\n"
            f"    store[key] = ('in_progress', now + lease_ttl)\n"
            f"    return True"
        )
        fix_line = "    if rec is not None and (rec[0] == 'done' or rec[1] > now):"
        bad_lines = [
            "    if rec is not None and rec[0] == 'done':",
            "    if rec is not None and rec[1] >= now:",
            "    if rec is not None and (rec[0] == 'in_progress' or rec[1] > now):",
        ]
        tests = (
            f"st = {{'k_done': ('done', 10), 'k_live': ('in_progress', 200), 'k_exp': ('in_progress', 100)}}\n"
            f"assert claim_idempotency(st, 'k_done', 150, {ttl}) is False\n"
            f"assert claim_idempotency(st, 'k_live', 150, {ttl}) is False\n"
            f"assert claim_idempotency(st, 'k_exp', 100, {ttl}) is True\n"
            f"assert claim_idempotency(st, 'k_new', 100, {ttl}) is True"
        )
        stem = (
            f"В сервисе «{svc_ru}» (`{svc_id}`) при обработке «{entity_ru}» ключ идемпотентности хранится в `store[key] = (status, lease_until)`. "
            f"Повторный захват должен отклоняться, если запись уже завершена (`status == 'done'`) или её активный лиз ещё не истёк (`lease_until > now`), "
            f"но разрешаться, если предыдущий воркер завис и `lease_until <= now`. Выберите корректное исправление строки 3."
        )
        expl = "Блокировать нужно как завершённые операции (`rec[0] == 'done'`), так и активные лизы (`rec[1] > now`); при `rec[1] <= now` незавершённый лиз перехватывается."
    elif k == 1:
        buggy = (
            f"def next_retry_delay(attempt: int, elapsed: int, base: int = {lim_v}, cap: int = {cap_v}, budget: int = {cap_v * 2}) -> int:\n"
            f"    raw = base * (2 ** attempt)\n"
            f"    delay = raw if elapsed + raw <= budget else -1\n"
            f"    return delay"
        )
        fix_line = "    delay = min(raw, cap) if elapsed + min(raw, cap) <= budget else -1"
        bad_lines = [
            "    delay = min(raw, cap) if elapsed + raw <= budget else -1",
            "    delay = max(raw, cap) if elapsed + min(raw, cap) <= budget else -1",
            "    delay = min(raw, budget - elapsed) if elapsed < budget else 0",
        ]
        tests = (
            f"d1 = next_retry_delay(10, {cap_v}, {lim_v}, {cap_v}, {cap_v * 2})\n"
            f"assert d1 == {cap_v}\n"
            f"assert next_retry_delay(10, {cap_v + 10}, {lim_v}, {cap_v}, {cap_v * 2}) == -1\n"
            f"assert next_retry_delay(1, 0, {lim_v}, {cap_v}, {cap_v * 2}) == {lim_v * 2}"
        )
        stem = (
            f"Клиент «{svc_ru}» (`{svc_id}`) при отправке «{entity_ru}» ограничивает каждую паузу повтора сверху потолком `cap = {cap_v}` мс "
            f"и возвращает `-1`, если даже ограниченная потолком пауза не помещается в остаток общего дедлайна `budget`. Выберите исправление строки 3."
        )
        expl = "Сначала пауза ограничивается потолком `min(raw, cap)`, и именно эта величина проверяется на укладывание в остаток бюджета `elapsed + min(raw, cap) <= budget`."
    elif k == 2:
        buggy = (
            f"def pick_ring_node(ring: list[tuple[int, str]], dead: set[str], key_hash: int) -> str | None:\n"
            f"    alive = [(h, n) for h, n in ring if n not in dead]\n"
            f"    if not alive:\n"
            f"        return None\n"
            f"    matches = [n for h, n in alive if h >= key_hash]\n"
            f"    return matches[0] if matches else None"
        )
        fix_line = "    return matches[0] if matches else alive[0][1]"
        bad_lines = [
            "    return matches[-1] if matches else alive[-1][1]",
            "    return matches[0] if matches else ring[0][1]",
            "    return alive[0][1] if matches else matches[0]",
        ]
        tests = (
            f"ring = [(10, 'n1'), (50, 'n2'), (90, 'n3')]\n"
            f"assert pick_ring_node(ring, {{'n1'}}, 95) == 'n2'\n"
            f"assert pick_ring_node(ring, set(), 40) == 'n2'\n"
            f"assert pick_ring_node(ring, {{'n1', 'n2', 'n3'}}, 20) is None"
        )
        stem = (
            f"Маршрутизатор консистентного хэширования в «{svc_ru}» (`{svc_id}`) распределяет «{entity_ru}» по отсортированному кольцу `ring = [(hash, node), ...]`. "
            f"Если `key_hash` больше хэшей всех живых узлов, кольцо должно замыкаться на первый живой узел `alive[0][1]`. Выберите исправление строки 6."
        )
        expl = "При отсутствии живых узлов с `h >= key_hash` кольцо замыкается по часовой стрелке на минимальный хэш среди живых узлов — `alive[0][1]`."
    elif k == 3:
        buggy = (
            f"def fetch_keyset_page(rows: list[tuple[int, int, str]], cur_ts: int, cur_id: int, limit: int = {lim_v}) -> list[tuple[int, int, str]]:\n"
            f"    ordered = sorted(rows, key=lambda r: (r[0], r[1]))\n"
            f"    tail = [r for r in ordered if r[0] > cur_ts]\n"
            f"    return tail[:limit]"
        )
        fix_line = "    tail = [r for r in ordered if (r[0], r[1]) > (cur_ts, cur_id)]"
        bad_lines = [
            "    tail = [r for r in ordered if r[0] >= cur_ts and r[1] != cur_id]",
            "    tail = [r for r in ordered if r[0] > cur_ts or r[1] > cur_id]",
            "    tail = [r for r in ordered if (r[0], r[1]) >= (cur_ts, cur_id)]",
        ]
        tests = (
            f"data = [({ttl - 1}, 9, 'old'), ({ttl}, 1, 'a'), ({ttl}, 2, 'b'), ({ttl}, 3, 'c'), ({ttl + 1}, 1, 'd')]\n"
            f"assert [x[2] for x in fetch_keyset_page(data, {ttl}, 1, {lim_v})] == ['b', 'c', 'd']\n"
            f"assert [x[2] for x in fetch_keyset_page(data, {ttl}, 3, {lim_v})] == ['d']"
        )
        stem = (
            f"API пагинации в «{svc_ru}» (`{svc_id}`) выдаёт «{entity_ru}» по составному курсору `(cur_ts, cur_id)`. "
            f"Текущий фильтр `r[0] > cur_ts` теряет записи с тем же временем `cur_ts`, но большим `id`. Выберите исправление строки 3."
        )
        expl = "Лексикографическое сравнение кортежей `(r[0], r[1]) > (cur_ts, cur_id)` эквивалентно `r[0] > cur_ts or (r[0] == cur_ts and r[1] > cur_id)` и не теряет граничные записи."
    elif k == 4:
        buggy = (
            f"def read_with_stale_fallback(cache: dict, key: str, now: int, loader_val: int | None, ttl: int = {ttl}) -> int | None:\n"
            f"    entry = cache.get(key)\n"
            f"    if entry is not None and entry[1] > now:\n"
            f"        return entry[0]\n"
            f"    if loader_val is not None:\n"
            f"        cache[key] = (loader_val, now + ttl)\n"
            f"        return loader_val\n"
            f"    return None"
        )
        fix_line = "    return entry[0] if entry is not None else None"
        bad_lines = [
            "    return entry[1] if entry is not None else None",
            "    return loader_val if entry is None else None",
            "    return entry[0] if entry is not None and entry[1] > now else None",
        ]
        tests = (
            f"c = {{'k1': ({cap_v}, 50)}}\n"
            f"assert read_with_stale_fallback(c, 'k1', 40, 999, {ttl}) == {cap_v}\n"
            f"assert read_with_stale_fallback(c, 'k1', 60, None, {ttl}) == {cap_v}\n"
            f"assert read_with_stale_fallback(c, 'k_miss', 60, None, {ttl}) is None\n"
            f"assert read_with_stale_fallback(c, 'k1', 60, 777, {ttl}) == 777"
        )
        stem = (
            f"Кэш «{svc_ru}» (`{svc_id}`) хранит «{entity_ru}» в формате `cache[key] = (val, expires_at)`. "
            f"При отказе источника (`loader_val is None`) и истёкшем TTL сервис должен отдавать устаревшее значение из кэша (stale-if-error), "
            f"если оно есть. Выберите исправление строки 8."
        )
        expl = "Паттерн stale-if-error при отказе источника возвращает сохранённое значение `entry[0]`, если запись в кэше существовала."
    elif k == 5:
        buggy = (
            f"def claim_outbox_batch(rows: list[dict], now: int, lease_s: int = {ttl}) -> list[int]:\n"
            f"    claimed: list[int] = []\n"
            f"    for r in rows:\n"
            f"        if r['status'] == 'pending':\n"
            f"            r['status'] = 'leased'\n"
            f"            r['lease_until'] = now + lease_s\n"
            f"            claimed.append(r['id'])\n"
            f"    return claimed"
        )
        fix_line = "        if r['status'] == 'pending' or (r['status'] == 'leased' and r['lease_until'] <= now):"
        bad_lines = [
            "        if r['status'] != 'sent' and r['lease_until'] < now:",
            "        if r['status'] == 'pending' or r['lease_until'] <= now:",
            "        if r['status'] in ('pending', 'leased') and r['lease_until'] <= now:",
        ]
        tests = (
            f"rows = [\n"
            f"    {{'id': 1, 'status': 'pending', 'lease_until': 999}},\n"
            f"    {{'id': 2, 'status': 'leased', 'lease_until': 100}},\n"
            f"    {{'id': 3, 'status': 'leased', 'lease_until': 150}},\n"
            f"    {{'id': 4, 'status': 'sent', 'lease_until': 10}},\n"
            f"]\n"
            f"assert claim_outbox_batch(rows, 100, {ttl}) == [1, 2]"
        )
        stem = (
            f"Воркер transactional outbox в «{svc_ru}» (`{svc_id}`) забирает на отправку события «{entity_ru}» со статусом `'pending'`, "
            f"а также зависшие события со статусом `'leased'`, у которых `lease_until <= now` (но не трогает уже отправленные `'sent'`). "
            f"Выберите исправление строки 4."
        )
        expl = "Условие должно захватывать все `'pending'` (независимо от поля `lease_until`) и только те `'leased'`, у которых `lease_until <= now`, исключая `'sent'`."
    elif k == 6:
        buggy = (
            f"def is_causally_ready(local_vc: dict[str, int], msg_vc: dict[str, int], sender: str) -> bool:\n"
            f"    if msg_vc.get(sender, 0) != local_vc.get(sender, 0) + 1:\n"
            f"        return False\n"
            f"    return sum(msg_vc.values()) <= sum(local_vc.values()) + 1"
        )
        fix_line = "    return all(msg_vc.get(n, 0) <= local_vc.get(n, 0) for n in msg_vc if n != sender)"
        bad_lines = [
            "    return all(msg_vc.get(n, 0) < local_vc.get(n, 0) for n in msg_vc if n != sender)",
            "    return any(msg_vc.get(n, 0) <= local_vc.get(n, 0) for n in msg_vc if n != sender)",
            "    return all(msg_vc.get(n, 0) == local_vc.get(n, 0) for n in msg_vc if n != sender)",
        ]
        tests = (
            f"loc = {{'A': {lim_v}, 'B': 3, 'C': 2}}\n"
            f"assert is_causally_ready(loc, {{'A': {lim_v + 1}, 'B': 2, 'C': 2}}, 'A') is True\n"
            f"assert is_causally_ready(loc, {{'A': {lim_v + 1}, 'B': 1, 'C': 3}}, 'A') is False\n"
            f"assert is_causally_ready(loc, {{'A': {lim_v + 2}, 'B': 3, 'C': 2}}, 'A') is False"
        )
        stem = (
            f"Реплика «{svc_ru}» (`{svc_id}`) применяет события «{entity_ru}» в причинном порядке по векторным часам: "
            f"от узла `sender` это ровно следующее событие (`msg_vc[sender] == local_vc[sender] + 1`), а по каждому другому узлу `n != sender` "
            f"локальная реплика уже видела не меньше событий (`msg_vc[n] <= local_vc[n]`). Выберите исправление строки 4."
        )
        expl = "Сумма компонент вектора не защищает от пропуска: если `B` меньше на 1, а `C` больше на 1, сумма совпадает, но зависимость от `C` ещё не доставлена."
    else:
        buggy = (
            f"def admit_tenant_request(tenant_used: int, tenant_limit: int, global_free: int, reserve: int, is_critical: bool) -> bool:\n"
            f"    if global_free <= 0:\n"
            f"        return False\n"
            f"    return tenant_used < tenant_limit"
        )
        fix_line = "    return tenant_used < tenant_limit and (is_critical or global_free > reserve)"
        bad_lines = [
            "    return is_critical or (tenant_used < tenant_limit and global_free > reserve)",
            "    return tenant_used < tenant_limit and (is_critical or global_free >= reserve)",
            "    return tenant_used <= tenant_limit and (is_critical or global_free > reserve)",
        ]
        tests = (
            f"assert admit_tenant_request(5, {lim_v + 5}, {ttl}, {ttl}, False) is False\n"
            f"assert admit_tenant_request(5, {lim_v + 5}, {ttl}, {ttl}, True) is True\n"
            f"assert admit_tenant_request({lim_v + 5}, {lim_v + 5}, {ttl + 10}, {ttl}, True) is False\n"
            f"assert admit_tenant_request(5, {lim_v + 5}, {ttl + 1}, {ttl}, False) is True"
        )
        stem = (
            f"Контроллер допуска в «{svc_ru}» (`{svc_id}`) проверяет квоту запросов «{entity_ru}»: "
            f"любой запрос (включая критичный) обязан укладываться в квоту тенанта `tenant_used < tenant_limit`, "
            f"а некритичные запросы дополнительно не могут расходовать защищённый резерв `reserve` (им требуется `global_free > reserve`). "
            f"Выберите исправление строки 4."
        )
        expl = "Квота тенанта `tenant_used < tenant_limit` обязательна для всех, а при `not is_critical` остаток общего пула должен быть строго больше защищённого резерва (`global_free > reserve`)."

    blines = buggy.splitlines()
    fixed_full = "\n".join(blines[:-1] + [fix_line]) if k != 0 else "\n".join(blines[:2] + [fix_line] + blines[3:])
    if k == 1:
        fixed_full = "\n".join(blines[:2] + [fix_line] + blines[3:])
    elif k == 3:
        fixed_full = "\n".join(blines[:2] + [fix_line] + blines[3:])
    elif k == 5:
        fixed_full = "\n".join(blines[:3] + [fix_line] + blines[4:])
    ch = changed_lines(buggy, fixed_full)
    assert len(ch) == 1, (fid, k, ch)
    line_no = next(iter(ch))
    label = f"Заменить строку {line_no} на:"
    opts, key = _stratified_options(rng, slot_idx, seed, (label, fix_line), [(label, b) for b in bad_lines])
    checks = []
    for o in opts:
        patched = "\n".join(blines[: line_no - 1] + [o.code or ""] + blines[line_no:])
        checks.append(Check(
            name=f"option:{o.id}",
            runner="python",
            program=py_harness(patched, tests),
            expect="pass" if o.id == key else "fail",
            embeds_display_code=False,
        ))
    return build_variant(
        fid, seed,
        stem=f"{dm['ru']} · уровень {'/'.join(_grades)} · {title_ru} [{id_p[5]}, окно {ttl} с] — " + stem,
        code=buggy,
        options=opts,
        answer_key=AnswerKey(kind="option", value=key, explanation=expl),
        context=svc_ru,
        verification="execution",
        checks=checks,
        defect_type=defect,
        display_code_note="Каждый вариант кода подставляется в функцию и проверяется набором граничных тестов в песочнице.",
        params={"bug_line": line_no, "svc": svc_id},
    )


def _gen_predict_output(fid: str, direction: str, slot_idx: int, seed: int) -> Variant:
    _, slug, _, _grades, _b, _tm, defect, title_ru = SLOT_SPECS[slot_idx]
    dm = DIR_META[direction]
    rng = make_rng(fid, seed)
    svc_ru, svc_id, entity_ru = dm["services"][seed % len(dm["services"])]
    id_p = _IDENT_POOLS[(seed // 2 + slot_idx) % len(_IDENT_POOLS)]
    k = slot_idx - 14  # 0..5
    seq_tag = 100 + (seed % 173) * 3 + rng.randint(0, 2)

    if k == 0:
        cap_b = rng.randint(8, 15)
        rate = rng.randint(2, 4)
        c1, c2, c3 = rng.randint(4, 7), rng.randint(5, 9), rng.randint(3, 6)
        t1, t2 = rng.randint(1, 3), rng.randint(4, 6)
        code = (
            f"def run_bucket():\n"
            f"    cap, tokens, rate, last_t = {cap_b}, {cap_b}, {rate}, 0\n"
            f"    ok = 0\n"
            f"    for t, cost in [(0, {c1}), ({t1}, {c2}), ({t2}, {c3})]:\n"
            f"        tokens = min(cap, tokens + (t - last_t) * rate)\n"
            f"        last_t = t\n"
            f"        if tokens >= cost:\n"
            f"            tokens -= cost\n"
            f"            ok += 1\n"
            f"    print(f'{{ok}}:{{tokens}}')\n\n"
            f"run_bucket()"
        )
        # compute exact output
        tok, last_t, ok = cap_b, 0, 0
        for t, cost in [(0, c1), (t1, c2), (t2, c3)]:
            tok = min(cap_b, tok + (t - last_t) * rate)
            last_t = t
            if tok >= cost:
                tok -= cost
                ok += 1
        out = f"{ok}:{tok}"
        stem = f"Ограничитель запросов в «{svc_ru}» (`{svc_id}`) регулирует поток «{entity_ru}» алгоритмом Token Bucket. Что выведет программа?"
        expl = f"На каждом событии сначала начисляются токены `(t - last_t) * rate` с потолком `{cap_b}`, затем при `tokens >= cost` списывается `cost`. Итог: `{out}`."
    elif k == 1:
        snap = rng.randint(15, 25)
        active_tx = snap - 2
        v1, v2, v3, v4 = rng.randint(10, 30), rng.randint(35, 60), rng.randint(65, 90), rng.randint(100, 150)
        code = (
            f"versions = [\n"
            f"    (10, 14, {v1}),\n"
            f"    (12, 0, {v2}),\n"
            f"    ({active_tx}, 0, {v3}),\n"
            f"    ({snap + 1}, 0, {v4}),\n"
            f"]\n"
            f"snap_tx = {snap}\n"
            f"active = {{{active_tx}}}\n"
            f"vis = [val for xmin, xmax, val in versions\n"
            f"       if xmin <= snap_tx and xmin not in active and (xmax == 0 or xmax > snap_tx or xmax in active)]\n"
            f"print(f'{{len(vis)}}:{{sum(vis)}}')"
        )
        out = f"1:{v2}"
        stem = f"Движок хранения в «{svc_ru}» (`{svc_id}`) вычисляет видимость версий «{entity_ru}» для снимка MVCC `snap_tx = {snap}` при множестве незавершённых транзакций `active`. Что выведет программа?"
        expl = f"Первая версия уже удалена к моменту `{snap}` (`xmax = 14 <= {snap}`), третья создана активной транзакцией `{active_tx}`, четвёртая создана после снимка (`{snap + 1} > {snap}`). Видна только вторая версия (`{v2}`)."
    elif k == 2:
        horizon = rng.randint(20, 40)
        v_a, v_b = rng.randint(100, 300), rng.randint(400, 700)
        code = (
            f"records = [\n"
            f"    ('k1', {horizon + 5}, {v_a}),\n"
            f"    ('k1', {horizon - 2}, 999),\n"
            f"    ('k2', {horizon - 5}, None),\n"
            f"    ('k3', {horizon + 2}, None),\n"
            f"    ('k4', {horizon - 1}, {v_b}),\n"
            f"]\n"
            f"min_snap = {horizon}\n"
            f"latest = {{}}\n"
            f"for k, seq, val in sorted(records, key=lambda r: (r[0], -r[1])):\n"
            f"    if k not in latest:\n"
            f"        latest[k] = (seq, val)\n"
            f"kept = [k for k, (seq, val) in sorted(latest.items()) if val is not None or seq >= min_snap]\n"
            f"print(','.join(kept))"
        )
        out = "k1,k3,k4"
        stem = f"Компактор LSM-дерева в «{svc_ru}» (`{svc_id}`) сжимает версионные записи «{entity_ru}» при горизонте активных снимков `min_snap = {horizon}`. Маркер удаления (`None`) можно отбросить только при `seq < min_snap`. Что выведет программа?"
        expl = f"У `k2` маркер удаления старше горизонта (`{horizon - 5} < {horizon}`), поэтому он удаляется; у `k3` маркер удаления новее горизонта (`{horizon + 2} >= {horizon}`) и сохраняется. Итог: `{out}`."
    elif k == 3:
        t_cand = rng.randint(4, 9)
        l_cand = rng.randint(12, 25)
        code = (
            f"peers = [\n"
            f"    ('n1', {t_cand - 1}, {l_cand + 5}),\n"
            f"    ('n2', {t_cand}, {l_cand - 1}),\n"
            f"    ('n3', {t_cand}, {l_cand + 1}),\n"
            f"    ('n4', {t_cand + 1}, {l_cand - 3}),\n"
            f"    ('n5', {t_cand}, {l_cand}),\n"
            f"]\n"
            f"ct, cl = {t_cand}, {l_cand}\n"
            f"votes = [n for n, vt, vl in peers if (ct > vt) or (ct == vt and cl >= vl)]\n"
            f"print(f'{{len(votes)}}:' + ','.join(votes))"
        )
        out = "3:n1,n2,n5"
        stem = f"Узел-кандидат Raft в «{svc_ru}» (`{svc_id}`) с журналом `(term={t_cand}, len={l_cand})` запрашивает голоса реплик «{entity_ru}». Реплика голосует, если журнал кандидата не менее актуален. Что выведет программа?"
        expl = f"Реплики `n1` (меньший term), `n2` (тот же term, короче журнал) и `n5` (равный журнал) отдают голос; `n3` и `n4` отказывают. Итог: `{out}`."
    elif k == 4:
        w1, w2, w3 = rng.randint(2, 5), rng.randint(3, 6), rng.randint(1, 4)
        l1, l2, l3 = rng.randint(20, 40), rng.randint(10, 25), rng.randint(50, 90)
        code = (
            f"nodes = [\n"
            f"    ['a', {w1}, {l1}],\n"
            f"    ['b', {w2}, {l2}],\n"
            f"    ['c', {w3}, {l3}],\n"
            f"]\n"
            f"picked = []\n"
            f"for _ in range(3):\n"
            f"    best = min(nodes, key=lambda x: (x[1] + 1) * x[2])\n"
            f"    picked.append(best[0])\n"
            f"    best[1] += 1\n"
            f"print(''.join(picked))"
        )
        ns = [["a", w1, l1], ["b", w2, l2], ["c", w3, l3]]
        pk = []
        for _ in range(3):
            b_node = min(ns, key=lambda x: (x[1] + 1) * x[2])
            pk.append(b_node[0])
            b_node[1] += 1
        out = "".join(pk)
        stem = f"Балансировщик нагрузки в «{svc_ru}» (`{svc_id}`) направляет 3 последовательных запроса «{entity_ru}» на узел с минимальной ожидаемой ценой `(inflight + 1) * latency_ms`. Что выведет программа?"
        expl = f"На каждом шаге выбирается узел с минимумом `(inflight + 1) * latency_ms`, после чего его счётчик `inflight` увеличивается на 1. Итог: `{out}`."
    else:
        t_base = rng.randint(10, 50)
        code = (
            f"rw_edges = [('T1', 'T2'), ('T2', 'T3'), ('T3', 'T1'), ('T4', 'T2')]\n"
            f"prio = {{'T1': {t_base + 5}, 'T2': {t_base}, 'T3': {t_base + 10}, 'T4': {t_base + 20}}}\n"
            f"adj = {{}}\n"
            f"for u, v in rw_edges:\n"
            f"    adj.setdefault(u, set()).add(v)\n"
            f"in_cycle = set()\n"
            f"for start in adj:\n"
            f"    cur = set(adj.get(start, ()))\n"
            f"    for _ in range(len(adj)):\n"
            f"        if start in cur:\n"
            f"            in_cycle.add(start)\n"
            f"            break\n"
            f"        cur = {{nxt for node in cur for nxt in adj.get(node, ())}}\n"
            f"victim = min(in_cycle, key=lambda t: (prio[t], t))\n"
            f"print(f'{{len(in_cycle)}}:{{victim}}')"
        )
        out = "3:T2"
        stem = f"Менеджер транзакций SSI в «{svc_ru}» (`{svc_id}`) при обработке «{entity_ru}» ищет транзакции, входящие в ориентированный цикл `rw`-антизависимостей, и откатывает жертву с минимальным приоритетом. Что выведет программа?"
        expl = "Транзакции `T1 -> T2 -> T3 -> T1` образуют цикл из 3 вершин (`T4` в цикл не входит); наименьший приоритет среди участников цикла у `T2`."

    chk = Check(name="stdout", runner="python", program=code, expect="stdout_equals", expected_stdout=out)
    return build_variant(
        fid, seed,
        stem=f"{dm['ru']} · уровень {'/'.join(_grades)} · {title_ru} [{id_p[5]}, пакет #{seq_tag}] — " + stem,
        code=code,
        answer_key=AnswerKey(kind="output", value=out, explanation=expl),
        context=svc_ru,
        verification="execution",
        checks=[chk],
        defect_type=defect,
        params={"svc": svc_id, "expected": out},
    )


def _gen_ob3_or_incident(fid: str, direction: str, slot_idx: int, seed: int, is_incident: bool) -> Variant:
    _, slug, fmt, _grades, _b, _tm, defect, title_ru = SLOT_SPECS[slot_idx]
    dm = DIR_META[direction]
    rng = make_rng(fid, seed)
    svc_ru, svc_id, entity_ru = dm["services"][seed % len(dm["services"])]
    id_p = _IDENT_POOLS[(seed // 2 + slot_idx) % len(_IDENT_POOLS)]
    ttl = 20 + (seed % 97) * 2 + rng.randint(0, 1)
    amt1 = (2 + (seed % 23)) * 100
    amt2 = (9 + ((seed * 3) % 29)) * 100

    buggy_code = (
        f"def process_events(events: list[tuple[str, int, int]], lease_ttl: int = {ttl}) -> int:\n"
        f"    # events: (op_id, worker_epoch, delta)\n"
        f"    seen: dict[str, int] = {{}}\n"
        f"    total = 0\n"
        f"    for op_id, epoch, delta in events:\n"
        f"        if op_id in seen and seen[op_id] > epoch:\n"
        f"            continue\n"
        f"        seen[op_id] = epoch\n"
        f"        total += delta\n"
        f"    return total"
    )
    good_code = buggy_code.replace("if op_id in seen and seen[op_id] > epoch:", "if op_id in seen:")

    def ref_eval(evs: list[tuple[str, int, int]]) -> str:
        s: set[str] = set()
        tot = 0
        for oid, _ep, d in evs:
            if oid in s:
                continue
            s.add(oid)
            tot += d
        return str(tot)

    repro_evs = [("op_1", 1, amt1), ("op_1", 2, amt1), ("op_2", 1, amt2)]
    clean_1 = [("op_1", 2, amt1), ("op_1", 1, amt1), ("op_2", 1, amt2)]
    clean_2 = [("op_1", 1, amt1), ("op_2", 2, amt2)]
    clean_3 = [("op_3", 1, amt1 + amt2)]

    fmt_evs = lambda evs: "; ".join(f"({oid}, epoch={ep}, delta={d})" for oid, ep, d in evs)  # noqa: E731
    by_text = {
        fmt_evs(repro_evs): repro_evs,
        fmt_evs(clean_1): clean_1,
        fmt_evs(clean_2): clean_2,
        fmt_evs(clean_3): clean_3,
    }
    opts1, key1 = _stratified_options(
        rng, slot_idx, seed,
        (fmt_evs(repro_evs), None),
        [(fmt_evs(c), None) for c in (clean_1, clean_2, clean_3)],
        step=1,
    )

    bad_fix_1 = buggy_code.replace("if op_id in seen and seen[op_id] > epoch:", "if op_id in seen and seen[op_id] == epoch:")
    bad_fix_2 = buggy_code.replace("if op_id in seen and seen[op_id] > epoch:", "if op_id not in seen:")
    bad_fix_3 = buggy_code.replace("total += delta", "total = delta")
    opts2, key2 = _stratified_options(
        rng, slot_idx, seed,
        ("Заменить функцию process_events на:", good_code),
        [("Заменить функцию process_events на:", b) for b in (bad_fix_1, bad_fix_2, bad_fix_3)],
        step=2,
    )

    checks: list[Check] = []
    for o in opts1:
        ev = by_text[o.text]
        prog = buggy_code + f"\n\nprint(process_events({ev!r}))\n"
        checks.append(Check(
            name=f"step1:{o.id}",
            runner="python",
            program=prog,
            expect="stdout_differs" if o.id == key1 else "stdout_equals",
            expected_stdout=ref_eval(ev),
        ))
    suite_evs = [("op_a", 1, amt1), ("op_a", 2, amt1), ("op_a", 1, amt1), ("op_b", 3, amt2)]
    for o in opts2:
        prog = (o.code or "") + f"\n\nprint(process_events({suite_evs!r}))\n"
        checks.append(Check(
            name=f"step2:{o.id}",
            runner="python",
            program=prog,
            embeds_display_code=False,
            expect="stdout_equals" if o.id == key2 else "stdout_differs",
            expected_stdout=ref_eval(suite_evs),
        ))

    stem = (
        f"{dm['ru']} · уровень {'/'.join(_grades)} · {title_ru} [{id_p[5]}, TTL {ttl} с] — В контуре «{svc_ru}» (`{svc_id}`) при обработке «{entity_ru}» обнаружено дублирование эффекта "
        f"при перехвате задачи новым воркером со старшей эпохой `epoch`. Каждая операция `op_id` должна применяться к итогу "
        f"ровно один раз независимо от номера эпохи воркера."
    )
    steps = ob3_steps(
        "Шаг 1. Выберите последовательность событий `(op_id, epoch, delta)`, на которой текущий код даёт неверный итог.",
        "Шаг 2. Выберите корректное исправление функции `process_events`.",
        f"Шаг 3. Опишите архитектурный инвариант идемпотентности и fencing-токенов для «{svc_ru}» при распределённой обработке "
        f"в нескольких воркерах и сетевых партициях (5–10 предложений).",
    )
    rubric = rubric_from({
        "criteria": [
            ("root_cause", "Объясняет причину сбоя: повтор от нового лидера/воркера с большей эпохой проходит фильтр `seen[op_id] > epoch` и применяется повторно", 0.35),
            ("atomic_storage", "Предлагает атомарную фиксацию `op_id` и бизнес-эффекта в одной транзакции БД (`INSERT ... ON CONFLICT DO NOTHING`) или через уникальный ключ состояния", 0.40),
            ("fencing_slo", "Разграничивает роль `epoch` (отсечение зомби-воркеров до коммита) и роль `op_id` (однократность бизнес-операции), указывает метрики контроля и верификацию", 0.25),
        ],
        "strong": (
            "Дефект возникает потому, что при истечении аренды первый воркер (epoch=1) успевает применить операцию, а второй воркер (epoch=2) "
            "повторно доставляет тот же op_id: условие seen[op_id] > epoch ложно, и операция применяется второй раз. В распределённой системе "
            "fencing-токен (epoch) защищает от записи устаревшего лидера, но не заменяет дедупликацию по op_id. Решение: хранить таблицу "
            "processed_ops(op_id PRIMARY KEY) в той же транзакции БД, что и изменение состояния, выполняя INSERT ... ON CONFLICT DO NOTHING, "
            "а также проверять epoch >= current_lease_epoch на ресурсе. Верификация — хаос-тест с паузой процесса (SIGSTOP) и параллельной доставкой."
        ),
        "medium": (
            "Код пропускает повтор с большим epoch, поэтому при смене воркера операция применяется дважды. Нужно проверять сам факт наличия "
            "op_id в базе обработанных операций с уникальным индексом в одной транзакции с обновлением данных."
        ),
        "weak": "Нужно увеличить lease_ttl и добавить блокировку в памяти процесса.",
        "notes": "Оценивается шаг 3; шаги 1 и 2 проверяются исполнением автоматически.",
    })
    ak = AnswerKey(
        kind="steps",
        value={"1": key1, "2": key2, "3": "rubric"},
        explanation=(
            "На шаге 1 повтор того же `op_1` со старшей эпохой `epoch=2` проходит проверку `seen['op_1'] > 2` (1 > 2 ложно) "
            "и удваивает сумму. На шаге 2 любая повторная доставка уже зафиксированного `op_id` отклоняется."
        ),
    )
    params: dict[str, Any] = {"svc": svc_id, "ttl": ttl, "amt1": amt1, "amt2": amt2}
    if is_incident:
        p95_base = rng.randint(85, 140)
        p95_deg = rng.randint(1450, 2400)
        params["incident"] = {
            "service": svc_id,
            "release": f"2026.10.{20 + (seed % 5)}-rc{1 + (seed % 4)}",
            "slo": {"metric": "p95_ms", "limit": 250, "unit": "мс"},
            "series": [
                {"id": "p95_ms", "label": "Латентность p95", "unit": "мс", "baseline": p95_base, "degraded": p95_deg, "recovered": p95_base + 10},
                {"id": "pool_free", "label": "Свободный ресурс пула", "unit": "ед.", "baseline": 16, "degraded": 0, "recovered": 14},
                {"id": "err_pct", "label": "Доля ошибок и дублей", "unit": "%", "baseline": 0.1, "degraded": 14.8, "recovered": 0.1},
            ],
            "logs": [
                {"t": 1, "level": "info", "msg": f"INFO [{svc_id}] release deployed, baseline p95={p95_base}ms"},
                {"t": 4, "level": "warn", "msg": f"WARN [{svc_id}] lease handoff epoch=2 while epoch=1 in-flight (ttl={ttl}s)"},
                {"t": 8, "level": "error", "msg": f"ERROR [{svc_id}] invariant violation: duplicate op_id applied, p95={p95_deg}ms"},
            ],
            "actions": [
                {"id": o.id, "label": f"Патч {o.id}", "sim_effect": "recovered" if o.id == key2 else "degraded"}
                for o in opts2
            ],
        }
    return build_variant(
        fid, seed,
        stem=stem,
        code=buggy_code,
        options=opts1 + opts2,
        answer_key=ak,
        rubric=rubric,
        context=svc_ru,
        verification="execution",
        checks=checks,
        steps=steps,
        defect_type=defect,
        params=params,
    )


def _gen_open_answer(fid: str, direction: str, slot_idx: int, seed: int) -> Variant:
    _, slug, _fmt, grades, _b, _tm, defect, title_ru = SLOT_SPECS[slot_idx]
    dm = DIR_META[direction]
    rng = make_rng(fid, seed)
    svc_ru, svc_id, entity_ru = dm["services"][seed % len(dm["services"])]
    id_p = _IDENT_POOLS[(seed // 2 + slot_idx) % len(_IDENT_POOLS)]
    rps = 1500 + (seed % 83) * 150 + rng.choice([0, 50, 100])
    slo_ms = rng.choice([80, 110, 140, 180, 220, 260])
    rpo_s = rng.choice([0, 5, 10, 15, 30, 60])
    cells = rng.choice([4, 6, 8, 12, 16])

    stem = (
        f"{dm['ru']} · уровень {'/'.join(grades)} · {title_ru} [{id_p[5]}] — Архитектурный комитет рассматривает развитие контура «{svc_ru}» (`{svc_id}`, "
        f"объект — «{entity_ru}»). Текущая пиковая нагрузка — {rps} запросов/с, целевой SLO по p99 — {slo_ms} мс, "
        f"целевой RPO при отказе зоны доступности — не более {rpo_s} с, целевое число изолированных ячеек (cells) — {cells}. "
        f"Тема решения ({'/'.join(grades)}): «{title_ru}». "
        f"Сформулируйте архитектурное решение: (1) границы консистентности и компромисс CAP/PACELC для «{entity_ru}»; "
        f"(2) схему изоляции отказов, квотирования и деградации при превышении бюджета ошибок; "
        f"(3) план поэтапного внедрения (Expand-Contract / канарка) и метрики автоматического отката."
    )
    rubric = rubric_from({
        "criteria": [
            ("consistency_model", f"Задаёт чёткую границу консистентности для «{entity_ru}» (кворум/лидер/идемпотентный outbox) с расчётом влияния на p99 ≤ {slo_ms} мс и RPO ≤ {rpo_s} с", 0.35),
            ("fault_isolation", f"Проектирует изоляцию по {cells} ячейкам (bulkhead, бюджетирование ретраев, сброс некритичной нагрузки) без каскадного отказа", 0.35),
            ("rollout_verification", "Описывает поэтапный переход без простоя (двойное чтение/запись, теневой трафик, критерии автоматического отката и хаос-проверки)", 0.30),
        ],
        "strong": (
            f"Для контура {svc_id} ({rps} RPS, p99 ≤ {slo_ms} мс, RPO ≤ {rpo_s} с) разделяю горячий путь на {cells} независимых ячеек "
            f"(шардирование по хешу тенанта/ключа). Внутри ячейки запись идёт через синхронный кворум в двух зонах доступности для соблюдения RPO, "
            f"а межъячеечные проекции обновляются асинхронно через transactional outbox с идемпотентными ключами. На входе каждой ячейки — "
            f"адаптивный лимитер и единый бюджет ретраев (не более 10 % дополнительного трафика), при просадке зависимости включается "
            f"graceful degradation со сбросом фоновых пересчётов. Миграцию провожу по схеме Expand-Contract: добавление новых полей/таблиц, "
            f"теневая сверка расхождений, канарское переключение 1% → 10% → 50% → 100% с автооткатом при росте p99 выше {slo_ms} мс."
        ),
        "medium": (
            f"Предлагаю разделить {svc_id} на шарды по ключу и настроить репликацию между зонами. Для удержания p99 ≤ {slo_ms} мс "
            f"использовать кэширование, таймауты и circuit breaker. Выкладку проводить через canary deployment с мониторингом ошибок и латентности."
        ),
        "weak": "Нужно добавить больше серверов в кластер, поставить балансировщик нагрузки и включить ретраи на всех клиентах.",
        "notes": "Оценивается полнота инженерного расчёта, привязка к заданным ограничениям SLO/RPO и отсутствие антипаттернов.",
    })
    ak = AnswerKey(
        kind="rubric",
        value="rubric",
        explanation=f"Эталонный разбор оценивает согласованность выбора консистентности (RPO ≤ {rpo_s} с), изоляции {cells} ячеек и плана миграции без простоя при p99 ≤ {slo_ms} мс.",
    )
    return build_variant(
        fid, seed,
        stem=stem,
        answer_key=ak,
        rubric=rubric,
        context=svc_ru,
        verification="rubric_only",
        defect_type=defect,
        params={"svc": svc_id, "rps": rps, "slo_ms": slo_ms, "rpo_s": rpo_s, "cells": cells},
    )


def make_lp_v2(direction: str, slot_idx: int):
    fid = family_id_for(direction, slot_idx)
    fmt = SLOT_SPECS[slot_idx][2]

    def generate(seed: int) -> Variant:
        if fmt == "find_bug":
            return _gen_find_bug(fid, direction, slot_idx, seed)
        if fmt == "choose_fix":
            return _gen_choose_fix(fid, direction, slot_idx, seed)
        if fmt == "predict_output":
            return _gen_predict_output(fid, direction, slot_idx, seed)
        if fmt in ("open_book_3step", "incident_sim"):
            return _gen_ob3_or_incident(fid, direction, slot_idx, seed, is_incident=(24 <= slot_idx <= 27 or fmt == "incident_sim"))
        return _gen_open_answer(fid, direction, slot_idx, seed)

    return generate
