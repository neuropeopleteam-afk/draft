"""common.retry_backoff.intern_fwd_k2 — mcq_concept (Стажёр). Худшее время до ошибки при ретраях с экспоненциальной паузой — прямой расчёт с учётом: TLS-рукопожатия, джиттер пауз.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«retry_backoff» в families/_w2010_scale_cat_common.py, ступень 2 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "common.retry_backoff.intern_fwd_k2"
N_ABOVE = (0, 1, 2)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
