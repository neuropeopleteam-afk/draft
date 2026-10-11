"""frontend.arch.optimistic_update_fix — choose_fix (Lead): оптимистичные обновления при параллельных изменениях.

Показан клиентский стор с оптимистичным обновлением: значение меняется в интерфейсе сразу, при ошибке
откатывается к «снимку» до изменения. Пользователь быстро меняет значение несколько раз подряд, ответы
приходят в произвольном порядке, часть изменений отклоняется сервером. Сервер применяет запросы в порядке
отправки; отклонённый — не применяет. Нужна замена метода изменения, при которой: (1) интерфейс меняется
сразу; (2) после того как все ответы пришли, значение в интерфейсе равно значению на сервере при любом
порядке ответов и любом наборе отказов; (3) поздний ответ на старое изменение не затирает более новое
(пока новое не отклонено).

Варианты (каждый исполняется в node):
  * good — журнал изменений ключа (номер, значение, состояние); показ — последнее неотклонённое изменение,
    при пустом — подтверждённое значение;
  * snapshot — откат к снимку на момент изменения и запись ответа без проверки номера: поздний ответ
    старого изменения затирает новое;
  * latest_only — ответ учитывается только для последнего изменения, откат — к снимку: если отклонены оба
    изменения подряд, интерфейс остаётся на отклонённом первом;
  * confirmed_unseq — откат к «последнему подтверждённому», которое обновляется любым успешным ответом без
    учёта номера: поздний успех старого изменения портит его, а откат при ещё не пришедшем старом —
    показывает исходное значение.
Состав дистракторов фиксирован. Ключ проверяется исполнением: поддельный API с управляемым порядком ответов
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
    this.ops = {{}};                    // id -> журнал изменений
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
    const log = this.ops[id] || (this.ops[id] = []);
    const op = {{ seq: ++this.seq, value, state: "pending" }};
    log.push(op);
    this.show(id);
    try {{
      op.value = await this.api.{api}(id, value);
      op.state = "ok";
    }} catch (e) {{
      op.state = "failed";
    }}
    this.show(id);
  }}

  show(id) {{
    const live = (this.ops[id] || []).filter((o) => o.state !== "failed");
    this.view[id] = live.length ? live[live.length - 1].value : this.confirmed[id];
  }}
}}""",
    "snapshot": """
  async {meth}(id, value) {{
    const before = this.view[id];
    this.view[id] = value;
    try {{
      const saved = await this.api.{api}(id, value);
      this.confirmed[id] = saved;
      this.view[id] = saved;
    }} catch (e) {{
      this.view[id] = before;
    }}
  }}
}}""",
    "latest_only": """
  async {meth}(id, value) {{
    const seq = ++this.seq;
    this.ops[id] = seq;
    const before = this.view[id];
    this.view[id] = value;
    try {{
      const saved = await this.api.{api}(id, value);
      if (this.ops[id] === seq) this.view[id] = saved;
    }} catch (e) {{
      if (this.ops[id] === seq) this.view[id] = before;
    }}
  }}
}}""",
    "confirmed_unseq": """
  async {meth}(id, value) {{
    const seq = ++this.seq;
    this.ops[id] = seq;
    this.view[id] = value;
    try {{
      const saved = await this.api.{api}(id, value);
      this.confirmed[id] = saved;
      if (this.ops[id] === seq) this.view[id] = saved;
    }} catch (e) {{
      if (this.ops[id] === seq) this.view[id] = this.confirmed[id];
    }}
  }}
}}""",
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
    names = {"log": rng.choice(["log", "journal", "history"]), "op": rng.choice(["op", "change", "entry"]),
             "live": rng.choice(["live", "alive", "notFailed"]), "before": rng.choice(["before", "prev", "snapshot"]),
             "saved": rng.choice(["saved", "stored", "fromServer"]), "show": rng.choice(["show", "render", "refresh"]),
             "value": rng.choice(["value", "next", "v"])}

    def ren(src: str) -> str:   # поверхностные имена; порядок обращений к rng не зависит от текста
        return re.sub(r"\b(log|op|live|before|saved|show|value)\b", lambda m: names[m.group(1)], src)

    head = HEAD.format(**f)
    code = {k: head + ren(m.format(**f)) + "\n" for k, m in METHODS.items()}
    sc_order = list(range(len(SCENARIOS)))
    rng.shuffle(sc_order)
    test = _test(cls, meth, api, key, values, sc_order)
    chosen = ["snapshot", "latest_only", "confirmed_unseq"]
    opts, akey = make_options(rng, ("Заменить класс на:", code["good"].rstrip()),
                              [("Заменить класс на:", code[c].rstrip()) for c in chosen])
    by_code = {c.rstrip(): k for k, c in code.items()}
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
            "применённый в порядке отправки» при любом порядке ответов. Откат к снимку и запись ответа без номера "
            "дают затирание нового старым; учёт только последнего изменения с откатом к снимку оставляет "
            "отклонённое первое изменение, если отклонены оба; «последнее подтверждённое» без номера портится "
            "поздним успехом старого изменения и при откате до прихода старого ответа.")),
        context=ctx, verification="execution", checks=checks, defect_type="optimistic_race",
        display_code_note=("Ответ проверяется исполнением в node: поддельный API с управляемым порядком ответов и "
                           "отказами, пять сценариев, после каждого — сравнение интерфейса с сервером."),
        params={"cls": cls, "values": [str(v) for v in values], "key": key, "scenarios": sc_order,
                "distractors": chosen})
