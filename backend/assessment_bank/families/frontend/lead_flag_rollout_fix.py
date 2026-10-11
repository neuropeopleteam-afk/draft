"""frontend.arch.lead_flag_rollout_fix — choose_fix (Lead у границы Lead/Principal, короткое): оценка флагов функций.

Клиент решает, показывать ли функцию, по флагу: доля включения (процент пользователей), аварийный выключатель и
ручные включения для тестировщиков. Принципы платформы даны без кода: аварийный выключатель главнее любых ручных
включений; пользователь видит один и тот же вариант во всех сессиях и на всех устройствах; расширение доли не
отключает уже включённых. Показанный код нарушает все три; кандидат выбирает замену функции, выполняющую все.

Правила (из пула выбираются два, варианты — схема 2×2: верный, нарушено первое, второе, оба):
* ``kill`` — проверка выключателя стоит раньше ручных включений;
* ``sticky`` — корзина считается по идентификатору пользователя, а не сессии;
* ``monotonic`` — соль корзины не зависит от доли (иначе при смене доли пользователи перетасовываются).
У вариантов свои локальные имена. Ключ проверяется исполнением в Node: каждая замена исполняется в составе модуля
на четырёх сценариях (выключатель против ручного включения; 300 пользователей в двух сессиях; рост доли 10 → 30 %
без выпадений; доля включённых около заданной и ручное выключение работает).
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import module_choose_fix
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.arch.lead_flag_rollout_fix"

CONTEXTS = [("новое оформление заказа", "checkout_v2"), ("лента рекомендаций", "feed_ranking"),
            ("быстрый вход", "quick_login"), ("новый поиск", "search_v3"), ("тёмная тема", "dark_theme"),
            ("оплата частями", "split_pay"), ("чат с поддержкой", "support_chat"), ("новая карточка товара", "pdp_v2")]
FN_NAMES = ["isEnabled", "flagOn", "isFeatureOn", "evaluateFlag", "shouldShow"]
LOCALS = {"FL": ["flag", "key", "name", "featureKey"], "U": ["user", "viewer", "u", "account"],
          "OV": ["overrides", "forced", "qaOverrides", "manual"], "CF": ["f", "cfg", "def", "spec"]}

MODULE = '''// Оценка флагов функций на клиенте: доля включения, аварийный выключатель, ручные включения тестировщиков.
const FLAGS = {
  "@KEY@": { percent: @PCT@, kill: false, salt: "@SALT@" },
};

function bucket(id, salt) {            // устойчивый номер корзины 0..99 (FNV-1a)
  let h = 2166136261;
  for (const ch of salt + ":" + id) {
    h ^= ch.charCodeAt(0);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h % 100;
}

{FN}
'''

CORRECT = '''function @FN@(@FL@, @U@, @OV@) {
  const @CF@ = FLAGS[@FL@];
  if (!@CF@ || @CF@.kill) return false;
  if (@OV@ && @FL@ in @OV@) return @OV@[@FL@];
  return bucket(@U@.id, @CF@.salt) < @CF@.percent;
}'''

RULES = {
    "kill": ("  if (!@CF@ || @CF@.kill) return false;\n  if (@OV@ && @FL@ in @OV@) return @OV@[@FL@];",
             "  if (@OV@ && @FL@ in @OV@) return @OV@[@FL@];\n  if (!@CF@ || @CF@.kill) return false;"),
    "sticky": ("bucket(@U@.id,", "bucket(@U@.sessionId,"),
    "monotonic": ("@CF@.salt)", "@CF@.salt + @CF@.percent)"),
}
RULE_TEXT = {"kill": "аварийный выключатель главнее любых ручных включений",
             "sticky": "пользователь видит один и тот же вариант во всех сессиях и на всех устройствах",
             "monotonic": "расширение доли не отключает уже включённых"}

TESTS = '''
const K = "@KEY@";
// 1) выключатель главнее ручного включения тестировщика
FLAGS[K].kill = true;
__assert(@FN@(K, { id: "qa-1", sessionId: "s-1" }, { [K]: true }) === false, "выключатель проигнорирован");
FLAGS[K].kill = false;
// 2) один пользователь — один вариант в разных сессиях
for (let i = 0; i < 300; i++) {
  const a = @FN@(K, { id: "user-" + i, sessionId: "web-" + (i * 7) }, {});
  const b = @FN@(K, { id: "user-" + i, sessionId: "app-" + (i * 13 + 5) }, {});
  __assert(a === b, "вариант зависит от сессии");
}
// 3) рост доли 10 -> 30 %: включённые остаются включёнными
FLAGS[K].percent = 10;
const before = [];
for (let i = 0; i < 400; i++) if (@FN@(K, { id: "c" + i, sessionId: "s" + i }, {})) before.push(i);
FLAGS[K].percent = 30;
for (const i of before) __assert(@FN@(K, { id: "c" + i, sessionId: "s" + i }, {}), "выпал при росте доли");
// 4) доля включённых около заданной; ручное выключение работает
FLAGS[K].percent = @PCT@;
let on = 0;
for (let i = 0; i < 2000; i++) if (@FN@(K, { id: "p" + i, sessionId: "p" + i }, {})) on++;
__assert(Math.abs(on / 2000 - @PCT@ / 100) < 0.05, "доля включённых не та: " + on);
__assert(@FN@(K, { id: "p1", sessionId: "p1" }, { [K]: false }) === false, "ручное выключение не работает");
'''


def _render(tpl: str, fn: str, names: dict[str, str]) -> str:
    out = tpl.replace("@FN@", fn)
    for k, v in names.items():
        out = out.replace(f"@{k}@", v)
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, key = rng.choice(CONTEXTS)
    fn = rng.choice(FN_NAMES)
    pct = rng.choice([5, 10, 20, 25, 40, 50])
    salt = rng.choice(["v1", "r2026", key[:4], "exp7", "roll"])
    a, b = rng.sample(sorted(RULES), 2)

    def variant(broken):
        names = {k: rng.choice(v) for k, v in LOCALS.items()}
        tpl = CORRECT
        for r in broken:
            old, new = RULES[r]
            assert tpl.count(old) == 1, r
            tpl = tpl.replace(old, new)
        return _render(tpl, fn, names)

    correct = variant([])
    distractors = [variant([a]), variant([b]), variant([a, b])]
    buggy_tpl = CORRECT
    for r in RULES:
        buggy_tpl = buggy_tpl.replace(*RULES[r])
    buggy = _render(buggy_tpl, fn, {k: v[0] for k, v in LOCALS.items()})
    module = MODULE.replace("@KEY@", key).replace("@PCT@", str(pct)).replace("@SALT@", salt)
    tests = TESTS.replace("@FN@", fn).replace("@KEY@", key).replace("@PCT@", str(pct))
    intro = rng.choice([
        f"Вы — ведущий инженер фронтенда. Функцию «{ctx}» выкатывают на {pct} % пользователей через флаг `{key}`; "
        f"решение принимает функция `{fn}` (модуль ниже).",
        f"После жалоб («функция «{ctx}» то есть, то нет») вы как ведущий инженер фронтенда разбираете функцию `{fn}`, "
        f"которая решает по флагу `{key}`, показывать ли функцию (модуль ниже, доля — {pct} %).",
        f"Флаг `{key}` включает «{ctx}» для {pct} % пользователей; функция `{fn}` (модуль ниже) решает, показывать ли "
        f"функцию, и вы как ведущий инженер фронтенда утверждаете её исправление.",
    ])
    principles = "; ".join(RULE_TEXT[r] for r in ("kill", "sticky", "monotonic"))
    stem = (f"{intro} Принципы платформы флагов: {principles}.\n\nКакая замена функции `{fn}` выполняет все три "
            f"принципа?")
    why = ("Верная замена: выключатель проверяется раньше ручных включений, корзина считается по id пользователя "
           "(не сессии), соль не зависит от доли — рост доли только добавляет корзины. Дистракторы нарушают: "
           f"«{RULE_TEXT[a]}», «{RULE_TEXT[b]}» или оба.")
    return module_choose_fix(FAMILY_ID, seed, rng, stem=stem, module=module, buggy_fn=buggy, correct_fn=correct,
                             distractors=distractors, tests=tests, context=ctx, defect="flag_policy", why=why,
                             label="Заменить функцию на:", runner="node", language="javascript",
                             params={"rules": f"{a}+{b}", "fn": fn, "key": key, "pct": pct, "salt": salt})
