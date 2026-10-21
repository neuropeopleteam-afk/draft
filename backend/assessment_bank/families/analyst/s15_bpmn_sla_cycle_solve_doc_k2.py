"""analyst.bpmn_sla_cycle.junior_solve_doc_k2 — mcq_concept (Junior). Нормативное время сквозного бизнес-процесса (BPMN) с ветвлениями — обратная задача: наибольший допустимый вход «длительность формирования пакета, мин» с учётом: ветка ручной экспертизы, петля доработки.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«bpmn_sla_cycle» в families/_w2010_scale_cat_analyst.py, ступень 2 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'analyst.bpmn_sla_cycle.junior_solve_doc_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
