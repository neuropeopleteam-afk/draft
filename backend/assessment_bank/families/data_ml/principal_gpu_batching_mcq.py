"""data_ml.serving.principal_gpu_batching_mcq — mcq_concept (Principal). Динамический батчинг на GPU — наибольший батч по SLO (ожидание + прогон) и число GPU с запасом загрузки.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["data_ml.serving.principal_gpu_batching_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "data_ml.serving.principal_gpu_batching_mcq"
generate = make(FAMILY_ID)
