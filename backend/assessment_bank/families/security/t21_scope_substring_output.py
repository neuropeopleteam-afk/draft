"""security.authz.t21_scope_substring_output — predict_output (набор t21, порог Junior): проверка прав токена
двумя генераторами списка — `in` по СТРОКЕ (подстрока) и `in` по списку из `split()` (точное совпадение).

Права токена хранятся одной строкой через пробел (`"orders:read files:read_all"`). Программа ищет недостающие
права двумя способами: `[s for s in required if s not in token_scope]` и `[s for s in required if s not in
token_scope.split()]`, печатает `",".join(missing) or "ok"`. Ловушки (две конструкции вместе): `in` по строке
ищет подстроку — «read», «orders», «files:read» находятся внутри «orders:read» / «files:read_all», хотя такого
права у токена нет; по списку после split() нужно точное совпадение; пустой список даёт пустую строку, и `or`
подставляет «ok». Ключ — независимая модель в генераторе; проверка — исполнение показанного кода в песочнице
Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.authz.t21_scope_substring_output"

CTX = ["сервис заказов", "кабинет партнёра", "внутренний биллинг", "API отчётов", "файловое хранилище",
       "сервис платежей", "панель модерации"]
RES = ["orders", "profile", "users", "billing", "reports", "audit", "files", "payments", "invoices"]
ACT = ["read", "write", "delete", "export"]
ABSENT = ["admin", "root", "superuser", "staff", "sudo"]
NAMES = [("token_scope", "required", "missing_str", "missing_list", "s"),
         ("granted", "needed", "gap1", "gap2", "x"),
         ("scope", "need", "miss_text", "miss_split", "r")]


def _is_sub(sub: str, text: str) -> bool:
    """Подстрока: перебор позиций (независимо от оператора in показанного кода)."""
    return any(text[i:i + len(sub)] == sub for i in range(len(text) - len(sub) + 1))


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    tv, rv, av, bv, iv = rng.choice(NAMES)
    for _ in range(500):
        res = rng.sample(RES, rng.randint(2, 3))
        granted = [f"{r}:{rng.choice(ACT)}" for r in res]
        if rng.random() < 0.5:
            i = rng.randrange(len(granted))
            granted[i] += "_all"
        scope = " ".join(granted)
        toks = scope.split(" ")
        required: list[str] = []
        n_abs = rng.choice([0, 0, 1, 1, 1, 2])
        if n_abs == 0 or rng.random() < 0.7:
            required.append(rng.choice(toks))
        subs = set()
        for g in toks:
            r, a = g.split(":")
            subs.update([r, a.replace("_all", "")])
            if a.endswith("_all"):
                subs.add(g[:-4])
        subs = sorted(s for s in subs if s not in toks)
        prefix = [g[:-4] for g in toks if g.endswith("_all") and g[:-4] not in required]
        k_sub = 2 if n_abs == 0 else rng.randint(1, 2)
        if prefix and rng.random() < 0.6:
            picked = [prefix[0]] + rng.sample([s for s in subs if s != prefix[0]], k_sub - 1)
        else:
            picked = rng.sample(subs, min(len(subs), k_sub))
        required += picked
        pool_abs = [f"{r}:{a}" for r in RES for a in ACT] + ABSENT
        pool_abs = [p for p in pool_abs if not _is_sub(p, scope)]
        required += rng.sample(pool_abs, n_abs)
        if not 3 <= len(required) <= 4 or len(set(required)) != len(required):
            continue
        rng.shuffle(required)
        break
    else:
        raise RuntimeError("t21_scope_substring: не собрался набор прав")
    req_lit = ", ".join(f'"{s}"' for s in required)
    code = (f'{tv} = "{scope}"\n'
            f"{rv} = [{req_lit}]\n"
            f"{av} = [{iv} for {iv} in {rv} if {iv} not in {tv}]\n"
            f"{bv} = [{iv} for {iv} in {rv} if {iv} not in {tv}.split()]\n"
            f'print(",".join({av}) or "ok")\n'
            f'print(",".join({bv}) or "ok")')
    loose = [s for s in required if not _is_sub(s, scope)]
    strict = [s for s in required if s not in toks]
    l1 = ",".join(loose) or "ok"
    l2 = ",".join(strict) or "ok"
    out = f"{l1}\n{l2}"
    sub_only = [s for s in required if _is_sub(s, scope) and s not in toks]
    exact = [s for s in required if s in toks]
    notes = []
    if exact:
        notes.append(f"{', '.join('«' + s + '»' for s in exact)} — точное право токена, его находят оба способа")
    notes.append(f"{', '.join('«' + s + '»' for s in sub_only)} — только подстрока строки прав: in по строке "
                 "находит, а в списке после split() такого элемента нет")
    absent = [s for s in required if not _is_sub(s, scope)]
    if absent:
        notes.append(f"{', '.join('«' + s + '»' for s in absent)} — нет даже как подстроки, не хватает в обоих "
                     "списках")
    expl = (f"Права токена после split(): {', '.join(toks)}. " + "; ".join(notes) + ". "
            f"Первая строка — {av}: {'пусто, поэтому or подставляет «ok»' if not loose else l1}; вторая — {bv}: "
            f"{'пусто, поэтому «ok»' if not strict else l2}. Вывод: «{l1}», «{l2}».")
    stem = (f"Шлюз API ({ctx}) сверяет права из токена доступа с правами, которые нужны вызываемому методу, "
            "двумя способами.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"scope": scope, "required": required}, language="python")
