"""data_eng.etl.cdc_apply_output — predict_output: применение событий CDC в порядке поступления.

События журнала изменений (как у Debezium: op c/u/d, ключ, LSN — позиция в журнале БД) приходят не по порядку:
повторная доставка, устаревшее обновление после более нового, позднее обновление после удаления. Код применяет их
по одному с защитой «пропусти, если LSN не новее последнего применённого для ключа». Подтипы:
* tombstone_dropped — при удалении защита по ключу сбрасывается, и позднее обновление с меньшим LSN «воскрешает»
  удалённую строку (ловушка);
* tombstone_kept — при удалении LSN запоминается (tombstone), позднее обновление отбрасывается.
Ответ — строки «ключ значение» итоговой таблицы по возрастанию ключа. Ключ ответа — независимая модель
генератора; проверка — исполнение показанного кода дословно в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_eng.etl.cdc_apply_output"

CTX = [("заказы", ["new", "paid", "packed", "shipped", "delivered"]),
       ("договоры", ["draft", "signed", "active", "suspended", "closed"]),
       ("тикеты поддержки", ["open", "in_progress", "waiting", "resolved"]),
       ("карточки товаров", ["draft", "review", "published", "archived"]),
       ("заявки на кредит", ["submitted", "scoring", "approved", "issued"]),
       ("подписки", ["trial", "active", "past_due", "canceled"])]

APPLY = {
    "tombstone_dropped": [
        "    if op == \"d\":",
        "        table.pop(key, None)",
        "        seen.pop(key, None)",
    ],
    "tombstone_kept": [
        "    if op == \"d\":",
        "        table.pop(key, None)",
        "        seen[key] = lsn",
    ],
}


def _code(events, sub):
    ev = ",\n".join(f"    ({op!r}, {k}, {lsn}, {v!r})".replace("'", '"') for op, k, lsn, v in events)
    return "\n".join(["EVENTS = [  # (op, ключ, LSN, значение) в порядке поступления", ev, "]", "",
                      "table, seen = {}, {}",
                      "for op, key, lsn, value in EVENTS:",
                      "    if lsn <= seen.get(key, 0):",
                      "        continue  # повтор или устаревшее событие",
                      *APPLY[sub],
                      "    else:",
                      "        table[key] = value",
                      "        seen[key] = lsn",
                      "for key in sorted(table):",
                      "    print(key, table[key])"])


def _model(events, sub):
    """Независимый расчёт: по каждому ключу — последний LSN-барьер и значение."""
    state = {}  # ключ → (барьер LSN или None, значение или None)
    for op, k, lsn, v in events:
        barrier, val = state.get(k, (None, None))
        if barrier is not None and lsn <= barrier:
            continue
        if op == "d":
            state[k] = ((lsn if sub == "tombstone_kept" else None), None)
        else:
            state[k] = (lsn, v)
    return "\n".join(f"{k} {v}" for k, (_, v) in sorted(state.items()) if v is not None)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, statuses = rng.choice(CTX)
    sub = rng.choice(sorted(APPLY))
    for _ in range(2000):
        nk = rng.randint(3, 4)
        base = rng.choice([100, 200, 500, 1000, 4000])
        keys = sorted(rng.sample(range(base + 1, base + 60), nk))
        zombie, swapk = rng.sample(keys, 2)
        per = {}
        for k in keys:
            n_upd = rng.randint(1, 2) if k not in (zombie, swapk) else 2
            seq = [("c", statuses[0])] + [("u", statuses[i]) for i in range(1, n_upd + 1)]
            if k == zombie:
                seq.append(("d", None))
            per[k] = seq
        # слить по ключам случайно с сохранением порядка внутри ключа; LSN по возрастанию
        idx = {k: 0 for k in keys}
        merged, lsn = [], rng.randint(10, 90)
        while any(idx[k] < len(per[k]) for k in keys):
            k = rng.choice([k for k in keys if idx[k] < len(per[k])])
            op, v = per[k][idx[k]]
            idx[k] += 1
            lsn += rng.randint(1, 4)
            merged.append((op, k, lsn, v))
        arr = list(merged)
        # позднее обновление после удаления: первое обновление ключа zombie переезжает в самый конец
        z_upd = next(e for e in arr if e[1] == zombie and e[0] == "u")
        arr.remove(z_upd)
        arr.append(z_upd)
        # устаревшее обновление: два обновления ключа swapk меняются местами
        s_upd = [i for i, e in enumerate(arr) if e[1] == swapk and e[0] == "u"]
        arr[s_upd[0]], arr[s_upd[1]] = arr[s_upd[1]], arr[s_upd[0]]
        # повторная доставка одного события (не последнего)
        if rng.random() < 0.7:
            rep = rng.choice(arr[:-2])
            pos = rng.randint(arr.index(rep) + 1, len(arr) - 1)
            arr.insert(pos, rep)
        if not 9 <= len(arr) <= 14:
            continue
        expected = _model(arr, sub)
        if expected:
            break
    code = _code(arr, sub)
    stem = (f"Сервис переносит изменения таблицы «{ctx}» из журнала CDC (события c — создание, u — изменение, "
            "d — удаление; LSN — позиция в журнале БД, растёт со временем) в копию в памяти. События пришли из "
            "нескольких партиций, поэтому порядок поступления не совпадает с порядком LSN. Что напечатает код? "
            "Ответ — строки `ключ значение` в порядке вывода.")
    expl = ("Защита пропускает событие, если его LSN не больше последнего применённого для ключа: повтор и "
            "устаревшее обновление отбрасываются. "
            + ("При удалении защита по ключу сбрасывается, поэтому позднее обновление с меньшим LSN после удаления "
               "применяется и строка «воскресает»." if sub == "tombstone_dropped" else
               "При удалении LSN сохраняется (tombstone), поэтому позднее обновление с меньшим LSN отбрасывается и "
               "удалённая строка не возвращается."))
    checks = [Check(name="stdout", runner="python", program=code, expect="stdout_equals", expected_stdout=expected)]
    ak = AnswerKey(kind="output", value=expected, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="python",
                         params={"subtype": sub, "zombie": zombie, "events": len(arr)})
