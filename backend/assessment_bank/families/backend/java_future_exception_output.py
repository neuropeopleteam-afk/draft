"""backend.java.future_exception_output — predict_output: исключения в цепочке CompletableFuture.

Один подтип: исключение (или его отсутствие — по данным) в середине цепочки thenApply → thenApply →
exceptionally → thenApply → join, затем отдельная задача supplyAsync, падающая сразу, и её join.
Ловушки: стадии после исключения пропускаются; exceptionally получает CompletionException, оборачивающую
исходное исключение; после восстановления цепочка продолжается; join бросает CompletionException
с исходной причиной. Ключ — независимая модель, сверка исполнением показанного кода (javac + JVM).
Печать идёт только из стадий одной линейной цепочки и из main после join — порядок детерминирован.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.java.future_exception_output"

# (контекст, исключение в цепочке, сообщение, исключение второй задачи, сообщение)
CONTEXTS = [("расчёт лимита", "IllegalArgumentException", "over limit", "IllegalStateException", "rates down"),
            ("проверка заказа", "IllegalStateException", "bad order", "UnsupportedOperationException", "no stock api"),
            ("скоринг", "ArithmeticException", "score overflow", "IllegalStateException", "bureau down"),
            ("тарифы доставки", "IllegalArgumentException", "zone unknown", "RuntimeException", "geo down"),
            ("курсы валют", "IllegalStateException", "stale rate", "IllegalArgumentException", "bad pair")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, exc1, msg1, exc2, msg2 = rng.choice(CONTEXTS)
    start = rng.randint(2, 40)
    add = rng.randint(1, 9)
    limit = rng.randint(10, 50)
    mul = rng.randint(2, 6)
    fallback = rng.choice([-1, 0, 1])
    tail = rng.randint(1, 20)
    show = rng.choice(["class", "cause"])
    throws = start + add > limit
    out: list[str] = []
    out.append(f"stage1 {start}")
    v = start + add
    if throws:
        out.append(("ex " + "CompletionException") if show == "class" else f"ex {msg1}")
        v = fallback
    else:
        out.append(f"stage2 {v}")
        v = v * mul
    v = v + tail
    out.append(f"result {v}")
    out.append(f"join {exc2}: {msg2}")
    ex_expr = 'ex.getClass().getSimpleName()' if show == "class" else 'ex.getCause().getMessage()'
    code = "\n".join([
        "import java.util.concurrent.*;",
        "",
        "public class Main {",
        "    public static void main(String[] args) {",
        f"        CompletableFuture<Integer> f = CompletableFuture.supplyAsync(() -> {start})",
        "                .thenApply(x -> {",
        '                    System.out.println("stage1 " + x);',
        f"                    int y = x + {add};",
        f'                    if (y > {limit}) throw new {exc1}("{msg1}");',
        "                    return y;",
        "                })",
        "                .thenApply(y -> {",
        '                    System.out.println("stage2 " + y);',
        f"                    return y * {mul};",
        "                })",
        "                .exceptionally(ex -> {",
        f'                    System.out.println("ex " + {ex_expr});',
        f"                    return {fallback};",
        "                })",
        f"                .thenApply(z -> z + {tail});",
        '        System.out.println("result " + f.join());',
        "        CompletableFuture<String> g = CompletableFuture.supplyAsync(() -> {",
        f'            throw new {exc2}("{msg2}");',
        "        });",
        "        try {",
        "            g.join();",
        "        } catch (CompletionException e) {",
        '            System.out.println("join " + e.getCause().getClass().getSimpleName() + ": "',
        "                    + e.getCause().getMessage());",
        "        }",
        "    }",
        "}"]) + "\n"
    expected = "\n".join(out)
    checks = [Check(name="run", runner="java", program=code, expect="stdout_equals", expected_stdout=expected)]
    stem = (f"Цепочка CompletableFuture ({ctx}). Что выведет программа? Запишите вывод построчно точно "
            f"в формате программы.")
    if throws:
        why = (f"{start} + {add} > {limit}: первая стадия бросает {exc1}, вторая пропускается. exceptionally "
               f"получает CompletionException с исходным исключением в getCause() и возвращает {fallback}; "
               f"цепочка продолжается: {fallback} + {tail}. join второй задачи бросает CompletionException, "
               f"причина — {exc2}.")
    else:
        why = (f"{start} + {add} ≤ {limit}: исключения нет, exceptionally пропускается, результат "
               f"({start} + {add}) × {mul} + {tail}. join второй задачи бросает CompletionException, "
               f"причина — {exc2}.")
    ak = AnswerKey(kind="output", value=expected, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         params={"throws": throws, "show": show})
