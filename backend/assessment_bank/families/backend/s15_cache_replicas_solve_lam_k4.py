"""backend.cache_replicas.senior_solve_lam_k4 — mcq_concept (Senior). Число реплик чтения PostgreSQL за кэшем Redis — обратная задача: наибольший допустимый вход «поток чтений, запросов в секунду» с учётом: ёмкость реплики, SQL-запросы на промах, запас по загрузке, применение WAL.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«cache_replicas» в families/_w2010_scale_cat_backend.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'backend.cache_replicas.senior_solve_lam_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
