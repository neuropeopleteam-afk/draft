"""common.perf.fanout_tail_mcq — mcq_concept: усиление хвоста задержки при fan-out («The Tail at Scale»).

Запрос параллельно опрашивает N независимых бэкендов и ждёт всех; у каждого доля ответов
медленнее порога L равна q (L — его p99 / p99,5 / p99,9). Какая доля пользовательских
запросов медленнее L? Ответ: 1 − (1 − q)^N — для Senior это базовая оценка при
проектировании fan-out (почему p99 бэкенда становится медианой фронта).

Подтип один (прямой расчёт), варьируются контекст, N, перцентиль и формулировка.
Дистракторы — содержательные ошибки, все в одной числовой форме:
  * same_as_backend — «доля как у одного бэкенда» (q);
  * union_bound — сумма N·q (верхняя оценка, а не вероятность; при N·q ≥ 0,3 заметно больше);
  * complement — (1 − q)^N, доля запросов, где медленных нет (перепутано дополнение).
Ключ проверяется исполнением: программа на Python перемножает вероятности «бэкенд уложился»
по каждому из N бэкендов точной арифметикой (Fraction) и печатает букву совпавшего варианта.
"""
from __future__ import annotations

from fractions import Fraction

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.perf.fanout_tail_mcq"

CONTEXTS = [
    ("поиск по каталогу", "шардов индекса", "шард", "поисковый запрос"),
    ("лента рекомендаций", "сервисов-источников", "источник", "запрос ленты"),
    ("агрегатор цен", "поставщиков", "поставщик", "запрос цены"),
    ("BFF мобильного приложения", "микросервисов", "микросервис", "запрос экрана"),
    ("аналитический дашборд", "партиций хранилища", "партиция", "запрос виджета"),
]
PCTS = [("99", Fraction(1, 100)), ("99,5", Fraction(1, 200)), ("99,9", Fraction(1, 1000))]

PROGRAM = """from fractions import Fraction
N, q = {n}, Fraction({qn}, {qd})
ok_all = Fraction(1)
for _ in range(N):          # бэкенды независимы, запрос ждёт всех
    ok_all *= 1 - q
slow = 1 - ok_all
options = {opts!r}
hit = [k for k, v in options.items() if abs(Fraction(v) - 100 * slow) <= Fraction(5, 100)]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _pct(x: Fraction) -> str:
    return f"{float(100 * x):.1f}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, many, one, req = rng.choice(CONTEXTS)
    for _ in range(500):
        pname, q = rng.choice(PCTS)
        n = rng.choice([20, 30, 40, 50, 60, 80, 100, 150, 200, 300, 500, 800])
        if not (Fraction(3, 10) <= n * q <= Fraction(9, 10)):
            continue
        good = 1 - (1 - q) ** n
        vals = {"good": good, "same_as_backend": q, "union_bound": n * q, "complement": (1 - q) ** n}
        shown = {k: _pct(v) for k, v in vals.items()}
        nums = sorted(float(v) for v in shown.values())
        if len(set(shown.values())) == 4 and min(b - a for a, b in zip(nums, nums[1:])) >= 3.0:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    lat = rng.choice([80, 120, 150, 200, 250, 300])
    text = {k: f"≈ {v.replace('.', ',')} % запросов" for k, v in shown.items()}
    chosen = ["same_as_backend", "union_bound", "complement"]
    opts, key = make_options(rng, (text["good"], None), [(text[d], None) for d in chosen])
    opt_vals = {o.id: o.text.split("≈ ")[1].split(" %")[0].replace(",", ".") for o in opts}
    lead = rng.choice([
        f"{ctx.capitalize()}: каждый {req} параллельно отправляется на {n} {many}, ответ "
        f"собирается, когда ответили все.",
        f"Сервис «{ctx}» обслуживает {req} так: запрос рассылается сразу на все {n} {many} и "
        f"ждёт ответа каждого.",
        f"В архитектуре «{ctx}» {req} — это fan-out на {n} {many} с ожиданием всех ответов."])
    stem = (f"{lead} У каждого бэкенда (тип «{one}») p{pname} задержки — {lat} мс, задержки разных "
            f"бэкендов независимы, сеть и сборка ответа пренебрежимо быстрые. Какая доля "
            f"пользовательских запросов будет медленнее {lat} мс?")
    checks = [Check(name="tail", runner="python",
                    program=PROGRAM.format(n=n, qn=q.numerator, qd=q.denominator, opts=opt_vals),
                    expect="stdout_equals", expected_stdout=key)]
    ak = AnswerKey(kind="option", value=key,
                   explanation=(f"Запрос быстрый, только если быстрыми оказались все {n} бэкендов: "
                                f"(1 − {str(float(q)).replace('.', ',')})^{n} ≈ {_pct(vals['complement']).replace('.', ',')} %; "
                                f"медленных — дополнение, ≈ {shown['good'].replace('.', ',')} %. "
                                f"«Как у одного бэкенда» ({shown['same_as_backend'].replace('.', ',')} %) "
                                f"игнорирует fan-out; N·q = {shown['union_bound'].replace('.', ',')} % "
                                f"— верхняя оценка, а не вероятность; "
                                f"{_pct(vals['complement']).replace('.', ',')} % — доля быстрых, "
                                f"а не медленных."))
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Ответ проверяется программой: точный расчёт "
                                           "вероятности по N независимым бэкендам.",
                         params={"n": n, "q": str(q), "percentile": pname, "latency_ms": lat,
                                 "shown": shown})
