"""analyst.backlog_story_points.middle_solve_ac_k2 — mcq_concept (Middle). Оценка трудоёмкости и сроков реализации эпика требований — обратная задача: наибольший допустимый вход «число сценариев Gherkin на историю» с учётом: граничные сценарии, уточнение требований.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«backlog_story_points» в families/_w2010_scale_cat_analyst.py, ступень 2 из 5, обратная задача по «ac»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "analyst.backlog_story_points.middle_solve_ac_k2"
N_ABOVE = (1, 2)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
