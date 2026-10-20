"""analyst.bpmn_sla_cycle.lead_solve_doc_k5 — mcq_concept (Principal). Нормативное время сквозного бизнес-процесса (BPMN) с ветвлениями — обратная задача: наибольший допустимый вход «длительность формирования пакета, мин» с учётом: ветка ручной экспертизы, петля доработки, ожидание в очередях, параллельный шлюз, финальная регистрация.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«bpmn_sla_cycle» в families/_w2010_scale_cat_analyst.py, ступень 5 из 5, обратная задача по «doc»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "analyst.bpmn_sla_cycle.lead_solve_doc_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
