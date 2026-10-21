"""mobile.offline.t21_queue_flush_output — predict_output (набор t21, порог Senior): отправка офлайн-очереди
циклом for…of с await, пока в очередь добавляются новые действия.

React Native-приложение при появлении сети отправляет накопленные действия по одному (каждая отправка — 200 мс
на таймере), а пользователь тем временем совершает новые действия (push в ту же очередь по таймерам). После цикла
очередь очищается `queue.length = 0`. Что проследить: итератор массива «живой» — элемент, добавленный до того,
как цикл дошёл до конца, тоже будет отправлен; добавленный после выхода из цикла переживёт очистку; await отдаёт
управление таймерам. Времена событий разнесены на 100 мс, порядок однозначен. Ключ — модель времени и очереди в
генераторе; проверка — исполнение показанного кода в песочнице Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.offline.t21_queue_flush_output"

CTX = [("лента соцсети", ["like", "comment", "share", "save", "follow"]),
       ("приложение заметок", ["edit", "pin", "tag", "move", "archive"]),
       ("приложение курьера", ["pickup", "photo", "sign", "deliver", "call"]),
       ("приложение опросов", ["answer", "skip", "rate", "note", "submit"]),
       ("магазин у дома", ["add", "remove", "promo", "address", "pay"])]
SEND_MS = 200
HALF = SEND_MS // 2


def _simulate(initial: list[str], pushes: list[tuple[int, str]]) -> tuple[list[str], int, list[str]]:
    """Возвращает (отправленные, момент выхода из цикла, остаток очереди к концу)."""
    queue = list(initial)
    pending = sorted(pushes)
    t, i, sent = 0, 0, []

    def apply_until(limit):
        while pending and pending[0][0] < limit:
            queue.append(pending.pop(0)[1])

    while True:
        apply_until(t)
        if i >= len(queue):
            break
        t += SEND_MS
        apply_until(t)
        sent.append(queue[i])
        i += 1
    end = t
    queue.clear()
    for _tm, it in pending:
        queue.append(it)
    return sent, end, queue


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, verbs = rng.choice(CTX)
    for _ in range(300):
        n0 = rng.randint(2, 3)
        n_push = rng.randint(1, 2)
        names = rng.sample(verbs, n0 + n_push)
        ids = rng.sample(range(1, 60), n0 + n_push)
        items = [f"{nm}:{i}" for nm, i in zip(names, ids)]
        slots = sorted(rng.sample(range(0, n0 + n_push + 2), n_push))
        pushes = [(s * SEND_MS + HALF, items[n0 + k]) for k, s in enumerate(slots)]
        sent, end, left = _simulate(items[:n0], pushes)
        inside = [it for tm, it in pushes if tm < end]
        # нужен хотя бы один «живой» элемент — добавлен во время цикла и отправлен тем же обходом
        if inside:
            break
    else:
        raise RuntimeError("t21_queue_flush: не собралось расписание")
    initial = items[:n0]
    last = max([end] + [tm for tm, _ in pushes])
    report_at = (last // SEND_MS + 1) * SEND_MS + HALF
    fn = rng.choice(["flush", "drainQueue", "syncPending"])
    lines = [f"const queue = [{', '.join(repr(x) for x in initial)}];",
             "const sent = [];",
             "const send = (item) => new Promise((resolve) => setTimeout(() => { sent.push(item); resolve(); }, "
             f"{SEND_MS}));",
             f"async function {fn}() {{",
             "  for (const item of queue) {",
             "    await send(item);",
             "  }",
             "  queue.length = 0;",
             "  console.log('flushed', sent.join(' '));",
             "}",
             f"{fn}();"]
    for tm, it in pushes:
        lines.append(f"setTimeout(() => queue.push('{it}'), {tm});")
    lines.append(f"setTimeout(() => console.log('left', queue.length, queue.join(' ')), {report_at});")
    code = "\n".join(lines)
    out = f"flushed {' '.join(sent)}\nleft {len(left)} {' '.join(left)}".rstrip()
    sends = ", ".join(f"{it} — до {SEND_MS * (k + 1)} мс" for k, it in enumerate(sent))
    notes = []
    for tm, it in pushes:
        if tm < end:
            notes.append(f"{it} добавлен в {tm} мс, когда цикл ещё не дошёл до конца массива, — итератор его видит "
                         f"и отправляет")
        else:
            notes.append(f"{it} добавлен в {tm} мс, уже после выхода из цикла ({end} мс) и очистки — он остаётся "
                         f"в очереди")
    expl = (f"Каждая отправка занимает {SEND_MS} мс, следующая начинается после await: {sends}. " + "; ".join(notes) +
            f". Цикл заканчивается в {end} мс, queue.length = 0 очищает массив, печатается «flushed {' '.join(sent)}»; "
            f"в {report_at} мс — «left {len(left)}{(' ' + ' '.join(left)) if left else ''}».")
    stem = (f"React Native-приложение ({ctx}) после восстановления сети отправляет офлайн-очередь действий по одному; "
            f"пока идёт отправка, пользователь совершает новые действия. Времена в setTimeout — мс от запуска.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"initial": initial, "pushes": [list(p) for p in pushes]}, language="javascript")
