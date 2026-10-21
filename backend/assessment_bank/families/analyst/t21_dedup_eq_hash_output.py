"""analyst.python.t21_dedup_eq_hash_output — predict_output (набор t21, порог Senior): дедупликация объектов через
set и dict — роль __eq__ и __hash__, какой ключ и какое значение остаются в словаре.

Класс записи (визит, заявка, клиент, событие) с целочисленным ключом пользователя. В большинстве вариантов заданы и
`__eq__`, и `__hash__` по ключу: `set` схлопывает повторы, а словарь `d[obj] = obj.attr` при повторе ключа ОСТАВЛЯЕТ
первый объект-ключ (и его место в порядке), но ЗАМЕНЯЕТ значение на последнее. В части вариантов задан только
`__hash__` — без `__eq__` объекты сравниваются по тождеству, и дедупликации нет вовсе. Ключ — независимая модель в
генераторе (без исполнения показанного кода); проверка — исполнение кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "analyst.python.t21_dedup_eq_hash_output"

# (сюжет, класс, поле ключа, поле атрибута, значения атрибута, имя списка)
CTX = [
    ("визиты на сайт из разных рекламных источников", "Visit", "user_id", "source", ["ads", "seo", "email", "blog"],
     "visits"),
    ("заявки на кредит из разных каналов", "Application", "client_id", "channel", ["app", "web", "office"],
     "applications"),
    ("анкеты участников опроса из нескольких волн", "Answer", "person_id", "wave", ["w1", "w2", "w3"], "answers"),
    ("события входа пользователей с разных устройств", "Login", "user_id", "device", ["ios", "android", "web"],
     "logins"),
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    plot, cls, key, attr, vals, var = rng.choice(CTX)
    with_eq = rng.random() < 0.7
    for _ in range(500):
        n = rng.randint(5, 6)
        ids = rng.sample(range(2, 40), rng.randint(2, 3))
        items = [(rng.choice(ids), rng.choice(vals)) for _ in range(n)]
        uniq = []
        for u, _a in items:
            if u not in uniq:
                uniq.append(u)
        if len(uniq) == len(items) or len(uniq) < 2:
            continue
        # у повторяющегося ключа первое и последнее значения атрибута различаются
        rep = [u for u in uniq if sum(1 for x in items if x[0] == u) > 1]
        if any(next(a for x, a in items if x == u) != [a for x, a in items if x == u][-1] for u in rep):
            break
    else:
        raise RuntimeError("t21_dedup_eq_hash: не собрались данные")
    lst = ", ".join(f'{cls}({u}, "{a}")' for u, a in items)
    eq = (f"    def __eq__(self, other):\n"
          f"        return self.{key} == other.{key}\n\n") if with_eq else ""
    code = (f"class {cls}:\n"
            f"    def __init__(self, {key}, {attr}):\n"
            f"        self.{key} = {key}\n"
            f"        self.{attr} = {attr}\n\n"
            f"{eq}"
            f"    def __hash__(self):\n"
            f"        return self.{key}\n\n\n"
            f"{var} = [{lst}]\n"
            f"last = {{}}\n"
            f"for x in {var}:\n"
            f"    last[x] = x.{attr}\n"
            f"print(len(set({var})), len(last))\n"
            f"for k, v in last.items():\n"
            f"    print(k.{key}, k.{attr}, v)")
    if with_eq:
        first_attr = {u: next(a for x, a in items if x == u) for u in uniq}
        last_attr = {u: [a for x, a in items if x == u][-1] for u in uniq}
        lines = [f"{len(uniq)} {len(uniq)}"] + [f"{u} {first_attr[u]} {last_attr[u]}" for u in uniq]
        why = (f"__eq__ и __hash__ — по {key}, поэтому set и dict считают записи с одним {key} одинаковыми: "
               f"{len(uniq)} уникальных. При повторной записи last[x] = … словарь оставляет ПЕРВЫЙ объект-ключ (и его "
               f"место в порядке), а значение заменяет на последнее: k.{attr} — из первой записи, v — из последней")
    else:
        lines = [f"{len(items)} {len(items)}"] + [f"{u} {a} {a}" for u, a in items]
        why = (f"__hash__ задан, а __eq__ нет — объекты сравниваются по тождеству (is), и одинаковый хэш не делает их "
               f"равными: дедупликации нет, в set и dict все {len(items)} объектов, у каждого k.{attr} совпадает с v")
    out = "\n".join(lines)
    stem = (f"Аналитик чистит выгрузку ({plot}): записи с одинаковым {key} хочется считать одной. Программа "
            f"складывает их в set и в словарь.")
    expl = f"{why}. Вывод: " + "; ".join(f"«{ln}»" for ln in lines) + "."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"items": items, "with_eq": with_eq}, language="python")
