"""frontend.principal_v2.watermark_late_admission_bug — find_bug (principal). Frontend-разработка: Потеря граничного события на стыке водяного знака и допустимого опоздания.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'frontend.principal_v2.watermark_late_admission_bug'
generate = make_lp_v2('frontend', 5)
