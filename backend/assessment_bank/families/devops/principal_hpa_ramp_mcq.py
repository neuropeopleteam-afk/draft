"""devops.k8s.principal_hpa_ramp_mcq — mcq_concept (Principal). minReplicas под линейный рост трафика — цикл HPA, запуск пода и readiness, текущие поды на 100 % CPU.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["devops.k8s.principal_hpa_ramp_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "devops.k8s.principal_hpa_ramp_mcq"
generate = make(FAMILY_ID)
