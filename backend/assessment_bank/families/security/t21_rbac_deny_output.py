"""security.authz.t21_rbac_deny_output — predict_output (набор t21, порог Senior): роли с наследованием,
обход графа со стеком и множеством visited, явный запрет сильнее разрешения на любом уровне.

Права роли собираются обходом родителей (несколько родителей, ромб, иногда цикл): разрешения и запреты со всех
посещённых ролей объединяются, итог — `allow - deny`. Ловушки: запрет у предка отменяет разрешение, выданное
самой роли или другому предку; повторный визит пропускается (`continue`), цикл не зацикливает обход; роль без
записи в PARENTS просто не имеет родителей. Печатаются решения по 3–4 парам (роль, действие) — без печати
множеств. Ключ — независимая модель (рекурсивный сбор предков) в генераторе; проверка — исполнение показанного
кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.authz.t21_rbac_deny_output"

CTX = [("CRM", ["viewer", "agent", "lead", "auditor", "manager"], ["read", "edit", "export", "delete"]),
       ("биллинг", ["reader", "clerk", "accountant", "auditor", "cfo"], ["view", "refund", "export", "close"]),
       ("CMS", ["guest", "author", "editor", "reviewer", "chief"], ["read", "write", "publish", "purge"]),
       ("облачная консоль", ["viewer", "dev", "ops", "sec", "owner"], ["list", "deploy", "ssh", "billing"])]


def _ancestors(role: str, parents: dict[str, list[str]]) -> list[str]:
    out: list[str] = []

    def walk(r: str) -> None:
        if r in out:
            return
        out.append(r)
        for p in parents.get(r, []):
            walk(p)
    walk(role)
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, roles, acts = rng.choice(CTX)
    base, mid1, mid2, side, top = roles
    parents = {top: [mid1, mid2], mid1: [base], mid2: [base], side: [base]}
    if rng.random() < 0.5:
        parents[base] = [side]        # цикл base → side → base
        cyc = True
    else:
        cyc = False
    a_read, a_edit, a_exp, a_del = acts
    allow = {base: [a_read], mid1: [a_edit, a_exp], mid2: [a_edit], top: [a_del]}
    deny_role = rng.choice([mid2, side]) if cyc else mid2
    deny = {deny_role: [rng.choice([a_exp, a_edit])]}
    if rng.random() < 0.5:
        deny[side] = deny.get(side, []) + [a_read]
    pairs_pool = [(top, a_exp), (top, a_edit), (top, a_read), (mid1, a_exp), (mid2, a_edit), (side, a_read),
                  (base, a_read), (top, a_del), (mid1, a_del), (mid1, a_edit), (mid1, a_read)]

    def model(role: str, act: str) -> tuple[bool, str]:
        anc = _ancestors(role, parents)
        al = [r for r in anc if act in allow.get(r, [])]
        dn = [r for r in anc if act in deny.get(r, [])]
        if dn:
            return False, f"{role}: запрет у {', '.join(dn)}" + (f" сильнее разрешения у {', '.join(al)}" if al else "")
        if al:
            return True, f"{role}: разрешение у {', '.join(al)}, запретов нет"
        return False, f"{role}: разрешения нет ни у одной роли цепочки ({', '.join(anc)})"

    def kind(role: str, act: str) -> str:
        anc = _ancestors(role, parents)
        al = any(act in allow.get(r, []) for r in anc)
        dn = any(act in deny.get(r, []) for r in anc)
        return "override" if al and dn else ("allow" if al and not dn else "none")

    for _ in range(300):
        pairs = rng.sample(pairs_pool, rng.randint(3, 4))
        ks = [kind(r, a) for r, a in pairs]
        if "override" in ks and "allow" in ks:
            break
    else:
        raise RuntimeError("t21_rbac_deny: не собрались пары")

    def lit(d: dict[str, list[str]]) -> str:
        return "{" + ", ".join(f'"{k}": [{", ".join(chr(34) + v + chr(34) for v in vs)}]' for k, vs in d.items()) + "}"
    code = (f"PARENTS = {lit(parents)}\n"
            f"ALLOW = {lit(allow)}\n"
            f"DENY = {lit(deny)}\n"
            "def perms(role):\n"
            "    allow, deny, seen = set(), set(), set()\n"
            "    stack = [role]\n"
            "    while stack:\n"
            "        r = stack.pop()\n"
            "        if r in seen:\n"
            "            continue\n"
            "        seen.add(r)\n"
            "        allow.update(ALLOW.get(r, []))\n"
            "        deny.update(DENY.get(r, []))\n"
            "        stack.extend(PARENTS.get(r, []))\n"
            "    return allow - deny\n"
            f"for role, action in {[tuple(p) for p in pairs]}:\n"
            '    print(role, action, "allow" if action in perms(role) else "deny")').replace("'", '"')
    lines, trace = [], []
    for role, act in pairs:
        ok, why = model(role, act)
        lines.append(f"{role} {act} {'allow' if ok else 'deny'}")
        trace.append(why)
    out = "\n".join(lines)
    expl = ("perms() обходит роль и всех её предков (стек, повторные роли пропускаются через seen"
            + (", поэтому цикл не мешает" if cyc else "") + "), собирает разрешения и запреты со всех уровней и "
            "возвращает allow − deny: запрет на любом уровне сильнее разрешения. " + "; ".join(trace) +
            f". Вывод: «{out.replace(chr(10), ' / ')}».")
    stem = (f"Ролевая модель доступа ({ctx}): роли наследуют права родительских ролей, а явные запреты задаются "
            "отдельно; программа проверяет несколько пар «роль — действие».")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"pairs": pairs, "cycle": cyc, "deny": deny}, language="python")
