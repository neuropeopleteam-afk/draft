"""devops.bash.t21_leading_zero_arith_output — predict_output (набор t21, порог Middle): число с ведущим нулём
в арифметике bash читается как восьмеричное.

Скрипт берёт номер с ведущими нулями — из имени архива/дампа/сборки (`dump_0014.sql`) или из порядковой даты
`2026-045` (день года, как у `date +%j`) — и считает следующий номер. Ловушки: в `$(( ))` и `(( ))` запись
`0014` — восьмеричная (1·8 + 4 = 12); `10#$n` задаёт основание 10 (14); `[ "$n" -lt X ]` сравнивает как десятичные
числа, а `(( n < X ))` — как арифметику (восьмеричную); `printf '%04d'` от `$((10#$n + 1))` печатает десятичное с
нулями. Все показанные числа без `10#` состоят из цифр 0–7 — ошибки «value too great for base» в коде нет. Ключ —
независимая модель (int(s, 8) / int(s, 10)) в генераторе; проверка — исполнение показанного скрипта в bash-песочнице.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.bash.t21_leading_zero_arith_output"

# (сюжет, переменная источника, префикс, суффикс, ширина номера, имя переменной номера)
SOURCES = [("ротация дампов базы", "last", "dump_", ".sql", 4, "n"),
           ("архив логов шлюза", "file", "gw.log.", "", 3, "idx"),
           ("нумерация сборок CI", "tag", "build-", "", 4, "num"),
           ("бэкапы конфигов", "last", "cfg-", ".tar.gz", 4, "n"),
           ("миграции схемы", "mig", "", "_add_index.sql", 4, "seq"),
           ("снимки диска", "snap", "snap.", "", 3, "k"),
           ("дежурства по дням года", "stamp", "2026-", "", 3, "doy"),
           ("отчёты по дням года", "day", "2026-", "", 3, "doy")]
LABELS = [("raw", "fixed"), ("v1", "v2"), ("calc", "base10"), ("plain", "dec")]


def _digits_ok(s: str) -> bool:
    return all(ch in "01234567" for ch in s)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, src, pre, suf, width, nv = rng.choice(SOURCES)
    for _ in range(500):
        val = rng.randint(10, 77)  # две значащие цифры: восьмеричное значение считается в уме (d1·8 + d2)
        s = str(val).zfill(width)
        if _digits_ok(s) and s[0] == "0" and int(s, 8) != val:
            break
    else:
        raise RuntimeError("t21_leading_zero: не подобран номер")
    oct_v, dec_v = int(s, 8), int(s, 10)
    l_raw, l_fix = rng.choice(LABELS)
    op, k = rng.choice([("+", 1), ("+", 1), ("+", 2), ("-", 1), ("-", 2)])
    calc = (lambda x: x + k) if op == "+" else (lambda x: x - k)
    name = f"{pre}{s}{suf}"
    lines = [f'{src}="{name}"']
    if pre and suf:
        lines += [f"{nv}=${{{src}#{pre}}}", f"{nv}=${{{nv}%{suf}}}"]
    elif pre:
        lines.append(f"{nv}=${{{src}#{pre}}}")
    else:
        lines.append(f"{nv}=${{{src}%{suf}}}")
    blocks = []   # (строки кода, строки вывода, пояснение)
    blocks.append(([f'echo "{l_raw}: $(({nv} {op} {k}))"'], [f"{l_raw}: {calc(oct_v)}"],
                   f"$(({nv} {op} {k})): «{s}» с ведущим нулём — восьмеричная запись, это {oct_v}, итог {calc(oct_v)}"))
    blocks.append(([f'echo "{l_fix}: $((10#${nv} {op} {k}))"'], [f"{l_fix}: {calc(dec_v)}"],
                   f"10#${nv} — основание 10: {dec_v} {op} {k} = {calc(dec_v)}"))
    extra = ["cmp", "printf"] if rng.random() < 0.5 else ["cmp"]
    if "cmp" in extra:
        if rng.random() < 0.8:
            thr = rng.randint(oct_v + 1, dec_v)
        else:
            thr = rng.choice([max(2, oct_v - rng.randint(1, 5)), dec_v + rng.randint(1, 5)])
        topt, aop, pyop = rng.choice([("-lt", "<", lambda a, b: a < b), ("-ge", ">=", lambda a, b: a >= b)])
        t_res = "yes" if pyop(dec_v, thr) else "no"
        a_res = "yes" if pyop(oct_v, thr) else "no"
        tl, al = rng.choice([("test", "arith"), ("cmp", "expr"), ("check", "math")])
        blocks.append(([f'[ "${nv}" {topt} {thr} ] && echo "{tl}: yes" || echo "{tl}: no"',
                        f'(( {nv} {aop} {thr} )) && echo "{al}: yes" || echo "{al}: no"'],
                       [f"{tl}: {t_res}", f"{al}: {a_res}"],
                       f"[ {topt} ] сравнивает десятичные числа ({dec_v} {aop} {thr} — {t_res}), а (( )) — "
                       f"арифметика с восьмеричной записью ({oct_v} {aop} {thr} — {a_res})"))
    if "printf" in extra:
        nxt = dec_v + 1
        shown = f"{pre}%0{width}d{suf}"
        blocks.append(([f"printf '{shown}\\n' $((10#${nv} + 1))"], [f"{pre}{str(nxt).zfill(width)}{suf}"],
                       f"printf получает уже десятичное {nxt} и дополняет нулями до {width} знаков"))
    head = blocks[:2]
    if rng.random() < 0.5:
        head.reverse()
    tail = blocks[2:]
    rng.shuffle(tail)
    order = head + tail if rng.random() < 0.7 else [head[0]] + tail + [head[1]]
    code_lines = lines + [ln for b in order for ln in b[0]]
    outs = [o for b in order for o in b[1]]
    code = "\n".join(code_lines)
    out = "\n".join(outs)
    expl = (f"После обрезки {nv}=«{s}». " + "; ".join(b[2] for b in order) +
            ". Вывод по строкам: " + " / ".join(f"«{x}»" for x in outs) + ".")
    what = "номер дня года из даты" if nv == "doy" else "номер из имени"
    stem = f"Скрипт ({ctx}) извлекает {what} «{name}» и вычисляет по нему соседние номера и проверку порога."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"s": s, "op": op, "k": k, "extra": extra}, language="bash")
