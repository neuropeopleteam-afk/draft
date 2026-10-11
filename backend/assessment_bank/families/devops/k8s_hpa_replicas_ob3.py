"""devops.k8s.hpa_replicas_ob3 — open_book_3step: расчёт числа реплик как в HorizontalPodAutoscaler.

Алгоритм HPA (документация Kubernetes «Horizontal Pod Autoscaling»): desired = ceil(current × metric / target);
если |metric / target − 1| ≤ tolerance (0,1 по умолчанию) — масштаб не меняется; результат ограничен
minReplicas/maxReplicas. Дефект один: округление вниз (`int(...)`) вместо ceil — при дробном результате
сервису не хватает реплики. Шаг 1 — сценарий, на котором дефект проявляется (дробное произведение в
пределах min/max, вне допуска); остальные — в допуске, целое произведение, упор в maxReplicas.
Шаг 2 — исправление: верное — `math.ceil(current * ratio)`; почти верные — `round(...)`, `int(...) + 1`,
`math.ceil(ratio) * current`. Шаг 3 — перенос: флаппинг и окно стабилизации, несколько метрик, неготовые
поды. Проверка шагов 1–2 — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

import math

from assessment_bank.gen_utils import build_variant, make_options, make_rng, ob3_steps, rubric_from
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "devops.k8s.hpa_replicas_ob3"

CTX = [("API заказов", "cpu"), ("воркеры очереди писем", "cpu"), ("шлюз платежей", "cpu"),
       ("сервис рекомендаций", "memory"), ("рендер превью", "cpu"), ("поиск по каталогу", "memory")]

EXPR = {None: "int(current * ratio)", "ceil": "math.ceil(current * ratio)", "round": "round(current * ratio)",
        "plus1": "int(current * ratio) + 1", "ceil_ratio": "math.ceil(ratio) * current"}


def _code(fix=None, var="utilization"):
    return "\n".join([
        "import math",
        "",
        "TOLERANCE = 0.1",
        "",
        "",
        f"def desired_replicas(current, {var}, target, min_r, max_r):",
        f"    ratio = {var} / target",
        "    if abs(ratio - 1.0) <= TOLERANCE:",
        "        return current",
        f"    desired = {EXPR[fix]}",
        "    return max(min_r, min(max_r, desired))",
    ])


def _ref(cur, util, target, lo, hi):
    ratio = util / target
    if abs(ratio - 1.0) <= 0.1:
        return cur
    return max(lo, min(hi, math.ceil(cur * ratio)))


def _run(fix, sc):
    ratio = sc[1] / sc[2]
    if abs(ratio - 1.0) <= 0.1:
        return sc[0]
    cur = sc[0]
    d = {None: int(cur * ratio), "ceil": math.ceil(cur * ratio), "round": round(cur * ratio),
         "plus1": int(cur * ratio) + 1, "ceil_ratio": math.ceil(ratio) * cur}[fix]
    return max(sc[3], min(sc[4], d))


def _prog(code, scenarios):
    calls = "\n".join(f"print(desired_replicas{sc!r})" for sc in scenarios)
    return code + "\n\n\n" + calls


CONDITIONS = {
    "flapping": dict(
        text=("После исправления реплики сервиса «прыгают» 6 → 8 → 6 каждые пару минут: нагрузка колеблется "
              "около порога. Почему так происходит и какими настройками HPA (autoscaling/v2) и приложения вы "
              "это уберёте?"),
        criteria=[("cause", "Метрика колеблется около целевого значения, при каждом пересчёте ceil даёт разное "
                            "число; масштабирование вниз сразу снимает поды, нагрузка на оставшиеся растёт", 0.35),
                  ("behavior", "behavior.scaleDown.stabilizationWindowSeconds (окно, в котором берётся максимум "
                               "рекомендаций), policies с ограничением скорости (подов/процентов за период), "
                               "отдельные настройки scaleUp", 0.4),
                  ("app", "Проверка запаса: requests подобраны по реальному потреблению, readiness не пускает "
                          "трафик на холодный под; наблюдение за графиком replicas и метрики", 0.25)],
        strong="""Нагрузка ходит около целевого значения, и ceil(current × ratio) на соседних пересчётах даёт
            то 8, то 6; уменьшение снимает поды, нагрузка на оставшиеся растёт, и HPA снова добавляет. В
            autoscaling/v2 задаю behavior.scaleDown.stabilizationWindowSeconds (например, 300): вниз
            масштабирует только до максимума рекомендаций за окно; policies ограничивают скорость (не больше
            одного пода или 20 % за минуту), для scaleUp оставляю быстрый рост. Со стороны приложения
            проверяю, что requests соответствуют реальному потреблению (иначе utilization искажена), а
            readiness-проба не пускает трафик на холодный под. Результат смотрю на графике replicas вместе с
            метрикой.""",
        medium="""Нужно увеличить окно стабилизации для scaleDown, чтобы HPA не уменьшал реплики сразу.""",
        weak="""Поставить minReplicas равным maxReplicas, чтобы реплики не менялись."""),
    "multi_metric": dict(
        text=("В HPA добавили вторую метрику — длину очереди на под (target 30 сообщений) к утилизации CPU. Как "
              "HPA выбирает число реплик при нескольких метриках, как это отразить в функции и что будет, если "
              "одна метрика временно недоступна?"),
        criteria=[("max_rule", "HPA считает рекомендацию по каждой метрике и берёт максимум (при росте); "
                               "реплики не должны уменьшаться из-за одной «спокойной» метрики", 0.4),
                  ("code", "Функция принимает список (значение, цель), считает ceil по каждой с допуском и "
                           "берёт max, затем ограничивает min/max; тесты на случаи «одна метрика за порогом»", 0.3),
                  ("missing", "Если часть метрик недоступна, HPA не уменьшает масштаб по оставшимся (может "
                              "только увеличить); алерт на отсутствие метрики", 0.3)],
        strong="""При нескольких метриках HPA считает желаемое число реплик по каждой отдельно и берёт
            максимум: CPU может говорить 4, очередь — 9, будет 9. В функции принимаю список пар (значение,
            цель), для каждой считаю ceil(current × value / target) с учётом допуска, беру max и только потом
            ограничиваю min/max; тестирую «CPU спокойный, очередь растёт» и наоборот. Если одна из метрик не
            получена, HPA не уменьшает масштаб по оставшимся — разрешено только увеличение, чтобы не
            снять поды вслепую; на отсутствие метрики ставлю алерт, иначе автомасштабирование тихо
            деградирует.""",
        medium="""HPA берёт большую из рекомендаций по метрикам. В функции посчитаю обе и возьму max.""",
        weak="""Нужно сложить две метрики и делить на сумму целей."""),
    "unready_pods": dict(
        text=("При выкладке новые поды 40 секунд прогреваются и ещё не готовы, а HPA в это время видит высокую "
              "утилизацию и добавляет реплики. Как HPA учитывает неготовые поды и поды без метрик, и что вы "
              "настроите, чтобы выкладка не раздувала число реплик?"),
        criteria=[("hpa_logic", "Неготовые поды и поды без метрик при росте считаются с консервативными "
                                "значениями (0 % при scale up, 100 % при scale down), пока не прошло время "
                                "инициализации; ratio пересчитывается", 0.4),
                  ("settings", "readinessProbe отражает реальную готовность, startupProbe для долгого старта; "
                               "окно инициализации CPU у контроллера; behavior.scaleUp с окном/ограничением", 0.35),
                  ("verify", "Проверка на стенде: график replicas и utilization при выкладке, нагрузочный тест, "
                             "сравнение с ожидаемым расчётом", 0.25)],
        strong="""HPA при расчёте отдельно обрабатывает неготовые поды и поды без метрик: при росте
            считает их потребление нулевым, при снижении — равным цели, и пересчитывает ratio, чтобы
            прогревающиеся поды не раздули рекомендацию; первые метрики CPU после старта игнорируются в
            течение окна инициализации. Значит, важно, чтобы readinessProbe отражала реальную готовность,
            а долгий старт закрывала startupProbe — иначе под «готов», но горячий от прогрева. Дополнительно
            behavior.scaleUp со stabilizationWindowSeconds и ограничением скорости. Проверяю выкладкой под
            нагрузкой: графики replicas и utilization, число реплик сверяю с ожидаемым расчётом.""",
        medium="""Нужно настроить readinessProbe, чтобы неготовые поды не учитывались, и замедлить scaleUp.""",
        weak="""Отключить HPA на время выкладки."""),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, kind = rng.choice(CTX)
    var = "utilization" if kind == "cpu" else "usage_ratio"
    code = _code(None, var)
    for _ in range(3000):
        lo, hi = rng.randint(2, 3), rng.randint(8, 12)
        target = rng.choice([50, 60, 70, 75, 80])
        cur = rng.randint(3, 6)
        # дробный рост в пределах; допуск; целый результат; упор в max
        bad = (cur, rng.randint(target + 15, target + 60), target, lo, hi)
        tol = (rng.randint(4, hi - 1), target + rng.choice([-5, -3, 2, 4, 6]), target, lo, hi)
        whole_cur = rng.choice([2, 4, 5])
        whole = (whole_cur * 2 if whole_cur * 2 < hi else 4, target * 3 // 2 if target % 2 == 0 else target * 2,
                 target, lo, hi)
        cap = (hi - 1, target * 2 + rng.randint(5, 20), target, lo, hi)
        if _run(None, bad) == _ref(*bad) or _ref(*bad) > hi:
            continue
        if any(_run(None, s) != _ref(*s) for s in (tol, whole, cap)):
            continue
        if abs(tol[1] / target - 1) > 0.1 or len({bad, tol, whole, cap}) < 4:
            continue
        # тестовый набор шага 2 отличает каждое почти верное исправление
        t2 = [bad, tol, whole, cap, (4, target + target // 2 - 1 if target > 60 else 89, target, 2, 10),
              (6, target + 10, target, 2, 20), (3, target * 2, target, 1, 10)]
        ref2 = [_ref(*s) for s in t2]
        if all(any(_run(f, s) != r for s, r in zip(t2, ref2)) for f in ("round", "plus1", "ceil_ratio")):
            break
    fmt = lambda s: (f"сейчас {s[0]} реплик, средняя утилизация {s[1]} % при цели {s[2]} %, "  # noqa: E731
                     f"minReplicas {s[3]}, maxReplicas {s[4]}")
    scen = [bad, tol, whole, cap]
    texts = [fmt(s) for s in scen]
    opts1, key1 = make_options(rng, (texts[0], None), [(t, None) for t in texts[1:]], step=1)
    by_text = dict(zip(texts, scen))
    checks = []
    for o in opts1:
        sc = by_text[o.text]
        checks.append(Check(name=f"step1:{o.id}", runner="python", program=_prog(code, [sc]),
                            expect="stdout_differs" if o.id == key1 else "stdout_equals",
                            expected_stdout=str(_ref(*sc))))
    lab = "Заменить строку расчёта на `desired = {}`:"
    opts2, key2 = make_options(rng, (lab.format(EXPR["ceil"]), _code("ceil", var)),
                               [(lab.format(EXPR[k]), _code(k, var)) for k in ("round", "plus1", "ceil_ratio")],
                               step=2)
    for o in opts2:
        checks.append(Check(name=f"step2:{o.id}", runner="python", program=_prog(o.code, t2),
                            expect="stdout_equals" if o.id == key2 else "stdout_differs",
                            expected_stdout="\n".join(map(str, ref2)), embeds_display_code=False))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    stem = (f"Для сервиса «{ctx}» команда написала собственный автомасштабировщик (метрика — {kind}) и хочет, чтобы "
            "он считал число реплик как HorizontalPodAutoscaler: desired = ceil(current × metric / target), "
            "без изменений при отклонении в пределах 10 %, с ограничением minReplicas/maxReplicas. Под нагрузкой "
            "сервису иногда не хватает реплики.")
    steps = ob3_steps(
        "Шаг 1. Воспроизведите дефект: в каком сценарии функция вернёт не то, что вернул бы HPA?",
        "Шаг 2. Выберите исправление, после которого функция совпадает с HPA на любых входных данных.",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    b = bad
    expl = (f"int() округляет вниз: {b[0]} × {b[1]} / {b[2]} даёт {int(b[0] * b[1] / b[2])} вместо {_ref(*b)}. В "
            "допуске, при целом произведении и упоре в maxReplicas результат совпадает. round() ошибается при "
            "дробной части меньше половины, int() + 1 — при целом произведении, ceil(ratio) × current — при "
            f"большинстве дробных отношений. Шаг 3 — «{cond_name}».")
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"}, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2, answer_key=ak,
                         rubric=rubric, context=ctx, verification="execution", checks=checks, steps=steps,
                         defect_type="floor_instead_of_ceil", params={"condition": cond_name, "bad": list(bad)})
