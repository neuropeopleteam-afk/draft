"""devops.es_shards.middle_fwd_k4 — mcq_concept (Middle). Число шардов индекса Elasticsearch — прямой расчёт с учётом: накладные индекса, размер шарда, реплики, рост.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«es_shards» в families/_w2010_scale_cat_devops.py, ступень 4 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "devops.es_shards.middle_fwd_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
