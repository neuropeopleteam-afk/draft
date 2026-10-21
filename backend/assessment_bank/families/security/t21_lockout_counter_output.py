"""security.auth.t21_lockout_counter_output — predict_output (набор t21, порог Стажёра): счётчик неудачных входов
ПОДРЯД, который сбрасывается при успешном входе, и флаг блокировки `fails >= лимит`.

Модуль входа разбирает журнал попыток одной учётной записи (True/False, «ok»/«fail» или коды 200/401): при успехе
счётчик неудач обнуляется, при неудаче растёт на 1; после цикла печатаются итоговый счётчик и флаг блокировки (в
части вариантов — ещё и общее число неудач). Ловушки чтения: успешный вход сбрасывает счётчик, поэтому неудач
«всего» больше, чем «подряд»; флаг считается по итоговому значению счётчика, а не по максимуму за журнал; граница
`>=` — ровно лимит неудач уже блокирует. Ключ — независимая модель (длина хвоста неудач после последнего успеха)
в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "security.auth.t21_lockout_counter_output"

CTX = [("онлайн-банк", "Онлайн-банк блокирует вход после нескольких неудачных попыток подряд; программа разбирает "
                       "журнал попыток входа одной учётной записи за сутки."),
       ("VPN-шлюз", "VPN-шлюз считает неудачные попытки входа сотрудника и решает, блокировать ли учётную запись; "
                    "программа разбирает журнал попыток за смену."),
       ("админка CMS", "Панель администратора сайта защищается от подбора пароля; программа разбирает журнал "
                       "попыток входа в одну учётную запись."),
       ("SSH-бастион", "SSH-бастион ведёт журнал попыток входа по паролю для каждой учётной записи; программа "
                       "решает по журналу, блокировать ли вход."),
       ("личный кабинет", "Личный кабинет магазина считает неудачные попытки ввода пароля; программа разбирает "
                          "журнал попыток одного покупателя.")]
# (представление попытки, как выглядит успех/неудача в списке, условие успеха)
REPR = [("bool", "True", "False", "if {v}:"),
        ("str", '"ok"', '"fail"', 'if {v} == "ok":'),
        ("code", "200", "401", "if {v} == 200:")]
NAMES = [("attempts", "ok"), ("log", "r"), ("results", "res"), ("tries", "t")]


def _model(seq: list[bool]) -> tuple[int, int]:
    """Независимая модель: неудачи подряд в конце журнала (после последнего успеха) и всего неудач."""
    tail = 0
    for ok in reversed(seq):
        if ok:
            break
        tail += 1
    return tail, seq.count(False)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, stem = rng.choice(CTX)
    limit = rng.choice([3, 4, 5])
    want_lock = rng.random() < 0.45
    if want_lock:   # блокировка ровно на лимите или с запасом
        target = limit if rng.random() < 0.5 else rng.randint(limit + 1, limit + 2)
    else:
        target = 0 if rng.random() < 0.15 else rng.randint(1, limit - 1)
    mid_streak = (not want_lock) and rng.random() < 0.5  # серия >= лимита в середине, прерванная успехом
    for _ in range(3000):
        n = rng.randint(6, 9)
        if n - target - 1 < 1:
            continue
        seq = [rng.random() < 0.4 for _ in range(n - target - 1)] + [True] + [False] * target
        tail, total = _model(seq)
        longest = max(len(r) for r in "".join("F" if not x else " " for x in seq).split(" "))
        resets = sum(1 for i in range(1, n) if seq[i] and not seq[i - 1])  # успех сразу после неудачи
        if resets == 0 or total < limit or tail == total or (mid_streak and longest < limit):
            continue
        break
    else:
        raise RuntimeError("t21_lockout_counter: не собрался журнал")
    kind, s_ok, s_fail, cond = rng.choice(REPR)
    lv, iv = rng.choice(NAMES)
    if kind != "bool" and iv == "ok":
        iv = "a"
    vals = ", ".join(s_ok if x else s_fail for x in seq)
    with_total = rng.random() < 0.6
    lines = [f"{lv} = [{vals}]",
             "fails = 0",
             f"for {iv} in {lv}:",
             "    " + cond.format(v=iv),
             "        fails = 0",
             "    else:",
             "        fails += 1"]
    if with_total:
        lines.append(f"print({lv}.count({s_fail}), fails, fails >= {limit})")
    else:
        lines.append(f"print(fails, fails >= {limit})")
    code = "\n".join(lines)
    locked = tail >= limit
    out = f"{total} {tail} {locked}" if with_total else f"{tail} {locked}"
    last_ok = max(i for i, x in enumerate(seq) if x) + 1 if any(seq) else 0
    tail_txt = (f"после последнего успешного входа (попытка {last_ok}) неудач подряд — {tail}"
                if tail else f"последняя попытка ({last_ok}) успешна — счётчик обнулён")
    mid = (f"; серия из {longest} {plural(longest, 'неудачи', 'неудач', 'неудач')} подряд в середине журнала "
           "прервана успешным входом и на итог не влияет" if longest >= limit and not tail >= limit else "")
    expl = (f"Каждый успешный вход обнуляет fails, неудача прибавляет 1. Всего неудач {total}, но {tail_txt}, "
            f"поэтому после цикла fails = {tail}; fails >= {limit} → {locked}{mid}"
            + (f"; {lv}.count({s_fail}) считает все неудачи журнала без сброса — {total}" if with_total else "")
            + ". Ловушка: счётчик считает неудачи ПОДРЯД и сбрасывается успехом, а флаг проверяется по итоговому "
              f"значению. Вывод: «{out}».")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"seq": seq, "limit": limit, "with_total": with_total, "kind": kind},
                          language="python")
