"""frontend.arch.optimistic_update_fix — choose_fix (Lead): оптимистичные обновления при параллельных изменениях.

Показан клиентский стор с оптимистичным обновлением: значение меняется в интерфейсе сразу, при ошибке
откатывается к «снимку» до изменения. Пользователь быстро меняет значение несколько раз подряд, ответы
приходят в произвольном порядке, часть изменений отклоняется сервером. Сервер применяет запросы в порядке
отправки; отклонённый — не применяет. Нужна замена метода изменения, при которой: (1) интерфейс меняется
сразу; (2) после того как все ответы пришли, значение в интерфейсе равно значению на сервере при любом
порядке ответов и любом наборе отказов; (3) поздний ответ на старое изменение не затирает более новое
(пока новое не отклонено).

Варианты (каждый исполняется в node) построены по схеме 2×2 от верного: журнал изменений ключа (номер,
значение, состояние), показ — последнее неотклонённое изменение, при пустом — подтверждённое значение.
Из пула правил выбираются два (a, b): варианты — верный, нарушено a, нарушено b, нарушены оба. Пул:
  * only_ok — показываются только подтверждённые изменения: интерфейс не меняется сразу;
  * clear_on_fail — при отказе журнал сбрасывается: теряются ещё ожидающие старые изменения;
  * clear_on_ok — при успехе журнал очищается, подтверждённое значение пишется без номера: поздний успех
    старого изменения затирает новое;
  * show_rejected — если отклонено всё, показывается последнее введённое, а не подтверждённое.
Пара (clear_on_fail, show_rejected) не используется (пустой журнал). Каждый вариант отличается от двух
других на одно правило и от третьего — на два, к тому же у каждого варианта свои локальные имена и
необязательные строки, поэтому ни длина, ни сходство вариантов не выдают ключ.
Ключ проверяется исполнением: поддельный API с управляемым порядком ответов
и отказами, пять сценариев, после каждого — сравнение интерфейса с сервером.
"""
from __future__ import annotations

import re

from assessment_bank.gen_utils import build_variant, js_harness, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.arch.optimistic_update_fix"

# контекст, класс, метод стора, метод API, что меняем, значения
CONTEXTS = [
    ("корзина интернет-магазина", "CartStore", "setQty", "updateQty", "количество товара", [1, 2, 3, 4, 5, 6]),
    ("доска задач", "BoardStore", "setColumn", "moveCard", "колонка карточки",
     ["todo", "doing", "review", "done", "blocked", "archive"]),
    ("настройки уведомлений", "PrefsStore", "setMode", "savePref", "режим уведомлений",
     ["all", "mentions", "digest", "none", "urgent", "weekly"]),
    ("оценка фильма", "RatingStore", "setStars", "rate", "число звёзд", [1, 2, 3, 4, 5, 0]),
    ("статус заказа у оператора", "OrderStore", "setStatus", "changeStatus", "статус заказа",
     ["new", "paid", "packed", "shipped", "done", "hold"]),
    ("приоритет обращения", "TicketStore", "setPriority", "updatePriority", "приоритет обращения",
     ["low", "normal", "high", "urgent", "critical", "minor"]),
]

HEAD = """class {cls} {{
  constructor(api, initial) {{
    this.api = api;
    this.view = {{ ...initial }};       // что видит пользователь
    this.confirmed = {{ ...initial }};  // последнее известное значение сервера
    this.ops = {{}};                    // служебное состояние по ключу
    this.errors = {{}};
    this.seq = 0;
  }}
"""

METHODS = {
    "buggy": """
  async {meth}(id, value) {{
    this.view[id] = value;
    try {{
      this.view[id] = await this.api.{api}(id, value);
    }} catch (e) {{
      this.view[id] = this.confirmed[id];
    }}
  }}
}}""",
    "good": """
  async {meth}(id, value) {{
    const seq = ++this.seq;
    const op = {{ seq, value, state: "pending" }};
    (this.ops[id] ||= []).push(op);
    this.show(id);
    try {{
      const saved = await this.api.{api}(id, value);
      Object.assign(op, {{ value: saved, state: "ok" }});
    }} catch (e) {{
      op.state = "failed";
    }}
    this.show(id);
  }}

  show(id) {{
    const live = this.ops[id].filter((o) => o.state !== "failed");
    this.view[id] = live.length ? live[live.length - 1].value : this.confirmed[id];
  }}
}}""",
}

# правило -> (фрагмент верного шаблона, замена); фрагменты разных правил не пересекаются
MUTATIONS = {
    "only_ok": ('(o) => o.state !== "failed"', '(o) => o.state === "ok"'),
    "clear_on_fail": ('      op.state = "failed";\n', '      this.ops[id] = [];\n'),
    "clear_on_ok": ('      Object.assign(op, {{ value: saved, state: "ok" }});\n',
                    '      this.confirmed[id] = saved;\n      this.ops[id] = [];\n'),
    "show_rejected": (": this.confirmed[id];", ": this.ops[id][this.ops[id].length - 1].value;"),
}
PAIRS = [(a, b) for i, a in enumerate(sorted(MUTATIONS)) for b in sorted(MUTATIONS)[i + 1:]
         if {a, b} != {"clear_on_fail", "show_rejected"}]
WHY = {
    "only_ok": "показ только подтверждённых изменений — интерфейс не меняется сразу (нарушено требование 1)",
    "clear_on_fail": "сброс журнала при отказе — вместе с отказом теряются ещё ожидающие старые изменения, и когда "
                     "они подтвердятся, интерфейс их не покажет",
    "clear_on_ok": "очистка журнала и запись подтверждённого значения при каждом успехе — поздний успех старого "
                   "изменения затирает новое",
    "show_rejected": "если отклонено всё, показывается последнее введённое значение, хотя сервер его не принял",
}

PRELUDE = """function makeApi(method, initial) {
  const api = { calls: [], initial: { ...initial } };
  api[method] = (id, value) => new Promise((resolve, reject) => api.calls.push({ id, value, resolve, reject }));
  return api;
}
const tick = () => new Promise((r) => setTimeout(r, 0));
// сервер применяет запросы в порядке отправки; отклонённый не применяется
function serverValue(api, id, outcome) {
  let v = api.initial[id];
  api.calls.forEach((c, i) => { if (c.id === id && outcome[i]) v = c.value; });
  return v;
}
async function settle(api, order, outcome) {
  for (const i of order) {
    const c = api.calls[i];
    if (outcome[i]) c.resolve(c.value); else c.reject(new Error("409"));
    await tick();
  }
}"""

# сценарий: изменения (индексы значений), порядок ответов, исходы; «затем» — продолжение после первой волны
SCENARIOS = [
    dict(name="поздний успех старого", vals=[1, 2], order=[1, 0], ok=[True, True]),
    dict(name="оба отклонены", vals=[1, 2], order=[0, 1], ok=[False, False]),
    dict(name="старый успех после нового, затем отказ", vals=[1, 2], order=[1, 0], ok=[True, True],
         then=dict(vals=[3], order=[2], ok=[False])),
    dict(name="новый отклонён, старый успешен позже", vals=[1, 2], order=[1, 0], ok=[False, True]),
    dict(name="три изменения вперемешку", vals=[1, 2, 3], order=[2, 0, 1], ok=[True, False, True]),
]


def _test(cls: str, meth: str, api: str, key: str, values: list, sc_order: list[int]) -> str:
    lit = lambda v: f'"{v}"' if isinstance(v, str) else str(v)  # noqa: E731
    init = lit(values[0])
    parts = []
    for n in sc_order:
        sc = SCENARIOS[n]
        body = [f"{{ // сценарий: {sc['name']}",
                f"  const api = makeApi('{api}', {{ '{key}': {init} }});",
                f"  const s = new {cls}(api, {{ '{key}': {init} }});",
                "  const pending = [];"]
        for vi in sc["vals"]:
            body.append(f"  pending.push(s.{meth}('{key}', {lit(values[vi])}));")
            body.append(f"  __assert(s.view['{key}'] === {lit(values[vi])}, 'сразу');")
        body.append(f"  await settle(api, {sc['order']}, {str(sc['ok'] + sc.get('then', {}).get('ok', [])).lower()});")
        if "then" in sc:
            t = sc["then"]
            for vi in t["vals"]:
                body.append(f"  pending.push(s.{meth}('{key}', {lit(values[vi])}));")
            body.append(f"  await settle(api, {t['order']}, {str(sc['ok'] + t['ok']).lower()});")
        outcome = str(sc["ok"] + sc.get("then", {}).get("ok", [])).lower()
        body.append("  await Promise.all(pending);")
        body.append(f"  __assert(s.view['{key}'] === serverValue(api, '{key}', {outcome}), "
                    f"'{sc['name']}: ' + s.view['{key}']);")
        body.append("}")
        parts.append("\n".join(body))
    return "\n".join(parts)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, cls, meth, api, what, pool = rng.choice(CONTEXTS)
    values = rng.sample(pool, 4)
    key = rng.choice(["item-7", "a1", "x42", "k-3", "p9"])
    f = dict(cls=cls, meth=meth, api=api)
    head = HEAD.format(**f)
    note = rng.choice(["// новое значение показываем сразу, ответ сервера учтём позже",
                       "// оптимистичное обновление: не ждём сервер",
                       "// интерфейс не должен ждать сети"])
    code = {"buggy": head + METHODS["buggy"].format(**f) + "\n"}
    a, b = rng.choice(PAIRS)
    sets = {"good": [], a: [a], b: [b], f"{a}+{b}": [a, b]}
    # у каждого варианта — свои локальные имена и необязательные строки (запись ошибки, пояснение): длина и
    # словарь варианта не выдают ключ; порядок обращений к rng не зависит от текста
    for k, muts in sets.items():
        tpl = METHODS["good"]
        for mname in muts:
            old, new = MUTATIONS[mname]
            if tpl.count(old) != 1:
                raise ValueError(f"фрагмент правила {mname} не найден ровно один раз")
            tpl = tpl.replace(old, new)
        names = {"op": rng.choice(["op", "change", "entry"]), "live": rng.choice(["live", "alive", "kept"]),
                 "saved": rng.choice(["saved", "stored", "result"]), "show": rng.choice(["show", "render", "sync"]),
                 "value": rng.choice(["value", "next", "v"]), "seq": rng.choice(["seq", "ticket", "n"])}
        add_err, add_note = rng.random() < 0.5, rng.random() < 0.5
        src = re.sub(r"(?<!this\.)\b(op|live|saved|show|value|seq)\b", lambda m: names[m.group(1)],
                     tpl.format(**f))
        src = src.replace("this.show(", f"this.{names['show']}(")
        if add_err:
            src = src.replace("} catch (e) {\n", "} catch (e) {\n      this.errors[id] = e.message;\n", 1)
        if add_note:
            sig = f"  async {meth}(id, {names['value']}) {{\n"
            src = src.replace(sig, sig + f"    {note}\n", 1)
        code[k] = head + src + "\n"
    if len({code[k] for k in sets}) != 4:
        raise ValueError("варианты 2×2 совпадают")
    sc_order = list(range(len(SCENARIOS)))
    rng.shuffle(sc_order)
    test = _test(cls, meth, api, key, values, sc_order)
    chosen = [a, b, f"{a}+{b}"]
    opts, akey = make_options(rng, ("Заменить класс на:", code["good"].rstrip()),
                              [("Заменить класс на:", code[c].rstrip()) for c in chosen])
    by_code = {code[k].rstrip(): k for k in sets}
    checks = [Check(name="buggy_fails", runner="node", program=js_harness(code["buggy"], test, PRELUDE),
                    expect="fail", embeds_display_code=False)]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="node", embeds_display_code=False,
                            program=js_harness(code[by_code[o.code]], test, PRELUDE),
                            expect="pass" if o.id == akey else "fail"))
    lead = rng.choice([
        f"В интерфейсе «{ctx}» ({what}) значение меняется сразу, а запрос уходит на сервер (`api.{api}`). "
        f"Пользователи жалуются: после быстрых изменений подряд интерфейс иногда показывает не то, что сохранено.",
        f"Стор `{cls}` («{ctx}») обновляет {what} оптимистично. Служба поддержки получает снимки экрана, где "
        f"интерфейс и сервер расходятся после нескольких быстрых изменений и отказов сервера.",
        f"«{ctx}»: {what} меняется в интерфейсе сразу, без ожидания ответа. Под нагрузкой ответы приходят в другом "
        f"порядке, часть изменений сервер отклоняет (конфликт версий), и интерфейс расходится с сервером.",
    ])
    stem = (f"{lead}\n\nСервер применяет запросы в порядке отправки, отклонённый запрос не применяет; ответы "
            f"приходят в любом порядке. Нужна замена класса, при которой: (1) значение в интерфейсе меняется сразу "
            f"при вызове `{meth}`; (2) когда пришли все ответы, `view` равно значению на сервере — при любом "
            f"порядке ответов и любом наборе отказов; (3) поздний ответ на старое изменение не затирает более новое, "
            f"пока новое не отклонено. Какая замена выполняет все требования?")
    return build_variant(
        FAMILY_ID, seed, stem=stem, code=code["buggy"], options=opts,
        answer_key=AnswerKey(kind="option", value=akey, explanation=(
            "Верно: журнал изменений ключа — показ равен последнему неотклонённому изменению (ожидающему или "
            "успешному), а если таких нет — подтверждённому значению; это совпадает с правилом сервера «последний "
            "применённый в порядке отправки» при любом порядке ответов. Остальные варианты нарушают правила: "
            f"{WHY[a]}; {WHY[b]}; третий вариант нарушает оба.")),
        context=ctx, verification="execution", checks=checks, defect_type="optimistic_race",
        display_code_note=("Ответ проверяется исполнением в node: поддельный API с управляемым порядком ответов и "
                           "отказами, пять сценариев, после каждого — сравнение интерфейса с сервером."),
        params={"cls": cls, "values": [str(v) for v in values], "key": key, "scenarios": sc_order,
                "distractors": chosen})
