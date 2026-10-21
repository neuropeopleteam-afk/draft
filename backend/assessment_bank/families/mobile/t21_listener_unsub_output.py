"""mobile.events.t21_listener_unsub_output — predict_output (набор t21, порог Senior): подписчики на статус
сети отписываются прямо во время рассылки — forEach по изменяемому массиву.

Мини-эмиттер статуса сети в React Native-приложении: subscribe кладёт слушателя в массив и возвращает функцию
отписки (splice по indexOf), emit обходит массив через forEach. Часть слушателей одноразовые — отписываются
при первом вызове. Что проследить: forEach идёт по индексам — после splice текущего элемента следующий сдвигается
на его место и в этой рассылке пропускается; длина обхода зафиксирована в начале, но индексы за новым концом
массива не посещаются; пропущенный одноразовый слушатель срабатывает (и отписывается) в следующей рассылке.
Ключ — точная модель forEach в генераторе; проверка — исполнение показанного кода в песочнице Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.events.t21_listener_unsub_output"

CTX = ["приложение доставки", "мессенджер", "банковское приложение", "приложение для заметок", "онлайн-кинотеатр"]
NAMES = ["banner", "sync", "toast", "badge", "retry", "metrics"]
STATES = ["online", "offline", "wifi", "cellular"]


def _simulate(listeners: list[tuple[str, bool]], emits: list[str]) -> tuple[list[str], list[str]]:
    arr = list(listeners)
    log, notes = [], []
    for st in emits:
        n0 = len(arr)
        called, skipped = [], []
        before = list(arr)
        for k in range(n0):
            if k >= len(arr):
                break
            name, once = arr[k]
            log.append(f"{name} {st}")
            called.append(name)
            if once:
                arr.pop(arr.index((name, once)))
        skipped = [nm for nm, _o in before if nm not in called]
        notes.append(f"emit('{st}'): вызваны {', '.join(called)}"
                     + (f"; пропущены из-за сдвига: {', '.join(skipped)}" if skipped else ""))
    return log, notes


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    for _ in range(300):
        n = rng.randint(3, 4)
        names = rng.sample(NAMES, n)
        once_idx = set(rng.sample(range(n - 1), rng.randint(1, 2)))   # одноразовый — не последним
        listeners = [(nm, i in once_idx) for i, nm in enumerate(names)]
        n_emit = rng.randint(2, 3)
        emits = [rng.choice(STATES)]
        while len(emits) < n_emit:
            emits.append(rng.choice([s for s in STATES if s != emits[-1]]))
        log, notes = _simulate(listeners, emits)
        if any("пропущены" in x for x in notes):
            break
    else:
        raise RuntimeError("t21_listener_unsub: не собрался набор слушателей")
    lines = ["const listeners = [];",
             "function subscribe(fn) {",
             "  listeners.push(fn);",
             "  return () => listeners.splice(listeners.indexOf(fn), 1);",
             "}",
             "function emit(status) {",
             "  listeners.forEach((fn) => fn(status));",
             "}"]
    for nm, once in listeners:
        if once:
            off = "off" + nm[0].upper() + nm[1:]
            lines.append(f"const {off} = subscribe((s) => {{ console.log('{nm}', s); {off}(); }});")
        else:
            lines.append(f"subscribe((s) => console.log('{nm}', s));")
    for st in emits:
        lines.append(f"emit('{st}');")
    code = "\n".join(lines)
    out = "\n".join(log)
    once_names = [nm for nm, o in listeners if o]
    expl = (f"Одноразовые слушатели ({', '.join(once_names)}) отписываются при первом вызове: splice удаляет "
            f"текущий элемент, следующий сдвигается на его индекс, а forEach переходит к следующему индексу — "
            f"сдвинутый слушатель в этой рассылке пропускается. " + "; ".join(notes) + ".")
    stem = (f"Мини-эмиттер статуса сети в React Native-приложении ({ctx}): часть подписчиков одноразовые и "
            f"отписываются прямо во время рассылки.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"listeners": [list(x) for x in listeners], "emits": emits}, language="javascript")
