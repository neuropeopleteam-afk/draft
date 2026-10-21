"""common.regex.t21_findall_groups_output — predict_output (набор t21, порог Junior): что возвращает re.findall
без групп, с одной группой и с двумя группами.

Строка журнала в формате «ключ=значение» (несколько записей через «; »). Три вызова re.findall: шаблон без групп
возвращает список ЦЕЛЫХ совпадений («ms=34»), шаблон с одной группой — список строк этой группы («ann»), с двумя
группами — список кортежей. В одной из записей по варианту нет второго поля, поэтому шаблон из двух полей находит
меньше совпадений, чем шаблон из одного. Ловушки: без групп печатается совпадение целиком, с группой — только
группа, с двумя группами — кортежи; \\w+ и \\d+ жадные до первого чужого символа. Ключ — независимая модель по
записям, из которых собрана строка (без re и без исполнения показанного кода); проверка — исполнение показанного
кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "common.regex.t21_findall_groups_output"

# (сюжет, словесное поле и значения, числовое поле A, числовое поле B)
CTX = [("структурный журнал веб-сервиса", ("user", ["ann", "bob", "eve", "kim", "lee", "max"]),
        ("code", 200, 504), ("ms", 3, 900)),
       ("журнал CI-сборок", ("job", ["build", "test", "lint", "deploy", "docs", "bench"]),
        ("rc", 0, 3), ("sec", 5, 400)),
       ("журнал очереди фоновых задач", ("task", ["email", "resize", "report", "backup", "sync"]),
        ("retry", 0, 5), ("ms", 10, 3000)),
       ("журнал платёжного шлюза", ("shop", ["books", "pizza", "taxi", "games", "flowers"]),
        ("order", 100, 999), ("sum", 50, 9000)),
       ("журнал входов в систему", ("login", ["ivan", "olga", "root", "guest", "admin"]),
        ("attempt", 1, 5), ("port", 2000, 9000))]


def _lst(xs) -> str:
    return "[" + ", ".join(repr(x) for x in xs) + "]"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, (wk, wvals), (ak, alo, ahi), (bk, blo, bhi) = rng.choice(CTX)
    var = rng.choice(["line", "log", "entry", "row"])
    n = rng.randint(2, 3)
    words = rng.sample(wvals, n)
    recs = []
    for w in words:
        recs.append({wk: w, ak: str(rng.randint(alo, ahi)), bk: str(rng.randint(blo, bhi))})
    drop = rng.random() < 0.6               # у одной записи нет поля A
    if drop:
        di = rng.randrange(n)
        del recs[di][ak]
    parts = []
    for r in recs:
        parts.append(" ".join(f"{k}={r[k]}" for k in (wk, ak, bk) if k in r))
    line = "; ".join(parts)
    # три шаблона: без групп (числовое поле B целиком), одна группа (слово), две группы (слово + поле A)
    p0 = f'r"{bk}=\\d+"'
    p1 = f'r"{wk}=(\\w+)"'
    p2 = f'r"{wk}=(\\w+) {ak}=(\\d+)"'
    r0 = [f"{bk}={r[bk]}" for r in recs]
    r1 = [r[wk] for r in recs]
    r2 = [(r[wk], r[ak]) for r in recs if ak in r]
    calls = [(p0, _lst(r0)), (p1, _lst(r1)), (p2, _lst(r2))]
    order = [0, 1, 2]
    if rng.random() < 0.5:
        rng.shuffle(order)
    code = ("import re\n"
            f'{var} = "{line}"\n'
            + "\n".join(f"print(re.findall({calls[i][0]}, {var}))" for i in order))
    out = "\n".join(calls[i][1] for i in order)
    miss = ""
    if drop:
        miss = (f" У записи {wk}={recs[di][wk]} нет поля «{ak}=», поэтому шаблон из двух полей её не находит: "
                f"совпадений {len(r2)}, а не {n}.")
    expl = (f"Без групп findall возвращает совпадения целиком: {_lst(r0)}. С одной группой — только текст группы: "
            f"{_lst(r1)}. С двумя группами — кортежи (группа 1, группа 2): {_lst(r2)}.{miss} Ловушка — ждать "
            f"целые совпадения при наличии групп или списки вместо кортежей.")
    stem = (f"Разбор логов ({ctx}): программа достаёт поля из строки журнала регулярными выражениями.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"line": line, "order": order, "drop": drop}, language="python")
