"""mobile.js.offline_queue_fix — choose_fix: очередь изменений, сделанных без сети, и порядок отправки.

Приложение работает офлайн: действия пользователя (создать заказ, добавить позицию, изменить адрес…)
складываются в очередь и отправляются, когда сеть появляется. Операции зависят друг от друга по порядку.
Сейчас `flush` при ошибке сети пропускает операцию и отправляет следующие — сервер получает их не по порядку и
отклоняет зависимые. Верно — остановиться на первой ошибке, оставив операцию в голове очереди.
Состав дистракторов фиксирован:
  * remove_first — операция удаляется из очереди до отправки: при ошибке она теряется;
  * retry_drop — три попытки подряд, затем операция выбрасывается: при недоступной сети теряется;
  * requeue_tail — неудавшаяся операция переносится в конец очереди: порядок нарушается.
Ключ проверяется исполнением в Node: модель сервера записывает порядок применения; два сценария — кратковременный
обрыв одного запроса и долгое отсутствие сети посреди отправки с последующим возвратом.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, js_harness, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._mob_utils import balanced_options

FAMILY_ID = "mobile.js.offline_queue_fix"

CTX = [("доставка продуктов", ["createOrder", "addItem", "addItem", "setAddress", "submit"]),
       ("полевой сервисный инженер", ["openTicket", "addPhoto", "addNote", "closeTicket"]),
       ("торговый представитель", ["createVisit", "addOrderLine", "addOrderLine", "signVisit"]),
       ("приложение склада", ["openInventory", "countItem", "countItem", "countItem", "closeInventory"]),
       ("медицинская карта врача на выезде", ["openVisit", "addDiagnosis", "addPrescription", "closeVisit"]),
       ("курьерское приложение", ["acceptParcel", "scanParcel", "addPhoto", "deliverParcel"]),
       ("приложение агронома в поле", ["createField", "addSample", "addSample", "attachMap", "closeReport"]),
       ("журнал обходов охраны", ["startRound", "checkPoint", "checkPoint", "reportIssue", "finishRound"]),
       ("приложение для инвентаризации библиотеки", ["openShelf", "markBook", "markBook", "closeShelf"]),
       ("бланк осмотра автомобиля", ["openInspection", "addDamage", "addPhoto", "signInspection"])]
METHODS = ["send", "post", "push", "upload"]
STEMS = [
    ("Мобильное приложение ({ctx}) работает без сети: действия пользователя складываются в очередь `{q}` и "
     "отправляются функцией `{fn}`, когда сеть появляется (событие NetInfo и возврат приложения на передний план). "
     "Операции зависят друг от друга и должны применяться на сервере строго в порядке действий пользователя, "
     "например {chain}. Жалоба: после кратковременных обрывов связи посреди отправки сервер получает действия не "
     "в том порядке, и данные собираются с ошибками. Какая замена функции исправит отправку?"),
    ("{Ctx}: пользователи часто остаются без связи, поэтому каждое действие сначала записывается в локальную "
     "очередь `{q}`, а `{fn}` отправляет её на сервер при появлении сети. Сервер применяет операции в том порядке, "
     "в каком они пришли, а порядок важен: {chain}. По журналам сервера после коротких обрывов связи операции "
     "иногда применяются не по порядку. Какой вариант `{fn}` нужен?"),
    ("В офлайн-режиме приложения «{ctx}» изменения копятся в `{q}`; `{fn}` вызывается, когда устройство снова в "
     "сети. Требования: сервер применяет операции строго в порядке их создания ({chain}), ни одна операция не "
     "теряется, даже если сеть пропадает надолго. Сейчас после мигания связи сервер получает операции в "
     "перепутанном порядке. Чем заменить `{fn}`?"),
]

PRELUDE = """function makeServer(failAt, outageFrom) {
  const s = { applied: [], online: true, calls: 0 };
  s.send = async (op) => {
    s.calls += 1;
    for (let k = 0; k < 2; k++) await null;
    if (s.calls === failAt) throw new Error('network');              // кратковременный обрыв
    if (s.calls >= outageFrom && s.online) s.online = false;          // сеть пропала надолго
    if (!s.online) throw new Error('offline');
    s.applied.push(op.seq);
    return { ok: true };
  };
  return s;
}"""


def _flush(kind: str, fn: str, q: str, m: str = "send") -> str:
    if kind == "buggy":
        loop = (f"  for (const op of [...{q}]) {{\n    try {{\n      await api.send(op);\n"
                f"      {q}.splice({q}.indexOf(op), 1);\n    }} catch (e) {{\n      continue;\n    }}\n  }}\n")
    elif kind == "good":
        loop = (f"  while ({q}.length > 0) {{\n    try {{\n      await api.send({q}[0]);\n"
                f"      {q}.shift();\n    }} catch (e) {{\n      return;\n    }}\n  }}\n")
    elif kind == "remove_first":
        loop = (f"  while ({q}.length > 0) {{\n    const op = {q}.shift();\n    try {{\n"
                f"      await api.send(op);\n    }} catch (e) {{\n      return;\n    }}\n  }}\n")
    elif kind == "retry_drop":
        loop = (f"  while ({q}.length > 0) {{\n    for (let i = 0; i < 3; i++) {{\n"
                f"      try {{ await api.send({q}[0]); break; }} catch (e) {{}}\n    }}\n"
                f"    {q}.shift();\n  }}\n")
    elif kind == "requeue_tail":
        loop = (f"  for (let n = {q}.length; n > 0; n--) {{\n    const op = {q}.shift();\n    try {{\n"
                f"      await api.send(op);\n    }} catch (e) {{\n      {q}.push(op);\n    }}\n  }}\n")
    else:
        raise ValueError(kind)
    return f"async function {fn}({q}, api) {{\n" + loop.replace("api.send(", f"api.{m}(") + "}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, ops = rng.choice(CTX)
    fn = rng.choice(["flush", "flushQueue", "syncPending", "drainOutbox"])
    q = rng.choice(["queue", "pending", "outbox"])
    m = rng.choice(METHODS)
    code = _flush("buggy", fn, q, m)
    dist = ["remove_first", "retry_drop", "requeue_tail"]
    opts, key = balanced_options(FAMILY_ID, seed, rng, ("Заменить функцию на:", _flush("good", fn, q, m)),
                                 [("Заменить функцию на:", _flush(d, fn, q, m)) for d in dist])
    fail_at = rng.randint(2, len(ops) - 1)
    lit = "[" + ", ".join(f"{{ seq: {i + 1}, type: '{t}' }}" for i, t in enumerate(ops)) + "]"
    out_at = rng.randint(2, len(ops) - 1)
    expected = list(range(1, len(ops) + 1))
    test = (f"{{\n  const api = makeServer({fail_at}, 1e9);\n  const {q} = {lit};\n"
            f"  await {fn}({q}, api);\n  await {fn}({q}, api);\n"
            f"  __assert(JSON.stringify(api.applied) === '{expected}'.replace(/ /g, ''), "
            f"'кратковременный обрыв, применено: ' + JSON.stringify(api.applied));\n}}\n"
            f"{{\n  const api = makeServer(0, {out_at});\n  const {q} = {lit};\n"
            f"  await {fn}({q}, api);\n  api.online = true;\n  api.calls = -1e9;\n  await {fn}({q}, api);\n"
            f"  __assert(JSON.stringify(api.applied) === '{expected}'.replace(/ /g, ''), "
            f"'долгий обрыв, применено: ' + JSON.stringify(api.applied));\n"
            f"  __assert({q}.length === 0, 'в очереди осталось: ' + {q}.length);\n}}")
    pre = PRELUDE.replace("s.send = ", f"s.{m} = ")
    checks = [Check(name=f"option:{o.id}", runner="node", embeds_display_code=False,
                    program=js_harness(o.code, test, pre), expect="pass" if o.id == key else "fail")
              for o in opts]
    checks.append(Check(name="buggy_fails", runner="node", program=js_harness(code, test, pre), expect="fail"))
    chain = " → ".join(f"`{t}`" for t in ops)
    stem = rng.choice(STEMS).format(ctx=ctx, Ctx=ctx[:1].upper() + ctx[1:], q=q, fn=fn, chain=chain)
    why = {"remove_first": "операция удаляется из очереди до отправки — при обрыве связи она теряется",
           "retry_drop": "после трёх неудачных попыток операция выбрасывается — без сети теряется",
           "requeue_tail": "неудавшаяся операция уходит в конец очереди — следующие применяются раньше неё"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=("Верно: отправлять голову очереди и удалять её только после успеха; при ошибке — "
                                "остановиться, оставив операцию первой (следующая попытка начнёт с неё). Дистракторы: "
                                + "; ".join(why[d] for d in dist) + "."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="skip_failed_op",
                         params={"fail_at": fail_at, "ops": ops, "method": m, "distractors": dist})
