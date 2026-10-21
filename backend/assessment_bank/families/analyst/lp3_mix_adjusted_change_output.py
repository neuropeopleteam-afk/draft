"""analyst.metrics.lp3_mix_adjusted_change_output — predict_output: изменение конверсии при неизменном составе трафика.

Конверсия по сегментам в двух периодах. Общая конверсия меняется и от поведения внутри сегментов, и от сдвига
состава трафика (парадокс Симпсона: внутри всех сегментов рост, в сумме — падение). Вопрос руководителя — «что
изменилось в поведении»: изменение конверсии при составе трафика как в первом периоде (стандартизация по весам
периода A): Σ w_A · (CR_B − CR_A). Ловушки: разница общих конверсий; веса периода B; среднее конверсий сегментов
без весов. Ответ — изменение в процентных пунктах с одним знаком после запятой и знаком (+ или −).
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "analyst.metrics.lp3_mix_adjusted_change_output"
CTX = [("онлайн-кинотеатр", "оформление подписки", ["органика", "реклама в соцсетях", "партнёры", "email"]),
       ("маркетплейс", "покупка", ["приложение", "мобильный сайт", "десктоп"]),
       ("банк", "заявка на карту", ["новые клиенты", "зарплатные клиенты", "клиенты с вкладом", "студенты"]),
       ("сервис доставки еды", "заказ", ["Москва", "Санкт-Петербург", "регионы"]),
       ("онлайн-школа", "покупка курса", ["вебинар", "контекстная реклама", "блогеры", "рассылка"])]

CALC = r'''
rows = []
for l in DATA.splitlines():
    if l.count("|") == 4 and not l.startswith("сегмент"):
        s, va, ca, vb, cb = [x.strip() for x in l.split("|")]
        rows.append((int(va), int(ca), int(vb), int(cb)))
VA = sum(r[0] for r in rows)
d = sum(va / VA * (cb / vb - ca / va) for va, ca, vb, cb in rows) * 100
s = f"{abs(d):.1f}".replace(".", ",")
print(("+" if d >= 0 else "−") + s)
'''


def _pp(d: float) -> str:
    return ("+" if d >= 0 else "−") + f"{abs(d):.1f}".replace(".", ",")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    biz, conv, segs = rng.choice(CTX)
    for _ in range(5000):
        rows = []
        for i, s in enumerate(segs):
            cr = rng.choice([0.6, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0]) / 100
            va = rng.randint(4, 60) * 1000
            vb = int(va * rng.choice([0.4, 0.6, 0.8, 1.2, 1.6, 2.2, 3.0]))
            crb = cr * rng.choice([0.85, 0.9, 0.95, 1.05, 1.1, 1.15, 1.25])
            rows.append((s, va, round(va * cr), vb, round(vb * crb)))
        VA, VB = sum(r[1] for r in rows), sum(r[3] for r in rows)
        d = sum(va / VA * (cb / vb - ca / va) for _, va, ca, vb, cb in rows) * 100
        raw = (sum(r[4] for r in rows) / VB - sum(r[2] for r in rows) / VA) * 100
        wb = sum(vb / VB * (cb / vb - ca / va) for _, va, ca, vb, cb in rows) * 100
        if abs(d) < 0.15 or abs(abs(d) * 10 - round(abs(d) * 10) - 0.5) < 0.06:
            continue
        if _pp(raw) == _pp(d) or _pp(wb) == _pp(d):
            continue
        if (raw > 0) == (d > 0) and rng.random() < 0.7:
            continue  # чаще всего — парадокс Симпсона: знак общего изменения обманывает
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    lines = ["сегмент | визиты A | конверсии A | визиты B | конверсии B"]
    for s, va, ca, vb, cb in rows:
        lines.append(f"{s} | {va} | {ca} | {vb} | {cb}")
    block = "\n".join(lines)
    stem = (f"{biz.capitalize()}: целевое действие — «{conv}». Данные за два периода по сегментам трафика — ниже. "
            "Руководитель спрашивает: «Поведение пользователей стало лучше или хуже, если не считать изменения "
            "состава трафика?» Посчитайте изменение конверсии от периода A к периоду B при составе трафика, как в "
            "периоде A. Ответ — в процентных пунктах с одним знаком после запятой и знаком, например +0,4 или −1,2.")
    expl = (f"Конверсии по сегментам A → B: " + "; ".join(f"{s}: {ca / va * 100:.2f} % → {cb / vb * 100:.2f} %"
                                                       for s, va, ca, vb, cb in rows) +
            f". Взвешиваем изменения долями визитов периода A: {_pp(d)} п.п. Разница общих конверсий — {_pp(raw)} п.п. "
            f"(её создаёт сдвиг состава), с весами периода B — {_pp(wb)} п.п.")
    out = _pp(d)
    alt = out.replace("−", "-")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=out, expl=expl, ctx=biz,
                         accept=[alt, alt.replace(",", "."), out.replace(",", "."), out + " п.п.", alt + " п.п.",
                                 out.lstrip("+"), alt.lstrip("+").replace(",", ".")],
                         params={"rows": [list(r) for r in rows]})
