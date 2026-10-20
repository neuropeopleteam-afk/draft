"""data_ml.vector_index.middle_solve_n_k3 — mcq_concept (Middle). Объём векторного индекса для семантического поиска — обратная задача: наибольший допустимый вход «число векторов, млн» с учётом: сжатие PQ, граф HNSW, реплики.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«vector_index» в families/_w2010_scale_cat_data_ml.py, ступень 3 из 5, обратная задача по «n»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_ml.vector_index.middle_solve_n_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
