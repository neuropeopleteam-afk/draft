"""security.lead.authz_policy_fix — choose_fix (Lead): проверка доступа к документам в многоорганизационной системе.

Показан модуль авторизации (~20 строк) с дефектом «делегирование не проверяет организацию»: пользователь, переведённый
в другую организацию, продолжает читать документы по старому делегированию. Варианты — четыре замены ``can`` в другом
стиле, чем показанный код; каждый дистрактор исправляет показанный дефект и нарушает правила политики — схема 2×2 из двух правил
пула ниже (нарушено одно, другое, оба; ни один вариант не «центральный»):

* ``owner_before_lock`` — владелец проверяется раньше блокировки (юридическое удержание не действует на владельца);
* ``grantor_unchecked`` — делегирование действует и после смены владельца (проверка «выдал не сам себе» вместо
  «выдал текущий владелец»);
* ``expiry_unchecked`` — срок делегирования не проверяется (проверяется лишь корректность окна).

Ключ — исполнение всех замен в составе модуля на девяти сценариях: верная проходит все, остальные и показанный код
падают хотя бы на одном.
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import factorial_distractors, module_choose_fix
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.lead.authz_policy_fix"

CONTEXTS = ["электронный документооборот", "юридический сервис", "кадровый портал", "сервис договоров",
            "медицинский архив", "бухгалтерия холдинга", "проектный портал", "закупочная площадка"]
NAME_POOLS = {
    "U": ["user", "actor", "subject", "caller", "member"],
    "D": ["doc", "resource", "record", "item", "obj"],
    "A": ["action", "op", "verb", "operation", "act"],
    "N": ["now", "at", "ts", "moment", "clock"],
    "G": ["g", "grant", "deleg", "share", "perm"],
    "H": ["holds", "locked", "frozen", "blocked", "legal_hold"],
}
ROLESETS = [(("viewer", "editor", "admin"), ("read", "write", "share")),
            (("reader", "author", "manager"), ("view", "edit", "delegate")),
            (("guest", "member", "owner_admin"), ("open", "update", "grant")),
            (("observer", "contributor", "lead"), ("get", "put", "invite"))]

HEAD = '''ROLE_RANK = {@R1@: 1, @R2@: 2, @R3@: 3}
ACTION_NEED = {@A1@: 1, @A2@: 2, @A3@: 3}


def active(@G@, @N@):
    """Делегирование действует с start включительно до end не включительно."""
    return @G@["start"] <= @N@ < @G@["end"]'''

AUDIT = '''def audit(@U@, @D@, @A@, allowed):
    """Запись журнала доступа (без содержимого документа)."""
    return {"user": @U@["id"], "doc": @D@["id"], "action": @A@, "allowed": bool(allowed)}'''

BUGGY = '''def can(@U@, @D@, @A@, @N@):
    need = ACTION_NEED[@A@]
    if @A@ in @D@.get("@H@", ()):
        return False
    if @U@["id"] == @D@["owner"]:
        return @U@["tenant"] == @D@["tenant"]
    for @G@ in @D@.get("grants", []):
        if @G@["to"] == @U@["id"] and @G@["from"] == @D@["owner"] and @G@["action"] == @A@ and active(@G@, @N@):
            return True
    return @U@["tenant"] == @D@["tenant"] and ROLE_RANK.get(@U@["role"], 0) >= need'''

CORRECT = '''def can(@U@, @D@, @A@, @N@):
    if @U@["tenant"] != @D@["tenant"]:
        return False
    if @A@ in @D@.get("@H@", ()):
        return False
    if @U@["id"] == @D@["owner"]:
        return True
    if ROLE_RANK.get(@U@["role"], 0) >= ACTION_NEED[@A@]:
        return True
    return any(@G@["to"] == @U@["id"] and @G@["from"] == @D@["owner"] and @G@["action"] == @A@
               and active(@G@, @N@) for @G@ in @D@.get("grants", []))'''

MUTATIONS = {  # правило → (фрагмент верного текста, замена); дистракторы — по схеме 2×2
    "owner_before_lock": ('''    if @A@ in @D@.get("@H@", ()):
        return False
    if @U@["id"] == @D@["owner"]:
        return True''', '''    if @U@["id"] == @D@["owner"]:
        return True
    if @A@ in @D@.get("@H@", ()):
        return False'''),
    "grantor_unchecked": ('@G@["from"] == @D@["owner"]', '@G@["from"] != @U@["id"]'),
    "expiry_unchecked": ("and active(@G@, @N@)", 'and @G@["end"] > @G@["start"]'),
}
DISTRACTORS = {k: CORRECT.replace(*v) for k, v in MUTATIONS.items()}
assert all(d != CORRECT for d in DISTRACTORS.values())

WHY = {
    "owner_before_lock": "владелец проверяется раньше блокировки — во время юридического удержания владелец может "
                         "изменить документ",
    "grantor_unchecked": "делегирование, выданное прежним владельцем, продолжает действовать после передачи "
                         "документа — права не отзываются вместе с владением",
    "expiry_unchecked": "проверяется только корректность окна, а не текущее время — истёкшее делегирование "
                        "действует бессрочно",
}


def _rename(code: str, names: dict[str, str]) -> str:
    for k, v in names.items():
        code = code.replace(f"@{k}@", v)
    if "@" in code:
        raise ValueError("не заменена метка имени")
    return code


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    names = {k: rng.choice(v) for k, v in NAME_POOLS.items()}
    roles, acts = rng.choice(ROLESETS)
    names.update({f"R{i + 1}": repr(r) for i, r in enumerate(roles)})
    names.update({f"A{i + 1}": repr(a) for i, a in enumerate(acts)})
    r_lo, r_mid, _r_hi = roles
    a_lo, a_mid, a_hi = acts
    t1, t2 = rng.sample(["t-north", "t-south", "t-east", "t-west", "t-retail", "t-bank", "t-labs"], 2)
    uid = lambda: f"u{rng.randint(100, 999)}"  # noqa: E731
    owner, alice, bob, prev = uid(), uid(), uid(), uid()
    while len({owner, alice, bob, prev}) < 4:
        owner, alice, bob, prev = uid(), uid(), uid(), uid()
    start, end = rng.choice([(100, 200), (1000, 1600), (50, 90), (7200, 10800)])
    mid = (start + end) // 2
    H = names["H"]

    def docd(grants=(), hold=(), own=owner):
        return {"id": f"d{rng.randint(10, 99)}", "tenant": t1, "owner": own, H: list(hold),
                "grants": [dict(g) for g in grants]}

    def user(i, tenant=t1, role=r_lo):
        return {"id": i, "tenant": tenant, "role": role}

    g_ok = {"from": owner, "to": alice, "action": a_mid, "start": start, "end": end}
    g_prev = {"from": prev, "to": alice, "action": a_mid, "start": start, "end": end}
    scen = [  # (имя, user, doc, action, now, ожидаемое)
        ("moved_to_other_tenant", user(alice, t2), docd([g_ok]), a_mid, mid, False),
        ("owner_under_hold", user(owner, role=r_mid), docd(hold=[a_mid]), a_mid, mid, False),
        ("grant_from_previous_owner", user(alice), docd([g_prev]), a_mid, mid, False),
        ("expired_grant", user(alice), docd([g_ok]), a_mid, end, False),
        ("valid_grant", user(alice), docd([g_ok]), a_mid, start, True),
        ("owner_share", user(owner), docd(), a_hi, mid, True),
        ("role_enough", user(bob, role=r_mid), docd(), a_mid, mid, True),
        ("role_too_low", user(bob, role=r_lo), docd(), a_mid, mid, False),
        ("hold_other_action", user(bob, role=r_lo), docd(hold=[a_mid]), a_lo, mid, True),
    ]
    rng.shuffle(scen)
    test_body = "\n".join(f"assert can({u!r}, {d!r}, {a!r}, {n!r}) is {exp!r}, {nm!r}"
                          for nm, u, d, a, n, exp in scen)
    blocks = [_rename(HEAD, names), "{FN}", _rename(AUDIT, names)]
    if rng.random() < 0.5:
        blocks = [blocks[0], blocks[2], "{FN}"]
    module = "\n\n\n".join(blocks)
    buggy, correct = _rename(BUGGY, names), _rename(CORRECT, names)
    dis, kinds = factorial_distractors(CORRECT, MUTATIONS, rng)
    dis = [_rename(d, names) for d in dis]
    policy = [
        "документ доступен только пользователям той же организации (`tenant`), и делегирование эту границу не "
        "расширяет",
        f"блокировка документа (`{H}` — список действий, например на время юридического удержания) запрещает эти "
        "действия всем, включая владельца",
        "владельцу доступны все действия",
        f"роль в организации разрешает действие, если её ранг не ниже требуемого (`{r_mid}` — до `{a_mid}`)",
        "делегирование выдаётся текущим владельцем на одно действие и действует с `start` включительно до `end` "
        "не включительно; при передаче документа делегирования прежнего владельца теряют силу",
    ]
    stem = (f"{ctx.capitalize()}: функция `can` решает, можно ли пользователю выполнить действие с документом. "
            "Политика: " + "; ".join(f"({i}) {p}" for i, p in enumerate(policy, 1)) +
            ". Инцидент: сотрудника перевели в дочернюю организацию (другой `tenant`), а он ещё неделю открывал "
            "документы прежней по старому делегированию. Какая замена `can` выполняет политику целиком?")
    why = ("Верная замена сначала отсекает чужую организацию (для всех путей, включая делегирование), затем "
           "применяет блокировку ко всем, включая владельца, и принимает делегирование только от текущего "
           "владельца в окне [start, end). Остальные варианты закрывают межорганизационный доступ, но: "
           + "; ".join(WHY[k] for k in kinds[:2]) + "; четвёртый вариант нарушает оба этих правила" + ". Ревью авторизации — по таблице политики, а не по одной строке "
           "инцидента: тесты на каждое правило и на их порядок.")
    return module_choose_fix(
        FAMILY_ID, seed, rng, stem=stem, module=module, buggy_fn=buggy, correct_fn=correct, distractors=dis,
        tests=test_body, context=ctx, defect="delegation_crosses_tenant", why=why, label="Заменить can на:",
        params={"roles": list(roles), "actions": list(acts), "window": [start, end], "distractors": kinds})
