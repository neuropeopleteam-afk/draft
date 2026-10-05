"""qa.load.slo_capacity_mcq — mcq_concept: интерпретация результатов нагрузочного теста.

Подтип ``capacity``: таблица ступенчатого теста (VU, успешные RPS, p50/p95/p99, ошибки) и
SLO «p95 ≤ X мс и ошибки ≤ Y %». Нужно найти максимальную проверенную нагрузку в рамках SLO.
Дистракторы — типичные ошибки чтения отчёта: смотреть на медиану вместо p95; не учитывать
ошибки (на последней ступени сервис быстро отвечает 503, и p95 «улучшается»); брать
ступень с максимальной пропускной способностью; брать p99 вместо p95 (слишком строго).

Подтип ``little``: закон Литтла. Сколько виртуальных пользователей нужно для заданного RPS
при среднем времени ответа и паузе пользователя (N = X·(R + Z)) или сколько запросов в
среднем одновременно обрабатывает сервер (L = X·R). Дистракторы: p95 вместо среднего,
забытая или лишняя пауза. Ключ проверяется исполнением: программа считает ответ по тем же
числам и печатает правильный вариант.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, text_table
from assessment_bank.schema import AnswerKey, Check

from ._qa_utils import balanced_options, ru_num

FAMILY_ID = "qa.load.slo_capacity_mcq"

SERVICES = ["сервис поиска товаров", "API оформления заказа", "сервис авторизации",
            "лента рекомендаций", "API расчёта доставки", "сервис платёжных уведомлений",
            "каталог вакансий", "API личного кабинета"]

CAP_PROGRAM = '''ROWS = {rows!r}   # (VU, RPS, p50, p95, p99, ошибки %)
P95_SLO, ERR_SLO = {x}, {y}
ok = [vu for vu, rps, p50, p95, p99, err in ROWS if p95 <= P95_SLO and err <= ERR_SLO]
# ступени идут по возрастанию нагрузки; берём последнюю, до которой все ступени в SLO
best = None
for vu, rps, p50, p95, p99, err in ROWS:
    if p95 <= P95_SLO and err <= ERR_SLO:
        best = vu
    else:
        break
assert best == max(v for v in ok if v <= best)
print(f"{{best}} VU")
'''

LITTLE_PROGRAM = '''X, R_MEAN, R_P95, Z = {x}, {rm}, {r95}, {z}   # RPS, с, с, с
MODE = {mode!r}
n = X * (R_MEAN + Z) if MODE == "vu" else X * R_MEAN
print(f"около {{round(n):,}}".replace(",", " ") + {suffix!r})
'''


def _err(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def _g(v: float) -> str:
    return f"{v:g}".replace(".", ",")


def _capacity(rng, seed):
    x = rng.choice([300, 400, 500, 800, 1000])
    y = rng.choice([0.5, 1.0, 2.0])
    vus = rng.choice([[50, 100, 150, 200, 250, 300, 350], [100, 200, 300, 400, 500, 600, 700],
                      [20, 40, 60, 80, 100, 120, 140], [200, 400, 600, 800, 1000, 1200, 1400]])
    c = rng.choice([2, 3])
    r = rng.choice([1.5, 2.0, 2.5, 3.0, 4.0])
    rows = []
    for i, vu in enumerate(vus):
        if i <= c:
            p95 = x * (0.35 + 0.53 * i / c) * rng.uniform(0.97, 1.03)
            p50 = p95 * rng.uniform(0.35, 0.45)
            p99 = p95 * rng.uniform(1.55, 1.9)
            err = y * rng.uniform(0.0, 0.2)
            rps = vu * r * (1 - 0.02 * i)
        elif i <= c + 2:
            k = i - c
            p95 = x * (1.3 if k == 1 else 2.0) * rng.uniform(0.97, 1.05)
            p50 = x * (0.6 if k == 1 else 0.85) * rng.uniform(0.95, 1.05)
            p99 = p95 * rng.uniform(1.5, 1.8)
            err = y * rng.uniform(0.3, 0.8)
            rps = rows[c][1] * (vus[c + 1] / vus[c]) * 0.9 if k == 1 else rows[-1][1] * 0.95
        elif i < len(vus) - 1:
            p95 = x * 3.0 * rng.uniform(0.97, 1.05)
            p50 = x * 1.4 * rng.uniform(0.95, 1.05)
            p99 = p95 * 1.5
            err = y * rng.uniform(0.5, 0.9)
            rps = rows[-1][1] * 0.9
        else:
            p95 = x * 0.7 * rng.uniform(0.95, 1.05)
            p50 = x * 0.15 * rng.uniform(0.9, 1.1)
            p99 = x * 1.6 * rng.uniform(0.95, 1.05)
            err = rng.uniform(8, 25)
            rps = rows[c + 1][1] * 0.6
        rows.append((vu, round(rps), round(p50), round(p95), round(p99), round(err, 2)))
    def last(pred):
        best = None
        for row in rows:
            if pred(row):
                best = row[0]
            else:
                break
        return best
    good = last(lambda r_: r_[3] <= x and r_[5] <= y)
    d = {"p50": max(r_[0] for r_ in rows if r_[2] <= x and r_[5] <= y),
         "no_errors": max(r_[0] for r_ in rows if r_[3] <= x),
         "max_rps": max(rows, key=lambda r_: r_[1])[0],
         "p99": last(lambda r_: r_[4] <= x and r_[5] <= y)}
    assert good == vus[c] and len({good, *d.values()}) == 5, (good, d)
    chosen = rng.sample(sorted(d), 3)
    opts, key = balanced_options(FAMILY_ID, seed, rng, (f"{good} VU", None),
                                 [(f"{d[k]} VU", None) for k in chosen])
    table = text_table(["VU", "RPS (успешные)", "p50, мс", "p95, мс", "p99, мс", "Ошибки, %"],
                       [[v, ru_num(rp), ru_num(a), ru_num(b), ru_num(cc), _err(e)]
                        for v, rp, a, b, cc, e in rows])
    stem_ctx = rng.choice(["Ступенчатый тест: каждая ступень держится 10 минут после "
                           "прогрева.", "Тест с нарастающей нагрузкой, ступени по 15 минут, "
                           "метрики сняты на стабильном участке."])
    stem = (f"Нагрузочный тест — {{svc}}. {stem_ctx} SLO: p95 времени ответа не больше "
            f"{ru_num(x)} мс и доля ошибок не больше {_g(y)} %. Какую максимальную из "
            f"проверенных нагрузок сервис выдерживает в рамках SLO?")
    why = {"p50": "по медиане (p50) — она скрывает хвост медленных ответов",
           "no_errors": "без учёта ошибок — на последней ступени сервис быстро отвечает 503, "
                        "поэтому p95 «улучшился»",
           "max_rps": "по максимуму пропускной способности — пик RPS достигается уже за "
                      "пределами SLO по задержке",
           "p99": "по p99 — это строже, чем требует SLO"}
    expl = (f"{good} VU — последняя ступень, где одновременно p95 ≤ {ru_num(x)} мс и ошибки "
            f"≤ {_g(y)} %. Дистракторы получены " + "; ".join(why[k] for k in chosen) + ".")
    program = CAP_PROGRAM.format(rows=rows, x=x, y=y)
    return stem, table, opts, key, expl, program, f"{good} VU", {"c": c, "distractors": chosen}


def _little(rng, seed):
    mode = rng.choice(["vu", "inflight"])
    for _ in range(200):
        x = rng.choice([150, 240, 400, 600, 900, 1200, 1800])
        rm = rng.choice([0.08, 0.12, 0.15, 0.2, 0.25, 0.3, 0.4])
        r95 = round(rm * rng.choice([2.5, 3.0, 4.0]), 2)
        z = rng.choice([1, 2, 3, 5]) if mode == "vu" else rng.choice([2, 3, 5, 8])
        if mode == "vu":
            vals = {"good": x * (rm + z), "p95": x * (r95 + z), "no_think": x * rm, "only_think": x * z}
        else:
            vals = {"good": x * rm, "p95": x * r95, "with_think": x * (rm + z), "only_think": x * z}
        v = sorted(vals.values())
        if all(b / a >= 1.15 for a, b in zip(v, v[1:])):
            break
    suffix = " виртуальных пользователей" if mode == "vu" else " одновременных запросов"
    fmt = lambda n: f"около {round(n):,}".replace(",", " ") + suffix
    names = [k for k in vals if k != "good"]
    opts, key = balanced_options(FAMILY_ID, seed, rng, (fmt(vals["good"]), None),
                                 [(fmt(vals[k]), None) for k in names])
    ms = lambda s: ru_num(int(round(s * 1000)))
    common = (f"Пользователь в сценарии ждёт ответ и делает паузу {z} с перед следующим "
              f"запросом. По прошлым тестам среднее время ответа — {ms(rm)} мс, p95 — "
              f"{ms(r95)} мс; при целевой нагрузке время ответа не меняется.")
    if mode == "vu":
        q = (f"Нужно подать на {{svc}} {ru_num(x)} запросов в секунду в закрытой модели "
             f"нагрузки (каждый виртуальный пользователь шлёт следующий запрос только после "
             f"ответа и паузы). {common} Сколько виртуальных пользователей нужно?")
        expl = (f"Закон Литтла: N = X·(R + Z) = {x}·({_g(rm)} + {z}) ≈ {round(vals['good'])}. Для "
                "числа пользователей берётся среднее время ответа, а не перцентиль, и пауза "
                "пользователя входит в цикл.")
    else:
        q = (f"{{svc}} обслуживает {ru_num(x)} запросов в секунду. {common} Сколько запросов в "
             f"среднем одновременно находятся в обработке на сервере (от этого зависит размер "
             f"пула соединений)?")
        expl = (f"Закон Литтла для сервера: L = X·R = {x}·{_g(rm)} ≈ {round(vals['good'])}. Пауза "
                "пользователя проходит вне сервера и в L не входит; используется среднее время "
                "ответа, а не p95.")
    program = LITTLE_PROGRAM.format(x=x, rm=rm, r95=r95, z=z, mode=mode, suffix=suffix)
    return q, None, opts, key, expl, program, fmt(vals["good"]), {"mode": mode}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    svc = rng.choice(SERVICES)
    kind = rng.choice(["capacity", "capacity", "little"])
    stem, table, opts, key, expl, program, expected, extra = (
        _capacity if kind == "capacity" else _little)(rng, seed)
    stem = stem.replace("{svc}", svc)
    stem = stem[0].upper() + stem[1:]
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    checks = [Check(name="compute", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=expected, embeds_display_code=False)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=table, options=opts, answer_key=ak,
                         context=svc, verification="execution", checks=checks, language="text",
                         display_code_note="Программа считает ответ по тем же числам, что "
                                           "показаны кандидату.",
                         params={"kind": kind, **extra})
