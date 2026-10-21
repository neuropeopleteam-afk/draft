"""common.backup_window.middle_fwd_k4 — mcq_concept (Middle). Длительность резервного копирования в окне обслуживания — прямой расчёт с учётом: инкрементальная копия, сжатие, проверка контрольных сумм, параллельные потоки.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«backup_window» в families/_w2010_scale_cat_common.py, ступень 4 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'common.backup_window.middle_fwd_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
