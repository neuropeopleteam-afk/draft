"""analyst.bpmn_sla_cycle.lead_solve_au_k4 — mcq_concept (Middle). Нормативное время сквозного бизнес-процесса (BPMN) с ветвлениями — обратная задача: наибольший допустимый вход «длительность автоматической проверки, мин» с учётом: ветка ручной экспертизы, петля доработки, ожидание в очередях, параллельный шлюз.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«bpmn_sla_cycle» в families/_w2010_scale_cat_analyst.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'analyst.bpmn_sla_cycle.lead_solve_au_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
