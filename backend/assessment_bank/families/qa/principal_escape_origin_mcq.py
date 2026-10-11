"""qa.principal.escape_origin_mcq — mcq_concept (Principal, короткое): сколько дефектов уйдёт в эксплуатацию за
квартал после усиления одного этапа конвейера, если дефекты возникают на разных этапах.

Этапы проверки идут по порядку, этап s находит дефект с вероятностью p_s (независимо). Дефект «в коде» проходит
все этапы, «в конфигурации окружения» появляется только к интеграционным тестам, «в интеграции с внешними
системами» — к сквозным (ранние этапы его не видят). Усилен один ранний этап (ревью кода или модульные тесты).
Ключ: R · Σ_источник n_o · Π_{s ≥ вход_o} (1 − p_s) после усиления.

Ловушки (пул; три выбираются так, что сколько их меньше ключа — 0–3 равновероятно):
  ниже ключа — ``all_through`` (все дефекты проходят все этапы), ``improved_all`` (усиленный ранний этап ловит и
  дефекты, появившиеся позже), ``code_only`` (учтены только дефекты кода);
  выше ключа — ``before`` (без усиления), ``last_only`` (ловит только последний этап), ``best_only`` (ловит только
  самый сильный этап).
Ключ проверяется исполнением: программа перебирает все 2^k исходов «нашёл / пропустил» по этапам для каждого
источника (иной путь, чем произведение в генераторе).
"""
from __future__ import annotations

from math import prod

from assessment_bank.families._principal_c_utils import formatter, numeric_mcq, pick_traps
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.principal.escape_origin_mcq"

CONTEXTS = ["мобильный банк", "интернет-магазин", "сервис доставки", "платформа бронирования", "страховой кабинет",
            "онлайн-кинотеатр", "маркетплейс услуг", "сервис такси", "облачная бухгалтерия", "портал госуслуг региона"]
ALL_STAGES = ["ревью кода", "модульные тесты", "интеграционные тесты", "сквозные тесты", "канареечный выпуск"]
ORIGINS = ["в коде", "в конфигурации окружения", "в интеграции с внешними системами"]

PROGRAM = """from fractions import Fraction as F
from itertools import product

{fmt}
STAGES = {stages!r}
P = {p!r}                 # вероятность найти дефект на этапе (после усиления)
ORIGINS = {origins!r}     # источник -> (дефектов за релиз, первый этап, который его видит)
R = {R}
total = F(0)
for name, (n, entry) in ORIGINS.items():
    seen = STAGES[entry:]
    escape = F(0)
    for outcome in product([True, False], repeat=len(seen)):   # True — этап нашёл
        pr = F(1)
        for st, found in zip(seen, outcome):
            pr *= F(P[st]) if found else 1 - F(P[st])
        if not any(outcome):
            escape += pr
    total += n * escape
print(fmt(float(total * R)))
"""


def _esc(stages, p, n_entry, R, mode="true", improved=None, p_before=None):
    q = dict(p)
    if mode == "before":
        q[improved] = p_before
    total = 0.0
    for o, (n, entry) in n_entry.items():
        if mode == "code_only" and o != ORIGINS[0]:
            continue
        if mode in ("all_through",):
            seen = stages
        elif mode == "improved_all":
            seen = stages[entry:] + ([improved] if stages.index(improved) < entry else [])
        else:
            seen = stages[entry:]
        if mode == "last_only":
            f = 1 - q[stages[-1]]
        elif mode == "best_only":
            f = 1 - max(q[s] for s in stages)
        else:
            f = prod(1 - q[s] for s in seen)
        total += n * f
    return R * total


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    n_below = rng.choice([0, 1, 2, 3])
    fmt, fmt_src = formatter("d1")
    for _ in range(4000):
        drop = rng.choice([0, 3, 4])                      # какой этап в этой команде отсутствует
        stages = [s for i, s in enumerate(ALL_STAGES) if i != drop]
        p = {s: rng.choice([0.3, 0.4, 0.5, 0.6, 0.7]) for s in stages}
        early = [s for s in stages if s in ("ревью кода", "модульные тесты")]
        improved = rng.choice(early)
        p_before = p[improved]
        p[improved] = round(min(0.9, p_before + rng.choice([0.2, 0.3])), 2)
        e_conf = stages.index("интеграционные тесты")
        e_ext = stages.index("сквозные тесты") if "сквозные тесты" in stages else e_conf
        n_entry = {ORIGINS[0]: (rng.choice([4, 5, 6, 7, 8, 9]), 0), ORIGINS[1]: (rng.choice([1, 2, 3, 4]), e_conf),
                   ORIGINS[2]: (rng.choice([1, 2, 3]), e_ext)}
        R = rng.choice([12, 18, 24, 26, 36])
        good = _esc(stages, p, n_entry, R)
        pool = {m: _esc(stages, p, n_entry, R, m, improved, p_before)
                for m in ("all_through", "improved_all", "code_only", "before", "last_only", "best_only")}
        traps = pick_traps(good, pool, n_below, rng, fmt, "d1", rel=0.08, lo=10, hi=100)
        if traps:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    rows = [f"  {i}. {s} — находит {round(100 * p[s])} % проходящих через этап дефектов"
            + (f" (было {round(100 * p_before)} %, после вложений)" if s == improved else "")
            for i, s in enumerate(stages, 1)]
    code = "\n".join(["Этапы конвейера по порядку:", *rows,
                      "Дефекты за один релиз (в среднем):",
                      f"  {ORIGINS[0]} — {n_entry[ORIGINS[0]][0]} (появляются до первого этапа)",
                      f"  {ORIGINS[1]} — {n_entry[ORIGINS[1]][0]} (появляются к этапу «{stages[e_conf]}»)",
                      f"  {ORIGINS[2]} — {n_entry[ORIGINS[2]][0]} (появляются к этапу «{stages[e_ext]}»)",
                      f"Релизов за квартал: {R}"])
    stem = (f"{ctx.capitalize()}: программа качества вложилась в этап «{improved}». Этапы работают независимо; "
            f"дефект, появившийся к какому-то этапу, более ранние этапы увидеть не могут. Сколько дефектов в среднем "
            f"уйдёт в эксплуатацию за квартал после вложений (с точностью до десятых)?")
    why = (f"Для каждого источника — доля, прошедшая все этапы, которые его видят: произведение (1 − p) по этим "
           f"этапам. Итого за квартал {fmt(good)}. Типичные ошибки: все дефекты проходят все этапы — "
           f"{fmt(pool['all_through'])}; усиленный ранний этап «ловит» и поздние дефекты — {fmt(pool['improved_all'])}; "
           f"учтены только дефекты кода — {fmt(pool['code_only'])}; без вложений было {fmt(pool['before'])}; только "
           f"последний этап — {fmt(pool['last_only'])}; только самый сильный этап — {fmt(pool['best_only'])}. Вывод: "
           f"вложение в ранний этап не снижает утечку дефектов, которые появляются позже него, — их долю надо "
           f"видеть по источникам, прежде чем выбирать этап.")
    program = PROGRAM.format(fmt=fmt_src, stages=stages, p=p, origins=n_entry, R=R)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=good, pool=pool, traps=traps, fmt=fmt,
                       program=program, why=why, code=code,
                       params={"improved": improved, "R": R, "stages": len(stages)},
                       note="Программа перебирает все исходы «нашёл / пропустил» по этапам для каждого источника.")
