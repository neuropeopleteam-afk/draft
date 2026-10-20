"""mobile.frame_jank_budget.middle_fwd_k4 — mcq_concept (Middle). Нагрузка главного потока UI при прокрутке сложной ленты — прямой расчёт с учётом: мемоизация состояния, фоновый парсинг, сложные тени, анимации переходов.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«frame_jank_budget» в families/_w2010_scale_cat_mobile.py, ступень 4 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'mobile.frame_jank_budget.middle_fwd_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
