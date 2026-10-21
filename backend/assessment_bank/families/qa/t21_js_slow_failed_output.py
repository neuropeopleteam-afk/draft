"""qa.reports.t21_js_slow_failed_output — predict_output (набор t21, порог Junior, JavaScript): filter + map с
деструктуризацией и reduce по результатам прогона.

Массив результатов тестов {name, ms, ok}: программа собирает имена медленных (строго больше порога) через filter/map с
деструктуризацией параметров и суммарное время упавших через filter/reduce с начальным 0. Ловушки: строгое сравнение
с порогом (в части вариантов время ровно на пороге), фильтр по !ok, порядок имён — как в массиве. Ключ — независимая
модель в генераторе; проверка — исполнение показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.reports.t21_js_slow_failed_output"

CTX = [("e2e-прогон витрины", ["home", "search", "cart", "checkout", "profile", "orders"]),
       ("UI-тесты админ-панели", ["login", "users", "roles", "audit", "export", "billing"]),
       ("компонентные тесты формы", ["render", "submit", "validate", "reset", "upload", "hint"]),
       ("API-тесты в CI", ["auth", "items", "prices", "stock", "refund", "report"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pool = rng.choice(CTX)
    limit = rng.choice([200, 250, 300, 400, 500])
    sum_var = rng.choice(["failedMs", "lostMs", "redMs"])
    for _ in range(300):
        n = rng.randint(4, 5)
        names = rng.sample(pool, n)
        runs = []
        for nm in names:
            ms = limit if rng.random() < 0.2 else rng.randrange(limit // 2, limit * 2 + 1, 10)
            runs.append((nm, ms, rng.random() < 0.55))
        slow = [nm for nm, ms, _ in runs if ms > limit]
        failed = [ms for _, ms, ok in runs if not ok]
        if slow and failed and any(ok for *_, ok in runs) and any(ms <= limit for _, ms, _ in runs):
            break
    else:
        raise RuntimeError("t21_js_slow_failed: не собрались результаты")
    lines = ["const runs = ["]
    for nm, ms, ok in runs:
        lines.append(f"  {{ name: \"{nm}\", ms: {ms}, ok: {'true' if ok else 'false'} }},")
    lines += ["];",
              f"const slow = runs.filter(({{ ms }}) => ms > {limit}).map(({{ name }}) => name);",
              f"const {sum_var} = runs.filter((r) => !r.ok).reduce((sum, r) => sum + r.ms, 0);",
              f"console.log(slow.join(\",\"), {sum_var});"]
    code = "\n".join(lines)
    total = sum(failed)
    out = f"{','.join(slow)} {total}"
    on_limit = [nm for nm, ms, _ in runs if ms == limit]
    edge = (f" {', '.join(on_limit)} ровно на пороге {limit} — условие ms > {limit} ложно, в список не попадает."
            if on_limit else "")
    expl = (f"filter оставляет тесты с ms > {limit}: {', '.join(slow)}; map берёт имена, join склеивает через запятую."
            f"{edge} Упавшие (ok: false): {' + '.join(map(str, failed))} = {total} — reduce начинает с 0. "
            f"console.log печатает два значения через пробел: «{out}».")
    stem = (f"Отчёт о прогоне ({ctx}): программа на JavaScript выбирает медленные тесты и считает, сколько "
            "времени заняли упавшие.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"runs": [list(r) for r in runs], "limit": limit}, language="javascript")
