"""frontend.http.request_cache_ob3 — открытая книга: кэш запросов с дедупликацией и TTL.

Требования к кэшу: одновременные вызовы с одним ключом — один сетевой запрос; успешный
ответ живёт ttl мс от начала запроса; ошибка не кэшируется (следующий вызов делает новый
запрос), а вызывающий код получает ошибку. Ключи шагов 1–2 считает дискретно-событийная
модель в генераторе, проверка — исполнение в Node.js с виртуальным временем.
"""
from __future__ import annotations

import json

from assessment_bank.families.frontend._fake_timers import FAKE_TIMERS
from assessment_bank.gen_utils import (build_variant, make_options, make_rng, ob3_steps,
                                       rubric_from)
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.http.request_cache_ob3"

HEAD = ["function createCache(fetcher, ttl) {", "  const store = new Map();",
        "  return function get(key) {", "    const hit = store.get(key);"]
HIT = "    if (hit && now() - hit.at < ttl) return hit.promise;"
CODES = {
    "good": HEAD + [HIT, "    const promise = fetcher(key);", "    store.set(key, { promise, at: now() });",
                    "    promise.catch(() => {",
                    "      if (store.get(key)?.promise === promise) store.delete(key);",
                    "    });", "    return promise;", "  };", "}"],
    "no_catch": HEAD + [HIT, "    const promise = fetcher(key);", "    store.set(key, { promise, at: now() });",
                        "    return promise;", "  };", "}"],
    "store_after": HEAD + [HIT, "    const promise = fetcher(key).then((value) => {",
                           "      store.set(key, { promise: Promise.resolve(value), at: now() });",
                           "      return value;", "    });", "    return promise;", "  };", "}"],
    "catch_swallow": HEAD + [HIT, "    const promise = fetcher(key);", "    store.set(key, { promise, at: now() });",
                             "    return promise.catch(() => {", "      store.delete(key);",
                             "    });", "  };", "}"],
    "delete_any": HEAD + [HIT, "    const promise = fetcher(key);", "    store.set(key, { promise, at: now() });",
                          "    promise.catch(() => {", "      store.delete(key);", "    });",
                          "    return promise;", "  };", "}"],
    "inverted_ttl": HEAD + ["    if (hit && now() - hit.at > ttl) return hit.promise;",
                            "    const promise = fetcher(key);", "    store.set(key, { promise, at: now() });",
                            "    promise.catch(() => {",
                            "      if (store.get(key)?.promise === promise) store.delete(key);",
                            "    });", "    return promise;", "  };", "}"],
}
BUGGY_KINDS = {"cached_rejection": "no_catch", "no_dedup": "store_after"}


def _code(kind):
    return "\n".join(CODES[kind])


def _simulate(kind, ttl, calls, server):
    """calls: [[t, key]]; server: {key: {"fail_until": t, "slow_until": t, "slow": ms, "lat": ms}}."""
    store, proms, reqs = {}, [], []  # proms: [state, value]
    results = [None] * len(calls)
    events = []  # (time, order, type, payload)
    seq = 0

    def new_request(key, t):
        nonlocal seq
        n = len(reqs) + 1
        sv = server[key]
        lat = sv["slow"] if t < sv.get("slow_until", -1) else sv["lat"]
        ok = not (t < sv.get("fail_until", -1))
        reqs.append((key, t))
        pid = len(proms)
        proms.append({"state": "pending", "value": None, "key": key, "n": n, "ok": ok})
        seq += 1
        events.append((t + lat, seq, "done", pid))
        return pid

    waiting = []  # (call index, pid, swallow)
    for i, (t, key) in enumerate(calls):
        seq += 1
        events.append((t, seq, "call", (i, key)))
    events.sort()
    while events:
        events.sort()
        t, _, typ, payload = events.pop(0)
        if typ == "call":
            i, key = payload
            hit = store.get(key)
            valid = hit is not None and ((t - hit["at"] > ttl) if kind == "inverted_ttl"
                                         else (t - hit["at"] < ttl))
            if valid:
                waiting.append((i, hit["pid"], False))
                continue
            pid = new_request(key, t)
            if kind != "store_after":
                store[key] = {"pid": pid, "at": t}
            waiting.append((i, pid, kind == "catch_swallow"))
        else:
            p = proms[payload]
            p["state"] = "ok" if p["ok"] else "err"
            p["value"] = f"{p['key']}#{p['n']}" if p["ok"] else f"ERR 503 #{p['n']}"
            key = p["key"]
            if kind == "store_after" and p["ok"]:
                pid2 = len(proms)
                proms.append({"state": "ok", "value": p["value"], "key": key, "n": p["n"], "ok": True})
                store[key] = {"pid": pid2, "at": t}
            if not p["ok"]:
                cur = store.get(key)
                if kind in ("good", "inverted_ttl") and cur and cur["pid"] == payload:
                    del store[key]
                elif kind in ("delete_any", "catch_swallow") and cur:
                    del store[key]
    for i, pid, swallow in waiting:
        p = proms[pid]
        results[i] = "undefined" if (swallow and p["state"] == "err") else p["value"]
    return f"requests={len(reqs)} | " + ", ".join(results)


def _program(code, ttl, calls, server):
    return (FAKE_TIMERS + "\nconst now = () => __clock.now;\n\n" + code + "\n\n;(async () => {\n"
            f"  const server = {json.dumps(server)};\n  let n = 0;\n"
            "  const fetcher = (key) => {\n    n += 1;\n    const id = n;\n    const sv = server[key];\n"
            "    const t = __clock.now;\n"
            "    const lat = t < (sv.slow_until ?? -1) ? sv.slow : sv.lat;\n"
            "    const ok = !(t < (sv.fail_until ?? -1));\n"
            "    return new Promise((resolve, reject) => setTimeout(() => (ok ? resolve(key + '#' + id) "
            ": reject(new Error('ERR 503 #' + id))), lat));\n  };\n"
            f"  const get = createCache(fetcher, {ttl});\n  const results = [];\n"
            f"  for (const [t, key] of {json.dumps(calls)}) {{\n    await advanceTo(t);\n"
            "    results.push(get(key).then((v) => String(v), (e) => e.message));\n  }\n"
            "  await advanceTo(1e9);\n  const out = await Promise.all(results);\n"
            "  console.log('requests=' + n + ' | ' + out.join(', '));\n})();\n")


CONDITIONS = {
    "swr": dict(
        text=("Продакт хочет, чтобы при возврате на экран данные показывались мгновенно, даже "
              "если TTL истёк, а затем тихо обновлялись. Как изменить кэш (stale-while-"
              "revalidate) и что учесть?"),
        criteria=[("swr", "Разделяет «свежесть» и «срок хранения»: отдаёт устаревшее значение "
                          "сразу и запускает фоновое обновление, по его завершении уведомляет "
                          "подписчиков", 0.4),
                  ("dedup", "Не плодит фоновые запросы: дедупликация обновления, ошибка "
                            "обновления не затирает последнее успешное значение", 0.35),
                  ("ux", "Показывает признак обновления/устаревания, учитывает фокус окна и "
                         "восстановление сети; упоминает готовые решения (SWR, TanStack Query)", 0.25)],
        strong="""Ввожу два срока: staleTime — пока данные свежие, отдаю их без запроса; gcTime —
            сколько хранить устаревшие. Если запись устарела, get сразу возвращает старое
            значение и запускает фоновое обновление; когда оно завершится, кэш обновляет запись
            и уведомляет подписчиков (компонент перерисуется). Фоновое обновление
            дедуплицирую так же, как обычные запросы: одна запись «в полёте» на ключ. Ошибка
            фонового обновления не затирает последнее успешное значение — показываю его с
            пометкой и повторяю позже с backoff. Обновлять полезно при возврате фокуса на
            вкладку и при восстановлении сети. В интерфейсе — ненавязчивый индикатор
            обновления. В проекте это проще взять из TanStack Query или SWR.""",
        medium="""Нужно возвращать старые данные сразу, а в фоне делать новый запрос и после
            ответа обновлять кэш и интерфейс. Ошибка фонового запроса не должна стирать данные.""",
        weak="""Нужно увеличить TTL до суток, тогда данные всегда будут в кэше."""),
    "mutation": dict(
        text=("Пользователь изменил свой профиль (PUT /profile), но экран профиля и шапка "
              "продолжают показывать старое имя до истечения TTL. Как связать изменения "
              "данных с кэшем запросов?"),
        criteria=[("invalidate", "Инвалидирует или обновляет связанные ключи после успешной "
                                 "мутации (по ключу и по префиксу/тегу)", 0.4),
                  ("optimistic", "Описывает оптимистичное обновление с откатом при ошибке или "
                                 "запись ответа сервера прямо в кэш", 0.35),
                  ("race", "Учитывает гонку: ответ запроса, начатого до мутации, не должен "
                           "перезаписать новые данные (отмена/версии)", 0.25)],
        strong="""После успешного PUT нужно сделать кэш согласованным: либо записать ответ
            сервера в кэш по ключу профиля (setQueryData), либо инвалидировать все связанные
            ключи — профиль, шапку, списки с автором; удобно хранить ключи с общим префиксом
            или тегами и инвалидировать по ним. Для отзывчивости — оптимистичное обновление:
            сразу меняю значение в кэше, сохраняю предыдущее и при ошибке откатываю с
            сообщением. Важна гонка: если GET профиля был начат до PUT и пришёл после, он
            запишет старые данные — поэтому при мутации отменяю такие запросы или сравниваю
            версию/updatedAt и не принимаю более старые. TanStack Query делает это через
            invalidateQueries и onMutate.""",
        medium="""После изменения профиля нужно удалить из кэша ключи, связанные с профилем, или
            записать в кэш новые данные из ответа сервера.""",
        weak="""Нужно отключить кэш для профиля."""),
    "keys": dict(
        text=("Кэш живёт весь сеанс SPA. Ключ — только URL без параметров пользователя; после "
              "выхода и входа под другим аккаунтом видны чужие данные, а за рабочий день "
              "вкладка занимает 1,5 ГБ памяти. Что не так и как исправить?"),
        criteria=[("key", "Ключ включает всё, от чего зависит ответ: параметры, пользователя/"
                          "организацию, язык; нормализация параметров", 0.35),
                  ("logout", "Очищает кэш при выходе и смене пользователя, не держит "
                             "персональные данные дольше нужного", 0.3),
                  ("memory", "Ограничивает память: LRU/максимум записей, удаление записей без "
                             "подписчиков по gcTime, не хранит промисы и большие ответы вечно", 0.35)],
        strong="""Ключ должен включать всё, от чего зависит ответ: путь, нормализованные
            параметры (отсортированные, без пустых), идентификатор пользователя или
            организации, язык. Иначе разные пользователи и запросы получают одну запись. При
            выходе и при смене аккаунта кэш полностью очищаю (и отменяю запросы в полёте),
            чтобы персональные данные не пережили сеанс. Рост памяти — из-за того, что Map
            никогда не очищается: записи с истёкшим TTL остаются навсегда. Добавляю
            ограничение размера (LRU на N записей), удаление записей без подписчиков через
            gcTime и периодическую чистку истёкших; большие ответы не кэширую или храню
            урезанно. Проверяю снимками кучи до и после длинного сценария.""",
        medium="""В ключ нужно добавить параметры запроса и пользователя, при выходе очищать кэш и
            ограничить число записей, удаляя старые.""",
        weak="""Нужно перезагружать страницу при выходе пользователя."""),
    "http": dict(
        text=("Коллега предлагает выкинуть самописный кэш и полагаться на HTTP-кэш браузера: "
              "сервер будет отдавать Cache-Control и ETag. Что даст и чего не даст HTTP-кэш "
              "по сравнению с кэшем в памяти приложения?"),
        criteria=[("http", "Понимает HTTP-кэш: Cache-Control max-age/no-cache, ETag и условные "
                           "запросы 304, private для персональных данных", 0.35),
                  ("gaps", "Видит, чего HTTP-кэш не даёт: дедупликацию одновременных запросов "
                           "в приложении, синхронный доступ к данным, инвалидацию после мутаций, "
                           "общее состояние для компонентов", 0.4),
                  ("combo", "Предлагает сочетание: HTTP-кэш для статики и редко меняющихся "
                            "ответов, кэш приложения для серверного состояния; Service Worker "
                            "для офлайна", 0.25)],
        strong="""HTTP-кэш полезен: с Cache-Control: max-age браузер не пойдёт в сеть, а с
            no-cache и ETag сделает условный запрос и получит 304 без тела — это экономит
            трафик. Для персональных ответов — Cache-Control: private, чтобы прокси их не
            кэшировали. Но он не заменяет кэш приложения: не дедуплицирует два одновременных
            fetch из разных компонентов (оба уйдут в сеть или будут ждать), не даёт
            синхронно прочитать данные при рендере, не знает о мутациях — после PUT нельзя
            выборочно сбросить связанные ответы, и у приложения нет общего состояния с
            подписками. Поэтому сочетаю: статика и редко меняющиеся справочники — HTTP-кэш с
            долгим max-age и хэшем в имени файла; серверное состояние — кэш приложения
            (TanStack Query) поверх условных запросов; офлайн — Service Worker.""",
        medium="""HTTP-кэш уменьшит число запросов и трафик за счёт Cache-Control и ETag, но не
            решит дедупликацию одновременных запросов и инвалидацию после изменений данных.""",
        weak="""HTTP-кэш полностью заменяет кэш в приложении, его достаточно."""),
}


def _scenarios(rng, ttl, lat, key):
    gap = rng.choice([20, 40, 60])
    half = lat // 2 + rng.choice([0, 5, 10])
    late = ttl + rng.choice([50, 100, 200])
    within = lat + gap + rng.choice([0, 30, 60])
    other = rng.choice(["catalog", "cart", "me"])
    return {
        "concurrent": ([[0, key], [half, key]], None),
        "concurrent_fail": ([[0, key], [half, key]], 1),
        "retry_within_ttl": ([[0, key], [within, key]], 1),
        "retry_after_ttl": ([[0, key], [late, key]], 1),
        "sequential_ok": ([[0, key], [within, key]], None),
        "after_ttl_ok": ([[0, key], [late, key]], None),
        "two_keys": ([[0, key], [half, other]], None),
    }, other


def _describe(calls, fail):
    times = ", ".join(f"get('{k}') в {t} мс" for t, k in calls)
    srv = ("сервер отвечает ошибкой 503 на запросы, отправленные в момент 0"
           if fail is not None else "сервер отвечает без ошибок")
    return f"Вызовы: {times}; {srv}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    subtype = rng.choice(sorted(BUGGY_KINDS))
    bk = BUGGY_KINDS[subtype]
    ttl = rng.choice([500, 800, 1000, 2000])
    lat = rng.choice([40, 60, 80, 120])
    key = rng.choice(["user:42", "orders?page=1", "profile", "prices:RUB", "vacancies"])
    scen, other = _scenarios(rng, ttl, lat, key)
    srv = lambda fail: {k: ({"lat": lat, "fail_until": fail} if fail is not None else {"lat": lat})  # noqa: E731
                        for k in (key, other)}
    repro, safe = [], []
    for name, (calls, fail) in sorted(scen.items()):
        same = _simulate(bk, ttl, calls, srv(fail)) == _simulate("good", ttl, calls, srv(fail))
        (safe if same else repro).append(name)
    kname = rng.choice(repro)
    dnames = rng.sample(safe, 3)
    texts = {n: _describe(*scen[n]) for n in [kname] + dnames}
    opts1, key1 = make_options(rng, (texts[kname], None), [(texts[n], None) for n in dnames], step=1)
    by_text = {v: k for k, v in texts.items()}
    # шаг 2: составной сценарий, на котором отличается каждое неверное исправление
    t0 = 2000 + ttl
    calls2 = [[0, "a"], [10, "a"], [1000, "b"], [1100, "b"], [t0, "c"], [t0 + ttl + 50, "c"],
              [t0 + ttl + 250, "c"]]
    server2 = {"a": {"lat": lat}, "b": {"lat": 40, "fail_until": 1050},
               "c": {"lat": 40, "slow": ttl + 200, "slow_until": t0 + 1, "fail_until": t0 + 1}}
    good2 = _simulate("good", ttl, calls2, server2)
    pool = [k for k in CODES if k not in ("good", bk) and _simulate(k, ttl, calls2, server2) != good2]
    dk = rng.sample(pool, 3)
    opts2, key2 = make_options(rng, ("Заменить функцию на:", _code("good")),
                               [("Заменить функцию на:", _code(k)) for k in dk], step=2)
    code = _code(bk)
    checks = []
    for o in opts1:
        calls, fail = scen[by_text[o.text]]
        exp = _simulate("good", ttl, calls, srv(fail))
        checks.append(Check(name=f"step1:{o.id}", runner="node",
                            program=_program(code, ttl, calls, srv(fail)),
                            expect="stdout_differs" if o.id == key1 else "stdout_equals",
                            expected_stdout=exp))
    for o in opts2:
        checks.append(Check(name=f"step2:{o.id}", runner="node", embeds_display_code=False,
                            program=_program(o.code, ttl, calls2, server2),
                            expect="stdout_equals" if o.id == key2 else "stdout_differs",
                            expected_stdout=good2))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    ctx = rng.choice(["личный кабинет", "каталог вакансий", "дашборд продаж", "CRM", "маркетплейс"])
    stem = (f"Кэш запросов ({ctx}): `createCache(fetcher, {ttl})`, `now()` — текущее время в мс. "
            f"Требования: одновременные вызовы с одним ключом — один сетевой запрос; успешный "
            f"ответ используется {ttl} мс от начала запроса; ошибка не кэшируется — следующий "
            f"вызов делает новый запрос, а вызывающий код получает ошибку. Сервер отвечает "
            f"через {lat} мс.")
    steps = ob3_steps(
        "Шаг 1. В каком сценарии код нарушит требования (лишний запрос, устаревшая ошибка или "
        "не тот результат)?",
        "Шаг 2. Выберите исправление.",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    why = {"no_catch": "отклонённый промис остаётся в кэше и возвращается до истечения TTL",
           "store_after": "запись появляется только после ответа — одновременные вызовы делают "
                          "несколько запросов",
           "catch_swallow": "вызывающий код получает undefined вместо ошибки",
           "delete_any": "ошибка старого медленного запроса удаляет уже новую запись по ключу",
           "inverted_ttl": "условие TTL перевёрнуто: свежие записи не используются"}
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                   explanation=f"Дефект: {why[bk]}. Верно: сохранять промис сразу (дедупликация) "
                               f"и удалять его при ошибке, только если в кэше всё ещё он. "
                               f"Дистракторы шага 2: " + "; ".join(why[k] for k in dk) + ".")
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2,
                         answer_key=ak, rubric=rubric, context=ctx, verification="execution",
                         checks=checks, steps=steps, defect_type="request_cache_semantics",
                         display_code_note="Шаг 2 проверяется на составном сценарии (одновременные "
                                           "вызовы, ошибка и повтор, медленный упавший запрос).",
                         params={"subtype": subtype, "distractors": dk, "condition": cond_name,
                                 "repro": kname, "safe": dnames})
