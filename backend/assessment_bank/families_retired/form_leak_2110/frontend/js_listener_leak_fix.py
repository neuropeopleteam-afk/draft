"""frontend.js.listener_leak_fix — choose_fix: утечка памяти из-за неснятого обработчика (bind)."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, js_harness, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.js.listener_leak_fix"

TARGET = """function makeTarget() {
  const map = new Map();
  return {
    addEventListener(type, fn, opts) {
      const list = map.get(type) || [];
      if (!list.some((l) => l.fn === fn)) list.push({ fn, once: !!(opts && opts.once) });
      map.set(type, list);
    },
    removeEventListener(type, fn) {
      map.set(type, (map.get(type) || []).filter((l) => l.fn !== fn));
    },
    dispatch(type, extra) {
      for (const l of [...(map.get(type) || [])]) {
        if (l.once) this.removeEventListener(type, l.fn);
        l.fn.call(this, { type, ...extra });
      }
    },
    count(type) { return (map.get(type) || []).length; },
  };
}"""

# (класс, событие, метод, тело метода, [(подготовка, extra, проверка)], контекст)
SCENARIOS = [
    ("StickyHeader", "scroll", "onScroll", "this.el.fixed = this.win.scrollY > 80;",
     [("win.scrollY = 120;", "{}", "el.fixed === true"), ("win.scrollY = 10;", "{}", "el.fixed === false")],
     "липкая шапка лендинга"),
    ("ResponsiveGrid", "resize", "onResize", "this.el.columns = this.win.innerWidth > 960 ? 4 : 2;",
     [("win.innerWidth = 1280;", "{}", "el.columns === 4"), ("win.innerWidth = 600;", "{}", "el.columns === 2")],
     "адаптивная сетка карточек"),
    ("HotkeyPanel", "keydown", "onKey", "if (event.key === 'Escape') this.el.open = false;",
     [("el.open = true;", "{ key: 'Escape' }", "el.open === false"), ("el.open = true;", "{ key: 'Escape' }", "el.open === false")],
     "панель с горячими клавишами"),
    ("PresenceBadge", "visibilitychange", "onVisibility", "this.el.away = this.win.hidden;",
     [("win.hidden = true;", "{}", "el.away === true"), ("win.hidden = false;", "{}", "el.away === false")],
     "индикатор присутствия в чате"),
]


def _opt(kind, ev, m):
    # Версия 2 (08.10): у всех вариантов одно строение — обработчик в `this.handler`, подписка, в `unmount` один-два
    # оператора; отличается только суть ошибки. Раньше верный вариант был единственным с полем `handler` и
    # дополнительной строкой `this.handler = null` и выделялся длиной (250 знаков против 170).
    sub = [f"this.win.addEventListener('{ev}', this.handler);"]
    unsub = [f"this.win.removeEventListener('{ev}', this.handler);", "this.handler = null;"]
    if kind == "good_arrow":
        mount = [f"this.handler = (event) => this.{m}(event);"] + sub
        unmount = unsub
    elif kind == "good_bind":
        mount = [f"this.handler = this.{m}.bind(this);"] + sub
        unmount = unsub
    elif kind == "unbound":
        mount = [f"this.handler = this.{m};"] + sub
        unmount = unsub
    elif kind == "once":
        mount = [f"this.handler = this.{m}.bind(this);",
                 f"this.win.addEventListener('{ev}', this.handler, {{ once: true }});"]
        unmount = unsub
    elif kind == "new_arrow":
        mount = [f"this.handler = (event) => this.{m}(event);"] + sub
        unmount = [f"this.win.removeEventListener('{ev}', (event) => this.{m}(event));", "this.handler = null;"]
    elif kind == "rebind_remove":
        mount = [f"this.handler = this.{m}.bind(this);"] + sub
        unmount = [f"this.win.removeEventListener('{ev}', this.{m}.bind(this));", "this.handler = null;"]
    elif kind == "null_refs":
        mount = [f"this.handler = this.{m}.bind(this);"] + sub
        unmount = ["this.el = null;", "this.win = null;", "this.handler = null;"]
    else:
        raise ValueError(kind)
    return "\n".join(["  mount() {"] + ["    " + x for x in mount] + ["  }", "  unmount() {"] +
                     ["    " + x for x in unmount] + ["  }"])


WHY = {"unbound": "метод передан без привязки: в обработчике this — окно, а не экземпляр, "
                  "и обработчик падает",
       "once": "once снимает обработчик после первого события — компонент перестаёт реагировать",
       "new_arrow": "в removeEventListener передаётся новая функция, а не та, что подписана, — "
                    "подписка остаётся",
       "rebind_remove": "bind создаёт новую функцию: снять подписку ею нельзя",
       "null_refs": "обнуление полей не снимает подписку: окно по-прежнему держит обработчик, "
                    "а тот при следующем событии падает"}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    cls, ev, m, body, steps, ctx = rng.choice(SCENARIOS)
    good = rng.choice(["good_arrow", "good_bind"])
    head = [f"class {cls} {{", "  constructor(win, el) {", "    this.win = win;", "    this.el = el;",
            "  }", f"  {m}(event) {{", f"    {body}", "  }"]
    buggy_methods = "\n".join([f"  mount() {{", f"    this.win.addEventListener('{ev}', this.{m}.bind(this));",
                               "  }", "  unmount() {",
                               f"    this.win.removeEventListener('{ev}', this.{m}.bind(this));", "  }"])
    code = "\n".join(head) + "\n" + buggy_methods + "\n}"
    chosen = rng.sample(sorted(WHY), 3)
    opts, key = make_options(rng, ("Заменить mount и unmount на:", _opt(good, ev, m)),
                             [("Заменить mount и unmount на:", _opt(k, ev, m)) for k in chosen])
    step_js = "\n".join(f"    {prep}\n    win.dispatch('{ev}', {extra});\n"
                        f"    __assert({chk}, 'обработчик не сработал: {chk}');" for prep, extra, chk in steps)
    test = (f"const win = makeTarget();\nfor (let k = 0; k < 3; k++) {{\n  const el = {{}};\n"
            f"  const c = new {cls}(win, el);\n  c.mount();\n"
            f"  __assert(win.count('{ev}') === 1, 'подписок после mount: ' + win.count('{ev}'));\n"
            f"{step_js}\n  c.unmount();\n"
            f"  __assert(win.count('{ev}') === 0, 'подписок после unmount: ' + win.count('{ev}'));\n}}\n"
            f"win.dispatch('{ev}', {{}});")
    checks = []
    for o in opts:
        prog = "\n".join(head) + "\n" + o.code + "\n}"
        checks.append(Check(name=f"option:{o.id}", runner="node", embeds_display_code=False,
                            program=js_harness(prog, test, TARGET),
                            expect="pass" if o.id == key else "fail"))
    checks.append(Check(name="buggy_fails", runner="node", program=js_harness(code, test, TARGET),
                        expect="fail"))
    n = rng.choice([12, 20, 30, 50])
    stem = (f"Класс `{cls}` ({ctx}) подписывается на событие `{ev}` окна в `mount` и "
            f"отписывается в `unmount`; экран с ним открывают и закрывают при навигации по SPA. "
            f"После {n} переходов снимок кучи в DevTools показывает {n} живых экземпляров "
            f"`{cls}` и отсоединённые DOM-узлы, а одно событие вызывает обработчик {n} раз. "
            f"Какое исправление устраняет утечку и сохраняет работу обработчика?")
    ak = AnswerKey(kind="option", value=key,
                   explanation="Каждый вызов bind создаёт новую функцию, поэтому "
                               "removeEventListener не находит подписку и окно держит "
                               "обработчик, а через него — экземпляр и DOM-узел. Нужно сохранить "
                               "одну ссылку на обработчик и снимать именно её. Дистракторы: "
                               + "; ".join(WHY[k] for k in chosen) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="listener_not_removed",
                         display_code_note="Окно заменено поддельным EventTarget с той же "
                                           "семантикой addEventListener/removeEventListener "
                                           "(сравнение по ссылке, once).",
                         params={"good": good, "distractors": chosen})
