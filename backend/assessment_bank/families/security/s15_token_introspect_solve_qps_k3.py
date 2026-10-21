"""security.token_introspect.middle_solve_qps_k3 — mcq_concept (Middle). Пропускная способность сервиса проверки токенов доступа — обратная задача: наибольший допустимый вход «внешний поток запросов/с» с учётом: локальный кэш, пиковый коэффициент, проверка отзыва.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«token_introspect» в families/_w2010_scale_cat_security.py, ступень 3 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'security.token_introspect.middle_solve_qps_k3'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
