"""security.encoding.t21_base64_padding_output — predict_output (набор t21, порог Junior): длина результата
`base64.b64encode` и число символов «=» в хвосте для строк разной длины.

Клиент кодирует несколько ASCII-строк (учётные данные `user:password`, идентификаторы, метки) и печатает для
каждой `len(enc)` и `enc.count(b"=")`, в части вариантов — ещё и сумму длин. Нужно знать две вещи вместе: base64
превращает каждые 3 байта в 4 символа, поэтому длина результата `4·⌈n/3⌉`; хвост «=» зависит от `n % 3`
(0 → нет, 1 → «==», 2 → «=»). Длины строк меняются от варианта к варианту, и остатки `n % 3` в одном варианте
разные. Ключ — независимая формула в генераторе (без модуля base64); проверка — исполнение показанного кода в
песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "security.encoding.t21_base64_padding_output"

CTX = ["интеграция с банком-партнёром", "выгрузка в бухгалтерию", "вызовы внутреннего API", "агент мониторинга",
       "сервис рассылок", "шлюз партнёрских заказов", "бот техподдержки"]
USERS = ["kate", "ivan", "svc", "bot", "admin", "ci", "ops", "anna", "deploy", "backup"]
PWDS = ["qwerty", "pa55", "s3cret", "12345", "letmein", "Zx9", "hunter2", "dragon", "x", "pw"]
LABELS = ["tenant-7", "eu-west", "prod", "v2", "id:4412", "key_01", "region=ru", "ab", "team-sec", "dc1"]
NAMES = [("parts", "s", "enc", "total"), ("values", "v", "b64", "size"), ("creds", "c", "encoded", "total"),
         ("items", "s", "out", "length")]


def _candidate(rng) -> str:
    kind = rng.random()
    if kind < 0.5:
        return f"{rng.choice(USERS)}:{rng.choice(PWDS)}"
    if kind < 0.8:
        return rng.choice(LABELS)
    return rng.choice(USERS) + rng.choice(["", "1", "42", "_ro"])


def _enc_len(n: int) -> int:
    return 4 * ((n + 2) // 3)


def _pad(n: int) -> int:
    return (3 - n % 3) % 3


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    lv, iv, ev, tv = rng.choice(NAMES)
    k = rng.choice([2, 3, 3])
    for _ in range(500):
        strs = [_candidate(rng) for _ in range(k)]
        lens = [len(s) for s in strs]
        if len(set(lens)) != k or len({n % 3 for n in lens}) < k:
            continue
        if min(lens) < 2 or max(lens) > 14:
            continue
        break
    else:
        raise RuntimeError("t21_base64_padding: не собрался набор строк")
    with_total = k == 3 or rng.random() < 0.3
    lit = ", ".join(f'"{s}"' for s in strs)
    if with_total:
        code = ("import base64\n"
                f"{lv} = [{lit}]\n"
                f"{tv} = 0\n"
                f"for {iv} in {lv}:\n"
                f"    {ev} = base64.b64encode({iv}.encode())\n"
                f"    {tv} += len({ev})\n"
                f'    print(len({ev}), {ev}.count(b"="))\n'
                f"print({tv})")
    else:
        code = ("import base64\n"
                f"{lv} = [{lit}]\n"
                f"for {iv} in {lv}:\n"
                f"    {ev} = base64.b64encode({iv}.encode())\n"
                f'    print(len({ev}), {ev}.count(b"="))')
    rows = [(_enc_len(n), _pad(n)) for n in lens]
    lines = [f"{a} {b}" for a, b in rows]
    if with_total:
        lines.append(str(sum(a for a, _b in rows)))
    out = "\n".join(lines)
    parts = "; ".join(f"«{s}» — {n} {plural(n, 'байт', 'байта', 'байт')}, "
                      f"4·⌈{n}/3⌉ = {a}, {n} % 3 = {n % 3} → «=» × {b}" for s, n, (a, b) in zip(strs, lens, rows))
    tot = f" Сумма длин: {' + '.join(str(a) for a, _b in rows)} = {sum(a for a, _b in rows)}." if with_total else ""
    expl = (f"base64 кодирует каждые 3 байта четырьмя символами, неполная последняя тройка добивается «=» "
            f"(остаток 1 → «==», остаток 2 → «=», 0 → без «=»): {parts}.{tot} Вывод по строкам: "
            f"«{out.replace(chr(10), ' / ')}».")
    stem = (f"{ctx[0].upper() + ctx[1:]}: программа кодирует в base64 значения для HTTP-заголовков и пишет в журнал "
            "размеры закодированных строк.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"strings": strs, "lens": lens, "with_total": with_total}, language="python")
