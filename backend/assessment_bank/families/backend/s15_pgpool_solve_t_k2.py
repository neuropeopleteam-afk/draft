"""backend.pgpool.middle_solve_t_k2 — mcq_concept (Middle). Размер пула соединений PostgreSQL по закону Литтла — обратная задача: наибольший допустимый вход «время удержания соединения» с учётом: пиковый коэффициент, запас утилизации.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«pgpool» в families/_w2010_scale_cat_backend.py, ступень 2 из 5, обратная задача по «t»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "backend.pgpool.middle_solve_t_k2"
N_ABOVE = (0, 1, 2)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
