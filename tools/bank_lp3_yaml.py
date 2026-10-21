"""Паспорта (YAML) семейств волны LP-3 (А3, 21.10.2026). Запуск из корня: python3 tools/bank_lp3_yaml.py

Параметры трудности — априорные, до калибровки на людях: a = 1,3 (ввод ответа, угадывание исключено),
b — у порога старшего грейда (Lead ≈ 2,0; Lead/Principal ≈ 2,3).
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1] / "backend" / "assessment_bank" / "families"

# (direction, module, family_id, title, skills, grades, b, time_s, суть задачи для basis/description)
LP3 = [
    ("backend", "lp3_pool_hold_rps_output", "backend.capacity.lp3_pool_hold_rps_output",
     "Потолок RPS из-за удержания соединений БД внешним вызовом в транзакции",
     ["connection_pool", "postgresql", "capacity_planning", "performance", "reliability"], ["lead"], 2.0, 600,
     "закон Литтла по типам запросов, внешний вызов внутри транзакции, потолок max_connections БД и целевая загрузка"),
    ("devops", "lp3_error_budget_releases_output", "devops.slo.lp3_error_budget_releases_output",
     "Сколько релизов позволяет остаток бюджета ошибок",
     ["sre", "slo", "deployment", "reliability", "on_call"], ["lead"], 2.0, 600,
     "бюджет ошибок 30-дневного окна, частичные инциденты по доле запросов, резерв и ожидаемый расход канарейки"),
    ("frontend", "lp3_defer_modules_tbt_output", "frontend.perf.lp3_defer_modules_tbt_output",
     "Минимум отложенных модулей ради бюджета TBT",
     ["web_performance", "core_web_vitals", "javascript", "webpack", "performance"], ["lead", "principal"], 2.3, 720,
     "TBT как сумма превышений над 50 мс, неделимые модули первого экрана, перебор вместо жадного выбора"),
    ("mobile", "lp3_hlc_merge_output", "mobile.sync.lp3_hlc_merge_output",
     "Итог офлайн-синхронизации по гибридным часам",
     ["offline_first", "persistence", "architecture", "networking", "caching"], ["lead"], 1.9, 480,
     "слияние правок по гибридной метке (время, счётчик), надгробия, порядок прихода на сервер не важен"),
    ("data_eng", "lp3_watermark_late_output", "data_eng.stream.lp3_watermark_late_output",
     "События окна при водяном знаке и допустимом опоздании",
     ["streaming", "kafka", "data_modeling", "etl", "data_quality"], ["lead"], 2.0, 600,
     "водяной знак по максимуму времени события, закрытие окна и отбрасывание опоздавших событий"),
    ("data_ml", "lp3_threshold_cost_output", "data_ml.eval.lp3_threshold_cost_output",
     "Порог классификатора по цене ошибок при требовании к полноте",
     ["classification_metrics", "precision_recall", "machine_learning", "ml_systems", "antifraud"], ["lead"], 2.0,
     720, "перебор порогов из выборки, цена FN/FP, ограничение по полноте, ничья — больший порог"),
    ("qa", "lp3_lpt_shards_output", "qa.ci.lp3_lpt_shards_output",
     "Сколько шардов CI нужно для цели по времени прогона",
     ["test_automation", "ci_cd", "test_strategy", "performance_testing", "qa_process"], ["lead"], 1.9, 600,
     "раскладка «самый длинный — в наименее загруженный», неделимые файлы, подготовка шарда"),
    ("security", "lp3_revocation_window_output", "security.tokens.lp3_revocation_window_output",
     "Окно использования украденной сессии после отзыва токенов",
     ["token_validation", "authorization", "secure_design", "threat_modeling", "containment"], ["lead", "principal"],
     2.3, 600, "последнее обновление access-токена до отзыва, локальная проверка JWT, кэш introspection"),
    ("analyst", "lp3_mix_adjusted_change_output", "analyst.metrics.lp3_mix_adjusted_change_output",
     "Изменение конверсии без сдвига состава трафика (парадокс Симпсона)",
     ["product_metrics", "data_analysis", "funnels", "aggregation", "stakeholders"], ["lead"], 2.0, 600,
     "стандартизация по весам первого периода против разницы общих конверсий"),
    ("common", "lp3_zone_loss_capacity_output", "common.reliability.lp3_zone_loss_capacity_output",
     "Сколько экземпляров добавить, чтобы пережить потерю любой зоны",
     ["reliability", "capacity_planning", "distributed_systems", "resilience", "cloud"], ["lead", "principal"], 2.3,
     600, "потеря самой крупной зоны, минимальная добавка перебором, а не поровну"),
    ("backend", "lp3_token_bucket_rejects_output", "backend.ratelimit.lp3_token_bucket_rejects_output",
     "Сколько запросов отклонит token bucket по журналу",
     ["rate_limiting", "api_design", "reliability", "performance", "distributed_systems"], ["senior", "lead"], 1.7, 480,
     "непрерывное пополнение с верхней границей, отказ без очереди, моделирование по журналу"),
    ("devops", "lp3_rollout_pdb_steps_output", "devops.k8s.lp3_rollout_pdb_steps_output",
     "Сколько волн займёт выкатка с maxSurge, PDB и ёмкостью узлов",
     ["kubernetes", "deployment", "reliability", "capacity_planning", "sre"], ["senior", "lead"], 1.7, 420,
     "одновременная замена ограничена maxSurge, свободными местами, maxUnavailable и PodDisruptionBudget"),
    ("frontend", "lp3_swr_requests_output", "frontend.http.lp3_swr_requests_output",
     "Сетевые запросы при max-age и stale-while-revalidate",
     ["http_caching", "web_performance", "browser", "api_integration", "performance"], ["lead"], 1.9, 480,
     "свежий ответ, устаревший с фоновой перепроверкой, сброс возраста после перепроверки"),
    ("mobile", "lp3_remote_config_delay_output", "mobile.config.lp3_remote_config_delay_output",
     "Когда пользователь увидит новое значение удалённой конфигурации",
     ["feature_flags", "release_management", "mobile_architecture", "networking", "caching"], ["lead"], 1.9, 480,
     "активация при следующем запуске и минимальный интервал загрузки"),
    ("data_eng", "lp3_scd2_rows_output", "data_eng.dwh.lp3_scd2_rows_output",
     "Число строк измерения SCD2 после пакета изменений",
     ["dwh", "data_modeling", "etl", "sql", "data_quality"], ["lead"], 1.9, 600,
     "версии по атрибутам SCD2, перезапись SCD1, повтор значения без изменений, новые ключи"),
    ("data_ml", "lp3_retrain_period_output", "data_ml.mlops.lp3_retrain_period_output",
     "Период переобучения модели с минимальной ценой дрейфа",
     ["mlops", "monitoring", "machine_learning", "ml_systems", "cost_optimization"], ["lead", "principal"], 2.3, 600,
     "целочисленный перебор периода против непрерывного приближения √(2C/(V·d))"),
    ("qa", "lp3_risk_regression_budget_output", "qa.strategy.lp3_risk_regression_budget_output",
     "Максимум покрытого риска регресса в бюджет времени",
     ["test_strategy", "risk_based_testing", "regression", "qa_process", "release_management"], ["lead", "principal"],
     2.3, 720, "перебор наборов с учётом дублирующих областей против жадного выбора"),
    ("security", "lp3_bruteforce_guesses_output", "security.auth.lp3_bruteforce_guesses_output",
     "Сколько паролей атакующий проверит за сутки при лимитах и блокировке",
     ["authentication", "threat_modeling", "rate_limiting", "secure_design", "account_security"], ["lead"], 2.0, 480,
     "меньшее из лимита по IP и циклов «серия попыток + блокировка» по учётным записям"),
    ("analyst", "lp3_cohort_active_output", "analyst.retention.lp3_cohort_active_output",
     "Активные пользователи в месяце по когортам и кривой удержания",
     ["retention", "cohort_analysis", "product_metrics", "forecasting", "data_analysis"], ["senior", "lead"], 1.7, 480,
     "удержание по возрасту когорты, а не по календарному месяцу; месяц привлечения — 100 %"),
    ("common", "lp3_backpressure_drops_output", "common.queues.lp3_backpressure_drops_output",
     "Сколько сообщений потеряется при всплеске перед очередью",
     ["queues", "reliability", "capacity_planning", "distributed_systems", "resilience"], ["senior", "lead"], 1.7, 420,
     "пошаговая модель очереди ограниченной ёмкости против сравнения средних"),
]


def main() -> None:
    for d, mod, fid, title, skills, grades, b, t, core in LP3:
        grades_ru = ", ".join(grades)
        doc = {
            "family_id": fid, "title": title, "direction": d, "skills": skills, "target_grades": grades,
            "format": "predict_output", "language": "text",
            "invariants": {"extra": {"wave": "LP-3", "answer": "typed", "key_varies": True}},
            "time_limit_s": t, "canary": False,
            "prior_difficulty": {"b": b, "a": 1.3, "sigma_variant": 0.3,
                                 "basis": (f"Априорная, до калибровки на людях (a = 1,3: ввод ответа, угадывание "
                                           f"исключено). Уровень {grades_ru}: {core}; наивный подход даёт другой "
                                           f"ответ, формула в условии не названа.")},
            "generator": f"assessment_bank.families.{d}.{mod}", "version": 1,
            "description": (f"Волна LP-3: {title.lower()}. Ответ вводится; программа-модель разбирает показанные "
                            f"данные и считает ключ, ключ меняется от варианта к варианту."),
        }
        path = ROOT / d / f"{mod}.yaml"
        path.write_text("# Волна LP-3 (tools/bank_lp3_yaml.py): расчётная задача старшего грейда с вводом ответа.\n"
                        + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
        print(path.relative_to(ROOT.parents[2]))


if __name__ == "__main__":
    main()
