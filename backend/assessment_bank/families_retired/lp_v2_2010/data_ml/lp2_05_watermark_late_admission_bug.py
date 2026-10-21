"""data_ml.principal_v2.watermark_late_admission_bug — find_bug (principal). Аналитика данных и ML: Потеря граничного события на стыке водяного знака и допустимого опоздания.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'data_ml.principal_v2.watermark_late_admission_bug'
generate = make_lp_v2('data_ml', 5)
