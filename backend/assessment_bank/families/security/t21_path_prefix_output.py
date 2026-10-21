"""security.authz.t21_path_prefix_output — predict_output (набор t21, порог Middle): доступ по префиксу пути —
наивный `path.startswith("/admin")` против нормализованной проверки.

Наивная проверка закрывает всё, что начинается со строки «/admin»: ловит и «/administrator-guide», но пропускает
«/Admin/panel» (регистр) и «/public/../admin/keys» (после нормализации это «/admin/keys»). Исправленная
проверка: `posixpath.normpath(p).lower()`, затем точное равенство префиксу или начало с «префикс + /». Ключ —
независимая модель по видам путей, которые выдаёт генератор (без posixpath); проверка — исполнение показанного
кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.authz.t21_path_prefix_output"

CTX = ["панель администратора", "внутренний портал", "служебный API", "биллинг", "консоль эксплуатации",
       "отладочные страницы"]
PREFIX = ["admin", "internal", "billing", "ops", "staff", "debug"]
LEAF = ["users", "keys", "panel", "export", "logs", "config", "tokens"]
PUB = ["public", "static", "docs", "help", "assets"]
NAMES = [("paths", "p", "naive", "n", "fixed"), ("urls", "path", "old", "norm", "new"),
         ("requests", "p", "v1", "clean", "v2")]


def _make(rng, kind: str, pre: str) -> tuple[str, str, str, str]:
    """(путь, наивное решение, исправленное, пояснение) — по виду пути, без вычисления normpath."""
    leaf, pub = rng.choice(LEAF), rng.choice(PUB)
    if kind == "plain":
        return f"/{pre}/{leaf}", "deny", "deny", "обычный закрытый путь"
    if kind == "longer":
        p = f"/{pre}{rng.choice(['istrator-guide', '-old', 's', '_v2', '-faq', 'board'])}"
        return p, "deny", "allow", "строка начинается с префикса, но это другой сегмент пути"
    if kind == "case":
        p = f"/{rng.choice([pre.capitalize(), pre.upper()])}/{leaf}"
        return p, "allow", "deny", "startswith чувствителен к регистру, lower() это исправляет"
    if kind == "dotdot":
        p = f"/{pub}/../{pre}/{leaf}"
        return p, "allow", "deny", f"normpath убирает «{pub}/..» и получается /{pre}/{leaf}"
    if kind == "dot":
        p = f"/./{pre}/{leaf}"
        return p, "allow", "deny", f"normpath убирает «./» — получается /{pre}/{leaf}"
    if kind == "escape":
        p = f"/{pre}/../{pub}/{leaf}"
        return p, "deny", "allow", f"после нормализации это /{pub}/{leaf}"
    if kind == "slash":
        p = f"/{pre}//{leaf}/"
        return p, "deny", "deny", f"normpath схлопывает «//» и убирает «/» в конце: /{pre}/{leaf}"
    p = f"/{pub}/{leaf}"
    return p, "allow", "allow", "открытый путь"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    pre = rng.choice(PREFIX)
    lv, iv, av, nv, bv = rng.choice(NAMES)
    tricky = rng.sample(["longer", "case", "dotdot", "dot", "escape", "slash"], rng.randint(3, 4))
    kinds = tricky + [rng.choice(["plain", "public"])]
    rng.shuffle(kinds)
    rows = []
    seen = set()
    for kind in kinds:
        for _ in range(20):
            row = _make(rng, kind, pre)
            if row[0] not in seen:
                break
        seen.add(row[0])
        rows.append(row)
    lit = ", ".join(f'"{p}"' for p, *_ in rows)
    code = ("import posixpath\n"
            f"{lv} = [{lit}]\n"
            f"for {iv} in {lv}:\n"
            f'    {av} = "deny" if {iv}.startswith("/{pre}") else "allow"\n'
            f"    {nv} = posixpath.normpath({iv}).lower()\n"
            f'    {bv} = "deny" if {nv} == "/{pre}" or {nv}.startswith("/{pre}/") else "allow"\n'
            f"    print({av}, {bv})")
    out = "\n".join(f"{a} {b}" for _p, a, b, _w in rows)
    trace = "; ".join(f"{p} → {a} {b} ({w})" for p, a, b, w in rows)
    expl = (f"Наивная проверка сравнивает начало строки с «/{pre}» с учётом регистра и без нормализации; "
            f"исправленная сначала применяет normpath и lower(), затем требует ровно «/{pre}» или «/{pre}/…». "
            f"{trace}. Вывод: «{out.replace(chr(10), ' / ')}».")
    stem = (f"Контроль доступа ({ctx}): программа сравнивает старую проверку закрытого раздела по префиксу пути "
            "с исправленной.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"prefix": pre, "kinds": kinds}, language="python")
