"""security.token.t21_aud_type_output — predict_output (набор t21, порог Senior): проверка claim `aud` оператором
`in`, смысл которого зависит от типа, и `exp` с допуском `leeway`.

Функция проверки токена: `if AUD not in tok["aud"]` — для строки это поиск ПОДСТРОКИ («api» находится в
«api-admin» и в «web,api»), для списка — точный элемент (["api-admin"] не подходит); затем
`now <= tok["exp"] + LEEWAY` — истёкший в пределах допуска токен принимается, граница включена. Порядок проверок
задаёт причину отказа, когда не проходят обе. Ключ — независимая модель в генераторе; проверка — исполнение
показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.token.t21_aud_type_output"

CTX = ["шлюз API", "сервис платежей", "внутренний биллинг", "API отчётов", "мобильный бэкенд", "сервис файлов"]
AUDS = ["api", "billing", "files", "reports"]


def _aud_value(rng, aud: str, kind: str):
    """(значение aud, проходит ли проверка in, пояснение) — по виду, без оператора in."""
    other = rng.choice(["web", "mobile", "admin", "partner"])
    if kind == "str_sub":
        v = rng.choice([f"{aud}-admin", f"{other},{aud}", f"{aud}.internal", f"{other} {aud}"])
        return v, True, "строка: in ищет подстроку и находит её"
    if kind == "str_exact":
        return aud, True, "строка совпадает целиком"
    if kind == "str_case":
        return aud.upper(), False, "строка в другом регистре — подстроки нет"
    if kind == "list_exact":
        v = [other, aud] if rng.random() < 0.5 else [aud]
        return v, True, "список: есть точный элемент"
    v = rng.choice([[f"{aud}-admin"], [other, f"{aud}s"], [f"{other},{aud}"]])
    return v, False, "список: in сравнивает элементы целиком"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    aud = rng.choice(AUDS)
    leeway = rng.choice([30, 60, 120])
    now = rng.randrange(5000, 9000, 100)
    aud_first = rng.random() < 0.6
    for _ in range(200):
        kinds = [rng.choice(["str_sub", "str_sub", "str_case", "str_exact"]),
                 rng.choice(["list_miss", "list_miss", "list_exact"]),
                 rng.choice(["str_sub", "list_exact", "list_miss", "str_case"])]
        rng.shuffle(kinds)
        offs = [rng.choice([-leeway, -leeway - rng.choice([1, 10]), -rng.randint(1, leeway - 1), rng.choice([60, 300])])
                for _k in kinds]
        if -leeway in offs and any(o < -leeway for o in offs) or rng.random() < 0.15:
            break
    toks = []
    for kind, off in zip(kinds, offs):
        val, aud_ok, why = _aud_value(rng, aud, kind)
        toks.append((val, now + off, aud_ok, why))
    first = ('    if AUD not in tok["aud"]:\n        return "reject aud"\n'
             '    if now > tok["exp"] + LEEWAY:\n        return f"reject exp {now - tok[\'exp\']}"\n')
    if not aud_first:
        first = ('    if now > tok["exp"] + LEEWAY:\n        return f"reject exp {now - tok[\'exp\']}"\n'
                 '    if AUD not in tok["aud"]:\n        return "reject aud"\n')
    lit = "\n".join(f'    {{"aud": {v!r}, "exp": {e}}},' for v, e, _a, _w in toks).replace("'", '"')
    code = (f'AUD, LEEWAY = "{aud}", {leeway}\n'
            "def verify(tok, now):\n"
            f"{first}"
            '    return "accept"\n'
            f"tokens = [\n{lit}\n]\n"
            "for tok in tokens:\n"
            f"    print(verify(tok, {now}))")
    lines, trace = [], []
    for val, exp, aud_ok, why in toks:
        exp_ok = not (now - exp > leeway)
        rexp = f"reject exp {now - exp}"
        if aud_first:
            res = "reject aud" if not aud_ok else (rexp if not exp_ok else "accept")
        else:
            res = rexp if not exp_ok else ("reject aud" if not aud_ok else "accept")
        lines.append(res)
        d = now - exp
        exp_txt = (f"exp {exp}: now − exp = {d}" + (f" ≤ {leeway} — в пределах допуска" if exp_ok and d > 0 else
                                                     " — срок не вышел" if d <= 0 else f" > {leeway}"))
        trace.append(f"aud {val!r} — {why}; {exp_txt} → {res}")
    out = "\n".join(lines)
    order = "сначала aud, потом exp" if aud_first else "сначала exp, потом aud"
    expl = (f"Порядок проверок: {order}; срок проверяется как now <= exp + {leeway} (граница включена). "
            + "; ".join(trace) + f". Вывод: «{out.replace(chr(10), ' / ')}».")
    stem = (f"Проверка токенов доступа ({ctx}): функция сверяет получателя токена (claim aud) и срок действия "
            "с допуском на расхождение часов.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"aud": aud, "leeway": leeway, "now": now, "aud_first": aud_first},
                          language="python")
