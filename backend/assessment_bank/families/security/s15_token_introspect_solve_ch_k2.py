"""security.token_introspect.middle_solve_ch_k2 — mcq_concept (Middle). Пропускная способность сервиса проверки токенов доступа — обратная задача: наименьший допустимый вход «доля попаданий в кэш, %» с учётом: локальный кэш, пиковый коэффициент.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«token_introspect» в families/_w2010_scale_cat_security.py, ступень 2 из 5, обратная задача по «ch»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "security.token_introspect.middle_solve_ch_k2"
N_ABOVE = (0, 1)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
