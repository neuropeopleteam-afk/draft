"""frontend.polling_load.middle_solve_p_k2 — mcq_concept (Middle). Нагрузка от поллинга вкладок браузера — обратная задача: наименьший допустимый вход «период опроса, с» с учётом: вкладки, скрытые вкладки.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«polling_load» в families/_w2010_scale_cat_frontend.py, ступень 2 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'frontend.polling_load.middle_solve_p_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
