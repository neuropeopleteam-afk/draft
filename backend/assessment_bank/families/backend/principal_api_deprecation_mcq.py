"""backend.strategy.principal_api_deprecation_mcq — mcq_concept (Principal, короткое): как выводить старую версию API.

Старой версией публичного API пользуются клиенты с долей s0 выручки партнёров V; сами они переходят на новую версию
с долей r в год (от оставшихся). Горизонт — H лет. Четыре плана:
  * поддерживать старую версию весь горизонт — M млн ₽ в год;
  * жёсткий срок через год — год поддержки M, затем оставшиеся клиенты уходят с вероятностью λ: потеря их выручки
    каждый следующий год;
  * слой совместимости (старые запросы переводятся в новые) — разово A, дальше m в год;
  * помочь с переходом (команда сопровождения партнёров) — разово P, все переходят равномерно за K лет; поддержка M
    только эти K лет, без потерь.
Годовая цена плана = Σ по годам поддержка + потери + разовые затраты в первый год.

Ловушки: «никогда не ломать клиентов» (поддерживать весь горизонт), «быстрее всего избавиться» (жёсткий срок) и
расчёт на два года. Верный план распределён поровну по четырём и отличается хотя бы от двух ловушек (если верен
сам ловушечный — хотя бы от одной). Ключ проверяется исполнением: программа моделирует годы для каждого плана
(доля клиентов на старой версии, поддержка, ушедшие) и печатает букву минимума суммы.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "backend.strategy.principal_api_deprecation_mcq"

CONTEXTS = ["API платёжного шлюза", "API логистики для магазинов", "API бронирования для агентств",
            "API рекламного кабинета", "API выгрузки заказов маркетплейса", "API кассовой платформы",
            "API геосервиса"]
NAMES = {"keep": "поддерживать старую версию весь горизонт", "deadline": "жёсткий срок отключения через год",
         "adapter": "слой совместимости поверх новой версии", "assist": "помочь партнёрам с переходом"}
ORDER = ["keep", "deadline", "adapter", "assist"]

PROGRAM = """opts = __OPTS__
H, V, s0, r, lam = {H}, {V}, {s0}, {r}, {lam}
M, A, m, P, K = {M}, {A}, {m}, {P}, {K}
labels = {labels!r}
cost = {{}}
for plan, label in labels.items():
    total, share, gone = 0.0, s0, 0.0
    for year in range(1, H + 1):
        if plan == "keep":
            total += M
        elif plan == "deadline":
            if year == 1:
                total += M
            else:
                if year == 2:
                    gone = share * lam               # после отключения уходит доля lam оставшихся
                total += V * gone
        elif plan == "adapter":
            total += (A if year == 1 else 0) + m
        elif plan == "assist":
            total += (P if year == 1 else 0) + (M if year <= K else 0)
        share *= 1 - r                               # естественный переход за год
    cost[label] = total
best = min(cost, key=cost.get)
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _argmin(v, rel=0.04):
    o = sorted(v.values())
    return min(v, key=v.get) if o[1] - o[0] >= rel * o[1] else None


def _costs(H, V, s0, r, lam, M, A, m, P, K):
    gone = s0 * (1 - r) * lam
    return {"keep": M * H, "deadline": M + V * gone * (H - 1), "adapter": A + m * H, "assist": P + M * min(K, H)}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)
    for _ in range(80000):
        H = rng.choice([3, 4, 5])
        V = rng.choice([200, 500, 1000, 3000])
        s0 = rng.choice([0.05, 0.1, 0.2, 0.3])
        r = rng.choice([0.1, 0.2, 0.3])
        lam = rng.choice([0.2, 0.4, 0.6])
        M = rng.choice([5, 8, 12, 20])
        A, m = rng.choice([10, 20, 30]), rng.choice([1, 2, 3])
        P, K = rng.choice([5, 10, 15]), rng.choice([1, 2])
        a = (H, V, s0, r, lam, M, A, m, P, K)
        full = _costs(*a)
        good = _argmin(full)
        if good != target:
            continue
        first = _argmin(_costs(2, V, s0, r, lam, M, A, m, P, K))
        if first is None:
            continue
        traps = ("keep", "deadline", first)
        if sum(t != good for t in traps) >= (1 if good in ("keep", "deadline") else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    cap = lambda t: t[0].upper() + t[1:]
    hy = plural(H, "год", "года", "лет")
    ky = plural(K, "год", "года", "лет")
    rows = [f"• {cap(NAMES['keep'])}: {M} млн ₽ в год (дежурства, исправления, тесты двух версий).",
            f"• {cap(NAMES['deadline'])}: год поддержки ({M} млн ₽), затем отключение; партнёры, не успевшие "
            f"перейти, уходят с вероятностью {fmt_num(100 * lam, 0)} % — их выручка теряется каждый следующий год.",
            f"• {cap(NAMES['adapter'])}: разово {A} млн ₽, дальше {m} млн ₽ в год; старая версия отключается "
            f"без потерь.",
            f"• {cap(NAMES['assist'])}: разово {P} млн ₽ на сопровождение; все партнёры переходят за {K} {ky}, "
            f"старую версию поддерживаем только это время ({M} млн ₽ в год), без потерь."]
    intro = rng.choice([
        f"Вы — главный инженер. У продукта «{ctx}» две версии, и нужно решить, как выводить старую.",
        f"Для продукта «{ctx}» архитектурный совет решает судьбу старой версии API; решение — за вами как за главным "
        f"инженером.",
        f"Поддержка старой версии продукта «{ctx}» тормозит развитие; главному инженеру нужно выбрать план её вывода.",
    ])
    stem = (f"{intro} Выручка партнёрского канала — ≈ {fmt_num(V, 0)} млн ₽ в год; партнёры на старой версии "
            f"приносят {fmt_num(100 * s0, 0)} % её; сами по себе за год переходят {fmt_num(100 * r, 0)} % оставшихся. "
            f"Горизонт — {H} {hy}. Планы:\n" + "\n".join(rows) +
            f"\n\nКакой план даёт минимальную сумму затрат и потерь за {H} {hy}?")
    gone = s0 * (1 - r) * lam
    expl = (f"Поддерживать: {M} × {H}; жёсткий срок: {M} + выручка × доля на старой версии через год × λ × ({H} − 1) "
            f"= {M} + {fmt_num(V, 0)} × {fmt_num(gone, 3)} × {H - 1}; слой: {A} + {m} × {H}; помощь: {P} + {M} × "
            f"{min(K, H)}. Итоги: " + "; ".join(f"{NAMES[k]} — {fmt_num(full[k], 1)} млн ₽" for k in ORDER) +
            f". Минимум — {NAMES[good]}. На горизонте двух лет вышло бы: {NAMES[first]}.")
    program = PROGRAM.format(H=H, V=V, s0=s0, r=r, lam=lam, M=M, A=A, m=m, P=P, K=K,
                             labels={k: NAMES[k] for k in ORDER})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={"H": H, "V": V, "s0": s0, "r": r, "lam": lam, "M": M, "A": A, "m": m, "P": P, "K": K,
                               "good": good, "first": first},
                       note="Ответ проверяется программой: моделирование лет для каждого плана.")
