"""backend.java.stream_lazy_output — predict_output: ленивость Stream API и короткое замыкание.

Один подтип: последовательный поток peek → filter → map → limit(k) → collect с журналом побочных
эффектов. Ловушки: элементы проходят конвейер по одному (вертикально, а не «весь peek, потом весь
filter»), limit останавливает обход источника, map вызывается только для прошедших фильтр.
Ключ — независимая модель конвейера; сверка исполнением показанного кода (javac + JVM).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.java.stream_lazy_output"

# (контекст, имя списка, слово для peek, слово для map, условие фильтра (java, python), описание)
CONTEXTS = [("заказы", "amounts", "see", "fee", "больше порога"), ("задержки запросов", "latencies", "read", "slow", "больше порога"),
            ("оценки", "grades", "got", "pass", "больше порога"), ("остатки", "stock", "scan", "low", "больше порога"),
            ("пульс", "pulses", "beat", "high", "больше порога")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, var, w_peek, w_map, _d = rng.choice(CONTEXTS)
    n = rng.randint(6, 8)
    data = rng.sample(range(1, 99), n)
    thr = sorted(data)[rng.randint(1, n - 3)]
    k = rng.randint(1, 3)
    mul = rng.randint(2, 5)
    add = rng.randint(1, 9)
    cmp_op = rng.choice([">", ">="])
    passes = (lambda x: x > thr) if cmp_op == ">" else (lambda x: x >= thr)
    if sum(1 for x in data if passes(x)) < k:
        k = 1
    # модель: вертикальная обработка, limit(k) прекращает обход после k-го элемента на выходе limit
    log: list[str] = []
    out: list[int] = []
    for x in data:
        log.append(f"{w_peek} {x}")
        if not passes(x):
            continue
        log.append(f"{w_map} {x}")
        out.append(x * mul + add)
        if len(out) == k:
            break
    code = "\n".join([
        "import java.util.*;",
        "import java.util.stream.*;",
        "",
        "public class Main {",
        "    public static void main(String[] args) {",
        f"        List<Integer> {var} = List.of({', '.join(map(str, data))});",
        "        List<String> log = new ArrayList<>();",
        f"        List<Integer> result = {var}.stream()",
        f'                .peek(x -> log.add("{w_peek} " + x))',
        f"                .filter(x -> x {cmp_op} {thr})",
        "                .map(x -> {",
        f'                    log.add("{w_map} " + x);',
        f"                    return x * {mul} + {add};",
        "                })",
        f"                .limit({k})",
        "                .collect(Collectors.toList());",
        "        log.forEach(System.out::println);",
        '        System.out.println("result " + result);',
        "    }",
        "}"]) + "\n"
    expected = "\n".join(log + ["result [" + ", ".join(map(str, out)) + "]"])
    checks = [Check(name="run", runner="java", program=code, expect="stdout_equals", expected_stdout=expected)]
    stem = (f"Поток Stream API обрабатывает {ctx} и пишет журнал побочных эффектов. Что выведет программа? "
            f"Запишите вывод построчно точно в формате программы.")
    why = (f"Последовательный поток ленив и обрабатывает элементы по одному через весь конвейер: peek → filter "
           f"→ map → limit. map вызывается только для прошедших фильтр, а после {k}-го элемента на выходе "
           f"limit({k}) обход источника прекращается — оставшиеся элементы не попадают даже в peek.")
    ak = AnswerKey(kind="output", value=expected, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"k": k, "n": n, "thr": thr})
