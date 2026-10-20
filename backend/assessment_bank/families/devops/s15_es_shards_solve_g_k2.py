"""devops.es_shards.junior_solve_g_k2 — mcq_concept (Junior). Число шардов индекса Elasticsearch — обратная задача: наибольший допустимый вход «объём в сутки, ГБ» с учётом: накладные индекса, размер шарда.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«es_shards» в families/_w2010_scale_cat_devops.py, ступень 2 из 5, обратная задача по «g»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "devops.es_shards.junior_solve_g_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
