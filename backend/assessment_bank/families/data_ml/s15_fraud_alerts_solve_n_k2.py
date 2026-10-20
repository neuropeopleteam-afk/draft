"""data_ml.fraud_alerts.junior_solve_n_k2 — mcq_concept (Junior). Нагрузка на аналитиков от алертов модели антифрода — обратная задача: наибольший допустимый вход «операций в сутки» с учётом: полнота, точность.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«fraud_alerts» в families/_w2010_scale_cat_data_ml.py, ступень 2 из 5, обратная задача по «n»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_ml.fraud_alerts.junior_solve_n_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
