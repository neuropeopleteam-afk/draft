"""common.linux.log_pipeline — predict_output: конвейер grep/cut/sort/uniq/awk над журналом."""
from __future__ import annotations

from collections import Counter

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.linux.log_pipeline"

CONTEXTS = [
    (["/api/orders", "/api/orders/42", "/api/cart", "/api/products/7", "/login"], "интернет-магазин"),
    (["/api/videos", "/api/videos/9", "/api/stream/7", "/api/subtitles", "/auth"], "видеосервис"),
    (["/api/accounts", "/api/accounts/3", "/api/transfers", "/api/cards", "/login"], "банк"),
    (["/api/courses", "/api/courses/5", "/api/lessons/3", "/api/quiz", "/auth"], "онлайн-школа"),
]
IPS = ["10.0.0.3", "10.0.0.7", "10.0.0.12", "10.0.1.5", "10.0.2.8"]
PIPES = ["top_err_ips", "err_paths", "post_stats", "slow_count", "top_status", "grep_count",
         "not_ok", "slowest_path"]


def _log(rng, paths):
    rows = []
    for _ in range(rng.randint(9, 13)):
        st = rng.choices([200, 201, 302, 404, 500], weights=[6, 1, 1, 2, 2])[0]
        meth = rng.choices(["GET", "POST", "DELETE"], weights=[6, 3, 1])[0]
        rows.append((rng.choice(IPS[:rng.randint(3, 5)]), meth, rng.choice(paths), st,
                     rng.randint(5, 900)))
    return rows


def _eval(kind, rows, arg):
    if kind == "top_err_ips":
        c = Counter(r[0] for r in rows if r[3] == 500)
        top = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))
        vals = [v for _, v in top]
        if len(top) < 2 or vals[0] == vals[1] or (len(vals) > 2 and vals[1] == vals[2]):
            return None
        return "\n".join(f"{v} {k}" for k, v in top[:2])
    if kind == "err_paths":
        return str(len({r[2] for r in rows if r[3] >= 400}))
    if kind == "post_stats":
        p = [r for r in rows if r[1] == "POST"]
        return f"{len(p)} {sum(r[4] for r in p)}" if p else None
    if kind == "slow_count":
        return str(sum(1 for r in rows if r[4] > arg))
    if kind == "top_status":
        c = Counter(r[3] for r in rows).most_common()
        if len(c) > 1 and c[0][1] == c[1][1]:
            return None
        return f"{c[0][1]} {c[0][0]}"
    if kind == "grep_count":
        n = sum(1 for r in rows if f"GET {arg}" in f"{r[1]} {r[2]}")
        return str(n) if n else None  # grep -c без совпадений завершается с кодом 1
    if kind == "not_ok":
        return str(sum(1 for r in rows if r[3] != 200))
    if kind == "slowest_path":
        ms = sorted(r[4] for r in rows)
        if ms[-1] == ms[-2]:
            return None
        return max(rows, key=lambda r: r[4])[2]
    raise ValueError(kind)


def _cmd(kind, arg):
    return {
        "top_err_ips": "grep ' 500 ' access.log | cut -d' ' -f1 | sort | uniq -c | sort -rn | head -n 2",
        "err_paths": "awk '$4 >= 400 {print $3}' access.log | sort -u | wc -l",
        "post_stats": "awk '$2 == \"POST\" {n++; s += $5} END {print n, s}' access.log",
        "slow_count": f"awk '$5 > {arg}' access.log | wc -l",
        "top_status": "cut -d' ' -f4 access.log | sort | uniq -c | sort -rn | head -n 1",
        "grep_count": f"grep -c 'GET {arg}' access.log",
        "not_ok": "grep -v ' 200 ' access.log | wc -l",
        "slowest_path": "sort -n -k5 access.log | tail -n 1 | cut -d' ' -f3",
    }[kind]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    paths, ctx = rng.choice(CONTEXTS)
    kind = rng.choice(PIPES)
    for _ in range(500):
        rows = _log(rng, paths)
        arg = rng.choice([100, 200, 300, 500]) if kind == "slow_count" else \
            (rng.choice([p for p in paths if p.startswith("/api/") and p.count("/") == 2])
             if kind == "grep_count" else None)
        out = _eval(kind, rows, arg)
        if out is not None and (kind != "top_err_ips" or sum(r[3] == 500 for r in rows) >= 4):
            break
    else:
        raise RuntimeError("не удалось подобрать журнал")
    log = "\n".join(" ".join(map(str, r)) for r in rows) + "\n"
    cmd = _cmd(kind, arg)
    stem = ("Файл `access.log` веб-сервиса (" + ctx + ") в формате `IP МЕТОД ПУТЬ СТАТУС МС`:\n\n"
            + log + "\nЧто выведет команда? Пробелы в начале строк можно не писать.")
    ak = AnswerKey(kind="output", value=out,
                   explanation={"top_err_ips": "uniq -c считает только соседние строки, поэтому "
                                               "перед ним нужна sort; sort -rn — по убыванию числа",
                                "grep_count": "grep -c считает строки с подстрокой — подходят и "
                                              "более длинные пути с тем же префиксом",
                                "not_ok": "grep -v ' 200 ' оставляет строки, где статус не 200"
                                }.get(kind, "Разбор: поля разделены одним пробелом; $4 — статус, $5 — время, мс."))
    checks = [Check(name="stdout", runner="bash", program=cmd, files={"access.log": log},
                    expect="stdout_equals", expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=cmd, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"pipeline": kind})
