"""frontend.js.abort_fetch_fix — choose_fix: отмена предыдущего запроса через AbortController."""
from __future__ import annotations

from assessment_bank.families.frontend._fake_abort import FAKE_ABORT
from assessment_bank.families.frontend._fake_timers import FAKE_TIMERS
from assessment_bank.gen_utils import build_variant, js_harness, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.js.abort_fetch_fix"

CTX = [("createProfileLoader", "showProfile", "профиль пользователя", "переключается между профилями"),
       ("createProductLoader", "renderCard", "карточка товара", "листает карточки товаров"),
       ("createChartLoader", "drawChart", "график котировок", "переключает тикеры"),
       ("createMailLoader", "showLetter", "просмотр письма", "перебирает письма в списке"),
       ("createOrderLoader", "renderOrder", "детали заказа", "переходит между заказами")]


def _code(kind: str, fn: str, cb: str) -> str:
    sig = "{ signal: controller.signal }"
    catch = ["    } catch (e) {", "      if (e.name !== 'AbortError') throw e;", "    }"]
    call = f"      const data = await fetchFn(id, {sig});"
    if kind == "buggy":
        outer, start = [], ["    const controller = new AbortController();"]
    elif kind in ("good", "no_signal", "inverted", "swallow"):
        outer = ["  let controller = null;"]
        start = ["    controller?.abort();", "    controller = new AbortController();"]
        if kind == "no_signal":
            call = "      const data = await fetchFn(id);"
        if kind == "inverted":
            catch = ["    } catch (e) {", "      if (e.name === 'AbortError') throw e;", "    }"]
        if kind == "swallow":
            catch = ["    } catch (e) {", "      return null;", "    }"]
    elif kind == "shared":
        outer = ["  const controller = new AbortController();"]
        start = ["    controller.abort();", "    const { signal } = controller;"]
        call = "      const data = await fetchFn(id, { signal });"
    elif kind == "late_assign":
        outer = ["  let controller = null;"]
        start = ["    controller?.abort();", "    const current = new AbortController();"]
        call = ("      const data = await fetchFn(id, { signal: current.signal });\n"
                "      controller = current;")
    else:
        raise ValueError(kind)
    lines = ([f"function {fn}(fetchFn, {cb}) {{"] + outer +
             ["  return async function load(id) {"] + start +
             ["    try {", call, f"      {cb}(data);"] + catch + ["  };", "}"])
    return "\n".join(lines)


WHY = {"no_signal": "без signal отмена не доходит до запроса — старый ответ всё равно отрисуется",
       "inverted": "условие перевёрнуто: отмена становится ошибкой, а ошибки сервера глотаются",
       "swallow": "ошибки сервера молча проглатываются, вызывающий код о них не узнает",
       "shared": "один контроллер на все вызовы: после первой отмены его signal навсегда "
                 "отменён, и все запросы сразу завершаются AbortError",
       "late_assign": "контроллер сохраняется только после ответа — новый вызов не видит "
                      "текущий запрос и не может его отменить"}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    fn, cb, ctx, action = rng.choice(CTX)
    a, b, c = rng.sample(range(10, 100), 3)
    ms1 = rng.choice([250, 300, 400, 600])
    t2 = rng.choice([50, 100, 150])
    ms2 = rng.choice([20, 40, 60])
    ms3 = rng.choice([30, 50, 70])
    code = _code("buggy", fn, cb)
    chosen = rng.sample(sorted(WHY), 3)
    opts, key = make_options(rng, ("Заменить функцию на:", _code("good", fn, cb)),
                             [("Заменить функцию на:", _code(k, fn, cb)) for k in chosen])
    test = f"""
        const api = makeFetch({{ {a}: {{ ms: {ms1} }}, {b}: {{ ms: {ms2} }}, {c}: {{ ms: {ms3}, fail: true }} }});
        const got = [];
        const load = {fn}(api.fetch, (d) => got.push(d));
        const p1 = load({a}).then(() => 'ok', (e) => e.name);
        await advanceTo({t2});
        const p2 = load({b}).then(() => 'ok', (e) => e.name);
        await advanceTo({t2 + ms1 + 100});
        const r1 = await p1;
        const r2 = await p2;
        __assert(JSON.stringify(got) === '["data-{b}"]', 'отрисовано ' + JSON.stringify(got));
        __assert(r1 === 'ok' && r2 === 'ok', 'load: ' + r1 + ' ' + r2);
        __assert(api.aborted === 1, 'отменено ' + api.aborted);
        const p3 = load({c}).then(() => 'ok', (e) => e.message);
        await advanceTo({t2 + ms1 + 200 + ms3});
        const r3 = await p3;
        __assert(r3 === 'HTTP 500', 'ошибка сервера: ' + r3);
    """
    prelude = FAKE_TIMERS + "\n" + FAKE_ABORT
    checks = [Check(name=f"option:{o.id}", runner="node", embeds_display_code=False,
                    program=js_harness(o.code, test, prelude),
                    expect="pass" if o.id == key else "fail") for o in opts]
    checks.append(Check(name="buggy_fails", runner="node", program=js_harness(code, test, prelude),
                        expect="fail"))
    stem = (f"Функция `{fn}` ({ctx}) возвращает `load(id)`: загрузить данные и передать их в "
            f"`{cb}`. Когда пользователь быстро {action}, на экране иногда остаются данные "
            f"предыдущего элемента: например, `load({a})` отвечает за {ms1} мс, а "
            f"`load({b})`, вызванный через {t2} мс, — за {ms2} мс. Требования: новый вызов "
            f"`load` отменяет предыдущий незавершённый запрос (`fetchFn` принимает "
            f"`{{ signal }}` и при отмене отклоняет промис с ошибкой `AbortError`); отмена не "
            f"считается ошибкой; ошибки сервера пробрасываются вызывающему коду. Какое "
            f"исправление верно?")
    ak = AnswerKey(kind="option", value=key,
                   explanation="Верно: контроллер хранится в замыкании, новый вызов отменяет "
                               "предыдущий и передаёт свой signal, AbortError не считается "
                               "ошибкой. Дистракторы: " + "; ".join(WHY[k] for k in chosen) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="abort_previous_request",
                         display_code_note="В песочнице нет fetch и AbortController: тесты "
                                           "используют совместимые поддельные реализации и "
                                           "виртуальное время.",
                         params={"distractors": chosen})
