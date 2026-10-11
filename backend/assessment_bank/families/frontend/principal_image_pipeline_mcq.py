"""frontend.perf.principal_image_pipeline_mcq — mcq_concept (Principal, короткое): как отдавать изображения.

Изображения на страницах — двух видов: статические (из репозитория) и загруженные пользователями (доля u
просмотров изображений). Четыре варианта:
  * отдавать оригиналы — без затрат на обработку; трафик T0 МБ на просмотр, LCP +m0;
  * обработка при сборке (адаптивные размеры, современный формат) — только статические: они T1 и +m1,
    загруженные остаются оригиналами; сборка C_b млн ₽ в год;
  * обработка при сборке и при загрузке пользователем — все изображения T1 и +m1; сборка и обработчик загрузок
    C_b + C_u;
  * сервис преобразования на лету — все изображения T2 и +m2 (лучший формат под браузер), плата f млн ₽ за
    миллиард преобразований (по одному на просмотр изображения, кэш не учитываем).
Годовая цена = трафик (просмотры × МБ × цена ГБ) + обработка + потеря выручки от LCP (W · x % · добавка / 100 мс,
смешанная по долям просмотров).

Ловушки: «наименьший трафик» (на лету), «без новых сервисов» (только при сборке) и расчёт без загруженных
пользователями (u = 0). Верный вариант распределён поровну по четырём и отличается хотя бы от двух ловушек (если
верна сама ловушка — хотя бы от одной). Ключ проверяется исполнением: программа проходит модельную выборку
просмотров изображений (доля u — загруженные), отдаёт каждый по правилу варианта и считает трафик, плату и
добавку LCP, затем печатает букву минимума.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.perf.principal_image_pipeline_mcq"

CONTEXTS = [("сервис объявлений", "фото объявлений"), ("маркетплейс", "фото товаров от продавцов"),
            ("сайт отзывов о ресторанах", "фото гостей"), ("сервис аренды жилья", "фото от хозяев"),
            ("социальная сеть путешественников", "фото из поездок"), ("магазин мебели", "фото покупателей в отзывах"),
            ("портал недвижимости", "фото от агентов")]
NAMES = {"orig": "отдавать оригиналы", "build": "обработка при сборке",
         "both": "обработка при сборке и при загрузке", "cdn": "сервис преобразования на лету"}
ORDER = ["orig", "build", "both", "cdn"]

PROGRAM = """opts = __OPTS__
V, u, gb, W, x = {V}, {u}, {gb}, {W}, {x}
T0, T1, T2, m0, m1, m2 = {T0}, {T1}, {T2}, {m0}, {m1}, {m2}
C_b, C_u, fee = {C_b}, {C_u}, {fee}
labels = {labels!r}
N = 1000
uploaded = int(round(N * u))                    # первые uploaded просмотров — загруженные пользователями
cost = {{}}
for plan, label in labels.items():
    mb = ms = 0.0
    for i in range(N):
        user = i < uploaded
        if plan == "orig" or (plan == "build" and user):
            mb, ms = mb + T0, ms + m0
        elif plan in ("build", "both"):
            mb, ms = mb + T1, ms + m1
        else:
            mb, ms = mb + T2, ms + m2
    fixed = {{"orig": 0, "build": C_b, "both": C_b + C_u, "cdn": V * fee}}[plan]
    traffic = V * 1e9 * (mb / N) / 1024 * gb / 1e6        # V — млрд просмотров; цена за ГБ в ₽; итог в млн ₽
    cost[label] = fixed + traffic + W * x / 100 * (ms / N) / 100
best = min(cost, key=cost.get)
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _argmin(d, rel=0.04):
    v = sorted(d.values())
    return min(d, key=d.get) if v[1] - v[0] >= rel * v[1] else None


def _costs(V, u, gb, W, x, T, m, C_b, C_u, fee):
    def tr(mb):
        return V * 1e9 * mb / 1024 * gb / 1e6

    def lcp(ms):
        return W * x / 100 * ms / 100
    mix = lambda a, b: u * a + (1 - u) * b
    return {"orig": tr(T[0]) + lcp(m[0]),
            "build": C_b + tr(mix(T[0], T[1])) + lcp(mix(m[0], m[1])),
            "both": C_b + C_u + tr(T[1]) + lcp(m[1]),
            "cdn": V * fee + tr(T[2]) + lcp(m[2])}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, ugc = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)
    for _ in range(80000):
        V = rng.choice([10, 20, 50, 100])                # млрд просмотров изображений в год
        u = rng.choice([0.2, 0.4, 0.6, 0.8])
        gb = rng.choice([0.5, 1, 2])                     # ₽ за ГБ
        W = rng.choice([200, 500, 1000, 3000])
        x = rng.choice([0.3, 0.5, 1.0])
        T = (rng.choice([0.8, 1.2, 2.0]), rng.choice([0.2, 0.3, 0.4]), rng.choice([0.12, 0.18, 0.25]))
        m = (rng.choice([150, 250, 400]), rng.choice([60, 100, 150]), rng.choice([40, 80, 120]))
        if not (T[2] < T[1] < T[0] and m[1] < m[0] and m[2] < m[0]):
            continue
        C_b, C_u, fee = rng.choice([2, 5, 10]), rng.choice([5, 10, 20]), rng.choice([0.2, 0.5, 1, 2])
        full = _costs(V, u, gb, W, x, T, m, C_b, C_u, fee)
        good = _argmin(full)
        if good != target:
            continue
        no_ugc = _argmin(_costs(V, 0.0, gb, W, x, T, m, C_b, C_u, fee))
        if no_ugc is None:
            continue
        traps = ("cdn", "build", no_ugc)
        if sum(t != good for t in traps) >= (1 if good in ("cdn", "build") else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    cap = lambda t: t[0].upper() + t[1:]
    mb = lambda v: fmt_num(v, 2).rstrip("0").rstrip(",")
    rows = [f"• {cap(NAMES['orig'])}: без затрат на обработку; {mb(T[0])} МБ на просмотр, +{m[0]} мс к LCP.",
            f"• {cap(NAMES['build'])} (адаптивные размеры, современный формат): статические — {mb(T[1])} МБ и "
            f"+{m[1]} мс, загруженные пользователями остаются оригиналами; сборка — {C_b} млн ₽ в год.",
            f"• {cap(NAMES['both'])}: все изображения — {mb(T[1])} МБ и +{m[1]} мс; сборка и обработчик загрузок — "
            f"{C_b + C_u} млн ₽ в год.",
            f"• {cap(NAMES['cdn'])}: все изображения — {mb(T[2])} МБ и +{m[2]} мс (лучший формат под браузер); "
            f"{fmt_num(fee, 1)} млн ₽ за миллиард преобразований, одно на просмотр."]
    intro = rng.choice([
        f"Вы — главный инженер фронтенда; продукт — {ctx}. Изображения — основная часть трафика и LCP, нужно "
        f"выбрать, как их отдавать.",
        f"В продукте «{ctx}» изображения тормозят страницы и съедают трафик; решение о способе их доставки — за "
        f"вами как за главным инженером фронтенда.",
        f"Для продукта «{ctx}» утверждают план по изображениям на год; выбрать вариант должны вы как главный "
        f"инженер фронтенда.",
    ])
    stem = (f"{intro} Просмотров изображений ≈ {V} млрд в год, {fmt_num(100 * u, 0)} % из них — загруженные "
            f"пользователями ({ugc}), остальные — статические из репозитория. Трафик стоит {fmt_num(gb, 1)} ₽ за "
            f"ГБ (1 ГБ = 1024 МБ). Выручка ≈ {fmt_num(W, 0)} млн ₽ в год, каждые 100 мс LCP стоят {fmt_num(x, 1)} % "
            f"выручки (добавка усредняется по просмотрам). Варианты:\n" + "\n".join(rows) +
            "\n\nКакой вариант даёт минимальную годовую цену (обработка, трафик и потеря выручки от LCP)?")
    expl = ("Цена = обработка + просмотры × средний МБ / 1024 × цена ГБ + выручка × x % × средняя добавка / 100 мс; "
            "у обработки только при сборке загруженные остаются оригиналами. Итоги: " +
            "; ".join(f"{NAMES[k]} — {fmt_num(full[k], 1)} млн ₽" for k in ORDER) +
            f". Минимум — {NAMES[good]}. Без загруженных пользователями вышло бы: {NAMES[no_ugc]}.")
    program = PROGRAM.format(V=V, u=u, gb=gb, W=W, x=x, T0=T[0], T1=T[1], T2=T[2], m0=m[0], m1=m[1], m2=m[2],
                             C_b=C_b, C_u=C_u, fee=fee, labels={k: NAMES[k] for k in ORDER})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={"V": V, "u": u, "gb": gb, "W": W, "x": x, "T": list(T), "m": list(m), "C_b": C_b,
                               "C_u": C_u, "fee": fee, "good": good, "no_ugc": no_ugc},
                       note="Ответ проверяется программой: модельная выборка просмотров и правило каждого варианта.")
