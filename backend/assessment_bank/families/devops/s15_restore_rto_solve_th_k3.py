"""devops.restore_rto.senior_solve_th_k3 — mcq_concept (Senior). Время восстановления базы из бэкапа (RTO) — обратная задача: наименьший допустимый вход «число потоков восстановления» с учётом: потоки, накат WAL, проверки.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«restore_rto» в families/_w2010_scale_cat_devops.py, ступень 3 из 5, обратная задача по «th»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "devops.restore_rto.senior_solve_th_k3"
N_ABOVE = (0, 1, 2)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
