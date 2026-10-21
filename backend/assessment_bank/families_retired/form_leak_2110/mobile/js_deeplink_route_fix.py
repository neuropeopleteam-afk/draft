"""mobile.js.deeplink_route_fix — choose_fix: диплинк с query-параметрами открывает не тот экран.

Приложение разбирает диплинки вида `scheme://host/путь?метки#якорь` и сопоставляет путь с таблицей маршрутов.
Путь берётся вместе с query-строкой, поэтому ссылки из push-уведомлений и рассылок с utm-метками не совпадают
ни с одним маршрутом и открывают главный экран. Состав дистракторов фиксирован: замена `?` на пустую строку
(склеивает путь с метками), отрезание query без отрезания схемы и хоста, декодирование без отрезания query.
Ключ проверяется исполнением в Node на наборе ссылок с метками, якорем и параметром пути.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, js_harness, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._mob_utils import balanced_options

FAMILY_ID = "mobile.js.deeplink_route_fix"

APPS = [("shop", "магазин", [("/catalog", "Catalog"), ("/cart", "Cart"), ("/orders/:id", "Order")]),
        ("bank", "банк", [("/cards", "Cards"), ("/transfers", "Transfers"), ("/payments/:id", "Payment")]),
        ("food", "доставка еды", [("/menu", "Menu"), ("/basket", "Basket"), ("/orders/:id", "Order")]),
        ("travel", "бронирование путешествий", [("/search", "Search"), ("/trips", "Trips"),
                                                 ("/bookings/:id", "Booking")]),
        ("fit", "фитнес", [("/schedule", "Schedule"), ("/profile", "Profile"), ("/classes/:id", "Class")])]
TAGS = ["utm_source=push", "utm_campaign=autumn", "from=sms", "ref=email", "utm_medium=banner"]


def _resolve(kind: str, prefix_const: str) -> str:
    line = {
        "buggy": f"  const path = link.slice({prefix_const}.length);",
        "good": f"  const path = link.slice({prefix_const}.length).split('#')[0].split('?')[0];",
        "replace_q": f"  const path = link.slice({prefix_const}.length).replace('?', '').replace('#', '');",
        "no_prefix": f"  const path = link.split('#')[0].split('?')[0];",
        "decode_only": f"  const path = decodeURIComponent(link.slice({prefix_const}.length));",
    }[kind]
    return ("function resolve(link) {\n  if (!link.startsWith(" + prefix_const + ")) return { screen: 'Home', params: {} };\n"
            + line + "\n  for (const [pattern, screen] of ROUTES) {\n    const params = match(pattern, path);\n"
            "    if (params) return { screen, params };\n  }\n  return { screen: 'Home', params: {} };\n}")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    host, ctx, routes = rng.choice(APPS)
    scheme = rng.choice([host + "app", "my" + host, host])
    prefix_const = rng.choice(["PREFIX", "BASE", "APP_LINK"])
    prefix = f"{scheme}://{host}"
    routes_js = "const ROUTES = [\n" + "".join(f"  ['{p}', '{s}'],\n" for p, s in routes) + "];"
    match_js = ("function match(pattern, path) {\n  const p = pattern.split('/');\n  const s = path.split('/');\n"
                "  if (p.length !== s.length) return null;\n  const params = {};\n"
                "  for (let i = 0; i < p.length; i++) {\n"
                "    if (p[i].startsWith(':')) params[p[i].slice(1)] = decodeURIComponent(s[i]);\n"
                "    else if (p[i] !== s[i]) return null;\n  }\n  return params;\n}")
    head = f"const {prefix_const} = '{prefix}';\n{routes_js}\n\n{match_js}\n\n"
    code = head + _resolve("buggy", prefix_const)
    dist = ["replace_q", "no_prefix", "decode_only"]
    opts, key = balanced_options(FAMILY_ID, seed, rng, ("Заменить функцию resolve на:", _resolve("good", prefix_const)),
                                 [("Заменить функцию resolve на:", _resolve(d, prefix_const)) for d in dist])
    t1, t2 = rng.sample(TAGS, 2)
    pid = rng.randint(100, 9999)
    static = rng.choice(routes[:2])
    cases = [(f"{prefix}{static[0]}?{t1}", static[1], {}),
             (f"{prefix}{routes[2][0].replace(':id', str(pid))}?{t2}#details", routes[2][1], {"id": str(pid)}),
             (f"{prefix}{routes[1 - routes.index(static)][0]}", routes[1 - routes.index(static)][1], {}),
             (f"{prefix}/unknown?{t1}", "Home", {})]
    test = "".join(
        f"{{ const r = resolve({link!r}); __assert(r.screen === {scr!r} && JSON.stringify(r.params) === "
        f"{repr(__import__('json').dumps(par, separators=(',', ':')))}, {link!r} + ' → ' + r.screen); }}\n"
        for link, scr, par in cases)
    checks = [Check(name=f"option:{o.id}", runner="node", embeds_display_code=False,
                    program=js_harness(head + o.code, test), expect="pass" if o.id == key else "fail")
              for o in opts]
    checks.append(Check(name="buggy_fails", runner="node", program=js_harness(code, test), expect="fail"))
    stem = (f"Мобильное приложение ({ctx}) открывает экраны по диплинкам `{prefix}/…`. Ссылка "
            f"`{prefix}{static[0]}` открывает нужный экран, а та же ссылка из push-уведомления — "
            f"`{cases[0][0]}` — открывает главный экран; ссылка `{cases[1][0]}` тоже ведёт на главный. Какая "
            f"замена функции `resolve` исправит разбор ссылок?")
    why = {"replace_q": "удаление символов «?» и «#» склеивает путь с метками — маршрут всё равно не совпадает",
           "no_prefix": "query отрезается, но схема и хост остаются в пути — не совпадает ни один маршрут",
           "decode_only": "декодирование не убирает query-строку"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=("Верно: от ссылки отрезаются префикс, якорь и query-строка, с маршрутами "
                                "сравнивается только путь. Дистракторы: " + "; ".join(why[d] for d in dist) + "."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="query_in_path",
                         params={"prefix": prefix, "cases": [c[0] for c in cases], "distractors": dist})
