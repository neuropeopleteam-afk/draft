"""data_eng.etl.t21_default_seen_set_output — predict_output (набор t21, порог Middle): дедупликация батчей функцией
с изменяемым аргументом по умолчанию `seen=set()` — множество общее для всех вызовов без явного аргумента.

Функция отбирает из батча ключи, которых ещё не было, и запоминает их в `seen`. Значение по умолчанию создаётся один
раз при определении функции, поэтому второй вызов «помнит» ключи первого; вызов с явным `set()` работает со своим
множеством и общее не меняет. Ловушки: считать каждый вызов независимым; забыть, что явный аргумент не трогает
общее множество. Ключ — независимая модель в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_eng.etl.t21_default_seen_set_output"

CTX = ["загрузка заказов файлами по часам", "приём событий батчами из очереди", "импорт платежей пачками",
       "загрузка кликов микробатчами", "перенос справочника клиентов частями"]
FN = ["new_keys", "dedup_batch", "fresh_ids", "unseen"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    fn = rng.choice(FN)
    for _ in range(1000):
        pool = rng.sample(range(1, 30), 9)
        calls = []
        n_calls = rng.randint(3, 4)
        explicit = rng.randint(1, n_calls - 1)        # номер вызова (с 0) с явным set(); первый — всегда по умолчанию
        for c in range(n_calls):
            batch = [rng.choice(pool) for _ in range(rng.randint(3, 4))]
            calls.append((batch, c == explicit))
        shared: list[int] = []
        outs = []
        own_if_shared = None
        for batch, own in calls:
            if own:
                own_if_shared = [k for k in dict.fromkeys(batch) if k not in shared]
            seen = [] if own else shared
            res = []
            for k in batch:
                if k not in seen:
                    seen.append(k)
                    res.append(k)
            outs.append(res)
        naive = [list(dict.fromkeys(b)) for b, _own in calls]
        # ловушки должны влиять: вызов по умолчанию теряет ключи из-за общего seen, а вызов со своим set()
        # возвращает ключи, которые общее множество уже видело
        affected = any(o != nv for (b, own), o, nv in zip(calls, outs, naive) if not own)
        if affected and all(outs) and own_if_shared != outs[explicit]:
            break
    else:
        raise RuntimeError("t21_default_seen_set: не собрались батчи")
    lines = [f"def {fn}(batch, seen=set()):",
             "    out = []",
             "    for key in batch:",
             "        if key not in seen:",
             "            seen.add(key)",
             "            out.append(key)",
             "    return out"]
    for batch, own in calls:
        args = "[" + ", ".join(str(k) for k in batch) + "]" + (", set()" if own else "")
        lines.append(f"print(*{fn}({args}))")
    code = "\n".join(lines)
    out = "\n".join(" ".join(str(k) for k in o) for o in outs)
    steps = []
    for i, ((batch, own), o) in enumerate(zip(calls, outs)):
        steps.append(f"вызов {i + 1}{' (своё set())' if own else ''} → {' '.join(str(k) for k in o)}")
    expl = ("Значение по умолчанию set() создаётся один раз при def, поэтому все вызовы без второго аргумента "
            "пополняют одно и то же множество, а вызов с явным set() — своё, общее он не меняет. "
            + "; ".join(steps)[0].upper() + "; ".join(steps)[1:] + ".")
    stem = f"Задача «{ctx}» отбрасывает повторы ключей функцией, которую вызывают для каждого батча."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"calls": len(calls), "explicit": explicit}, language="python")
