"""Чистка адаптивного пула: семейства, слабые по калибровке панелью моделей (модель, не люди).

Флаг ``ASSESSMENT_WEAK_EXCLUDE`` (по умолчанию выключен). Включён — эти семейства не выдаются ни в основной части, ни в
дотестировании (как фильтр по стеку: уже выданные в сессии задания остаются и учитываются). Выключен — пул как раньше.

Список — из банка (ветка feat/bank-core-plus, ``reports/weak_families.json``, поле ``exclude``): отрицательная
дискриминация шага; панель не информативна (p = 0/1); a < 0,6; a_eff < 0,55; p на уровне угадывания при r_pbis < 0,2;
неизоморфные варианты при σ > 1,0. Канарейки и open_answer в список не входят.

Почему за флагом, а не по умолчанию: на симуляции всего пути (docs/validation/GRADE_ACCURACY.md, раздел «Чистка
пула») исключение улучшает точность и завышение только в мире, где эти семейства на деле слабые, а повтор (κw)
в обоих мирах ниже, чем без исключения, — меньше сменных семейств для второй попытки. Новые значения по умолчанию —
только если лучше по всем ограничениям; здесь — нет. Решение о включении — по калибровке на людях или вместе с
сильными семействами у порогов (добор банка).
"""
from __future__ import annotations

# 21.10: убраны 5 семейств, выведенных из банка по форме ключа (А3; в банке их нет — поведение не меняется):
# common.git.move_commits_mcq, data_ml.sql.latest_record_fix, data_ml.stats.ztest_fix, backend.go.map_race_fix,
# security.supply.dependency_patch_fix
WEAK_FAMILIES: frozenset[str] = frozenset("""
backend.db.overbooking_ob3 backend.go.defer_recover_output backend.go.slice_append_output
backend.kafka.offset_commit_mcq backend.py.idempotency_coarse_ob3 common.conc.async_lost_update_ob3
common.db.index_plan_mcq common.db.tx_isolation_mcq common.perf.fanout_tail_mcq common.time.tz_report_ob3
data_ml.ab.sample_size_mcq data_ml.stats.mean_median_output frontend.a11y.focus_trap_ob3
frontend.js.microtask_order frontend.react.state_batch_mcq frontend.ts.nullish_mcq qa.api.cursor_pagination_ob3
qa.pytest.shared_state_ob3 security.access.owner_check_bug security.auth.token_validation_ob3
security.crypto.aead_mcq""".split())

WEAK_SOURCE = "банк feat/bank-core-plus 5493728, reports/weak_families.json (калибровка панелью моделей, не люди)"


def weak_excluded(settings=None) -> frozenset[str]:
    """Семейства, не выдаваемые кандидатам при включённом ``ASSESSMENT_WEAK_EXCLUDE``; при выключенном — пусто."""
    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()
    return WEAK_FAMILIES if getattr(settings, "assessment_weak_exclude", False) else frozenset()
