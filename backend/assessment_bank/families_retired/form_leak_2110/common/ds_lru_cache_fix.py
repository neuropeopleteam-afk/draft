"""common.ds.lru_cache_fix — choose_fix: LRU-кэш на OrderedDict не обновляет «свежесть» при чтении."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.ds.lru_cache_fix"

CONTEXTS = [("SessionCache", "sid", ["s1", "s2", "s3", "s4", "s5", "s6"], "сессии пользователей"),
            ("PreviewCache", "path", ["a.png", "b.png", "c.jpg", "d.jpg", "e.gif", "f.webp"], "превью изображений"),
            ("DnsCache", "host", ["api", "cdn", "auth", "mail", "db", "s3"], "DNS-резолвер"),
            ("RateCache", "pair", ["USD", "EUR", "CNY", "TRY", "KZT", "AED"], "курсы валют"),
            ("ProfileCache", "user_id", ["u10", "u11", "u12", "u13", "u14", "u15"], "профили API")]

GET = {
    "buggy": ["    def get(self, {k}):", "        if {k} not in self.data:", "            return None",
              "        return self.data[{k}]"],
    "good": ["    def get(self, {k}):", "        if {k} not in self.data:", "            return None",
             "        self.data.move_to_end({k})", "        return self.data[{k}]"],
    "last_false": ["    def get(self, {k}):", "        if {k} not in self.data:", "            return None",
                   "        self.data.move_to_end({k}, last=False)", "        return self.data[{k}]"],
    "move_first": ["    def get(self, {k}):", "        self.data.move_to_end({k})",
                   "        if {k} not in self.data:", "            return None",
                   "        return self.data[{k}]"],
    "dict_get": ["    def get(self, {k}):", "        value = self.data.get({k})",
                 "        if value is not None:", "            self.data[{k}] = value",
                 "        return value"],
}
PUT = {
    "good": ["    def put(self, {k}, value):", "        self.data[{k}] = value",
             "        self.data.move_to_end({k})", "        if len(self.data) > self.capacity:",
             "            self.data.popitem(last=False)"],
    "last_true": ["    def put(self, {k}, value):", "        self.data[{k}] = value",
                  "        self.data.move_to_end({k})", "        if len(self.data) > self.capacity:",
                  "            self.data.popitem(last=True)"],
}


def _cls(name, k, get_kind, put_kind="good"):
    lines = ["from collections import OrderedDict", "", "", f"class {name}:",
             "    def __init__(self, capacity):", "        self.capacity = capacity",
             "        self.data = OrderedDict()", ""]
    lines += [l.format(k=k) for l in GET[get_kind]] + [""] + [l.format(k=k) for l in PUT[put_kind]]
    return "\n".join(lines)


class _Model:
    def __init__(self, cap):
        self.cap, self.keys, self.vals = cap, [], {}

    def get(self, k):
        if k not in self.vals:
            return None
        self.keys.remove(k)
        self.keys.append(k)
        return self.vals[k]

    def put(self, k, v):
        if k in self.vals:
            self.keys.remove(k)
        self.keys.append(k)
        self.vals[k] = v
        if len(self.keys) > self.cap:
            old = self.keys.pop(0)
            del self.vals[old]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    name, k, pool, ctx = rng.choice(CONTEXTS)
    cap = rng.randint(2, 3)
    keys = rng.sample(pool, cap + 2)
    base, fresh, extra = keys[:cap], keys[cap], keys[cap + 1]
    hot = base[0]
    m = _Model(cap)
    ops, asserts = [], []
    for i, key in enumerate(base):
        ops.append(f"c.put({key!r}, {i + 1})")
        m.put(key, i + 1)
    ops.append(f"got = c.get({hot!r})")
    got = m.get(hot)
    asserts.append(f"assert got == {got!r}")
    ops.append(f"assert c.get({extra!r}) is None")
    m.get(extra)
    ops.append(f"c.put({fresh!r}, 99)")
    m.put(fresh, 99)
    for key in sorted(set(base) | {fresh}):
        asserts.append(f"assert c.get({key!r}) == {m.vals.get(key)!r}, {key!r}")
        m.get(key)
    tests = f"c = {name}({cap})\n" + "\n".join(ops + asserts)
    code = _cls(name, k, "buggy")
    chosen = rng.sample(["last_false", "move_first", "dict_get", "last_true"], 3)
    variant_code = lambda kind: (_cls(name, k, "buggy", "last_true") if kind == "last_true"
                                 else _cls(name, k, kind))
    opts, key = make_options(rng, ("Заменить класс на:", _cls(name, k, "good")),
                             [("Заменить класс на:", variant_code(d)) for d in chosen])
    checks = [Check(name=f"option:{o.id}", runner="python", program=py_harness(o.code, tests),
                    expect="pass" if o.id == key else "fail", embeds_display_code=False)
              for o in opts]
    checks.append(Check(name="buggy_fails", runner="python", program=py_harness(code, tests),
                        expect="fail"))
    order = ", ".join(f"put({x!r})" for x in base)
    stem = (f"`{name}` ({ctx}) — LRU-кэш на {cap} элемента: при переполнении вытесняется ключ, "
            f"к которому дольше всего не обращались (чтение тоже считается обращением). После "
            f"{order}, `get({hot!r})` и `put({fresh!r})` из кэша пропадает `{hot!r}`, хотя к нему "
            f"только что обращались. Какое исправление верно? Промах `get` должен возвращать None.")
    why = {"last_false": "move_to_end(..., last=False) переносит ключ в начало — его вытеснят первым",
           "move_first": "move_to_end до проверки бросает KeyError на промахе",
           "dict_get": "присваивание существующему ключу не меняет его позицию в OrderedDict",
           "last_true": "popitem(last=True) вытесняет только что добавленный ключ, а get по-прежнему "
                        "не обновляет порядок"}
    ak = AnswerKey(kind="option", value=key,
                   explanation="Верно: при попадании в get переносить ключ в конец "
                               "(move_to_end), вытеснять из начала. Дистракторы: "
                               + "; ".join(why[d] for d in chosen) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="lru_no_refresh_on_get",
                         params={"distractors": chosen, "capacity": cap})
