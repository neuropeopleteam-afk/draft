"""backend.py.mutable_default — find_bug: изменяемое значение по умолчанию накапливает данные."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.py.mutable_default"

# (имя функции, аргумент, тип контейнера, строки тела, вызов-1, вызов-2, проверка, контекст, описание)
TAGS = ["Python", "SQL", "Docker", "Linux", "Kafka", "Redis", "Go", "Rust"]
NAMES = ["Ия", "Олег", "Анна", "Марк", "Вера"]


def _scenarios(rng):
    t1, t2 = rng.sample(TAGS, 2)
    p1, p2 = rng.sample(range(1, 9), 2)
    s1 = rng.choice([10, 50, 100])
    n = rng.choice(NAMES)
    ip1, ip2 = (f"10.0.{rng.randint(0, 9)}.{rng.randint(1, 254)}" for _ in range(2))
    sku1, sku2 = (f"{rng.choice('ABKM')}-{rng.randint(1, 99)}" for _ in range(2))
    q2 = rng.randint(1, 5)
    return [
        dict(fn=rng.choice(["add_tag", "attach_tag"]), arg="tags", kind="list", ctx="блог",
             params="post_id, tag", body=["tag = tag.strip().lower()", "if tag and tag not in {acc}:",
                                          "    {acc}.append(tag)", "return {acc}"],
             call1=f"{{fn}}(1, '{t1}')", call2=f"{{fn}}(2, '{t2}')", expect2=repr([t2.lower()]),
             descr="добавляет нормализованный тег к списку тегов поста"),
        dict(fn=rng.choice(["build_params", "query_params"]), arg="params", kind="dict",
             ctx="HTTP-клиент", params="page, size",
             body=["{acc}['page'] = page", "if size != 20:", "    {acc}['size'] = size", "return {acc}"],
             call1=f"{{fn}}({p1}, {s1})", call2=f"{{fn}}({p2}, 20)", expect2=repr({"page": p2}),
             descr="собирает параметры запроса к API, size передаётся, только если он не равен 20"),
        dict(fn=rng.choice(["collect_errors", "validate_form"]), arg="errors", kind="list",
             ctx="валидация форм", params="form",
             body=["for field in ('email', 'name'):", "    if not form.get(field):",
                   "        {acc}.append(f'{{field}}: обязательное поле')", "return {acc}"],
             call1=f"{{fn}}({{{{'name': '{n}'}}}})",
             call2=f"{{fn}}({{{{'email': 'user{p1}@example.ru', 'name': '{n}'}}}})", expect2="[]",
             descr="возвращает список ошибок валидации формы"),
        dict(fn=rng.choice(["seen_ips", "unique_ips"]), arg="seen", kind="set", ctx="антифрод",
             params="log_lines", body=["for line in log_lines:", "    ip = line.split()[0]",
                                       "    {acc}.add(ip)", "return {acc}"],
             call1=f"{{fn}}(['{ip1} GET /'])", call2=f"{{fn}}(['{ip2} GET /login'])",
             expect2=repr({ip2}) if ip1 != ip2 else "set()",
             descr="возвращает множество IP-адресов из переданных строк журнала"),
        dict(fn=rng.choice(["add_item", "put_to_cart"]), arg="cart", kind="dict", ctx="корзина",
             params="sku, qty", body=["if qty <= 0:", "    raise ValueError('qty must be positive')",
                                      "{acc}[sku] = {acc}.get(sku, 0) + qty", "return {acc}"],
             call1=f"{{fn}}('{sku1}', 2)", call2=f"{{fn}}('{sku2}', {q2})",
             expect2=repr({sku2: q2 + (2 if sku1 == sku2 else 0)}) if sku1 != sku2 else repr({sku2: q2}),
             descr="добавляет товар в корзину и возвращает её содержимое"),
    ]


EMPTY = {"list": "[]", "dict": "{}", "set": "set()"}
HELPERS = [
    ["def normalize_sku(sku: str) -> str:", "    return sku.strip().upper()"],
    ["def chunk(items, size=100):", "    return [items[i:i + size] for i in range(0, len(items), size)]"],
    ["def fmt_money(value, currency='RUB'):", "    return f'{value:.2f} {currency}'"],
    ["def is_internal(ip: str, prefix='10.') -> bool:", "    return ip.startswith(prefix)"],
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    sc = rng.choice(_scenarios(rng))
    sc = {**sc, "call1": sc["call1"].format(fn=sc["fn"]), "call2": sc["call2"].format(fn=sc["fn"])}
    acc = sc["arg"]
    helper = rng.choice(HELPERS)
    extra_kw = rng.choice(["", ", strict=False", ", limit=50"])
    sig_bad = f"def {sc['fn']}({sc['params']}{extra_kw}, {acc}={EMPTY[sc['kind']]}):"
    sig_good = f"def {sc['fn']}({sc['params']}{extra_kw}, {acc}=None):"
    body = ["    " + b.format(acc=acc) for b in sc["body"]]
    before = helper + ["", ""] if rng.random() < 0.6 else []
    after = ([] if before else ["", ""] + helper)
    buggy_lines = before + [sig_bad] + body + after
    fixed_lines = before + [sig_good, f"    if {acc} is None:", f"        {acc} = {EMPTY[sc['kind']]}"] \
        + body + after
    buggy, fixed = "\n".join(buggy_lines), "\n".join(fixed_lines)
    key_line = len(before) + 1
    assert changed_lines(buggy, fixed) == {key_line}
    test = f"{sc['call1']}\nassert {sc['call2']} == {sc['expect2']}, 'накопились данные прошлого вызова'"
    checks = [Check(name="buggy_fails", runner="python", program=py_harness(buggy, test), expect="fail"),
              Check(name="fixed_passes", runner="python", program=py_harness(fixed, test),
                    expect="pass", embeds_display_code=False)]
    stem = (f"Функция `{sc['fn']}` ({sc['ctx']}) {sc['descr']}. В продакшене заметили: при "
            f"повторных вызовах без аргумента `{acc}` в результате оказываются данные из прошлых "
            f"вызовов, например `{sc['call1']}`, затем `{sc['call2']}` возвращает не "
            f"`{sc['expect2']}`. Укажите номер строки, в которой находится ошибка.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=f"Строка {key_line}: значение по умолчанию `{EMPTY[sc['kind']]}` "
                               "вычисляется один раз при определении функции и разделяется между "
                               f"вызовами. Исправление: `{acc}=None` и создание нового контейнера внутри.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=sc["ctx"],
                         verification="execution", checks=checks, defect_type="mutable_default",
                         params={"fixed_code": fixed, "scenario": sc["fn"]})
