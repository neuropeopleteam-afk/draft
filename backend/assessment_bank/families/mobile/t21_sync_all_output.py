"""mobile.sync.t21_sync_all_output — predict_output (набор t21, порог Senior): синхронизация разделов после
выхода из офлайна через Promise.all — быстрый отказ и порядок результатов.

React Native-приложение после восстановления сети синхронизирует несколько разделов параллельно (таймеры с разной
задержкой, часть запросов завершается ошибкой) и ждёт их через Promise.all(...).then(...).catch(...)[.finally].
Что проследить: Promise.all отклоняется на ПЕРВОЙ по времени ошибке, обработчики catch / finally выполняются
микрозадачами сразу после этого таймера — до завершения остальных запросов, которые не отменяются и печатают
своё «done»; вторая ошибка уже ни на что не влияет; при успехе результаты идут в порядке массива, а не в порядке
завершения. Ключ — модель таймеров и промисов в генераторе; проверка — исполнение показанного кода в песочнице
Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.sync.t21_sync_all_output"

CTX = [("приложение интернет-магазина", ["cart", "favs", "profile", "orders"]),
       ("приложение заметок", ["notes", "tags", "trash", "settings"]),
       ("приложение фитнес-трекера", ["workouts", "goals", "weight", "badges"]),
       ("приложение курьера", ["routes", "parcels", "payouts", "chat"]),
       ("приложение банка", ["accounts", "cards", "limits", "offers"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pool = rng.choice(CTX)
    n = rng.randint(3, 4)
    names = rng.sample(pool, n)
    delays = rng.sample([10, 20, 30, 40, 50, 60], n)
    r = rng.random()
    n_fail = 0 if r < 0.2 else (1 if r < 0.7 else 2)
    fails = set(rng.sample(range(n), n_fail))
    # при успехе порядок завершения должен отличаться от порядка массива — иначе ловушки нет
    if n_fail == 0 and sorted(range(n), key=lambda i: delays[i]) == list(range(n)):
        delays = delays[1:] + delays[:1]
    with_finally = rng.random() < 0.5
    fn = rng.choice(["syncPart", "pull", "fetchSection"])
    ok_tag = rng.choice(["synced", "up to date"])
    fail_tag = rng.choice(["failed", "sync error"])
    fin_tag = rng.choice(["spinner off", "hide loader", "unlock pull"])
    start_tag = rng.choice(["sync started", "online again", "resync"])
    calls = ", ".join(f"{fn}('{nm}', {delays[i]}, {'false' if i in fails else 'true'})"
                      for i, nm in enumerate(names))
    lines = [f"function {fn}(name, ms, ok) {{",
             "  return new Promise((resolve, reject) => setTimeout(() => {",
             "    console.log('done', name);",
             "    if (ok) resolve(name); else reject(new Error(name));",
             "  }, ms));",
             "}",
             f"Promise.all([{calls}])",
             f"  .then((names) => console.log('{ok_tag}', names.join(',')))",
             f"  .catch((e) => console.log('{fail_tag}', e.message))"]
    if with_finally:
        lines.append(f"  .finally(() => console.log('{fin_tag}'));")
    else:
        lines[-1] += ";"
    lines.append(f"console.log('{start_tag}');")
    code = "\n".join(lines)
    # модель: синхронно — только start_tag; таймеры по возрастанию задержки, после каждого — микрозадачи
    log = [start_tag]
    settled = False
    order = sorted(range(n), key=lambda i: delays[i])
    for k, i in enumerate(order):
        log.append(f"done {names[i]}")
        if settled:
            continue
        if i in fails:
            settled = True
            log.append(f"{fail_tag} {names[i]}")
            if with_finally:
                log.append(fin_tag)
        elif k == n - 1:
            settled = True
            log.append(f"{ok_tag} {','.join(names)}")
            if with_finally:
                log.append(fin_tag)
    out = "\n".join(log)
    fin_txt = f" и finally («{fin_tag}»)" if with_finally else ""
    if fails:
        first = min(fails, key=lambda i: delays[i])
        expl = (f"Синхронно печатается только «{start_tag}». Таймеры срабатывают по возрастанию задержки. Первая по "
                f"времени ошибка — {names[first]} ({delays[first]} мс): Promise.all сразу отклоняется, then "
                f"пропускается, catch{fin_txt} {'выполняются' if with_finally else 'выполняется'} микрозадачами сразу после этого таймера — раньше "
                f"остальных запросов. Остальные запросы не отменяются и печатают своё «done»"
                f"{'; вторая ошибка уже ни на что не влияет' if len(fails) > 1 else ''}.")
    else:
        expl = (f"Синхронно печатается только «{start_tag}». Таймеры срабатывают по возрастанию задержки, ошибок нет: "
                f"после последнего Promise.all выполняется, и then печатает результаты в порядке массива "
                f"({','.join(names)}), а не в порядке завершения{fin_txt and ', затем finally'}.")
    stem = (f"{ctx[0].upper() + ctx[1:]} после выхода из офлайна синхронизирует разделы параллельно; функция {fn} "
            f"имитирует запрос с задержкой ms и успехом или ошибкой (ok).")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"names": names, "delays": delays, "fails": sorted(fails),
                                  "finally": with_finally}, language="javascript")
