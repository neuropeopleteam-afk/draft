"""mobile.js.token_refresh_fix — choose_fix: параллельные 401 и одноразовый refresh-токен (single-flight).

Клиент мобильного приложения (React Native / JS-слой) при ответе 401 обновляет пару токенов и повторяет запрос.
Сервер выдаёт одноразовые refresh-токены с ротацией и обнаружением повторного использования (OAuth 2.0 Security
BCP, RFC 9700 §4.14.2): предъявление уже использованного refresh-токена отзывает всю цепочку, и пользователя
выкидывает из приложения. Экран запускает несколько запросов сразу; каждый получает 401 и запускает своё обновление.

Верное исправление — одно обновление на всех («single-flight»): общий промис, сбрасываемый по завершении.
Состав дистракторов фиксирован (трудность от него зависит):
  * never_reset — общий промис без сброса: первая волна проходит, после следующего истечения токена обновления нет;
  * stale_token — single-flight верный, но повтор запроса идёт с токеном, сохранённым до обновления;
  * retry_refresh — при ошибке обновления повторить его: второй параллельный refresh уже с использованным
    токеном → сервер отзывает цепочку.
Ключ проверяется исполнением в Node: модель сервера с ротацией и отзывом, две волны параллельных запросов.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, js_harness, make_rng

from ._mob_utils import balanced_options
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "mobile.js.token_refresh_fix"

CTX = [("банковское приложение", "/accounts", "/cards", "/limits"),
       ("каршеринг", "/cars/nearby", "/trips/active", "/wallet"),
       ("приложение поликлиники", "/visits", "/referrals", "/lab-results"),
       ("электронный дневник школьника", "/grades", "/homework", "/timetable"),
       ("приложение доставки", "/orders", "/addresses", "/promo"),
       ("такси", "/rides", "/payment-methods", "/profile"),
       ("фитнес-клуб", "/schedule", "/bookings", "/membership"),
       ("онлайн-кинотеатр", "/continue", "/favorites", "/recommendations"),
       ("медицинская запись", "/appointments", "/doctors", "/results")]
STEMS = [
    ("Мобильное приложение ({ctx}): главный экран при открытии параллельно запрашивает `{p1}`, `{p2}` и `{p3}`. "
     "Access-токен живёт {ttl} минут; при ответе 401 клиент обновляет пару токенов и повторяет запрос. Сервер "
     "выдаёт одноразовые refresh-токены с ротацией: повторное предъявление уже использованного refresh-токена "
     "отзывает всю сессию. Жалоба: после паузы в работе пользователей регулярно выкидывает на экран входа. Какая "
     "замена кода исправит проблему?"),
    ("{Ctx}: после возврата в приложение через {ttl}+ минут (access-токен уже истёк) экран сразу шлёт запросы "
     "`{p1}`, `{p2}`, `{p3}`, каждый получает 401. Сервер авторизации ротирует refresh-токены и при повторном "
     "использовании старого отзывает все токены пользователя (защита от кражи). В журналах — пачки «invalid_grant», "
     "пользователь видит экран входа. Как переписать код?"),
    ("Клиент API приложения «{ctx}» прозрачно обновляет токены: получив 401, вызывает refresh и повторяет запрос. "
     "Refresh-токен одноразовый, после использования сервер выдаёт новый, а предъявление использованного считает "
     "атакой и завершает сессию. Access-токен действует {ttl} минут; экраны обычно делают несколько запросов "
     "одновременно (например, `{p1}` и `{p2}`, затем `{p3}`). Жалоба: случайные выходы из аккаунта. Какой вариант "
     "кода верен?"),
]
NAMES = [("refreshTokens", "inflight"), ("renewSession", "pending"), ("updateTokens", "refreshing"),
         ("rotateTokens", "current")]

PRELUDE = """function makeServer() {
  const s = { gen: 1, used: new Set(), revoked: false, refreshCalls: 0 };
  s.valid = 'a1';
  s.store = { access: 'a1', refresh: 'r1' };
  const wait = async (n) => { for (let i = 0; i < n; i++) await null; };
  s.api = {
    get: async (path, token) => { await wait(2); return { status: (!s.revoked && token === s.valid) ? 200 : 401, path }; },
    refresh: async (rt) => {
      s.refreshCalls += 1;
      await wait(4);
      if (s.revoked || s.used.has(rt) || rt !== 'r' + s.gen) { s.revoked = true; throw new Error('invalid_grant'); }
      s.used.add(rt); s.gen += 1; s.valid = 'a' + s.gen;
      return { access: 'a' + s.gen, refresh: 'r' + s.gen };
    },
  };
  s.expire = () => { s.valid = 'expired-' + s.gen; };
  return s;
}"""

SETUP = """const srv = makeServer();
const { api, store } = srv;
srv.expire();
let accessToken = 'a1';"""

TEST = """const w1 = await Promise.all([request(P1), request(P2), request(P3)]);
__assert(w1.every((r) => r.status === 200), 'волна 1: ' + w1.map((r) => r.status));
__assert(srv.refreshCalls === 1, 'волна 1, обновлений: ' + srv.refreshCalls);
srv.expire();
const w2 = await Promise.all([request(P2), request(P1)]);
__assert(w2.every((r) => r.status === 200), 'волна 2: ' + w2.map((r) => r.status));
__assert(srv.refreshCalls === 2 && !srv.revoked, 'волна 2, обновлений: ' + srv.refreshCalls);"""


def _code(kind: str, fn: str, flag: str) -> str:
    refresh = (f"let {flag} = null;\n\nasync function {fn}() {{\n  const r = await api.refresh(store.refresh);\n"
               f"  store.refresh = r.refresh;\n  accessToken = r.access;\n}}\n\n")
    head = "async function request(path) {\n  let res = await api.get(path, accessToken);\n  if (res.status === 401) {\n"
    tail = "  }\n  return res;\n}"
    body = {
        "buggy": f"    await {fn}();\n    res = await api.get(path, accessToken);\n",
        "good": (f"    if (!{flag}) {flag} = {fn}().finally(() => {{ {flag} = null; }});\n"
                 f"    await {flag};\n    res = await api.get(path, accessToken);\n"),
        "never_reset": (f"    if (!{flag}) {flag} = {fn}();\n"
                        f"    await {flag};\n    res = await api.get(path, accessToken);\n"),
        "stale_token": (f"    const token = accessToken;\n"
                        f"    if (!{flag}) {flag} = {fn}().finally(() => {{ {flag} = null; }});\n"
                        f"    await {flag};\n    res = await api.get(path, token);\n"),
        "retry_refresh": (f"    try {{ await {fn}(); }} catch (e) {{ await {fn}(); }}\n"
                          f"    res = await api.get(path, accessToken);\n"),
    }[kind]
    return refresh + head + body + tail


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, *paths = rng.choice(CTX)
    rng.shuffle(paths)
    p1, p2, p3 = paths
    fn, flag = rng.choice(NAMES)
    code = _code("buggy", fn, flag)
    good = _code("good", fn, flag)
    dist = ["never_reset", "stale_token", "retry_refresh"]
    opts, key = balanced_options(FAMILY_ID, seed, rng, ("Заменить код на:", good),
                                 [("Заменить код на:", _code(d, fn, flag)) for d in dist])
    test = TEST.replace("P1", repr(p1)).replace("P2", repr(p2)).replace("P3", repr(p3))

    def prog(src):
        return js_harness(src, test, PRELUDE + "\n" + SETUP)
    checks = [Check(name=f"option:{o.id}", runner="node", program=prog(o.code), embeds_display_code=False,
                    expect="pass" if o.id == key else "fail") for o in opts]
    checks.append(Check(name="buggy_fails", runner="node", program=prog(code), expect="fail"))
    stem = rng.choice(STEMS).format(ctx=ctx, Ctx=ctx[:1].upper() + ctx[1:], p1=p1, p2=p2, p3=p3,
                                    ttl=rng.choice([5, 10, 15, 30]))
    why = {"never_reset": "общий промис не сбрасывается — после следующего истечения access-токена `await` "
                          "получает старый выполненный промис, обновления нет, запрос остаётся с 401",
           "stale_token": "токен для повтора запомнен до обновления — повтор уходит со старым токеном и снова 401",
           "retry_refresh": "параллельные запросы всё равно обновляют каждый сам; второй refresh приходит с уже "
                            "использованным токеном, сервер отзывает сессию"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=("Верно: одно обновление на все параллельные 401 — общий промис, сбрасываемый в "
                                "finally, и повтор с новым токеном. Дистракторы: " +
                                "; ".join(why[d] for d in dist) + "."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="parallel_refresh",
                         params={"names": [fn, flag], "paths": [p1, p2, p3], "distractors": dist})
