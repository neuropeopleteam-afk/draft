"""common.http.principal_cdn_origin_load_mcq — mcq_concept (Principal): нагрузка на origin за CDN с щитом.

H горячих объектов запрашиваются во всех P точках присутствия CDN (каждый — чаще раза в секунду), TTL — T секунд.
Без щита каждая точка обновляет каждый объект раз в TTL: H·P/T запросов в секунду. С origin shield точки ходят в
щит, щит — в origin: H/T. Хвост — λ запросов в секунду к редким объектам, доля попаданий в кэш у них h (с учётом
щита). stale-while-revalidate не меняет частоту обновлений. Вопрос: запросов в секунду к origin с щитом.
Ловушки: без щита, TTL в минутах, весь поток хвоста без кэша, хвост с щитом, умноженный на P, без хвоста.
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import num, numeric_variant

FAMILY_ID = "common.http.principal_cdn_origin_load_mcq"
CONTEXTS = ["картинки каталога", "страницы карточек товаров", "JSON-ответы витрины", "превью видео", "статика приложения",
            "обложки книг", "страницы новостей", "карточки объявлений"]

MODEL = '''
def rps(P, shield=True, tail=True, tail_cache=True, ttl_min=False, tail_x_pops=False):
    ttl = P["T"] * (60 if ttl_min else 1)
    hot = P["H"] / ttl * (1 if shield else P["P"])
    t = P["lam"] * (1 - P["h"] / 100) if tail_cache else P["lam"]
    if tail_x_pops:
        t *= P["P"]
    return round(hot + (t if tail else 0))

def answer(P):
    return rps(P)

def traps(P):
    return {"no_shield": rps(P, shield=False), "ttl_minutes": rps(P, ttl_min=True), "tail_uncached": rps(P, tail_cache=False),
            "no_tail": rps(P, tail=False), "tail_x_pops": rps(P, tail_x_pops=True),
            "no_shield_no_tail": rps(P, shield=False, tail=False)}

def fmt(x):
    return f"≈ {x:,} в секунду".replace(",", "\\u00a0")
'''


def _sample(rng):
    return {"H": rng.choice([20_000, 50_000, 80_000, 120_000, 200_000]), "P": rng.choice([12, 20, 30, 45, 60]),
            "T": rng.choice([60, 120, 300, 600, 900]), "lam": rng.choice([500, 800, 1200, 2000, 3000]),
            "h": rng.choice([40, 55, 70, 80, 90])}


def _stem(P, ctx):
    return (f"{ctx[0].upper() + ctx[1:]} отдаются через CDN: {P['P']} точек присутствия, включён origin shield (точки "
            f"ходят в щит, щит — в origin). {num(P['H'])} горячих объектов запрашиваются во всех точках чаще раза в "
            f"секунду; Cache-Control: max-age={P['T']}, stale-while-revalidate=30. Кроме того, ≈ {num(P['lam'])} "
            f"запросов в секунду приходится на редкие объекты, у них доля попаданий в кэш (точки + щит) — {P['h']} %.\n\n"
            "Сколько запросов в секунду в среднем приходит на origin?")


def _explain(P, a, traps):
    return (f"Горячий объект щит обновляет раз в TTL независимо от числа точек: {num(P['H'])} / {P['T']} = "
            f"{num(P['H'] / P['T'], 1)} в секунду (stale-while-revalidate меняет задержку, а не частоту). Хвост: "
            f"{num(P['lam'])} · (1 − {num(P['h'] / 100, 2)}) = {num(P['lam'] * (1 - P['h'] / 100), 1)}. Итого ≈ {num(a)}.")


TRAP_DESC = {"no_shield": "каждая точка обновляет объект сама (без щита)", "ttl_minutes": "max-age принят за минуты",
             "tail_uncached": "весь хвост мимо кэша", "no_tail": "без хвоста редких объектов",
             "tail_x_pops": "промахи хвоста умножены на число точек", "no_shield_no_tail": "без щита и без хвоста"}


def generate(seed: int):
    return numeric_variant(FAMILY_ID, seed, contexts=CONTEXTS, sample=_sample, model=MODEL, stem=_stem,
                           explain=_explain, rel=0.12, abs_min=5, trap_first="no_shield", trap_desc=TRAP_DESC)
