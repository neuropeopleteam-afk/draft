"""frontend.react.state_batch_mcq — mcq_concept: useState, замыкание на значение рендера и
очередь обновлений (React 18).

Ключ проверяется исполнением: тот же обработчик (JSX заменён объектом) запускается на
минимальной модели useState — обновления копятся в очереди и применяются по порядку при
следующем рендере (значение — заменяет, функция — получает текущее состояние), а
переменная состояния в обработчике — значение текущего рендера.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.react.state_batch_mcq"

CTX = [("LikeButton", "likes", "лайки под постом"), ("CartCounter", "qty", "счётчик товара"),
       ("StarRating", "stars", "оценка отзыва"), ("Pager", "page", "пагинация списка"),
       ("ClickGame", "score", "мини-игра")]

RUNTIME = """const __hooks = { state: [], queue: [], i: 0 };
function useState(init) {
  const i = __hooks.i++;
  if (!(i in __hooks.state)) __hooks.state[i] = init;
  return [__hooks.state[i], (u) => __hooks.queue.push([i, u])];
}
function __render(C) { __hooks.i = 0; return C(); }
function __flush() {
  for (const [i, u] of __hooks.queue) __hooks.state[i] = typeof u === 'function' ? u(__hooks.state[i]) : u;
  __hooks.queue = [];
}"""


def _model(init, seq, clicks, model):
    state, logs = init, []
    for _ in range(clicks):
        captured = cur = pending = state
        ks = [k for kind, k in seq if kind != "log"]
        for kind, k in seq:
            if kind == "log":
                logs.append(cur if model == "sync" else captured)
                continue
            if model == "sync":
                cur = cur + k
                pending = cur
            elif model == "sum":
                pending += k
            elif model == "all_value":
                pending = captured + k
            elif model == "first_only":
                pending = captured + ks[0]
            elif kind == "value":
                pending = captured + k
            else:
                pending = pending + k
        if model == "log_new":
            _, fin = _model(state, seq, 1, "correct")
            logs[-sum(1 for kd, _ in seq if kd == "log"):] = [fin]
            pending = fin
        state = pending
    return logs, state


def _text(logs, final):
    lg = " и ".join(map(str, logs))
    return f"в консоли {lg}, на кнопке {final}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    comp, s, ctx = rng.choice(CTX)
    setter = "set" + s[0].upper() + s[1:]
    for _ in range(300):
        init = rng.randint(0, 5)
        kinds = [rng.choice(["value", "updater"]) for _ in range(3)]
        if len(set(kinds)) == 1:
            continue
        seq = [(k, rng.randint(1, 5)) for k in kinds]
        seq.insert(rng.randint(0, 3), ("log", 0))
        clicks = rng.choice([1, 1, 2])
        correct = _model(init, seq, clicks, "correct")
        if correct == _model(init, seq, clicks, "sum") or correct == _model(init, seq, clicks, "all_value"):
            continue
        ctext = _text(*correct)
        distr = []
        models = ["sync", "sum", "all_value", "first_only", "log_new"]
        rng.shuffle(models)
        for m in models:
            t = _text(*_model(init, seq, clicks, m))
            if t != ctext and t not in distr:
                distr.append(t)
        if len(distr) >= 3:
            break
    else:
        raise RuntimeError("мало дистракторов")
    body = []
    for kind, k in seq:
        if kind == "log":
            body.append(f"    console.log({s});")
        elif kind == "value":
            body.append(f"    {setter}({s} + {k});")
        else:
            body.append(f"    {setter}((prev) => prev + {k});")
    head = [f"function {comp}() {{", f"  const [{s}, {setter}] = useState({init});",
            "  function handleClick() {"] + body + ["  }"]
    code = "\n".join(head + [f"  return <button onClick={{handleClick}}>{{{s}}}</button>;", "}"])
    js = "\n".join(head + [f"  return {{ onClick: handleClick, text: {s} }};", "}"])
    program = (RUNTIME + "\n" + js + "\n" + f"let ui = __render({comp});\n" +
               "for (let c = 0; c < %d; c++) { ui.onClick(); __flush(); ui = __render(%s); }\n"
               % (clicks, comp) + "console.log('button=' + ui.text);\n")
    logs, final = correct
    expected = "\n".join(map(str, logs)) + f"\nbutton={final}"
    opts, key = make_options(rng, (ctext, None), [(d, None) for d in distr[:3]])
    clicks_txt = ("один раз" if clicks == 1 else
                  "два раза; между нажатиями компонент успел перерисоваться")
    stem = (f"Компонент `{comp}` ({ctx}), React 18, StrictMode выключен. Пользователь нажал "
            f"кнопку {clicks_txt}. Что будет выведено в консоль и какое число покажет кнопка "
            f"после всех перерисовок?")
    ak = AnswerKey(kind="option", value=key,
                   explanation=f"`{s}` внутри обработчика — значение текущего рендера, "
                               f"setState его не меняет (console.log выводит старое значение). "
                               f"Обновления копятся и применяются по порядку при следующем "
                               f"рендере: `{setter}({s} + k)` заменяет состояние на "
                               f"«значение рендера + k», `{setter}((prev) => prev + k)` "
                               f"прибавляет k к результату предыдущих обновлений.")
    checks = [Check(name="stdout", runner="node", program=program, expect="stdout_equals",
                    expected_stdout=expected, embeds_display_code=False)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         display_code_note="Ключ проверен исполнением обработчика (JSX заменён "
                                           "объектом) на минимальной модели useState React 18: "
                                           "очередь обновлений применяется при следующем рендере.",
                         params={"seq": seq, "clicks": clicks, "init": init})
