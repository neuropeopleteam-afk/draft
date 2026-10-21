"""mobile.release.t21_build_sort_output — predict_output (набор t21, порог Middle): номера сборок и версии
приложения — sort() без функции сравнения сортирует как строки.

Экран выбора сборки для бета-тестировщиков в React Native-приложении: программа сортирует номера сборок
`[...builds].sort()` без компаратора и с компаратором, а строки версий — `versions.sort()`, и берёт «самую новую»
версию с конца. Неочевидная семантика: sort() без функции сравнивает элементы как строки посимвольно — 1003
раньше 120, 87 после 410, '10.0.0' раньше '2.9.0', '2.10.0' раньше '2.9.1'; с компаратором (a, b) => a − b —
числовой порядок. Ключ — независимая модель в генераторе (сортировка строковых представлений); проверка —
исполнение показанного кода в песочнице Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.release.t21_build_sort_output"

CTX = ["бета-сборки приложения доставки", "сборки банковского приложения", "версии приложения такси",
       "сборки приложения маркетплейса", "версии корпоративного мессенджера"]


def _builds(rng) -> list[int]:
    for _ in range(500):
        n = rng.randint(4, 5)
        xs = sorted({rng.choice([rng.randint(8, 99), rng.randint(100, 999), rng.randint(1000, 1500)])
                     for _ in range(n)})
        if len(xs) != n:
            continue
        lex = sorted(xs, key=str)
        # нужны разные длины чисел и расхождение строкового порядка с числовым на обоих концах
        if len({len(str(x)) for x in xs}) >= 2 and lex[0] != xs[0] and lex[-1] != xs[-1]:
            rng.shuffle(xs)
            return xs
    raise RuntimeError("t21_build_sort: не собрались номера сборок")


def _versions(rng, pick: str) -> list[str]:
    for _ in range(500):
        major = rng.randint(2, 9)
        cand = {f"{major}.{rng.randint(10, 19)}.{rng.randint(0, 3)}",
                f"{major}.{rng.randint(2, 9)}.{rng.randint(0, 9)}",
                f"{major + rng.choice([0, 1])}.{rng.randint(0, 9)}.{rng.randint(0, 9)}",
                f"1{rng.randint(0, 2)}.{rng.randint(0, 5)}.0" if rng.random() < 0.5 else
                f"{major}.{rng.randint(10, 12)}.{rng.randint(4, 9)}"}
        vs = sorted(cand)   # порядок множества строк зависит от PYTHONHASHSEED — сначала упорядочить
        if len(vs) < 3:
            continue
        key = lambda v: tuple(int(p) for p in v.split("."))  # noqa: E731
        lex = sorted(vs)
        if (pick == "last" and lex[-1] != max(vs, key=key)) or (pick == "first" and lex[0] != min(vs, key=key)):
            rng.shuffle(vs)
            return vs
    raise RuntimeError("t21_build_sort: не собрались версии")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    builds = _builds(rng)
    desc = rng.random() < 0.5
    pick = rng.choice(["first", "last"])
    versions = _versions(rng, pick)
    b_name = rng.choice(["builds", "buildNumbers", "codes"])
    v_name = rng.choice(["versions", "releases", "tags"])
    cmp_txt = "(a, b) => b - a" if desc else "(a, b) => a - b"
    lines = [f"const {b_name} = [{', '.join(map(str, builds))}];",
             f"const asText = [...{b_name}].sort();",
             f"const asNumber = [...{b_name}].sort({cmp_txt});",
             f"const {v_name} = [{', '.join(repr(v) for v in versions)}];",
             f"{v_name}.sort();",
             "console.log(asText.join(' '));",
             "console.log(asNumber[0], asNumber[asNumber.length - 1]);"]
    if pick == "last":
        lines.append(f"console.log('latest', {v_name}[{v_name}.length - 1]);")
    else:
        lines.append(f"console.log('oldest', {v_name}[0]);")
    code = "\n".join(lines)
    as_text = sorted(builds, key=str)
    as_num = sorted(builds, reverse=desc)
    vs_sorted = sorted(versions)
    v_out = vs_sorted[-1] if pick == "last" else vs_sorted[0]
    out = (f"{' '.join(map(str, as_text))}\n{as_num[0]} {as_num[-1]}\n"
           f"{'latest' if pick == 'last' else 'oldest'} {v_out}")
    expl = (f"sort() без функции сравнения приводит элементы к строкам и сравнивает посимвольно: "
            f"{', '.join(repr(str(x)) for x in as_text)} — отсюда «{' '.join(map(str, as_text))}». С компаратором "
            f"{cmp_txt} порядок числовой{' по убыванию' if desc else ''}: первый {as_num[0]}, последний "
            f"{as_num[-1]}. Версии — тоже строки и сортируются посимвольно: {', '.join(vs_sorted)}, поэтому "
            f"{'последней' if pick == 'last' else 'первой'} оказывается {v_out}.")
    stem = (f"React Native-экран выбора сборки для бета-тестировщиков ({ctx}): программа сортирует номера сборок и "
            f"строки версий, чтобы показать список и крайние значения.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"builds": builds, "versions": versions, "desc": desc, "pick": pick},
                          language="javascript")
