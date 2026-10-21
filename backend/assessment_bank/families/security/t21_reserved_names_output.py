"""security.input.t21_reserved_names_output — predict_output (набор t21, порог Стажёра): цикл со счётчиком и
проверкой `name.strip().lower() in reserved` по списку заявок на логин.

Регистрация не даёт занять служебные имена: заявка отклоняется, если имя после `strip()` и `lower()` точно
совпадает с элементом списка `reserved`. Ловушки чтения: `strip()` убирает пробелы только по краям (пробел внутри
остаётся), `lower()` приводит регистр, а `in` по СПИСКУ — точное совпадение элемента («administrator», «r00t»,
«root1» не совпадают с «admin» / «root»). Печатаются отклонённые (после strip, регистр исходный) и число
принятых. Ключ — независимая модель в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "security.input.t21_reserved_names_output"

CTX = ["корпоративный портал", "форум поддержки", "онлайн-банк", "облачный сервис заметок", "почтовый сервис",
       "игровая платформа", "маркетплейс", "трекер задач"]
RESERVED = ["admin", "root", "support", "system", "security", "billing", "help", "abuse", "moderator",
            "postmaster", "operator", "service"]
USERS = ["kate", "ivan.petrov", "anna_dev", "m.orlov", "sergey", "olga", "denis77", "lena.k", "artem", "nina_qa"]
SUPER = {"admin": ["administrator", "admins", "admin1"], "root": ["rootkit", "root1", "groot"],
         "moderator": ["moderators", "moderator2"], "operator": ["operator1", "operators"],
         "postmaster": ["postmaster1"], "service": ["services", "service_bot"]}
LEET = {"o": "0", "e": "3", "a": "4"}  # без i→1: «bill1ng» трудно отличить от «billing»
NAMES = [("reserved", "signups", "rejected"), ("blocked", "requests", "denied"),
         ("service_names", "logins", "refused"), ("reserved", "candidates", "bad")]


def _match_form(rng, w: str) -> str:
    """Запись служебного имени, которая ПОСЛЕ strip().lower() совпадает с ним (пробелы по краям, регистр)."""
    forms = [w.capitalize() + " ", " " + w, w.upper(), "  " + w.capitalize(), w + "  ", " " + w.upper() + " "]
    return rng.choice(forms)


def _near_miss(rng, w: str) -> tuple[str, str]:
    """Похожая запись, которая НЕ совпадает: надстрока, «leet»-замена, пробел внутри, суффикс; второе — пояснение."""
    kinds = ["super", "inner", "suffix"]
    weights = [3, 3, 1]
    leet_chars = [ch for ch in LEET if ch in w[1:]]
    if leet_chars:
        kinds.append("leet")
        weights.append(3)
    kind = rng.choices(kinds, weights=weights)[0]
    if kind == "super":
        longer = rng.choice(SUPER.get(w, [w + "s", w + "_team"]))
        return longer, "другое, более длинное слово"
    if kind == "inner":
        k = rng.randint(2, len(w) - 2)
        s = w[:k] + " " + w[k:]
        return (s.capitalize() if rng.random() < 0.5 else s), "пробел внутри строки strip() не убирает"
    if kind == "leet":
        ch = rng.choice(leet_chars)
        return w[0] + w[1:].replace(ch, LEET[ch]), "цифра вместо буквы"
    return w + rng.choice(["1", "_", "-bot", "2"]), "лишние символы в конце"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    rv, sv, cv = rng.choice(NAMES)
    for _ in range(200):
        reserved = rng.sample(RESERVED, rng.randint(3, 4))
        n_match = rng.randint(1, 2)
        n_miss = rng.randint(2, 3)
        n_user = rng.randint(1, 2) if n_match + n_miss < 5 else rng.randint(0, 1)
        entries = [_match_form(rng, w) for w in rng.sample(reserved, n_match)]
        misses = [_near_miss(rng, w) for w in rng.choices(reserved, k=n_miss)]
        entries += [m for m, _why in misses]
        entries += rng.sample(USERS, n_user)
        keys = [e.strip().lower() for e in entries]
        if len(set(keys)) != len(keys) or not 5 <= len(entries) <= 6:
            continue
        rng.shuffle(entries)
        break
    else:
        raise RuntimeError("t21_reserved_names: не собрался список заявок")
    lit_r = ", ".join(f'"{w}"' for w in reserved)
    lit_s = ", ".join(f'"{e}"' for e in entries)
    code = (f"{rv} = [{lit_r}]\n"
            f"{sv} = [{lit_s}]\n"
            f"{cv} = 0\n"
            f"for name in {sv}:\n"
            f"    if name.strip().lower() in {rv}:\n"
            '        print("rejected:", name.strip())\n'
            f"        {cv} += 1\n"
            f'print("accepted:", len({sv}) - {cv})')
    # независимая модель: пробелы только по краям, нижний регистр, точное совпадение элемента списка
    rej = [e.strip(" ") for e in entries if e.strip(" ").lower() in reserved]
    acc = len(entries) - len(rej)
    out = "\n".join([f"rejected: {r}" for r in rej] + [f"accepted: {acc}"])
    why = dict(misses)
    miss_txt = "; ".join(f"«{e}» — {why[e]}" for e in entries if e in why and e.strip(" ").lower() not in reserved)
    nr = len(rej)
    expl = (f"После strip() и lower() точно совпадают со служебными именами {nr} "
            f"{plural(nr, 'заявка', 'заявки', 'заявок')}: {', '.join('«' + r + '»' for r in rej)} — "
            f"{'её' if nr == 1 else 'их'} печатают после strip() (регистр исходный). Похожие записи не совпадают, "
            f"in по списку сравнивает элементы целиком: {miss_txt}. Принято {len(entries)} − {nr} = {acc}. Вывод: "
            f"«{out.replace(chr(10), ' / ')}».")
    stem = (f"Регистрация пользователей ({ctx}): программа не даёт занять служебные имена и разбирает очередь "
            "заявок на логин.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"reserved": reserved, "entries": entries}, language="python")
