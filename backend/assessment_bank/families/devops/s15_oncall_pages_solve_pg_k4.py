"""devops.oncall_pages.lead_solve_pg_k4 — mcq_concept (Lead). Нагрузка дежурного по алертам — обратная задача: наибольший допустимый вход «доля критичных сработок, %» с учётом: доля пейджей, группировка, чистка шума, ротация.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«oncall_pages» в families/_w2010_scale_cat_devops.py, ступень 4 из 5, обратная задача по «pg»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "devops.oncall_pages.lead_solve_pg_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
