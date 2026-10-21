"""qa.mock.t21_late_binding_output — predict_output (набор t21, порог Middle): список проверок, собранный lambda
в цикле, — позднее связывание против параметра по умолчанию.

Для каждого ожидаемого значения (код ответа, тип содержимого, статус) в цикле или генераторе списка создаются две
проверки: `lambda r: r == code` (переменная читается в момент ВЫЗОВА — все проверки видят последнее значение) и
`lambda r, code=code: r == code` (значение фиксируется при создании). Обе пачки прогоняются на ответах заглушки
сервиса, печатается число сработавших проверок (sum) или «прошли ли все» (all). Ловушки: поздние проверки — это N
копий «r == последнее»; для ответа, равного последнему ожидаемому, срабатывают ВСЕ поздние; для остальных
ожидаемых — ни одна. Отличие от backend.http.t21_route_lambda_late_binding_output (словарь обработчиков URL,
смена префикса после цикла): здесь проверки-предикаты, обе версии рядом и агрегирование по ответам. Ключ —
независимая модель в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.mock.t21_late_binding_output"

# (сюжет, имя переменной цикла, пул ожидаемых значений, пул «чужих» ответов)
CTX = [("контрактные тесты API заказов", "code", [200, 201, 202, 204], [404, 500, 302]),
       ("проверки заголовков ответа", "ctype", ["json", "xml", "csv", "html"], ["text", "pdf"]),
       ("тесты статусов платежа", "status", ["new", "paid", "held", "void"], ["error", "lost"]),
       ("тесты ролей доступа", "role", ["admin", "editor", "viewer", "auditor"], ["guest", "bot"]),
       ("проверки кодов ошибок валидации", "err", ["E1", "E2", "E3", "E7"], ["E9", "OK"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, var, pool, alien = rng.choice(CTX)
    k = rng.choice([3, 3, 4])
    expected = rng.sample(pool, k)
    last = expected[-1]
    others = [e for e in expected if e != last]
    resp = [rng.choice(others), last]
    if rng.random() < 0.6:
        resp.append(rng.choice(alien))
    rng.shuffle(resp)
    agg = rng.choice(["sum", "sum", "all"])
    form = rng.choice(["loop", "comp"])
    names = rng.choice([("late", "bound"), ("checks", "fixed"), ("lazy", "early")])
    ln, bn = names
    lit = lambda v: repr(v).replace("'", '"')  # noqa: E731
    exp_lit = "[" + ", ".join(lit(e) for e in expected) + "]"
    resp_lit = "[" + ", ".join(lit(r) for r in resp) + "]"
    if form == "loop":
        build = [f"{ln}, {bn} = [], []", f"for {var} in expected:", f"    {ln}.append(lambda r: r == {var})",
                 f"    {bn}.append(lambda r, {var}={var}: r == {var})"]
    else:
        build = [f"{ln} = [lambda r: r == {var} for {var} in expected]",
                 f"{bn} = [lambda r, {var}={var}: r == {var} for {var} in expected]"]
    if agg == "sum":
        show = f"    print(r, sum(c(r) for c in {ln}), sum(c(r) for c in {bn}))"
    else:
        show = f"    print(r, all(c(r) for c in {ln}), all(c(r) for c in {bn}))"
    code = "\n".join([f"expected = {exp_lit}"] + build + [f"responses = {resp_lit}", "for r in responses:", show])
    outs, notes = [], []
    for r in resp:
        late_hits = k if r == last else 0
        bound_hits = sum(1 for e in expected if e == r)
        if agg == "sum":
            outs.append(f"{r} {late_hits} {bound_hits}")
        else:
            outs.append(f"{r} {late_hits == k} {bound_hits == k}")
        if r == last:
            notes.append(f"{r} равен последнему ожидаемому — срабатывают все {k} поздние проверки, из "
                         f"зафиксированных — одна")
        elif r in expected:
            notes.append(f"{r} есть в expected, но не последний — поздние проверки (все сравнивают с {last}) "
                         f"не срабатывают, зафиксированная — одна")
        else:
            notes.append(f"{r} не ожидается — 0 и 0")
    out = "\n".join(outs)
    where = "цикла for" if form == "loop" else "генератора списка"
    agg_note = ("sum считает сработавшие проверки (True = 1)" if agg == "sum" else
                f"all истинно, только если сработали все {k} проверки")
    expl = (f"Lambda без параметра по умолчанию читает {var} в момент вызова — после {where} это последнее "
            f"значение {lit(last)}, поэтому все {k} проверки в {ln} одинаковы: r == {lit(last)}. В {bn} значение "
            f"зафиксировано параметром по умолчанию {var}={var}. {agg_note}. " + "; ".join(notes) +
            ". Вывод по строкам: " + " / ".join(f"«{o}»" for o in outs) + ".")
    stem = (f"Автотесты ({ctx}): программа собирает список проверок для ожидаемых значений двумя способами и "
            f"прогоняет их на ответах заглушки сервиса.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"expected": expected, "responses": resp, "agg": agg, "form": form},
                          language="python")
