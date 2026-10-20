"""frontend.image_weight.senior_solve_n_k4 — mcq_concept (Lead). Вес картинок первого экрана с учётом DPR и форматов — обратная задача: наибольший допустимый вход «число карточек» с учётом: DPR экрана, ленивая загрузка, переход на AVIF, заголовки.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«image_weight» в families/_w2010_scale_cat_frontend.py, ступень 4 из 5, обратная задача по «n»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "frontend.image_weight.senior_solve_n_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
