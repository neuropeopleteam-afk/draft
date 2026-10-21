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
