"""security.secrets.t21_strong_func_bash_output — predict_output (набор t21, порог Junior): функция-проверка
пароля в bash, код возврата функции и `if func "$p"` в цикле по словам.

Функция `strong() { [ ${#1} -ge $MIN ] && [ "$1" != "$LOGIN" ]; }` ничего не печатает: её код возврата — код
последней выполненной команды (если первая проверка ложна, `&&` не выполняет вторую, и функция возвращает 1).
Цикл по словам-паролям: при успехе увеличивает счётчик, иначе печатает «weak: <пароль>»; в конце — число
сильных. Ловушки (две конструкции вместе): `-ge` пропускает пароль длиной ровно MIN; пароль, совпадающий с
логином, отклоняется, даже если он длинный; короткий логин отсекается уже проверкой длины. Ключ — независимая
модель в генераторе; проверка — исполнение показанного скрипта в bash-песочнице.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "security.secrets.t21_strong_func_bash_output"

CTX = ["онбординг сотрудников", "сервисные учётки CI", "панель администратора сайта", "VPN-доступ подрядчиков",
       "учётки базы данных", "личный кабинет клиента", "доступ к бастион-хосту"]
LOGINS = ["kate.smirnova", "ivan_petrov", "deploy_bot", "backup_user", "operator", "ci-runner", "anna.k", "admin",
          "olga", "monitoring"]
WORDS = ["qwe", "abc", "test", "pass", "love", "hello", "lucky", "tiger", "qwerty", "dragon", "monkey", "secret",
         "shadow", "master", "spring", "winter", "s3cr3t", "letmein", "Moscow7", "sunshine", "zaq1xsw2", "p4ssw0rd",
         "starwars", "Tr0ub4dor", "blueberry", "snowflake", "butterfly", "chocolate", "kingfisher", "basketball",
         "whiteboard", "greenhouse", "watermelon", "lighthouse", "nightingale", "correcthorse", "thunderstorm"]
NAMES = [("strong", "ok", "weak"), ("is_strong", "good", "weak"), ("check_pw", "passed", "reject")]


def _word(rng, n: int) -> str:
    """Пароль длины ровно n: слово длины n−3…n, добитое цифрами."""
    cands = [w for w in WORDS if n - 3 <= len(w) <= n]
    if not cands:
        top = max(len(w) for w in WORDS if len(w) <= n)
        cands = [w for w in WORDS if top - 1 <= len(w) <= top]
    base = rng.choice(cands)
    while len(base) < n:
        base += str(rng.randint(0, 9))
    return base


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    fv, cv, lab = rng.choice(NAMES)
    mn = rng.choice([6, 8, 10, 12])
    long_login = rng.random() < 0.75
    pool = [x for x in LOGINS if (len(x) >= mn) == long_login]
    if not pool:
        pool = [x for x in LOGINS if len(x) >= mn] or LOGINS
    login = rng.choice(pool)
    for _ in range(300):
        pws = {_word(rng, mn), _word(rng, mn - 1), _word(rng, mn + rng.randint(2, 4))}
        if long_login or rng.random() < 0.5:
            pws.add(login)
        if rng.random() < 0.5:
            pws.add(_word(rng, rng.choice([mn - 3, mn + 1, mn + 3])))
        pws = sorted(pws)
        if 4 <= len(pws) <= 6 and all(len(p) >= 3 for p in pws):
            rng.shuffle(pws)
            break
    else:
        raise RuntimeError("t21_strong_func: не собрался список паролей")
    code = (f"MIN={mn}\n"
            f'LOGIN="{login}"\n'
            f'{fv}() {{ [ ${{#1}} -ge $MIN ] && [ "$1" != "$LOGIN" ]; }}\n'
            f"{cv}=0\n"
            f"for p in {' '.join(pws)}; do\n"
            f'  if {fv} "$p"; then {cv}=$(({cv}+1)); else echo "{lab}: $p"; fi\n'
            "done\n"
            f'echo "${cv}"')
    good = [p for p in pws if len(p) >= mn and p != login]
    bad = [p for p in pws if p not in good]
    out = "\n".join([f"{lab}: {p}" for p in bad] + [str(len(good))])
    why = []
    for p in pws:
        if len(p) < mn:
            why.append(f"«{p}» — {len(p)} < {mn}, вторая проверка не выполняется, код 1 → {lab}")
        elif p == login:
            why.append(f"«{p}» — длина {len(p)} ≥ {mn}, но совпадает с LOGIN, последняя команда даёт 1 → {lab}")
        elif len(p) == mn:
            why.append(f"«{p}» — ровно {mn}, -ge пропускает, код 0")
        else:
            why.append(f"«{p}» — {len(p)} ≥ {mn}, код 0")
    expl = (f"Код возврата функции — код последней выполненной команды цепочки &&. По порядку: {'; '.join(why)}. "
            f"Код 0 у {len(good)} {plural(len(good), 'пароля', 'паролей', 'паролей')} — это значение счётчика. Вывод: "
            f"«{out.replace(chr(10), ' / ')}».")
    stem = (f"Проверка паролей ({ctx}): скрипт прогоняет список кандидатов через функцию-проверку и считает "
            "подходящие.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"min": mn, "login": login, "passwords": pws}, language="bash")
