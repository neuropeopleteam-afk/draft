"""common.crypto.principal_gcm_key_rotation_mcq — mcq_concept (Principal): как часто менять ключ AES-GCM.

Флот из m экземпляров шифрует одним ключом AES-GCM со случайными 96-битными IV; по NIST SP 800-38D число вызовов
шифрования одним ключом при случайных IV — не больше 2^32. Сейчас каждый экземпляр шифрует v сообщений в секунду,
трафик растёт на g % в месяц; период ротации задаётся на год вперёд — по нагрузке конца года. Вопрос: наибольший
период ротации в часах (целых). Ловушки: на один экземпляр, без роста, граница «дня рождения» 2^48, 2^64,
рост за месяц вместо года, предел 2^31.
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import num, numeric_variant

FAMILY_ID = "common.crypto.principal_gcm_key_rotation_mcq"
CONTEXTS = ["шифрование полей карт в платёжном шлюзе", "шифрование токенов сессий", "шифрование персональных данных в CRM",
            "шифрование вложений в мессенджере", "шифрование событий аудита", "шифрование резервных копий профилей",
            "шифрование черновиков документов", "шифрование медкарт в клинике"]

MODEL = '''
from math import floor

def hours(P, limit=2 ** 32, fleet=True, growth=True, months=12):
    rate = P["v"] * (P["m"] if fleet else 1) * ((1 + P["g"] / 100) ** months if growth else 1)
    return floor(limit / rate / 3600)

def answer(P):
    return hours(P)

def brute(P):
    rate = P["v"] * P["m"]
    for _ in range(12):
        rate *= 1 + P["g"] / 100
    h = 0
    while (h + 1) * 3600 * rate <= 2 ** 32:
        h += 1
    return h

def traps(P):
    return {"per_instance": hours(P, fleet=False), "no_growth": hours(P, growth=False), "birthday48": hours(P, limit=2 ** 48),
            "limit31": hours(P, limit=2 ** 31), "month_growth": hours(P, months=1), "limit30": hours(P, limit=2 ** 30),
            "double_rate": hours(P) // 2}

def fmt(x):
    return f"{x:,} ч".replace(",", "\\u00a0")
'''


def _sample(rng):
    return {"m": rng.choice([4, 6, 8, 12, 16, 24]), "v": rng.choice([200, 300, 500, 800, 1000, 1500, 2000]),
            "g": rng.choice([3, 5, 8, 10])}


def _accept(P, ns):
    return 4 <= ns["answer"](P) <= 5000


def _stem(P, ctx):
    return (f"{ctx[0].upper() + ctx[1:]}: {P['m']} экземпляров сервиса шифруют одним общим ключом AES-GCM со случайным "
            f"96-битным IV на каждое сообщение. Сейчас каждый экземпляр шифрует ≈ {num(P['v'])} сообщений в секунду, "
            f"трафик растёт на {P['g']} % в месяц (сложный процент). Ограничение NIST SP 800-38D для случайных IV — не "
            f"больше 2^32 шифрований одним ключом. Период ротации ключа задают на год вперёд, по нагрузке конца года.\n\n"
            "Какой наибольший период ротации ключа (в целых часах) соблюдает ограничение?")


def _explain(P, a, traps):
    rate = P["v"] * P["m"] * (1 + P["g"] / 100) ** 12
    return (f"Ключ общий — считаем весь флот: {P['m']} · {num(P['v'])} = {num(P['m'] * P['v'])} шифрований в секунду "
            f"сейчас, через 12 месяцев — ≈ {num(rate)}. 2^32 ≈ 4,29 млрд шифрований хватает на {a} ч; ограничение "
            "касается числа вызовов с одним ключом, а не каждого экземпляра.")


TRAP_DESC = {"per_instance": "предел на каждый экземпляр, а не на общий ключ", "no_growth": "по текущей нагрузке без роста",
             "birthday48": "граница «дня рождения» 2^48 вместо предела NIST", "limit31": "предел 2^31",
             "month_growth": "рост только за месяц", "limit30": "предел 2^30", "double_rate": "период вдвое короче нужного"}


def generate(seed: int):
    return numeric_variant(FAMILY_ID, seed, contexts=CONTEXTS, sample=_sample, model=MODEL, stem=_stem,
                           explain=_explain, accept=_accept, rel=0.15, abs_min=1, trap_first="per_instance",
                           trap_desc=TRAP_DESC)
