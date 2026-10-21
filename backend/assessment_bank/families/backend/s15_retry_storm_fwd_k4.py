"""backend.retry_storm.middle_fwd_k4 — mcq_concept (Middle). Нагрузка на зависимость при шторме ретраев — прямой расчёт с учётом: деление по подам, ретраи на двух уровнях, пиковый коэффициент, отброс лимитером.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«retry_storm» в families/_w2010_scale_cat_backend.py, ступень 4 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'backend.retry_storm.middle_fwd_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
