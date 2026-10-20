"""Волна 20.10-S («масштабирование банка до 1 500+ семейств»): определения моделей параметрических семейств.

Как устроено (и почему каждое семейство — честное, со своей исполняемой моделью):

* **Базовая модель** (:class:`Arch`) — реальный инженерный/продуктовый расчёт направления (пул соединений, кворум,
  бюджет ошибок SLO, лаг консьюмеров Kafka, размер индекса, батчинг на GPU, воронка и т. д.): базовая формула и
  пять поправочных факторов (пик, ретраи, запас утилизации, репликация, накладные расходы …). Каждый фактор — одно
  предложение условия, один шаг модели и ДВЕ ловушки (типичные ошибки: «фактор не учтён», «учтён не так»).
* **Семейство** = базовая модель × ступень сложности (сколько факторов взаимодействуют: 2…5) × направление вопроса:
  прямой расчёт (``fwd``) или обратная задача по одному из двух входов (``solve_<параметр>``: наибольшее/наименьшее
  значение входа на сетке, при котором выполняется лимит). У каждого семейства свой текст модели ``MODEL`` (только
  его факторы), свои ловушки, свой грейд и априорные IRT-параметры.
* **Генерация** — :func:`assessment_bank.families._w2010_kit.numeric_variant`: ключ = ``fmt(answer(P))`` исполнением
  модели; проверка «model» (ключ), «trap» (ловушка ≠ ключ) и для обратных задач «brute» (линейный перебор сетки
  вместо бисекции — подтверждает и монотонность). Ответ равновероятно на любом месте по величине среди четырёх.
* Вся арифметика модели — точные дроби (:class:`fractions.Fraction`): округление вверх/вниз без ошибок плавающей
  точки.

Модуль семейства — тонкая обёртка ``generate = make(FAMILY_ID)``; YAML и обёртки собирает
``tools/w2010_scale1500.py`` из этого описания (правьте каталоги ``_w2010_scale_cat_*.py``, не YAML).
"""
from __future__ import annotations

import re
import zlib
from fractions import Fraction
from typing import Any

from assessment_bank.families._w2010_kit import load_model, num, numeric_variant
from assessment_bank.gen_utils import plural

# (режим, число факторов, грейд, базовое b): прямой расчёт — Стажёр…Senior, обратные задачи — Junior…Principal
LEVELS: list[tuple[str, int, str, float]] = [
    ("fwd", 2, "intern", -1.3), ("fwd", 3, "junior", -0.6), ("fwd", 4, "middle", 0.2), ("fwd", 5, "senior", 1.0),
    ("inv0", 2, "junior", -0.3), ("inv0", 3, "middle", 0.5), ("inv0", 4, "lead", 2.10), ("inv0", 5, "principal", 3.04),
    ("inv1", 2, "middle", 0.8), ("inv1", 3, "senior", 1.5), ("inv1", 4, "lead", 2.26), ("inv1", 5, "principal", 3.16),
]
TIME = {"intern": 180, "junior": 180, "middle": 210, "senior": 210, "lead": 180, "principal": 180}
GRADE_RU = {"intern": "Стажёр", "junior": "Junior", "middle": "Middle", "senior": "Senior", "lead": "Lead",
            "principal": "Principal"}
NOTE = ("Ответ проверяется программой-моделью по тем же числам, что в условии (точные дроби, без ошибок округления "
        "плавающей точки).")

ARCHS: dict[str, "Arch"] = {}
FAMILIES: dict[str, dict[str, Any]] = {}
_RX = re.compile(r"\{(\w+)(?:\|([^}]*))?\}")
_IDENT = re.compile(r"\b([A-Za-z_]\w*)\b")
_SAFE = {"x", "min", "max", "abs", "F"}
_DOTS = re.compile(r"(?<!\.)\.\.(?!\.)")


# --------------------------------------------------------------------------- форматирование
def nfmt(v: Any) -> str:
    """Число в условии: целое — с разрядами, дробное — до 3 знаков без хвостовых нулей."""
    if isinstance(v, Fraction):
        v = float(v)
    if isinstance(v, float) and abs(v - round(v)) > 1e-9:
        s = f"{v:.3f}".rstrip("0").rstrip(".")
        ip, _, fp = s.partition(".")
        return num(int(ip)) + ("," + fp if fp else "") if not ip.startswith("-") else s.replace(".", ",")
    return num(int(round(v)))


def unit_text(v: Any, unit: Any) -> str:
    """Подпись числа с единицей: unit — строка (мс, ГБ, %, RPS) или (одна, две, пять) для склонения."""
    if isinstance(unit, (tuple, list)):
        fv = float(v)
        form = unit[1] if abs(fv - round(fv)) > 1e-9 else plural(int(round(fv)), *unit)
        return f"{nfmt(v)} {form}"
    if unit == "%":
        return f"{nfmt(v)} %"
    return f"{nfmt(v)} {unit}".rstrip() if unit else nfmt(v)


def render(tpl: str, P: dict, ctx: str, unknown: str | None = None) -> str:
    def rep(m):
        name, forms = m.group(1), m.group(2)
        if name == "ctx":
            return ctx
        if name == unknown:
            return "X" + (" " + forms.split(",")[2] if forms else "")
        v = P[name]
        return unit_text(v, forms.split(",")) if forms else nfmt(v)
    return _RX.sub(rep, tpl)


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


# --------------------------------------------------------------------------- описание базовой модели
class Arch:
    """Базовая модель направления.

    base   — (текст, выражение, {параметр: выбор}, {ловушка: (выражение, описание)}, подпись шага)
    F      — 5 факторов: (имя, подпись, текст, выражение от x, {параметр: выбор}, {ловушка: (выражение, описание)})
    inv    — 2 обратные задачи: (параметр, (от, до, шаг), "max"|"min", подпись входа, единица входа)
    out    — единица ответа: строка или (одна, две, пять); rnd — ceil | floor | r<N> (округлить до N знаков)
    need   — для обратной задачи: "le" (итог ≤ лимита B) или "ge" (итог ≥ B); budget — текст лимита с {B|…}
    Выбор параметра: список значений или (от, до, шаг) для randrange.
    """

    def __init__(self, d: str, key: str, *, title: str, skills: list[str], construct: str, ctx: list[str],
                 base: tuple, F: list[tuple], q: str, out: Any, inv: list[tuple], budget: str, need: str = "le",
                 rnd: str = "ceil", lim: tuple = (2, 10 ** 9), rel: float = 0.1, cond: str | None = None):
        assert len(ctx) >= 8, (key, "нужно ≥ 8 контекстов")
        assert len(F) == 5 and len(inv) == 2, key
        self.d, self.key, self.title, self.skills, self.construct = d, key, title, skills, construct
        self.ctx, self.base, self.F, self.q, self.out, self.inv = ctx, base, F, q, out, inv
        self.budget, self.need, self.rnd, self.lim, self.rel = budget, need, rnd, lim, rel
        self.cond = cond or ("итог не превысит лимит" if need == "le" else "требование будет выполнено")
        names = set(base[2])
        assert not (names & {"x", "F", "_P", "B"}), (key, "зарезервированное имя параметра")
        _chk(key, "base", [base[1]] + [t[0] for t in base[3].values()], names)
        seen = set(base[3])
        for f in F:
            assert not (set(f[4]) & names), (key, f[0], "повтор параметра")
            names |= set(f[4])
            _chk(key, f[0], [f[3]] + [t[0] for t in f[5].values()], names | {"x"})
            assert not (set(f[5]) & seen), (key, f[0], "повтор имени ловушки")
            seen |= set(f[5])
            for n in f[4]:
                assert "{" + n in f[2], (key, f[0], n, "параметр не упомянут в тексте")
        for n in base[2]:
            assert "{" + n in base[0], (key, n, "параметр не упомянут в тексте базы")
        for p, *_ in inv:
            assert p in base[2] or p in F[0][4] or p in F[1][4], (key, p, "вход обратной задачи — в базе или F1/F2")
        self.params = names
        ARCHS[f"{d}.{key}"] = self


def _chk(key: str, where: str, exprs: list[str], allowed: set[str]) -> None:
    for e in exprs:
        bad = {n for n in _IDENT.findall(e) if n not in allowed and n not in _SAFE}
        assert not bad, (key, where, e, bad)


def A(d: str, key: str, **kw) -> Arch:
    return Arch(d, key, **kw)


# --------------------------------------------------------------------------- типовые поправочные факторы
# Каждый — (имя, подпись, текст, выражение от x, {параметр: выбор}, {ловушка: (выражение, описание)}).
def peak(text: str, ch=(1.5, 2, 2.5, 3, 4), p: str = "k", name: str = "peak", label: str = "пиковый коэффициент"):
    return (name, label, text, f"x*{p}", {p: list(ch)},
            {f"no_{name}": ("x", f"не учтено: {label}"), f"{name}_twice": (f"x*{p}*{p}", f"дважды учтено: {label}")})


def util(text: str, ch=(60, 65, 70, 75, 80), p: str = "u", name: str = "util", label: str = "запас по загрузке"):
    return (name, label, text, f"x*100/{p}", {p: list(ch)},
            {f"no_{name}": ("x", f"не учтено: {label}"),
             f"{name}_free": (f"x*100/(100-{p})", "деление на свободную долю вместо допустимой загрузки")})


def pct(text: str, ch, p: str, name: str, label: str):
    """Надбавка p %: x·(100 + p)/100."""
    return (name, label, text, f"x*(100+{p})/100", {p: list(ch)},
            {f"no_{name}": ("x", f"не учтено: {label}"),
             f"{name}_only": (f"x*{p}/100", f"взята только надбавка ({label}) без основы"),
             f"{name}_twice": (f"x*(100+2*{p})/100", f"надбавка учтена дважды ({label})")})


def loss(text: str, ch, p: str, name: str, label: str):
    """Доля p % теряется/вычитается: x·(100 − p)/100."""
    return (name, label, text, f"x*(100-{p})/100", {p: list(ch)},
            {f"no_{name}": ("x", f"не учтено: {label}"),
             f"{name}_plus": (f"x*(100+{p})/100", f"процент прибавлен вместо вычета ({label})"),
             f"{name}_only": (f"x*{p}/100", f"взята только вычитаемая доля ({label})")})


def gross(text: str, ch, p: str, name: str, label: str):
    """Чтобы после потери p % осталось x, нужно x·100/(100 − p)."""
    return (name, label, text, f"x*100/(100-{p})", {p: list(ch)},
            {f"no_{name}": ("x", f"не учтено: {label}"),
             f"{name}_minus": (f"x*(100-{p})/100", f"процент вычтен вместо компенсации ({label})"),
             f"{name}_ratio": (f"x*100/{p}", f"деление на долю потерь вместо оставшейся доли ({label})")})


def mult(text: str, ch, p: str, name: str, label: str, plus_desc: str | None = None):
    return (name, label, text, f"x*{p}", {p: list(ch)},
            {f"no_{name}": ("x", f"не учтено: {label}"),
             f"{name}_plus1": (f"x*({p}+1)", plus_desc or f"{label}: множитель понят как число дополнительных копий")})


def split(text: str, ch, p: str, name: str, label: str):
    return (name, label, text, f"x/{p}", {p: list(ch)},
            {f"no_{name}": ("x", f"не учтено: {label}"),
             f"{name}_mul": (f"x*{p}", f"{label}: умножено вместо деления"),
             f"{name}_plus1": (f"x/({p}+1)", f"{label}: в делитель добавлена лишняя единица")})


def add(text: str, ch, p: str, name: str, label: str):
    return (name, label, text, f"x+{p}", {p: list(ch)},
            {f"no_{name}": ("x", f"не учтено: {label}"), f"{name}_twice": (f"x+2*{p}", f"дважды учтено: {label}")})


def sub(text: str, ch, p: str, name: str, label: str):
    return (name, label, text, f"x-{p}", {p: list(ch)},
            {f"no_{name}": ("x", f"не учтено: {label}"), f"{name}_plus": (f"x+{p}", f"прибавлено вместо вычета: {label}"),
             f"{name}_twice": (f"x-2*{p}", f"вычтено дважды: {label}")})


# --------------------------------------------------------------------------- исходный текст модели
def _fn(name: str, expr: str, params: set[str], with_x: bool) -> str:
    used = [n for n in dict.fromkeys(_IDENT.findall(expr)) if n in params]
    head = f"def {name}(_P{', x' if with_x else ''}):\n"
    body = "".join(f"    {n} = _P[{n!r}]\n" for n in used)
    return head + body + f"    return F({expr})\n"


def _round_src(rnd: str) -> tuple[str, dict[str, tuple[str, str]]]:
    if rnd == "ceil":
        return ("def rnd(x):\n    return -((-x.numerator) // x.denominator)\n\n"
                "def rnd_floor(x):\n    return x.numerator // x.denominator\n",
                {"floor": ("rnd_floor", "округлено вниз — ресурса не хватит")})
    if rnd == "floor":
        return ("def rnd(x):\n    return x.numerator // x.denominator\n\n"
                "def rnd_ceil(x):\n    return -((-x.numerator) // x.denominator)\n",
                {"ceil": ("rnd_ceil", "округлено вверх — неполная единица посчитана целой")})
    nd = int(rnd[1:])
    return f"def rnd(x):\n    return round(x, {nd})\n", {}


def model_source(a: Arch, k: int, mode: str) -> tuple[str, dict[str, str]]:
    """Текст модели семейства (только его k факторов) и описания ловушек."""
    params = a.params | {"B"}
    btxt, bexpr, _bp, btraps, _blabel = a.base
    parts = ["from fractions import Fraction as F\n", "\ndef _f(v):\n    return F(str(v)) if isinstance(v, float) "
             "else F(v)\n\n", _fn("base", bexpr, params, False)]
    swaps: list[str] = []
    desc: dict[str, str] = {}
    for i, (tn, (texpr, tdesc)) in enumerate(btraps.items()):
        parts.append("\n" + _fn(f"base_t{i}", texpr, params, False))
        swaps.append(f"    {tn!r}: ('base', base_t{i}),\n")
        desc[tn] = tdesc
    steps = []
    for j, (fname, _lab, _txt, fexpr, _fp, ftraps) in enumerate(a.F[:k]):
        parts.append("\n" + _fn(f"step_{fname}", fexpr, params, True))
        steps.append(f"({fname!r}, step_{fname})")
        for i, (tn, (texpr, tdesc)) in enumerate(ftraps.items()):
            parts.append("\n" + _fn(f"{fname}_t{i}", texpr, params, True))
            swaps.append(f"    {tn!r}: ({fname!r}, {fname}_t{i}),\n")
            desc[tn] = tdesc
    rsrc, rtraps = _round_src(a.rnd)
    parts.append("\n" + rsrc)
    for tn, (fn, tdesc) in rtraps.items():
        swaps.append(f"    {tn!r}: ('round', {fn}),\n")
        desc[tn] = tdesc
    parts.append(f"\nSTEPS = [{', '.join(steps)}]\n\nSWAPS = {{\n{''.join(swaps)}}}\n")
    parts.append('''
def calc(P, swap=None):
    v = {n: _f(x) for n, x in P.items() if isinstance(x, (int, float)) and not isinstance(x, bool)}
    s = SWAPS.get(swap)
    x = (s[1] if s and s[0] == "base" else base)(v)
    for name, f in STEPS:
        x = (s[1] if s and s[0] == name else f)(v, x)
    return (s[1] if s and s[0] == "round" else rnd)(x)
''')
    if mode == "fwd":
        parts.append('''
def answer(P):
    return calc(P)

def _safe(f, *a):
    try:
        return f(*a)
    except ZeroDivisionError:      # ошибочная модель может делить на ноль — такой ловушки нет
        return None

def traps(P):
    return {t: _safe(calc, P, t) for t in SWAPS}
''')
        parts.append(f"\nUNIT = {a.out!r}\nND = {_nd(a.rnd)}\n")
    else:
        p, (lo, hi, st), sense, _lab, unit = a.inv[int(mode[3])]
        cmp = "<=" if a.need == "le" else ">="
        parts.append(f'''
XN = {p!r}
GRID = list(range({lo}, {hi} + 1, {st}))
SENSE = {sense!r}

def ok(P, X, swap=None):
    Q = dict(P)
    Q[XN] = X
    return calc(Q, swap) {cmp} _f(P["B"])

def solve(P, swap=None):
    """Бисекция по сетке GRID (итог монотонен по X): крайнее X, при котором лимит выполняется."""
    good = [ok(P, GRID[0], swap), ok(P, GRID[-1], swap)]
    if SENSE == "max":
        if not good[0] or good[1]:
            return None
        lo, hi = 0, len(GRID) - 1          # ok(lo) и не ok(hi)
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if ok(P, GRID[mid], swap) else (lo, mid)
        return GRID[lo]
    if good[0] or not good[1]:
        return None
    lo, hi = 0, len(GRID) - 1              # не ok(lo) и ok(hi)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (lo, mid) if ok(P, GRID[mid], swap) else (mid, hi)
    return GRID[hi]

def answer(P):
    return solve(P)

def brute(P):
    """Линейный перебор всей сетки (без предположения о монотонности)."""
    xs = [X for X in GRID if ok(P, X)]
    if not xs:
        return None
    return max(xs) if SENSE == "max" else min(xs)

def _safe(f, *a):
    try:
        return f(*a)
    except ZeroDivisionError:      # ошибочная модель может делить на ноль — такой ловушки нет
        return None

def traps(P):
    return {{t: _safe(solve, P, t) for t in SWAPS}}
''')
        parts.append(f"\nUNIT = {unit!r}\nND = 0\n")
    parts.append('''
def fmt(x):
    if x is None:
        return "—"
    fv = float(x)
    if ND == 0:
        s = f"{int(round(fv)):,}".replace(",", "\\u00a0")
    else:
        s = f"{fv:,.{ND}f}".replace(",", "\\u00a0").replace(".", ",")
    if isinstance(UNIT, (tuple, list)):
        n = int(round(fv))
        if ND or abs(fv - n) > 1e-9:
            return s + " " + UNIT[1]
        n = abs(n)
        form = UNIT[2] if 11 <= n % 100 <= 14 else UNIT[0] if n % 10 == 1 else UNIT[1] if 2 <= n % 10 <= 4 else UNIT[2]
        return s + " " + form
    return s + (" " + UNIT if UNIT else "")
''')
    return "".join(parts), desc


def _nd(rnd: str) -> int:
    return 0 if rnd in ("ceil", "floor") else int(rnd[1:])


# --------------------------------------------------------------------------- выборка параметров
def _draw(r, spec):
    if isinstance(spec, tuple):
        lo, hi, st = spec
        return r.randrange(lo, hi + 1, st)
    return r.choice(list(spec))


def _human(expr: str, v: dict, x: Any) -> str:
    def rep(m):
        n = m.group(1)
        if n == "x":
            return nfmt(x)
        if n in v:
            return nfmt(v[n])
        return n
    return _IDENT.sub(rep, expr).replace("**", "^").replace("*", "·").replace("//", " div ")


# --------------------------------------------------------------------------- сборка семейств
_FID_GRADE = {("inv0", 4): "senior", ("inv0", 5): "lead"}


def _fid(a: Arch, mode: str, k: int, grade: str) -> tuple[str, str, str]:
    mname = "fwd" if mode == "fwd" else "solve_" + a.inv[int(mode[3])][0].lower()
    gslug = _FID_GRADE.get((mode, k), grade)
    fid = f"{a.d}.{a.key}.{gslug}_{mname}_k{k}"
    mod = f"s15_{a.key}_{mname}_k{k}"
    return fid, mod, mname


def _register(a: Arch) -> None:
    for mode, k, grade, b0 in LEVELS:
        fid, mod, mname = _fid(a, mode, k, grade)
        FAMILIES[fid] = {"arch": a, "mode": mode, "k": k, "grade": grade, "b0": b0, "mod": mod, "mname": mname}


_CUT_B = {"intern": -1.2, "junior": -0.35, "middle": 0.10, "senior": 1.12, "lead": 1.98, "principal": 2.90}


def family_meta(fid: str) -> dict[str, Any]:
    """Поля YAML семейства: title, construct, skills, грейд, IRT-параметры, ловушки, описание."""
    from assessment_bank.simulation import stream
    m = FAMILIES[fid]
    a, mode, k, grade = m["arch"], m["mode"], m["k"], m["grade"]
    labels = [f[1] for f in a.F[:k]]
    _src, desc = model_source(a, k, mode)
    rng_t = stream(20261011, "truth", fid)
    shift = float(rng_t.normal(0, 0.5))
    eps = float(rng_t.normal(0, 0.15))
    cut_b = _CUT_B[grade]
    if abs(shift + eps) <= 0.45:
        b = round(max(-3.5, min(3.5, cut_b - 0.45 * (shift + eps))), 2)
        aa = 3.0
        tm = 120
    else:
        b = round(cut_b, 2)
        aa = 1.45
        tm = 240
    if mode == "fwd":
        title = f"{cap(a.title)} — прямой расчёт с учётом: {', '.join(labels)}"
        task = "прямой расчёт по модели"
    else:
        p, (lo, hi, st), sense, lab, unit = a.inv[int(mode[3])]
        word = "наибольший" if sense == "max" else "наименьший"
        title = f"{cap(a.title)} — обратная задача: {word} допустимый вход «{lab}» с учётом: {', '.join(labels)}"
        task = f"обратная задача: {word} вход «{lab}» на сетке с шагом {st}, при котором {a.cond}"
    construct = (f"{cap(a.construct)}. Ступень {k} из 5: взаимодействуют {k} поправочных фактора(ов) "
                 f"({'; '.join(labels)}); {task}.")
    basis = (f"Априорная трудность (не по людям). {cap(a.construct)}; {k} взаимодействующих фактора(ов) "
             f"({', '.join(labels)}), {task}. Грейд {GRADE_RU[grade]} (b {str(b).replace('.', ',')} по числу "
             f"факторов и направлению вопроса: прямой расчёт легче обратной задачи; волна 20.10-S, без калибровки "
             f"панелью). σ 0,3")
    return {"family_id": fid, "title": title, "direction": a.d, "skills": list(a.skills), "grade": grade,
            "b": b, "a": aa, "time": tm, "traps": sorted(desc), "basis": basis, "construct": construct,
            "mod": m["mod"], "desc": f"{GRADE_RU[grade]}: {a.title} — {task}. {k} фактора(ов): {', '.join(labels)}. "
            "Ключ — исполнением модели (точные дроби)" + (", для обратной задачи — ещё и линейным перебором сетки."
                                                           if mode != "fwd" else ".")}


def make(fid: str, n_above: tuple[int, ...] | None = None):
    """generate(seed) семейства. n_above — при каком числе ловушек «выше ключа» подбор параметров выполним
    (посчитано заранее tools/w2010_scale1500.py по пробной выборке и записано в модуль семейства), чтобы не тратить
    тысячи попыток на невыполнимый вариант; место ключа по величине равновероятно среди допустимых."""
    m = FAMILIES[fid]
    a, mode, k = m["arch"], m["mode"], m["k"]
    src, desc = model_source(a, k, mode)
    ns = load_model(src)
    pspecs: dict[str, Any] = dict(a.base[2])
    for f in a.F[:k]:
        pspecs.update(f[4])
    inv = a.inv[int(mode[3])] if mode != "fwd" else None
    xn = inv[0] if inv else None

    def sample(r):
        P = {n: _draw(r, s) for n, s in pspecs.items()}
        if inv:
            y0 = ns["calc"](P)
            del P[xn]
            P["B"] = int(y0) if Fraction(y0).denominator == 1 else float(y0)
        return P

    def accept(P, ns_):
        try:
            ans = ns_["answer"](P)
        except ZeroDivisionError:
            return False
        if ans is None:
            return False
        if inv:
            # brute (линейный перебор) сверяет kit после подбора; здесь — только дешёвые условия
            return a.lim[0] <= P["B"] <= a.lim[1]
        return a.lim[0] <= ans <= a.lim[1]

    def stem(P, ctx):
        txt = [render(a.base[0], P, ctx, xn)] + [render(f[2], P, ctx, xn) for f in a.F[:k]]
        if inv:
            p, (lo, hi, st), sense, lab, unit = inv
            word = "наибольшее" if sense == "max" else "наименьшее"
            txt.append(render(a.budget, P, ctx))
            txt.append(f"\n\nX — {lab}; его перебирают от {unit_text(lo, unit)} до {unit_text(hi, unit)} с шагом "
                       f"{unit_text(st, unit)}. Каково {word} X из этого ряда, при котором {a.cond}?")
        else:
            txt.append("\n\n" + a.q)
        out = " ".join(t for t in txt if not t.startswith("\n\n")) + "".join(t for t in txt if t.startswith("\n\n"))
        return _DOTS.sub(".", out)

    def explain(P, ans, traps):
        v = {n: x for n, x in P.items() if isinstance(x, (int, float))}
        if inv:
            p, (lo, hi, st), sense, lab, unit = inv
            Q = dict(P)
            Q[xn] = ans
            y1 = ns["calc"](Q)
            nb = ans + st if sense == "max" else ans - st
            Q[xn] = nb
            y2 = ns["calc"](Q)
            rel = "≤" if a.need == "le" else "≥"
            bad = ">" if a.need == "le" else "<"
            o = lambda y: unit_text(y, a.out)  # noqa: E731
            return (f"Итог модели монотонен по X, поэтому ищем границу на сетке. При X = {unit_text(ans, unit)} "
                    f"итог — {o(y1)} {rel} {o(P['B'])} (лимит), а при соседнем X = {unit_text(nb, unit)} — "
                    f"{o(y2)} {bad} {o(P['B'])}: ответ — {unit_text(ans, unit)}. Линейный перебор всей сетки даёт "
                    f"то же значение.")
        x = None
        vv = {n: Fraction(str(t)) if isinstance(t, float) else Fraction(t) for n, t in v.items()}
        bexpr = a.base[1]
        x = eval(compile(bexpr, "<b>", "eval"), {"F": Fraction, "min": min, "max": max}, dict(vv))  # noqa: S307
        steps = [f"{a.base[4]}: {_human(bexpr, v, None)} = {nfmt(x)}"]
        for f in a.F[:k]:
            nx = eval(compile(f[3], "<f>", "eval"), {"F": Fraction, "min": min, "max": max},  # noqa: S307
                      {**vv, "x": Fraction(x)})
            steps.append(f"{f[1]}: {_human(f[3], v, x)} = {nfmt(nx)}")
            x = nx
        rword = {"ceil": "округление вверх", "floor": "округление вниз"}.get(a.rnd, "округление")
        return "Шаги модели: " + "; ".join(steps) + f"; {rword} — {ns['fmt'](ans)}."

    def explain_clean(P, ans, traps):
        return _DOTS.sub(".", explain(P, ans, traps))

    def generate(seed: int):
        return numeric_variant(fid, seed, contexts=a.ctx, sample=sample, model=src, stem=stem, explain=explain_clean,
                               accept=accept, rel=a.rel if not inv else min(a.rel, 0.06),
                               abs_min=(10 ** -_nd(a.rnd)) if not inv else inv[1][2],
                               trap_desc=desc, note=NOTE, n_above_choices=tuple(n_above or (0, 1, 2, 3)))
    generate.sample, generate.accept, generate.model = sample, accept, src
    generate.rel = a.rel if not inv else min(a.rel, 0.06)
    generate.abs_min = (10 ** -_nd(a.rnd)) if not inv else inv[1][2]
    return generate


# --------------------------------------------------------------------------- каталоги направлений
import importlib  # noqa: E402

CATALOGS = ("common", "backend", "frontend", "data_ml", "data_eng", "devops", "qa", "security", "mobile", "analyst")
for _d in CATALOGS:
    try:
        importlib.import_module(f"assessment_bank.families._w2010_scale_cat_{_d}")  # регистрирует базовые модели
    except ModuleNotFoundError as _e:
        if _e.name != f"assessment_bank.families._w2010_scale_cat_{_d}":
            raise

for _a in list(ARCHS.values()):
    _register(_a)
