"""qa.bench_runs.senior_solve_dl_k3 — mcq_concept (Senior). Число прогонов бенчмарка для обнаружения регрессии — обратная задача: наименьший допустимый вход «детектируемая регрессия Δ, мс» с учётом: сценарии, версии, прогрев.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«bench_runs» в families/_w2010_scale_cat_qa.py, ступень 3 из 5, обратная задача по «dl»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "qa.bench_runs.senior_solve_dl_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
