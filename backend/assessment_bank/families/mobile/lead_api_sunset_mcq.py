"""mobile.lead.api_sunset_mcq — mcq_concept (Lead): когда можно отключить старую версию API при длинном хвосте версий.

Мобильный клиент нельзя «откатить» или исправить на устройствах сразу: старые версии приложения живут месяцами.
Старый эндпоинт используют версии до V_old включительно; экран «Обновите приложение» по минимальной версии с
сервера умеет показывать только начиная с версии V_gate — более старые версии после отключения просто сломаются
молча. Доли активных пользователей по версиям даны таблицей; каждую неделю доля m пользователей каждой старой
версии обновляется до текущей (геометрическое убывание). Отключение допустимо, когда молча ломающихся — не больше
X % активных; вопрос — через сколько недель и какая доля в этот момент увидит экран обязательного обновления.

Дистракторы — схема 2×2 (неделя верна/неверна × доля экрана обновления на неделю отключения/на сегодня; ни один
вариант не «центральный»): неверная неделя — по варианту ``all_old`` (молча ломающимися считаются все версии со
старым эндпоинтом — экран обязательного обновления забыт, слишком поздно) или ``linear`` (убывание линейное: m от
исходной доли в неделю); ``today_forced`` — доля экрана обновления взята на сегодня; четвёртый — обе ошибки.
Ключ — расчёт программой.
"""
from __future__ import annotations

import math

from assessment_bank.families._lead_b_utils import computed_mcq, pct
from assessment_bank.gen_utils import make_rng, plural, text_table

FAMILY_ID = "mobile.lead.api_sunset_mcq"

CONTEXTS = ["банковское приложение", "приложение такси", "маркетплейс", "приложение доставки продуктов",
            "онлайн-кинотеатр", "приложение авиакомпании", "электронный дневник", "приложение фитнес-клуба"]

PROGRAM = '''SHARES = {shares!r}   # версия -> доля активных пользователей
ORDER = {order!r}
V_OLD, V_GATE, M, X = {v_old!r}, {v_gate!r}, {m!r}, {x!r}
idx = ORDER.index
silent = sum(s for v, s in SHARES.items() if idx(v) < idx(V_GATE))
forced = sum(s for v, s in SHARES.items() if idx(V_GATE) <= idx(v) <= idx(V_OLD))
w = 0
while silent * (1 - M) ** w > X + 1e-12:
    w += 1
share = forced * (1 - M) ** w
s = f"{{100 * share:.1f}}".replace(".", ",")
s = s.rstrip("0").rstrip(",") if "," in s else s
print(f"через {{w}} нед.; экран обновления увидят около {{s}} % активных")
'''


def _opt(w: int, share: float) -> str:
    return f"через {w} нед.; экран обновления увидят около {pct(share)} активных"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    major = rng.choice([3, 4, 5, 6, 7])
    k = 7
    order = [f"{major}.{i}" for i in range(k)]
    for _ in range(500):
        raw = [rng.choice([2, 3, 4, 5, 6, 8]) for _ in range(k - 2)] + [rng.choice([18, 22, 26]), rng.choice([30, 35, 40])]
        tot = sum(raw)
        shares = {v: round(r / tot, 3) for v, r in zip(order, raw)}
        shares[order[-1]] = round(1 - sum(shares[v] for v in order[:-1]), 3)
        g = rng.choice([2, 3])
        v_gate, v_old = order[g], order[g + rng.choice([1, 2])]
        m = rng.choice([0.08, 0.1, 0.12, 0.15, 0.2])
        x = rng.choice([0.005, 0.01, 0.02])
        silent = sum(shares[v] for v in order[:g])
        forced = sum(shares[v] for v in order[g:order.index(v_old) + 1])
        if silent <= x:
            continue
        w = next(i for i in range(200) if silent * (1 - m) ** i <= x + 1e-12)
        w_all = next(i for i in range(400) if (silent + forced) * (1 - m) ** i <= x + 1e-12)
        w_lin = math.ceil((1 - x / silent) / m - 1e-12)
        wrong_w = rng.choice(["all_old", "linear"])
        ww = w_all if wrong_w == "all_old" else w_lin
        # схема 2×2: неделя верна/неверна × доля экрана обновления на неделю отключения/на сегодня
        opts = {"good": _opt(w, forced * (1 - m) ** w), "today_forced": _opt(w, forced),
                wrong_w: _opt(ww, forced * (1 - m) ** w), wrong_w + "+today_forced": _opt(ww, forced)}
        if len(set(opts.values())) == 4 and 3 <= w <= 40 and w_lin != w and ww != w:
            break
    else:  # pragma: no cover
        raise RuntimeError("не нашлось параметров")
    table = text_table(["Версия", "Доля активных"], [[v, pct(shares[v])] for v in order])
    xw = pct(x)
    stem = (f"{ctx.capitalize()}: старый эндпоинт API нужно отключить — его используют версии приложения до "
            f"{v_old} включительно, новые версии работают с новым. Экран «Обновите приложение» по минимальной "
            f"версии с сервера показывают только версии начиная с {v_gate}; более старые после отключения "
            f"перестанут работать без объяснений. Доли активных пользователей по версиям — в таблице. По "
            f"статистике каждую неделю {pct(m, 0)} пользователей каждой старой версии обновляются до текущей "
            f"(доля каждой старой версии за неделю умножается на {str(round(1 - m, 2)).replace('.', ',')}), число активных "
            f"не меняется. Правило: отключать, когда молча ломающихся — не больше {xw} активных. Через сколько "
            f"полных недель можно отключать и какая доля активных в этот момент увидит экран обязательного "
            f"обновления?")
    why = (f"Молча сломаются только версии до {v_gate} (без экрана обновления): сейчас {pct(silent)}; нужно "
           f"{pct(silent)}·{str(round(1 - m, 2)).replace('.', ',')}^w ≤ {xw} → w = {w}. Версии от {v_gate} до {v_old} "
           f"({pct(forced)} сегодня) увидят экран обязательного обновления: к неделе {w} их доля "
           f"{pct(forced * (1 - m) ** w)}. Если считать молча ломающимися все версии со старым эндпоинтом, "
           f"отключение откладывается без причины; линейное убывание неверно описывает долю, обновляющуюся каждую "
           f"неделю; доля на сегодня завышает число затронутых. Практика Lead: экран обязательного обновления и "
           f"флаги на сервере закладываются заранее, отключение — постепенное, с мониторингом ошибок по версиям.")
    return computed_mcq(FAMILY_ID, seed, rng, stem=stem, correct=opts["good"],
                        distractors=[v for k, v in opts.items() if k != "good"],
                        program=PROGRAM.format(shares=shares, order=order, v_old=v_old, v_gate=v_gate, m=m, x=x),
                        why=why, context=ctx, code=table, language="text",
                        params={"v_gate": v_gate, "v_old": v_old, "m": m, "x": x, "w": w,
                                "distractors": [k for k in opts if k != "good"]})
