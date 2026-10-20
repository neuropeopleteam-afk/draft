"""common.alg.principal_rehash_moves_mcq — mcq_concept (Principal): сколько ключей переедет при решардинге mod N.

Ключи — целые id 0…K−1, шард = id mod N. План: в два шага N → N1 → N2 (каждый шаг — полный перенос ключей,
сменивших шард). Сколько всего переносов ключей за оба шага? На шаге N → M ключ остаётся, если id mod N = id mod M:
в каждом блоке длины НОК(N, M) таких ровно min(N, M). Ловушки: оценка согласованного хэширования K·Δ/M, «переносы
только на новые шарды», прямой переход N → N2 (без промежуточного шага), доля 1 − 1/M, половина ключей.
``brute`` — перебор всех id.
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import num, numeric_variant

FAMILY_ID = "common.alg.principal_rehash_moves_mcq"
CONTEXTS = ["кэш сессий", "шардированная таблица заказов", "хранилище корзин", "очередь задач по клиентам",
            "хранилище событий аналитики", "кэш профилей", "шардированный счётчик лимитов", "хранилище черновиков"]

MODEL = '''
from math import gcd

def moved(K, n, m):
    L = n * m // gcd(n, m)
    q, rest = divmod(K, L)
    stay = q * min(n, m) + min(rest, min(n, m))
    return K - stay

def answer(P):
    return moved(P["K"], P["N"], P["N1"]) + moved(P["K"], P["N1"], P["N2"])

def brute(P):
    c = 0
    for k in range(P["K"]):
        c += (k % P["N"] != k % P["N1"]) + (k % P["N1"] != k % P["N2"])
    return c

def traps(P):
    K, N, N1, N2 = P["K"], P["N"], P["N1"], P["N2"]
    return {"consistent": round(K * (N1 - N) / N1 + K * (N2 - N1) / N2), "direct": moved(K, N, N2),
            "one_minus": round(K * (1 - 1 / N1) + K * (1 - 1 / N2)), "half": K,
            "new_only": round(K * (N2 - N) / N2), "last_step": moved(K, N1, N2), "all_twice": 2 * K,
            "stay_one_per_lcm": 2 * K - round(K / (N * N1 // gcd(N, N1))) - round(K / (N1 * N2 // gcd(N1, N2))),
            "one_minus_old": round(K * (1 - 1 / N) + K * (1 - 1 / N1))}

def fmt(x):
    return f"{x:,}".replace(",", "\\u00a0")
'''


def _sample(rng):
    n = rng.choice([4, 6, 8, 10, 12, 16])
    n1 = n + rng.choice([2, 4, n // 2, n])
    n2 = n1 + rng.choice([2, 4, n1 // 2, n1])
    return {"K": rng.choice([12_000, 24_000, 36_000, 48_000, 60_000, 72_000]) + rng.choice([0, 7, 13, 101]),
            "N": n, "N1": n1, "N2": n2}


def _stem(P, ctx):
    return (f"{ctx[0].upper() + ctx[1:]}: {num(P['K'])} ключей с целыми id от 0 до {num(P['K'] - 1)}, шард ключа — "
            f"id mod N, сейчас N = {P['N']}. План роста — в два шага: {P['N']} → {P['N1']} шардов, после завершения "
            f"переноса — {P['N1']} → {P['N2']}. На каждом шаге переносятся ровно те ключи, у которых сменился шард.\n\n"
            "Сколько всего переносов ключей будет за оба шага (ключ, перенесённый дважды, считается дважды)?")


def _moved(K, n, m):
    from math import gcd
    L = n * m // gcd(n, m)
    q, rest = divmod(K, L)
    return K - (q * min(n, m) + min(rest, min(n, m)))


def _explain(P, a, traps):
    s1, s2 = _moved(P["K"], P["N"], P["N1"]), _moved(P["K"], P["N1"], P["N2"])
    return (f"Ключ остаётся на шаге N → M, если id mod N = id mod M: в каждом блоке длины НОК(N, M) таких id ровно "
            f"min(N, M). Шаг {P['N']} → {P['N1']}: переносов {num(s1)}; шаг {P['N1']} → {P['N2']}: {num(s2)}. Всего "
            f"{num(a)} — при mod N переезжает почти всё, в отличие от согласованного хэширования (≈ K·Δ/M).")


TRAP_DESC = {"consistent": "оценка согласованного хэширования K·Δ/M", "direct": "сразу N → N2 без промежуточного шага",
             "one_minus": "доля 1 − 1/M на каждом шаге", "half": "по половине ключей на каждом шаге",
             "new_only": "переносы только на новые шарды", "last_step": "только второй шаг",
             "all_twice": "все ключи на каждом шаге", "stay_one_per_lcm": "остаётся один ключ на блок НОК вместо min(N, M)",
             "one_minus_old": "доля 1 − 1/N по старому числу шардов"}


def generate(seed: int):
    return numeric_variant(FAMILY_ID, seed, contexts=CONTEXTS, sample=_sample, model=MODEL, stem=_stem,
                           explain=_explain, rel=0.06, abs_min=50, trap_first="consistent", trap_desc=TRAP_DESC)
