"""data_eng.strategy.principal_tiering_mcq — mcq_concept (Principal): политика уровней хранения на горизонте трёх лет.

Платформа данных хранит сырые события; поступление растёт на g % в месяц, объём чтений — тоже. Уровни:
горячий (дорогое хранение, чтение бесплатно), тёплый (дешевле, плата за прочитанный ТБ), холодный (архив:
дёшево, но дорогое извлечение). Чтения убывают с возрастом данных геометрически: доля чтений данных возраста
a месяцев ∝ d^a. Политика (H, W): данные моложе H месяцев — горячие, от H до W — тёплые, старше W — холодные.
Данные моложе 3 месяцев читаются интерактивно — горячие при любой политике (H ≥ 3).
Четыре политики — по схеме 2×2: два значения H × два значения W (каждый вариант делит H с одним вариантом и
W с другим — форма не выдаёт ключ). Вопрос — какая политика даёт минимальную стоимость за 36 месяцев.

Ловушки: минимум по одному хранению (без платы за чтение и извлечение), минимум без роста (по первому месяцу).
Генератор подбирает числа так, что верный ответ отличается хотя бы от одной ловушки, минимум единственный
(отрыв ≥ 3 %) и меняется между вариантами.
Ключ проверяется исполнением: программа помесячно проигрывает 36 месяцев — слои данных по возрасту, хранение
по уровням, чтения по возрасту — для каждой политики и печатает букву минимума.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_eng.strategy.principal_tiering_mcq"

CONTEXTS = ["события мобильного приложения", "журналы платёжного шлюза", "клики рекламной сети",
            "телеметрия датчиков", "события маркетплейса", "журналы звонков контакт-центра"]

HORIZON = 36

PROGRAM = """opts = __OPTS__
policies = {policies!r}   # подпись -> (H, W): моложе H — горячий, от H до W — тёплый, старше — холодный
v0, s0, g, d = {v0}, {s0}, {g}, {d}
hot, warm, cold, warm_read, cold_read = {hot}, {warm}, {cold}, {warm_read}, {cold_read}
months = {horizon}

def total(H, W):
    layers = []                              # объём каждого месячного слоя, ТБ (индекс — месяц поступления)
    cost = 0.0
    for t in range(months):
        layers.append(v0 * (1 + g) ** t)
        reads = s0 * (1 + g) ** t
        weights = [d ** (t - m) for m in range(t + 1)]
        norm = sum(weights)
        for m, vol in enumerate(layers):
            age = t - m
            share = reads * weights[m] / norm
            if age < H:
                cost += vol * hot
            elif age < W:
                cost += vol * warm + share * warm_read
            else:
                cost += vol * cold + share * cold_read
    return cost

best, best_cost = None, None
for name, (H, W) in policies.items():
    if H < 3:                                # моложе 3 месяцев — только горячий уровень
        continue
    c = total(H, W)
    if best_cost is None or c < best_cost - 1e-6:
        best, best_cost = name, c
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _total(H, W, v0, s0, g, d, prices, *, reads=True, growth=True, months=HORIZON):
    hot, warm, cold, warm_read, cold_read = prices
    gg = g if growth else 0.0
    vols, cost = [], 0.0
    for t in range(months):
        vols.append(v0 * (1 + gg) ** t)
        r = s0 * (1 + gg) ** t
        w = [d ** (t - m) for m in range(t + 1)]
        norm = sum(w)
        for m, vol in enumerate(vols):
            age, share = t - m, r * w[m] / norm
            if age < H:
                cost += vol * hot
            elif age < W:
                cost += vol * warm + (share * warm_read if reads else 0)
            else:
                cost += vol * cold + (share * cold_read if reads else 0)
    return cost


def _argmin(dct, rel=0.03):
    s = sorted(dct.values())
    if len(s) < 2:
        return min(dct, key=dct.get) if s else None
    return min(dct, key=dct.get) if s[1] - s[0] >= rel * s[1] else None


def _label(H, W):
    if W >= HORIZON:
        return f"горячий {H} мес., дальше — тёплый (архив не используется)"
    return f"горячий {H} мес., тёплый до {W} мес., дальше — архив"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    for _ in range(4000):
        v0 = rng.choice([20, 40, 60, 100])               # ТБ в месяц на старте
        s0 = rng.choice([100, 300, 600, 1200])          # прочитано ТБ в месяц на старте
        g = rng.choice([0.02, 0.04, 0.06])
        d = rng.choice([0.5, 0.65, 0.8])
        prices = (rng.choice([1800, 2400]), rng.choice([500, 800]), rng.choice([80, 150]),
                  rng.choice([150, 400]), rng.choice([1500, 4000]))
        hs = sorted(rng.sample([3, 6, 12], 2))
        ws = sorted(rng.sample([w for w in (12, 24, 36) if w > hs[1]], 2))
        pols = [(h, w) for h in hs for w in ws]          # схема 2×2: каждый вариант делит H с одним и W с другим
        full = {p: _total(*p, v0, s0, g, d, prices) for p in pols}
        good = _argmin(full)
        if good is None:
            continue
        storage_only = _argmin({p: _total(*p, v0, s0, g, d, prices, reads=False) for p in pols})
        no_growth = _argmin({p: _total(*p, v0, s0, g, d, prices, growth=False) for p in pols})
        if None in (storage_only, no_growth):
            continue
        if sum(1 for t in (storage_only, no_growth) if t != good) >= 1:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    hot, warm, cold, warm_read, cold_read = prices
    order = sorted(pols)
    labels = {p: _label(*p) for p in order}
    stem = (f"Вы — главный инженер платформы данных; хранилище — «{ctx}». Поступает ≈ {v0} ТБ в месяц, объём растёт на "
            f"{fmt_num(100 * g, 0)} % в месяц; читается ≈ {s0} ТБ в месяц (растёт так же), причём чтения быстро "
            f"убывают с возрастом данных: на данные возраста a месяцев приходится доля ∝ {fmt_num(d, 2)}^a. Цены за "
            f"ТБ в месяц: горячий уровень — {hot} ₽ (чтение бесплатно), тёплый — {warm} ₽ и {warm_read} ₽ за "
            f"прочитанный ТБ, архив — {cold} ₽ и {cold_read} ₽ за извлечённый ТБ. Данные моложе 3 месяцев аналитики "
            f"читают интерактивно — они в горячем уровне при любой политике. Политики:\n" +
            "\n".join(f"• {labels[p].capitalize()}." for p in order) +
            "\n\nКакая политика даёт минимальную стоимость хранения и чтения за 3 года?")
    expl = (f"Помесячно на 36 месяцев: слои данных по месяцу поступления, хранение по уровню возраста, чтения по "
            f"возрасту с платой тёплого уровня и архива. Итоги: " +
            "; ".join(f"{labels[p]} — {fmt_num(full[p] / 1e6, 1)} млн ₽" for p in order if p in full) +
            f". Минимум — {labels[good]}. Ловушки: только хранение (без платы за чтение и извлечение) — "
            f"{labels[storage_only]}; без роста — {labels[no_growth]}.")
    program = PROGRAM.format(policies={labels[p]: p for p in order}, v0=v0, s0=s0, g=g, d=d, hot=hot, warm=warm,
                             cold=cold, warm_read=warm_read, cold_read=cold_read, horizon=HORIZON)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=labels[good],
                       distractors=[labels[p] for p in order if p != good], program=program, explanation=expl,
                       params={"v0": v0, "s0": s0, "g": g, "d": d, "prices": list(prices), "good": list(good),
                               "storage_only": list(storage_only), "no_growth": list(no_growth)},
                       note="Ответ проверяется программой: 36 месяцев помесячно для каждой политики.")
