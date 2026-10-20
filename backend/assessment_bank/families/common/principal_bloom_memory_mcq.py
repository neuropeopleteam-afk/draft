"""common.alg.principal_bloom_memory_mcq — mcq_concept (Principal): память под фильтры Блума с запасом роста.

Фильтр Блума на n элементов с долей ложных срабатываний p: m = −n·ln p / (ln 2)² бит, k = (m/n)·ln 2 хэш-функций.
Данные разбиты на S шардов поровну, у каждого шарда свой фильтр; фильтры строятся на объём через год (рост g % в
месяц). Вопрос: сколько МиБ памяти на все фильтры (бит → байт → МиБ, округление вверх до целых МиБ). Ловушки:
биты вместо байт, log10 вместо ln, без роста, на один шард, p в процентах как доля, вдвое больше p.
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import num, numeric_variant

FAMILY_ID = "common.alg.principal_bloom_memory_mcq"
CONTEXTS = ["проверка «пароль в утечках»", "дедупликация событий", "проверка занятых логинов", "антифрод: виденные карты",
            "краулер: посещённые URL", "проверка промокодов", "LSM-хранилище: ключи SST-файлов", "рассылки: отписавшиеся"]

MODEL = '''
from math import ceil, log, log10

def mib(P, bits=False, use_log10=False, growth=True, one_shard=False, pct=False, p_mult=1):
    n_total = P["n"] * 1_000_000 * ((1 + P["g"] / 100) ** 12 if growth else 1)
    n = n_total / P["S"]
    p = P["p"] / (1 if pct else 100) * p_mult
    if p >= 1:
        return None
    lnp = log10(p) if use_log10 else log(p)
    m_bits = -n * lnp / (log(2) ** 2)
    total = m_bits * (1 if one_shard else P["S"])
    return ceil(total / (1 if bits else 8) / 2 ** 20)

def answer(P):
    return mib(P)

def traps(P):
    return {"bits": mib(P, bits=True), "log10": mib(P, use_log10=True), "no_growth": mib(P, growth=False),
            "one_shard": mib(P, one_shard=True), "pct_as_share": mib(P, pct=True), "double_p": mib(P, p_mult=2),
            "tenth_p": mib(P, p_mult=0.1)}

def fmt(x):
    return f"{x:,} МиБ".replace(",", "\\u00a0")
'''


def _sample(rng):
    return {"n": rng.choice([50, 80, 120, 200, 300, 500]), "g": rng.choice([2, 3, 5, 8]),
            "S": rng.choice([8, 16, 32, 64]), "p": rng.choice([0.1, 0.5, 1.0, 2.0])}


def _stem(P, ctx):
    return (f"{ctx[0].upper() + ctx[1:]}: сейчас {P['n']} млн элементов, рост — {P['g']} % в месяц (сложный процент). "
            f"Данные разбиты на {P['S']} шардов поровну, у каждого шарда свой фильтр Блума с оптимальным числом хэш-"
            f"функций и долей ложных срабатываний {num(P['p'], 1)} %. Фильтры строят сразу на объём через 12 месяцев.\n\n"
            "Сколько памяти нужно на все фильтры (МиБ, с округлением вверх)?")


def _explain(P, a, traps):
    return (f"Оптимальный фильтр: m = −n·ln p / (ln 2)² бит ≈ {num(-__import__('math').log(P['p'] / 100) / 0.4805, 2)} "
            f"бит на элемент при p = {num(P['p'] / 100, 3)}. Элементов через год: {P['n']} млн · "
            f"{num((1 + P['g'] / 100) ** 12, 3)}; сумма по шардам равна фильтру на все элементы; бит → байт → МиБ: "
            f"{num(a)} МиБ.")


TRAP_DESC = {"bits": "биты не переведены в байты", "log10": "десятичный логарифм вместо натурального",
             "no_growth": "без роста за год", "one_shard": "только один шард", "pct_as_share": "проценты приняты за долю",
             "double_p": "доля ложных срабатываний вдвое больше", "tenth_p": "доля ложных срабатываний в 10 раз меньше"}


def generate(seed: int):
    return numeric_variant(FAMILY_ID, seed, contexts=CONTEXTS, sample=_sample, model=MODEL, stem=_stem,
                           explain=_explain, rel=0.1, abs_min=2, trap_first="bits", trap_desc=TRAP_DESC)
