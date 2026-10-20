"""common.retry_backoff.senior_fwd_k5 — mcq_concept (Senior). Худшее время до ошибки при ретраях с экспоненциальной паузой — прямой расчёт с учётом: TLS-рукопожатия, джиттер пауз, сетевые задержки, DNS-запрос, обработка ошибки.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«retry_backoff» в families/_w2010_scale_cat_common.py, ступень 5 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "common.retry_backoff.senior_fwd_k5"
N_ABOVE = (0, 1, 2)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
