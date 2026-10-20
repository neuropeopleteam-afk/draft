"""security.soc_triage.senior_solve_al_k4 — mcq_concept (Lead). Размер смены инженеров мониторинга инцидентов (SOC) — обратная задача: наибольший допустимый вход «сырых оповещений за смену» с учётом: время разбора, углублённая проверка, длительность смены, запас по загрузке.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«soc_triage» в families/_w2010_scale_cat_security.py, ступень 4 из 5, обратная задача по «al»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "security.soc_triage.senior_solve_al_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
