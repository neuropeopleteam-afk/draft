"""mobile.principal.rollout_segments_mcq — mcq_concept (Principal): решение о поэтапной выкатке по сегментам.

Новая версия приложения выкачена на 5 % пользователей; по четырём сегментам (версии ОС) — число сессий и сессий со
сбоем. Порог: доля сессий со сбоем не выше L = p₀ + δ (p₀ — доля у прежней версии на миллионах сессий). Правило:
продолжать в сегменте, если с уверенностью 95 % доля ниже порога (верхняя граница интервала < L); откатывать, если с
уверенностью 95 % выше (нижняя граница > L); иначе — держать долю и набирать данные. Числа подобраны так, что
решение одинаково для интервала Уилсона и нормального приближения, для z = 1,645 и z = 1,96 (нет двусмысленности
«одно- или двусторонний»).

Дистракторы (фиксированный состав, все — разные наборы решений): ``point`` — сравнение точечной оценки с порогом
(без «держать»); ``pooled`` — одно решение по сумме сегментов для всех; ``baseline`` — интервал сравнивается с p₀
вместо порога. Ключ проверяется исполнением: программа считает интервалы Уилсона по тем же числам.
"""
from __future__ import annotations

import math

from assessment_bank.families._lead_b_utils import computed_mcq, ru_num
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.principal.rollout_segments_mcq"

CONTEXTS = ["мобильный банк", "приложение доставки", "приложение такси", "маркетплейс", "приложение для заметок",
            "стриминговый сервис", "приложение авиакомпании", "фитнес-приложение"]
ANDROID = ["Android 10–11", "Android 12", "Android 13", "Android 14–15"]
IOS = ["iOS 16", "iOS 17", "iOS 18"]
ZS = (1.645, 1.96)

PROGRAM = '''import math

SEGMENTS = {segs!r}   # сегмент: (сессий, сессий со сбоем)
LIMIT = {limit!r}     # порог доли сессий со сбоем
Z = 1.96


def wilson(x, n):
    p = x / n
    c = (p + Z * Z / (2 * n)) / (1 + Z * Z / n)
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    return c - h, c + h


out = []
for name, (n, x) in SEGMENTS.items():
    lo, hi = wilson(x, n)
    out.append(name + " — " + ("продолжить" if hi < LIMIT else "откатить" if lo > LIMIT else "держать"))
print("; ".join(out))
'''


def _wilson(x, n, z):
    p = x / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return c - h, c + h


def _wald(x, n, z):
    p = x / n
    h = z * math.sqrt(p * (1 - p) / n)
    return p - h, p + h


def _decide(x, n, limit):
    """Решение, одинаковое для всех методов и z, иначе None. Граница не ближе 3 % от порога."""
    res = set()
    for z in ZS:
        for f in (_wilson, _wald):
            lo, hi = f(x, n, z)
            if abs(hi - limit) < 0.03 * limit or abs(lo - limit) < 0.03 * limit:
                return None
            res.add("продолжить" if hi < limit else "откатить" if lo > limit else "держать")
    return res.pop() if len(res) == 1 else None


def _text(names, decisions) -> str:
    return "; ".join(f"{n} — {d}" for n, d in zip(names, decisions))


def _segment(rng, kind, p0, limit):
    for _ in range(200):
        n = rng.choice([6000, 8000, 12000, 15000, 20000, 30000, 40000, 60000, 90000])
        if kind == "продолжить":
            r = p0 * rng.uniform(0.5, 1.15)
        elif kind == "откатить":
            r = limit * rng.uniform(1.4, 2.2)
        else:
            r = limit * rng.uniform(0.82, 1.18)
        x = max(1, round(r * n))
        if _decide(x, n, limit) == kind:
            return n, x
    return None


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    for _ in range(3000):
        names = sorted(rng.sample(ANDROID, 2), key=ANDROID.index) + sorted(rng.sample(IOS, 2), key=IOS.index)
        p0 = rng.choice([0.0020, 0.0025, 0.0030, 0.0035, 0.0040])
        delta = rng.choice([0.0010, 0.0015, 0.0020])
        limit = round(p0 + delta, 6)
        kinds = [rng.choice(["продолжить", "держать", "откатить"]) for _ in range(4)]
        if "держать" not in kinds or len(set(kinds)) < 2:
            continue
        segs = [_segment(rng, k, p0, limit) for k in kinds]
        if any(s is None for s in segs):
            continue
        # точечное правило: без «держать»
        point = ["продолжить" if x / n <= limit else "откатить" for n, x in segs]
        pn = sum(n for n, _ in segs)
        px = sum(x for _, x in segs)
        pooled_d = _decide(px, pn, limit)
        base = [_decide(x, n, p0) for n, x in segs]
        if pooled_d is None or any(b is None for b in base):
            continue
        good = _text(names, kinds)
        opts = [good, _text(names, point), _text(names, [pooled_d] * 4), _text(names, base)]
        # набор типов решений верного варианта не выделяется: у какого-то дистрактора типов не меньше
        sig = [len({d for d in o.split("; ") for d in [d.split(" — ")[1]]}) for o in opts]
        if len(set(opts)) == 4 and max(sig[1:]) >= sig[0]:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось построить вариант")
    segd = {nm: (n, x) for nm, (n, x) in zip(names, segs)}
    rows = ["сегмент | сессий на новой версии | сессий со сбоем"]
    rows += [f"{nm} | {ru_num(n)} | {ru_num(x)}" for nm, (n, x) in segd.items()]
    code = "\n".join(rows)
    p0s, lims = ru_num(round(p0 * 100, 3)), ru_num(round(limit * 100, 3))
    stem = (f"{ctx.capitalize()}: новая версия выкачена на 5 % пользователей, выкатку можно вести отдельно по "
            f"сегментам (версиям ОС). У прежней версии доля сессий со сбоем — {p0s} % (миллионы сессий); порог для "
            f"новой — не выше {lims} %. Правило: в сегменте продолжать выкатку, если с уверенностью 95 % доля "
            f"сбоев ниже порога; откатывать, если с уверенностью 95 % выше порога; иначе — держать текущую долю и "
            f"набирать данные. Данные за сутки — в таблице. Какие решения верны?")
    parts = []
    for nm, (n, x) in segd.items():
        lo, hi = _wilson(x, n, 1.96)
        parts.append(f"{nm}: {ru_num(round(100 * x / n, 3))} % [{ru_num(round(100 * lo, 3))}; "
                     f"{ru_num(round(100 * hi, 3))}]")
    plo, phi = _wilson(px, pn, 1.96)
    why = (f"Интервал для доли сбоев (Уилсон, 95 %; нормальное приближение и одностороннее z = 1,645 дают те же "
           f"решения): {'; '.join(parts)}. Порог {lims} %: верхняя граница ниже — продолжать, нижняя выше — "
           f"откатывать, порог внутри — держать. Точечная оценка без интервала путает «мало данных» с «хорошо» или "
           f"«плохо». Сумма сегментов ({ru_num(round(100 * px / pn, 3))} % [{ru_num(round(100 * plo, 3))}; "
           f"{ru_num(round(100 * phi, 3))}]) прячет плохой сегмент за хорошими — решение по сегментам. Сравнение "
           f"с долей прежней версии ({p0s} %) вместо порога смешивает «не хуже прежней» и «в пределах допустимого».")
    program = PROGRAM.format(segs=segd, limit=limit)
    return computed_mcq(FAMILY_ID, seed, rng, stem=stem, correct=good, distractors=opts[1:], program=program,
                        why=why, context=ctx, code=code, language="text",
                        note="Программа считает интервалы Уилсона (95 %) по тем же числам и применяет правило "
                             "выкатки к каждому сегменту.",
                        params={"p0": p0, "limit": limit})
