"""Волна 20.10-S («масштабирование банка до 1 500+ семейств»): определения моделей параметрических семейств.

Как устроено (и почему каждое семейство — честное, со своей исполняемой моделью):

* **Базовая модель** (:class:`Arch`) — реальный инженерный/продуктовый расчёт направления (пул соединений, кворум,
  бюджет ошибок SLO, лаг консьюмеров Kafka, размер индекса, батчинг на GPU, воронка и т. д.): базовая формула и
  пять поправочных факторов (пик, ретраи, запас утилизации, репликация, накладные расходы …). Каждый фактор — одно
  предложение условия, один шаг модели и ловушки (типичные ошибки: «фактор не учтён», «учтён дважды», «перепутаны
  единицы измерения или направление округления»).
* **Семейство** = базовая модель × ступень сложности (сколько факторов взаимодействуют: 2…5) × направление вопроса:
  прямой расчёт (``fwd``) или обратная задача по одному из двух входов (``solve_<параметр>``: наибольшее/наименьшее
  значение входа на сетке, при котором выполняется лимит). Расчётные задачи волны размечены максимум до Senior
  (Стажёр, Junior, Middle, Senior); старшие грейды (Lead, Principal) в банке представлены содержательными кодовыми,
  архитектурными и инцидентными семействами.
* **Генерация** — :func:`assessment_bank.families._w2010_kit.numeric_variant`: 5 вариантов ответа (A–E), ключ =
  ``fmt(answer(P))`` исполнением модели; место ключа по величине и по букве стратифицировано равномерно (по 20 % на
  каждую из 5 позиций); в обратных задачах лимит B строго отделён от ответа и от значения модели при ответе.
* Вся арифметика модели — точные дроби (:class:`fractions.Fraction`): округление вверх/вниз без ошибок плавающей
  точки.
"""
from __future__ import annotations

import math
import re
import zlib
from fractions import Fraction
from typing import Any

from assessment_bank.families._w2010_kit import load_model, num, numeric_variant
from assessment_bank.gen_utils import plural

# (режим, число факторов, целевой грейд YAML, базовое b): расчётные задачи — максимум до Senior (исправление B4)
LEVELS: list[tuple[str, int, str, float]] = [
    ("fwd", 2, "intern", -1.30),
    ("fwd", 3, "junior", -0.60),
    ("fwd", 4, "middle", 0.25),
    ("fwd", 5, "senior", 1.05),
    ("inv0", 2, "junior", -0.30),
    ("inv0", 3, "middle", 0.45),
    ("inv0", 4, "senior", 1.22),
    ("inv0", 5, "senior", 1.52),
    ("inv1", 2, "middle", 0.10),
    ("inv1", 3, "senior", 1.36),
    ("inv1", 4, "middle", 0.68),
    ("inv1", 5, "senior", 1.68),
]
# Слаг в family_id сохранён для обратной совместимости имён модулей s15_*.py и ссылок
_SLUG_GRADE: dict[tuple[str, int], str] = {
    ("fwd", 2): "intern", ("fwd", 3): "junior", ("fwd", 4): "middle", ("fwd", 5): "senior",
    ("inv0", 2): "junior", ("inv0", 3): "middle", ("inv0", 4): "senior", ("inv0", 5): "lead",
    ("inv1", 2): "middle", ("inv1", 3): "senior", ("inv1", 4): "lead", ("inv1", 5): "principal",
}
TIME_BY_LEVEL: dict[tuple[str, int], int] = {
    ("fwd", 2): 150, ("fwd", 3): 180, ("fwd", 4): 240, ("fwd", 5): 270,
    ("inv0", 2): 210, ("inv0", 3): 240, ("inv0", 4): 300, ("inv0", 5): 330,
    ("inv1", 2): 210, ("inv1", 3): 300, ("inv1", 4): 270, ("inv1", 5): 360,
}
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

# Резервные дистракторы («_fb_*») — НЕ модели ошибок: это контрольные значения рядом с ответом, они нужны, когда
# у модели меньше четырёх различимых ловушек при этих числах. Подписаны честно (проверка 20.10: прежние подписи
# «двоичная приставка», «удвоение бюджета» не соответствовали тому, как значения считались).
_FB_FWD_DESC = {f"_fb_{d}{i}": "контрольное значение того же порядка рядом с ответом (не связано с конкретной ошибкой)"
                for d in ("up", "dn") for i in range(1, 7)}
_FB_INV_DESC = {f"_fb_{d}{i}{t}": "соседнее значение того же ряда X (контрольное, не связано с конкретной ошибкой)"
                for d in ("up", "dn") for i in range(1, 7) for t in ("", "s")}


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
    """Базовая модель направления."""

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
    nd_val = _nd(a.rnd)
    if mode == "fwd":
        desc.update(_FB_FWD_DESC)
        parts.append(f"\nUNIT = {a.out!r}\nND = {nd_val}\n")
        parts.append('''
def answer(P):
    return calc(P)

def _safe(f, *a):
    try:
        return f(*a)
    except ZeroDivisionError:
        return None

def traps(P):
    out = {t: _safe(calc, P, t) for t in SWAPS}
    ans = _safe(calc, P)
    if ans is not None:
        fv = _f(ans)
        st = F(1, 10 ** ND) if ND else F(1)
        for i, (nm, dm) in enumerate(((108, 100), (118, 100), (129, 100), (142, 100), (157, 100), (174, 100)), 1):
            out[f"_fb_up{i}"] = rnd(fv * F(nm, dm)) + i * st
        for i, (nm, dm) in enumerate(((92, 100), (83, 100), (74, 100), (65, 100), (55, 100), (45, 100)), 1):
            v = rnd(fv * F(nm, dm)) - i * st
            if v > 0:
                out[f"_fb_dn{i}"] = v
    return out
''')
    else:
        desc.update(_FB_INV_DESC)
        p, (lo, hi, st), sense, _lab, unit = a.inv[int(mode[3])]
        cmp = "<=" if a.need == "le" else ">="
        parts.append(f'''
XN = {p!r}
STEP = {st}
LO = {lo}
HI = {hi}
GRID = list(range({lo}, {hi} + 1, {st}))
# Ловушки решаются на ТОМ ЖЕ ряду X, что назван в условии (проверка 20.10: прежняя TRAP_GRID до 4·hi со сдвигом
# по фазе давала дистракторы вне ряда, и ключ угадывался исключением в 27,5 % обратных вариантов).
TRAP_GRID = GRID
SENSE = {sense!r}

def ok(P, X, swap=None):
    Q = dict(P)
    Q[XN] = X
    return calc(Q, swap) {cmp} _f(P["B"])

def _solve_on(grid, P, swap=None):
    good = [ok(P, grid[0], swap), ok(P, grid[-1], swap)]
    if SENSE == "max":
        if not good[0] or good[1]:
            return None
        lo_i, hi_i = 0, len(grid) - 1
        while hi_i - lo_i > 1:
            mid = (lo_i + hi_i) // 2
            lo_i, hi_i = (mid, hi_i) if ok(P, grid[mid], swap) else (lo_i, mid)
        return grid[lo_i]
    if good[0] or not good[1]:
        return None
    lo_i, hi_i = 0, len(grid) - 1
    while hi_i - lo_i > 1:
        mid = (lo_i + hi_i) // 2
        lo_i, hi_i = (lo_i, mid) if ok(P, grid[mid], swap) else (mid, hi_i)
    return grid[hi_i]

def solve(P, swap=None):
    return _solve_on(GRID if swap is None else TRAP_GRID, P, swap)

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
    except ZeroDivisionError:
        return None

def traps(P):
    out = {{t: _safe(solve, P, t) for t in SWAPS}}
    ans = _safe(solve, P)
    if ans is not None:
        for i, pct_m in enumerate((9, 18, 28, 39, 52, 66), 1):
            delta = max(i * STEP, int((ans * pct_m // 100 // STEP) * STEP))
            for nm, v in ((f"_fb_up{{i}}", ans + delta), (f"_fb_dn{{i}}", ans - delta),
                          (f"_fb_up{{i}}s", ans + i * STEP), (f"_fb_dn{{i}}s", ans - i * STEP)):
                if LO <= v <= HI and (v - LO) % STEP == 0:
                    out.setdefault(nm, v)
    return {{k: v for k, v in out.items() if v is None or (LO <= v <= HI and (v - LO) % STEP == 0)}}
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
def _fid(a: Arch, mode: str, k: int, _grade: str) -> tuple[str, str, str]:
    mname = "fwd" if mode == "fwd" else "solve_" + a.inv[int(mode[3])][0].lower()
    gslug = _SLUG_GRADE[(mode, k)]
    fid = f"{a.d}.{a.key}.{gslug}_{mname}_k{k}"
    mod = f"s15_{a.key}_{mname}_k{k}"
    return fid, mod, mname


def _register(a: Arch) -> None:
    for mode, k, grade, b0 in LEVELS:
        fid, mod, mname = _fid(a, mode, k, grade)
        FAMILIES[fid] = {
            "arch": a, "mode": mode, "k": k, "grade": grade, "b0": b0,
            "mod": mod, "mname": mname, "time": TIME_BY_LEVEL[(mode, k)],
        }


def family_meta(fid: str) -> dict[str, Any]:
    """Поля YAML семейства: честные априорные параметры a = 1,0, b от порога грейда по содержательной сложности."""
    m = FAMILIES[fid]
    a, mode, k, grade, b0, tm = m["arch"], m["mode"], m["k"], m["grade"], m["b0"], m["time"]
    labels = [f[1] for f in a.F[:k]]
    _src, desc = model_source(a, k, mode)
    # Детерминированный содержательный сдвиг [-0.10, +0.10], полностью отвязанный от stream(20261011, "truth")
    h = zlib.crc32(f"bank_prior_v2:{fid}".encode("utf-8"))
    offset = ((h % 21) - 10) / 100.0
    b = round(b0 + offset, 2)
    aa = 1.0
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
    basis = (f"Априорная оценка до калибровки на людях (a = 1,0, σ = 0,3). {cap(a.construct)}; "
             f"{k} взаимодействующих фактора(ов) ({', '.join(labels)}), {task}. "
             f"Целевой грейд {GRADE_RU[grade]} (b = {str(b).replace('.', ',')} по числу факторов и типу расчёта).")
    return {
        "family_id": fid, "title": title, "direction": a.d, "skills": list(a.skills), "grade": grade,
        "b": b, "a": aa, "time": tm, "traps": sorted(desc), "basis": basis, "construct": construct,
        "mod": m["mod"], "n_options": 5,
        "desc": (f"{GRADE_RU[grade]}: {a.title} — {task}. {k} фактора(ов): {', '.join(labels)}. "
                 "Ключ — исполнением модели (точные дроби)"
                 + (", для обратной задачи — ещё и линейным перебором сетки." if mode != "fwd" else ".")),
    }


def make(fid: str, n_above: tuple[int, ...] | None = None):
    """Ленивая сборка генератора варианта семейства (5 вариантов ответа, стратификация места ключа по величине)."""
    state: dict[str, Any] = {}

    def _init() -> None:
        if state:
            return
        m = FAMILIES[fid]
        a, mode, k, grade = m["arch"], m["mode"], m["k"], m["grade"]
        src, desc = model_source(a, k, mode)
        ns = load_model(src)
        pspecs: dict[str, Any] = dict(a.base[2])
        for f in a.F[:k]:
            pspecs.update(f[4])
        inv = a.inv[int(mode[3])] if mode != "fwd" else None
        xn = inv[0] if inv else None
        state.update(a=a, mode=mode, k=k, grade=grade, src=src, desc=desc, ns=ns, pspecs=pspecs, inv=inv, xn=xn)

    def sample(r):
        _init()
        a, inv, xn, ns, pspecs = state["a"], state["inv"], state["xn"], state["ns"], state["pspecs"]
        P = {n: _draw(r, s) for n, s in pspecs.items()}
        if inv:
            p, (lo, hi, st), sense, _lab, _unit = inv
            lo_draw = max(lo + st, 5 * st)
            hi_draw = hi - st
            if lo_draw <= hi_draw:
                x0 = r.randrange(lo_draw, hi_draw + 1, st)
            else:
                x0 = r.randrange(lo + st, hi, st) if hi - lo >= 2 * st else lo
            P[xn] = x0
            y0 = ns["calc"](P)
            step_dir = st if sense == "max" else -st
            while lo_draw <= x0 + step_dir <= hi_draw and ns["calc"]({**P, xn: x0 + step_dir}) == y0:
                x0 += step_dir
            P[xn] = x0
            y0 = ns["calc"](P)
            nb = x0 + step_dir
            y_nb = ns["calc"]({**P, xn: nb})
            del P[xn]
            f0, f1 = float(y0), float(y_nb)
            low_y, high_y = min(f0, f1), max(f0, f1)
            gap = high_y - low_y
            frac = r.choice((0.32, 0.44, 0.56, 0.68))
            if gap >= 2.0 and a.rnd in ("ceil", "floor"):
                b_val: int | float = int(math.floor(low_y)) + max(1, min(int(math.ceil(high_y)) - int(math.floor(low_y)) - 1, int(round(gap * frac))))
                if b_val == x0 or b_val == y0 or b_val == y_nb:
                    alt = b_val + 1 if b_val + 1 < high_y else (b_val - 1 if b_val - 1 > low_y else round(low_y + gap * 0.5, 1))
                    b_val = alt
            elif gap > 0:
                b_val = round(low_y + gap * frac, 2)
                if b_val <= low_y or b_val >= high_y or b_val == x0:
                    b_val = round((low_y + high_y) / 2.0, 3)
            else:
                b_val = float(y0) + (0.5 if a.need == "le" else -0.5)
            P["B"] = b_val
        return P

    def accept(P, ns_):
        _init()
        a, inv, xn = state["a"], state["inv"], state["xn"]
        try:
            ans = ns_["answer"](P)
        except ZeroDivisionError:
            return False
        if ans is None:
            return False
        if inv:
            _p, (lo, hi, st), sense, _lab, _unit = inv
            if not (lo + st <= ans <= hi - st):
                return False
            if ans < 5 * st and hi >= 7 * st:
                return False
            step_dir = st if sense == "max" else -st
            if not ns_["ok"](P, ans) or ns_["ok"](P, ans + step_dir):
                return False
            b_val = P["B"]
            if b_val == ans or nfmt(b_val) == nfmt(ans):
                return False
            y_at_ans = ns_["calc"]({**P, xn: ans})
            if b_val == y_at_ans or nfmt(b_val) == nfmt(y_at_ans) or abs(float(b_val) - float(y_at_ans)) < 1e-6:
                return False
            return a.lim[0] <= b_val <= a.lim[1]
        if a.rnd in ("ceil", "floor") and ans < 6:
            return False
        return a.lim[0] <= ans <= a.lim[1]

    def stem(P, ctx):
        _init()
        a, k, grade, inv, xn = state["a"], state["k"], state["grade"], state["inv"], state["xn"]
        labels = ", ".join(f[1] for f in a.F[:k])
        if inv:
            _p, (lo, hi, st), sense, lab, unit = inv
            word = "наибольшее" if sense == "max" else "наименьшее"
            header = f"Обратный расчёт входа «{lab}» с учётом факторов: {labels}."
        else:
            header = f"Прямой расчёт показателя «{a.base[4]}» с учётом факторов: {labels}."
        txt = [header, render(a.base[0], P, ctx, xn)] + [render(f[2], P, ctx, xn) for f in a.F[:k]]
        if inv:
            _p, (lo, hi, st), sense, lab, unit = inv
            word = "наибольшее" if sense == "max" else "наименьшее"
            txt.append(render(a.budget, P, ctx))
            # Проверка вслепую 21.10: модель округляет итог до сравнения с лимитом, а в обратных задачах это не
            # было сказано — решатель без округления находил соседнее X. Теперь правило названо, ключ прежний.
            if a.rnd == "ceil":
                txt.append("Итог считается в целых единицах (округление вверх) и сравнивается с лимитом.")
            elif a.rnd == "floor":
                txt.append("Итог считается в целых единицах (округление вниз) и сравнивается с лимитом.")
            elif _nd(a.rnd) > 0:
                txt.append(f"Итог округляется до {_nd(a.rnd)} знака(ов) после запятой и сравнивается с лимитом.")
            txt.append(f"\n\nX — {lab}; его перебирают от {unit_text(lo, unit)} до {unit_text(hi, unit)} с шагом "
                       f"{unit_text(st, unit)}. Каково {word} X из этого ряда, при котором {a.cond}?")
        else:
            r_hint = (
                " (Итог округлите вверх до целого.)"
                if a.rnd == "ceil"
                else (" (Итог округлите вниз до целого.)" if a.rnd == "floor" else "")
            )
            txt.append("\n\n" + a.q + r_hint)
        out = " ".join(t for t in txt if not t.startswith("\n\n")) + "".join(t for t in txt if t.startswith("\n\n"))
        return _DOTS.sub(".", out)

    def explain(P, ans, traps):
        _init()
        a, k, inv, xn, ns = state["a"], state["k"], state["inv"], state["xn"], state["ns"]
        v = {n: x for n, x in P.items() if isinstance(x, (int, float))}
        if inv:
            _p, (_lo, _hi, st), sense, _lab, unit = inv
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
        _init()
        a, inv, src, desc, ns = state["a"], state["inv"], state["src"], state["desc"], state["ns"]
        return numeric_variant(
            fid, seed,
            contexts=a.ctx, sample=sample, model=src, stem=stem, explain=explain_clean,
            accept=accept, rel=min(a.rel, 0.05) if not inv else min(a.rel, 0.04),
            abs_min=(10 ** -_nd(a.rnd)) if not inv else inv[1][2],
            trap_desc=desc, note=NOTE,
            n_above_choices=(0, 1, 2, 3, 4),
            n_distractors=4,
            ns_cached=ns,
            stratified=True,
        )

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
