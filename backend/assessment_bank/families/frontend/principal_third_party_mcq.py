"""frontend.perf.principal_third_party_mcq — mcq_concept (Principal, короткое): одно действие с внешними скриптами.

Страницы тормозят внешние скрипты. На квартал есть ресурс ровно на одно действие из четырёх:
  * убрать виджет онлайн-чата — LCP быстрее на m_chat мс, но теряется выручка, которую приносит чат (V_chat);
  * загружать аналитику после первого действия пользователя — быстрее на m_an мс, но теряется доля событий q
    (уходящие до первого действия); цена неполных данных — q · D_an (ошибочные решения по экспериментам);
  * перенести скрипт A/B-тестов на сервер — быстрее на m_ab мс, работа и сопровождение E_ab в год;
  * не трогать скрипты, ускорить ответ сервера — быстрее на m_srv мс, инфраструктура E_srv в год.
Каждые 100 мс LCP стоят x % выручки W; ускорение даёт W · x % · m / 100. Чистая годовая выгода = ускорение −
цена действия. Вопрос — какое действие даёт наибольшую чистую выгоду.

Ловушки: «самое большое ускорение», «самое дешёвое действие», расчёт без потерь данных аналитики (цена «после
первого действия» = 0). Верное действие распределено поровну по четырём и отличается хотя бы от двух ловушек (если
верна сама ловушка — хотя бы от одной). Ключ проверяется исполнением: программа проходит сессии модельной выборки
(доля q уходит до первого действия) и для каждого действия считает выигрыш и потери, затем печатает букву
максимума выгоды.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.perf.principal_third_party_mcq"

CONTEXTS = ["интернет-магазин одежды", "сервис доставки цветов", "онлайн-школа", "сайт застройщика",
            "сервис бронирования ресторанов", "магазин электроники", "сайт страховой компании"]
NAMES = {"chat": "убрать виджет онлайн-чата", "an": "загружать аналитику после первого действия",
         "ab": "перенести скрипт A/B-тестов на сервер", "srv": "не трогать скрипты, ускорить сервер"}
ORDER = ["chat", "an", "ab", "srv"]

PROGRAM = """opts = __OPTS__
W, x = {W}, {x}
q, D_an = {q}, {D_an}
acts = {acts!r}       # подпись -> (ускорение, мс; прямая цена, млн ₽ в год; теряет ли события аналитики)
N = 1000
early = int(round(N * q))                       # сессии, которые уходят до первого действия
gain = {{}}
for label, (ms, price, loses_events) in acts.items():
    lost_share = 0.0
    if loses_events:
        lost_share = sum(1 for i in range(N) if i < early) / N
    gain[label] = W * x / 100 * ms / 100 - price - lost_share * D_an
best = max(gain, key=gain.get)
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _argmax(d, rel=0.04):
    v = sorted(d.values(), reverse=True)
    return max(d, key=d.get) if v[0] - v[1] >= rel * max(abs(v[0]), 1e-9) else None


def _gains(ms, price, W, x, q, D_an, data_cost=True):
    return {k: W * x / 100 * ms[k] / 100 - price[k] - (q * D_an if (k == "an" and data_cost) else 0) for k in ORDER}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)
    for _ in range(60000):
        W = rng.choice([500, 1000, 2000, 4000])
        x = rng.choice([0.5, 1.0, 1.5])
        ms = {"chat": rng.choice([150, 250, 350]), "an": rng.choice([100, 200, 300]),
              "ab": rng.choice([150, 250, 400]), "srv": rng.choice([100, 200, 300])}
        q = rng.choice([0.1, 0.2, 0.3, 0.4])
        D_an = rng.choice([10, 20, 40, 80])
        price = {"chat": rng.choice([3, 6, 10, 20]), "an": 0, "ab": rng.choice([4, 8, 12]),
                 "srv": rng.choice([5, 10, 15])}
        full = _gains(ms, price, W, x, q, D_an)
        good = _argmax(full)
        if good != target or full[good] <= 0:
            continue
        no_data = _argmax(_gains(ms, price, W, x, q, D_an, data_cost=False))
        if no_data is None:
            continue
        top = max(ms.values())
        if list(ms.values()).count(top) != 1:
            continue
        fastest = max(ORDER, key=lambda k: ms[k])
        cheapest = "an"                                     # прямая цена 0
        traps = (fastest, cheapest, no_data)
        if sum(t != good for t in traps) >= (1 if good in (fastest, cheapest) else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    cap = lambda t: t[0].upper() + t[1:]
    rows = [f"• {cap(NAMES['chat'])}: LCP быстрее на {ms['chat']} мс; чат приносит ≈ {price['chat']} млн ₽ выручки в "
            f"год, она пропадёт.",
            f"• {cap(NAMES['an'])}: LCP быстрее на {ms['an']} мс, без прямых затрат; {fmt_num(100 * q, 0)} % сессий "
            f"заканчиваются до первого действия, их события пропадут; полные данные по экспериментам оцениваются в "
            f"{D_an} млн ₽ в год (столько стоят ошибочные решения без них), потери пропорциональны доле пропавших "
            f"событий.",
            f"• {cap(NAMES['ab'])}: LCP быстрее на {ms['ab']} мс; работа и сопровождение — {price['ab']} млн ₽ в год.",
            f"• {cap(NAMES['srv'])}: LCP быстрее на {ms['srv']} мс; инфраструктура — {price['srv']} млн ₽ в год."]
    intro = rng.choice([
        f"Вы — главный инженер фронтенда; продукт — {ctx}. Внешние скрипты замедляют страницы, а ресурса на "
        f"квартал хватает ровно на одно действие.",
        f"В продукте «{ctx}» внешние скрипты съели бюджет скорости страниц. Команда может сделать в квартале одно "
        f"действие — выбрать его должны вы как главный инженер фронтенда.",
        f"Аудит скорости продукта «{ctx}» показал, что главная проблема — внешние скрипты; на квартал есть ресурс "
        f"на одно действие, решение за главным инженером фронтенда.",
    ])
    stem = (f"{intro} Выручка ≈ {fmt_num(W, 0)} млн ₽ в год; по экспериментам каждые 100 мс LCP стоят "
            f"{fmt_num(x, 1)} % выручки (ускорение даёт столько же). Действия (эффекты не складываются — делаем одно):\n"
            + "\n".join(rows) + "\n\nКакое действие даёт наибольшую чистую годовую выгоду (рост выручки от ускорения "
            "минус цена действия)?")
    expl = (f"Выгода = W × {fmt_num(x, 1)} % × ускорение / 100 мс − цена; у аналитики цена = доля пропавших событий × "
            f"цена полных данных = {fmt_num(q * D_an, 1)} млн ₽. Итоги: " +
            "; ".join(f"{NAMES[k]} — {fmt_num(full[k], 1)} млн ₽" for k in ORDER) +
            f". Максимум — {NAMES[good]}. Ловушки: самое большое ускорение — {NAMES[fastest]}, без прямых затрат — "
            f"{NAMES['an']}, без цены пропавших событий — {NAMES[no_data]}.")
    program = PROGRAM.format(W=W, x=x, q=q, D_an=D_an,
                             acts={NAMES[k]: (ms[k], price[k], k == "an") for k in ORDER})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={"W": W, "x": x, "q": q, "D_an": D_an, "good": good, "no_data": no_data,
                               **{f"ms_{k}": ms[k] for k in ORDER}, **{f"price_{k}": price[k] for k in ORDER}},
                       note="Ответ проверяется программой: модельная выборка сессий и выгода каждого действия.")
