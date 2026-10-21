"""backend.go.map_race_fix — choose_fix: конкурентная запись в map из горутин.

Исходный код считает элементы пакетов в горутинах и пишет в общую map без синхронизации
(fatal error: concurrent map writes / гонка данных). Нужно выбрать верное исправление.
Состав вариантов фиксирован (урок калибровки 05.10):
  * верный — счётчик с sync.Mutex и методом с указательным получателем, wg.Add до запуска горутины;
  * value_receiver — тот же счётчик, но метод с получателем-значением: мьютекс копируется при каждом
    вызове, защиты нет (детектор гонок, go vet copylocks);
  * unlocked_write — под мьютексом только чтение, запись в map после Unlock;
  * unbuffered_wait — локальные map отправляются в небуферизованный канал, а wg.Wait() стоит до чтения
    канала: взаимная блокировка.
Проверка исполнением: каждый вариант собирается с -race и запускается на тесте; верный проходит,
остальные падают (гонка, deadlock или неверный результат).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.go.map_race_fix"

# (контекст, функция, что считаем, элементы)
CONTEXTS = [("логи доступа", "countStatus", "коды ответов", ["200", "404", "500", "301", "403"]),
            ("заказы маркетплейса", "countCities", "города доставки", ["msk", "spb", "kzn", "nsk", "ekb"]),
            ("события аналитики", "countEvents", "типы событий", ["view", "click", "buy", "share", "like"]),
            ("тикеты поддержки", "countTags", "теги обращений", ["bug", "billing", "login", "ux", "api"]),
            ("платежи", "countMethods", "способы оплаты", ["card", "sbp", "cash", "wallet", "credit"])]

COUNTER = '''type {T} struct {{
\tmu sync.Mutex
\tm  map[string]int
}}

func (c {recv}) {M}(k string) {{
\tc.mu.Lock()
\tdefer c.mu.Unlock()
\tc.m[k]++
}}'''
TYPES = ["counter", "tally", "stats", "registry", "histogram"]
METHODS = ["add", "inc", "record", "bump", "observe"]
BATCH_VARS = ["b", "batch", "chunk", "part", "page"]
KEY_VARS = ["k", "key", "item", "v", "name"]


def _variants(fn: str, T: str, M: str) -> dict[str, str]:
    head = f"func {fn}(batches [][]string) map[string]int {{"
    counter_body = "\n".join([
        head,
        f"\tc := &{T}{{m: map[string]int{{}}}}",
        "\tvar wg sync.WaitGroup",
        "\tfor _, b := range batches {",
        "\t\twg.Add(1)",
        "\t\tgo func(b []string) {",
        "\t\t\tdefer wg.Done()",
        "\t\t\tfor _, k := range b {",
        f"\t\t\t\tc.{M}(k)",
        "\t\t\t}",
        "\t\t}(b)",
        "\t}",
        "\twg.Wait()",
        "\treturn c.m",
        "}"])
    return {
        "correct": COUNTER.format(T=T, M=M, recv="*" + T) + "\n\n" + counter_body,
        "value_receiver": COUNTER.format(T=T, M=M, recv=T) + "\n\n" + counter_body,
        "unlocked_write": "\n".join([
            head, "\tcounts := map[string]int{}", "\tvar mu sync.Mutex", "\tvar wg sync.WaitGroup",
            "\tfor _, b := range batches {", "\t\twg.Add(1)", "\t\tgo func(b []string) {",
            "\t\t\tdefer wg.Done()", "\t\t\tfor _, k := range b {", "\t\t\t\tmu.Lock()",
            "\t\t\t\tn := counts[k]", "\t\t\t\tmu.Unlock()", "\t\t\t\tcounts[k] = n + 1", "\t\t\t}",
            "\t\t}(b)", "\t}", "\twg.Wait()", "\treturn counts", "}"]),
        "unbuffered_wait": "\n".join([
            head, "\tparts := make(chan map[string]int)", "\tvar wg sync.WaitGroup",
            "\tfor _, b := range batches {", "\t\twg.Add(1)", "\t\tgo func(b []string) {",
            "\t\t\tdefer wg.Done()", "\t\t\tlocal := map[string]int{}", "\t\t\tfor _, k := range b {",
            "\t\t\t\tlocal[k]++", "\t\t\t}", "\t\t\tparts <- local", "\t\t}(b)", "\t}", "\twg.Wait()",
            "\tclose(parts)", "\tcounts := map[string]int{}", "\tfor p := range parts {",
            "\t\tfor k, n := range p {", "\t\t\tcounts[k] += n", "\t\t}", "\t}", "\treturn counts", "}"]),
    }


def _program(func_src: str, fn: str, batches: list[list[str]], expected: dict[str, int]) -> str:
    lit = "[][]string{" + ", ".join("{" + ", ".join(f'"{x}"' for x in b) + "}" for b in batches) + "}"
    exp = "map[string]int{" + ", ".join(f'"{k}": {v}' for k, v in sorted(expected.items())) + "}"
    # deadlock под детектором гонок runtime не распознаёт — тест сам ограничивает время (1 с)
    return ("package main\n\nimport (\n\t\"fmt\"\n\t\"reflect\"\n\t\"sync\"\n\t\"time\"\n)\n\n" + func_src +
            "\n\nfunc main() {\n"
            "\tdone := make(chan map[string]int, 1)\n"
            f"\tgo func() {{ done <- {fn}({lit}) }}()\n"
            "\tselect {\n\tcase got := <-done:\n"
            f"\t\tif reflect.DeepEqual(got, {exp}) {{\n\t\t\tfmt.Println(\"RESULT: PASS\")\n\t\t}} else {{\n"
            "\t\t\tfmt.Println(\"RESULT: FAIL\", got)\n\t\t}\n"
            "\tcase <-time.After(time.Second):\n\t\tfmt.Println(\"RESULT: FAIL deadlock\")\n\t}\n}\n")


def _rename(src: str, bv: str, kv: str) -> str:
    """Имена переменных пакета и ключа (поверхностное разнообразие)."""
    import re
    src = re.sub(r"\bb\b", bv, src)
    return re.sub(r"\bk\b", kv, src)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, fn, what, items = rng.choice(CONTEXTS)
    n_batches = rng.randint(4, 6)
    batches = [[rng.choice(items) for _ in range(rng.randint(30, 60))] for _ in range(n_batches)]
    expected: dict[str, int] = {}
    for b in batches:
        for k in b:
            expected[k] = expected.get(k, 0) + 1
    buggy = "\n".join([
        f"func {fn}(batches [][]string) map[string]int {{", "\tcounts := map[string]int{}",
        "\tvar wg sync.WaitGroup", "\tfor _, b := range batches {", "\t\twg.Add(1)",
        "\t\tgo func(b []string) {", "\t\t\tdefer wg.Done()", "\t\t\tfor _, k := range b {",
        "\t\t\t\tcounts[k]++", "\t\t\t}", "\t\t}(b)", "\t}", "\twg.Wait()", "\treturn counts", "}"])
    T, M = rng.choice(TYPES), rng.choice(METHODS)
    bv, kv = rng.choice(BATCH_VARS), rng.choice(KEY_VARS)
    srcs = {n: _rename(src, bv, kv) for n, src in _variants(fn, T, M).items()}
    buggy = _rename(buggy, bv, kv)
    names = ["correct", "value_receiver", "unlocked_write", "unbuffered_wait"]
    labels = {"correct": "Счётчик с мьютексом, метод с указательным получателем",
              "value_receiver": "Счётчик с мьютексом, метод с получателем-значением",
              "unlocked_write": "Мьютекс вокруг чтения значения, запись после Unlock",
              "unbuffered_wait": "Локальные map в горутинах, сбор через канал после wg.Wait()"}
    opts, key = make_options(rng, (labels["correct"], srcs["correct"]),
                             [(labels[n], srcs[n]) for n in names[1:]])
    by_text = {o.text: o.id for o in opts}
    checks = [Check(name="original_fails", runner="go", program=_program(buggy, fn, batches, expected),
                    expect="fail")]
    for nme in names:
        checks.append(Check(name=f"option:{by_text[labels[nme]]}", runner="go",
                            program=_program(srcs[nme], fn, batches, expected),
                            expect="pass" if nme == "correct" else "fail", embeds_display_code=False))
    stem = (f"Функция `{fn}` ({ctx}; пакетов {n_batches}) считает {what} в пакетах параллельно — по горутине на пакет. "
            f"Под нагрузкой процесс падает с `fatal error: concurrent map writes`, а `go test -race` "
            f"сообщает о гонке данных. Какой вариант функции корректен: без гонок и взаимных блокировок, "
            f"с верным итогом?")
    why = (f"Верен счётчик с мьютексом и методом на *{T}. С получателем-значением мьютекс копируется при "
           "каждом вызове, и блокировка ничего не защищает (go vet: copylocks). Запись после Unlock — гонка "
           "чтения-записи и потерянные обновления. Небуферизованный канал с wg.Wait() до чтения — deadlock: "
           "горутины ждут получателя, а main ждёт горутины.")
    ak = AnswerKey(kind="option", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="unsynchronized_map",
                         params={"n_batches": n_batches})
