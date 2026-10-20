"""qa.device_matrix.senior_fwd_k5 — mcq_concept (Senior). Число прогонов в матрице устройств — прямой расчёт с учётом: локали, pairwise-сокращение, тесты на комбинацию, перезапуски, smoke-прогоны.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«device_matrix» в families/_w2010_scale_cat_qa.py, ступень 5 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "qa.device_matrix.senior_fwd_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
