"""analyst.bpmn_sla_cycle.middle_solve_au_k2 — mcq_concept (Middle). Нормативное время сквозного бизнес-процесса (BPMN) с ветвлениями — обратная задача: наибольший допустимый вход «длительность автоматической проверки, мин» с учётом: ветка ручной экспертизы, петля доработки.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«bpmn_sla_cycle» в families/_w2010_scale_cat_analyst.py, ступень 2 из 5, обратная задача по «au»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "analyst.bpmn_sla_cycle.middle_solve_au_k2"
N_ABOVE = (1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
