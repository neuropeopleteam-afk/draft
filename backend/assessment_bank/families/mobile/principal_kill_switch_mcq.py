"""mobile.principal.kill_switch_mcq — mcq_concept (Principal, короткое): через сколько часов флаг аварийного
отключения функции дойдёт до заданной доли пользователей, если приложение берёт конфигурацию при запуске и
кэширует её на TTL.

Приложение при запуске (в среднем λ раз в час на пользователя, запуски случайны и независимы — пуассоновский поток)
запрашивает конфигурацию, только если кэш старше TTL. В момент переключения флага возраст кэша у пользователей
распределён равномерно от 0 до TTL, то есть кэш истекает в момент e ~ U(0, TTL), а флаг приходит при первом запуске
после e. Доля получивших к моменту H: S(H) = E_e[1 − e^(−λ(H − e)⁺)]. Ключ — H, при котором S(H) = X.

Ловушки: ниже ключа — ``no_ttl`` (кэш не учитывают), ``half_ttl`` (все ждут истечения кэша TTL / 2 — неравенство
Йенсена), ``linear`` (вероятность запуска λ·t без экспоненты), ``product`` (доля = P(кэш истёк) × P(был запуск));
выше — ``full_ttl`` (все ждут полный TTL), ``sum_quantiles`` (квантиль X·TTL ожидания кэша плюс квантиль запуска);
``ttl_plus_mean`` (TTL плюс среднее время до запуска 1/λ) — с любой стороны. Сколько ловушек меньше ключа — 1–3
равновероятно. Ключ проверяется исполнением: программа интегрирует долю по e методом Симпсона и находит H
бисекцией.
"""
from __future__ import annotations

import math

from assessment_bank.families._principal_c_utils import formatter, numeric_mcq, pick_traps
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.principal.kill_switch_mcq"

CONTEXTS = [("мобильный банк", "переводы по QR-коду"), ("приложение доставки", "новая оплата при получении"),
            ("приложение такси", "предзаказ поездки"), ("приложение маркетплейса", "новая корзина"),
            ("приложение авиакомпании", "онлайн-регистрация на рейс"), ("приложение онлайн-кинотеатра", "новый плеер"),
            ("приложение сети АЗС", "оплата у колонки"), ("приложение медклиники", "видеоприём")]

PROGRAM = """import math

{fmt}
TTL, lam, X = {TTL}, {lam}, {X}             # кэш конфигурации, ч; запусков в час; нужная доля
def share(H, n=2000):                         # доля получивших флаг к H: кэш истекает в e ~ U(0, TTL)
    def got(e):
        return 1 - math.exp(-lam * (H - e)) if H > e else 0.0
    h = TTL / n
    s = got(0) + got(TTL)
    for k in range(1, n):
        s += (4 if k % 2 else 2) * got(k * h)
    return s * h / 3 / TTL
lo, hi = 0.0, 1000.0
for _ in range(100):
    mid = (lo + hi) / 2
    if share(mid) < X:
        lo = mid
    else:
        hi = mid
print(fmt((lo + hi) / 2))
"""


def _solve(f, X, hi=1000.0):
    lo = 0.0
    if f(hi) < X:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if f(mid) < X:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _share(H, TTL, lam):
    if H <= 0:
        return 0.0
    if H >= TTL:
        return 1 - math.exp(-lam * H) * (math.exp(lam * TTL) - 1) / (lam * TTL)
    return (H - (1 - math.exp(-lam * H)) / lam) / TTL


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, feature = rng.choice(CONTEXTS)
    n_below = rng.choice([1, 2, 3])
    fmt, fmt_src = formatter("d1", "ч")
    for _ in range(6000):
        TTL = rng.choice([4, 6, 8, 12, 24])
        lam = rng.choice([0.1, 0.125, 0.15, 0.2, 0.25, 0.3])
        X = rng.choice([0.8, 0.9, 0.95])
        q = -math.log(1 - X) / lam
        good = _solve(lambda H: _share(H, TTL, lam), X)
        lin = lambda H: (sum(min(1.0, max(0.0, lam * (H - TTL * (k + 0.5) / 400))) for k in range(400)) / 400)  # noqa: E731
        prod = lambda H: min(1.0, H / TTL) * (1 - math.exp(-lam * H))  # noqa: E731
        pool = {"no_ttl": q, "half_ttl": TTL / 2 + q, "linear": _solve(lin, X), "product": _solve(prod, X),
                "full_ttl": TTL + q, "sum_quantiles": X * TTL + q, "ttl_plus_mean": TTL + 1 / lam}
        traps = pick_traps(good, pool, n_below, rng, fmt, "d1", rel=0.05, lo=10, hi=100)
        if traps:
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    lam_txt = f"{lam:g}".replace(".", ",")
    X_txt = f"{round(X * 100)} %"
    code = "\n".join([f"Конфигурация (в т. ч. флаг «{feature}»): приложение запрашивает её при запуске, если кэш старше {TTL} ч",
                      f"Запуски: в среднем {lam_txt} в час на пользователя, случайные и независимые",
                      f"К моменту переключения возраст кэша у пользователей распределён равномерно от 0 до {TTL} ч",
                      "Push и фоновые обновления конфигурации не используются."])
    stem = (f"{ctx[0].upper() + ctx[1:]}: функцию «{feature}» аварийно выключили флагом. Через сколько часов после "
            f"переключения флаг получат {X_txt} активных пользователей?")
    why = (f"Кэш истекает в момент e, равномерный на [0; {TTL}], флаг приходит с первым запуском после e: доля к H — "
           f"среднее по e от 1 − e^(−λ(H − e)). Она достигает {X_txt} при H = {fmt(good)}. Ошибки: без кэша — "
           f"{fmt(pool['no_ttl'])}; все ждут половину TTL — {fmt(pool['half_ttl'])}; линейная вероятность запуска — "
           f"{fmt(pool['linear'])}; произведение «кэш истёк» × «был запуск» — {fmt(pool['product'])}; все ждут "
           f"полный TTL — {fmt(pool['full_ttl'])}; сумма квантилей — {fmt(pool['sum_quantiles'])}; TTL плюс среднее "
           f"время до запуска — {fmt(pool['ttl_plus_mean'])}. Вывод: время аварийного отключения задают TTL кэша и "
           f"частота запусков вместе — для быстрых флагов нужен короткий TTL или push-канал.")
    program = PROGRAM.format(fmt=fmt_src, TTL=TTL, lam=lam, X=X)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=good, pool=pool, traps=traps, fmt=fmt,
                       program=program, why=why, code=code, params={"TTL": TTL, "lam": lam, "X": X},
                       note="Программа интегрирует долю получивших флаг методом Симпсона и находит время бисекцией.")
