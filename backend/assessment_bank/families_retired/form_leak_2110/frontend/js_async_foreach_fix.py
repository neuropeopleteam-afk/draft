"""frontend.js.async_foreach_fix — choose_fix: async-колбэк в forEach и последовательные запросы."""
from __future__ import annotations

import json

from assessment_bank.gen_utils import build_variant, js_harness, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.js.async_foreach_fix"

CTX = [("uploadFiles", "files", "file", "upload", "загрузчик файлов"),
       ("syncDrafts", "drafts", "draft", "save", "редактор черновиков"),
       ("sendInvites", "emails", "email", "invite", "приглашения в команду"),
       ("markAsRead", "messageIds", "id", "markRead", "мессенджер")]


def _fn(name, coll, one, method, kind):
    head = f"async function {name}({coll}, api) {{\n  const results = [];\n"
    if kind == "buggy":
        mid = (f"  {coll}.forEach(async ({one}) => {{\n    const r = await api.{method}({one});\n"
               f"    results.push(r);\n  }});\n")
    elif kind == "good":
        mid = f"  for (const {one} of {coll}) {{\n    results.push(await api.{method}({one}));\n  }}\n"
    elif kind == "promise_all":
        mid = (f"  const all = await Promise.all({coll}.map(({one}) => api.{method}({one})));\n"
               f"  results.push(...all);\n")
    elif kind == "await_foreach":
        mid = (f"  await {coll}.forEach(async ({one}) => {{\n    results.push(await api.{method}({one}));\n"
               f"  }});\n")
    elif kind == "for_in":
        mid = f"  for (const {one} in {coll}) {{\n    results.push(await api.{method}({one}));\n  }}\n"
    elif kind == "map_async":
        mid = (f"  await {coll}.map(async ({one}) => {{\n    results.push(await api.{method}({one}));\n"
               f"  }});\n")
    else:
        raise ValueError(kind)
    return head + mid + "  return results;\n}"


PRELUDE = """function makeApi(method) {
  const api = { active: 0, maxActive: 0, calls: [] };
  api[method] = async (x) => {
    api.active += 1;
    api.maxActive = Math.max(api.maxActive, api.active);
    api.calls.push(x);
    for (let k = 0; k < 3; k++) await null;
    api.active -= 1;
    return 'ok:' + x;
  };
  return api;
}"""


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    name, coll, one, method, ctx = rng.choice(CTX)
    items = rng.sample(["a.pdf", "b.png", "c.txt", "d.csv", "e.doc"], rng.randint(3, 4)) \
        if coll == "files" else [f"{one}-{rng.randint(10, 99)}" for _ in range(rng.randint(3, 4))]
    if len(set(items)) < len(items):
        items = [f"{x}-{i}" for i, x in enumerate(items)]
    code = _fn(name, coll, one, method, "buggy")
    chosen = rng.sample(["promise_all", "await_foreach", "for_in", "map_async"], 3)
    opts, key = make_options(rng, ("Заменить функцию на:", _fn(name, coll, one, method, "good")),
                             [("Заменить функцию на:", _fn(name, coll, one, method, k)) for k in chosen])
    lit = json.dumps(items, ensure_ascii=False)
    expected = json.dumps(["ok:" + x for x in items], ensure_ascii=False, separators=(",", ":"))
    test = (f"const api = makeApi({method!r});\nconst res = await {name}({lit}, api);\n"
            f"__assert(JSON.stringify(res) === {json.dumps(expected, ensure_ascii=False)}, 'результат ' + JSON.stringify(res));\n"
            "__assert(api.maxActive === 1, 'параллельно: ' + api.maxActive);")
    checks = [Check(name=f"option:{o.id}", runner="node", embeds_display_code=False,
                    program=js_harness(o.code, test, PRELUDE),
                    expect="pass" if o.id == key else "fail") for o in opts]
    checks.append(Check(name="buggy_fails", runner="node", program=js_harness(code, test, PRELUDE),
                        expect="fail"))
    stem = (f"Функция `{name}` ({ctx}) должна вызвать `api.{method}` для каждого элемента "
            f"строго по очереди (сервер не допускает параллельных запросов одного пользователя) и "
            f"вернуть массив ответов в исходном порядке. Сейчас вызов `{name}({lit}, api)` "
            f"возвращает пустой массив, а "
            f"запросы уходят одновременно. Какое исправление верно?")
    why = {"promise_all": "Promise.all запускает все запросы параллельно",
           "await_foreach": "forEach возвращает undefined — await ничего не ждёт",
           "for_in": "for...in перебирает индексы-строки, а не элементы",
           "map_async": "await массива промисов не ждёт их, запросы параллельны"}
    ak = AnswerKey(kind="option", value=key,
                   explanation="Верно: for...of с await внутри — запросы последовательно, порядок "
                               "сохраняется. Дистракторы: " + "; ".join(why[k] for k in chosen) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="async_foreach", params={"distractors": chosen})
