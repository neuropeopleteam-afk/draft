"""analyst.backlog_story_points.middle_solve_us_k3 — mcq_concept (Middle). Оценка трудоёмкости и сроков реализации эпика требований — обратная задача: наибольший допустимый вход «число User Stories в эпике» с учётом: граничные сценарии, уточнение требований, число разработчиков.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«backlog_story_points» в families/_w2010_scale_cat_analyst.py, ступень 3 из 5, обратная задача по «us»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "analyst.backlog_story_points.middle_solve_us_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
