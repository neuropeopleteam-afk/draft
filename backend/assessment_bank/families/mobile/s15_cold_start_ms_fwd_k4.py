"""mobile.cold_start_ms.middle_fwd_k4 — mcq_concept (Middle). Бюджет времени холодного старта мобильного приложения — прямой расчёт с учётом: ленивая инициализация, параллельный пул, работа с Keystore, первый кадр UI.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«cold_start_ms» в families/_w2010_scale_cat_mobile.py, ступень 4 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'mobile.cold_start_ms.middle_fwd_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
