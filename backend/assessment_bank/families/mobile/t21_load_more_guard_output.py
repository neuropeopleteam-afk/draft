"""mobile.paging.t21_load_more_guard_output — predict_output (набор t21, порог Senior): подгрузка следующей
страницы списка по onEndReached с флагом loading — повторные вызовы во время загрузки.

FlatList в React Native вызывает onEndReached несколько раз подряд; loadMore защищена флагом loading (ставится
синхронно до await, снимается после). Загрузка страницы — 100 мс на таймере. Вызовы приходят синхронно, из
микрозадачи (Promise.then) и из таймеров. Что проследить: синхронная часть async-функции до await успевает
поднять флаг, поэтому вызов из then уже видит loading; таймер на 100 мс, созданный ПОСЛЕ таймера загрузки с той
же задержкой, срабатывает после него, а продолжение после await (микрозадача) успевает снять флаг до этого
таймера; остальные времена разнесены не меньше чем на 40 мс от завершений загрузок. Ключ — модель таймеров и
микрозадач в генераторе; проверка — исполнение показанного кода в песочнице Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.paging.t21_load_more_guard_output"

CTX = [("лента объявлений", "ads"), ("история операций", "operations"), ("каталог товаров", "products"),
       ("список отзывов", "reviews"), ("лента новостей", "posts")]
TAG_SETS = [["A", "B", "C", "D", "E"], ["e1", "e2", "e3", "e4", "e5"], ["s1", "s2", "s3", "s4", "s5"]]
FETCH_MS = 100


def _simulate(second_via_then: bool, timer_calls: list[tuple[str, int]], tags: tuple[str, str], size: int,
              arr: str):
    """События: A — синхронно, B — синхронно или из then, остальные — таймеры (созданы при старте по порядку)."""
    log: list[str] = []
    st = {"loading": False, "page": 0, "items": 0}
    completions: list[int] = []
    # очередь событий: (время, порядок создания, вид, данные); загрузка A создаётся раньше таймеров вызовов
    events: list[tuple[int, int, str, str]] = []
    seq = [0]

    def call(tag: str, now: int):
        if st["loading"]:
            log.append(f"{tag} skip")
            return
        st["loading"] = True
        nxt = st["page"] + 1
        seq[0] += 1
        events.append((now + FETCH_MS, seq[0], "done", f"{tag}|{nxt}"))
        completions.append(now + FETCH_MS)

    a_tag, b_tag = tags
    call(a_tag, 0)
    if not second_via_then:
        call(b_tag, 0)
    for tag, tm in timer_calls:
        seq[0] += 1
        events.append((tm, seq[0], "call", tag))
    if second_via_then:
        call(b_tag, 0)   # микрозадача после синхронного кода, до любых таймеров
    while events:
        events.sort()
        tm, _s, kind, data = events.pop(0)
        if kind == "call":
            call(data, tm)
        else:
            tag, nxt = data.split("|")
            st["page"] = int(nxt)
            st["items"] += size
            st["loading"] = False
            log.append(f"{tag} page {st['page']} {arr} {st['items']}")
    return log, completions


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, arr = rng.choice(CTX)
    size = rng.choice([2, 3, 4, 5])
    tags_all = rng.choice(TAG_SETS)
    second_via_then = rng.random() < 0.5
    for _ in range(500):
        n_timers = rng.randint(2, 3)
        times = sorted(rng.sample([50, 100, 130, 170, 200, 240, 270, 310, 340, 380], n_timers))
        timer_calls = list(zip(tags_all[2:2 + n_timers], times))
        log, comps = _simulate(second_via_then, timer_calls, (tags_all[0], tags_all[1]), size, arr)
        ok = True
        for _tag, tm in timer_calls:
            for c in comps:
                if tm == c == FETCH_MS:
                    continue      # таймер вызова и таймер первой загрузки созданы при старте: порядок FIFO
                if abs(tm - c) < 40:
                    ok = False
        n_loads = sum(1 for x in log if " page " in x)
        n_skips = sum(1 for x in log if x.endswith("skip"))
        if ok and n_loads >= 2 and n_skips >= 2:   # кроме B, хотя бы один вызов из таймера попадает на загрузку
            break
    else:
        raise RuntimeError("t21_load_more_guard: не собралось расписание")
    fn = rng.choice(["loadMore", "onEndReached", "fetchNext"])
    flag = rng.choice(["loading", "busy", "inFlight", "isFetching"])
    fetch = rng.choice(["fetchPage", "requestPage", "getPage"])
    lines = ["let page = 0;",
             f"let {flag} = false;",
             f"const {arr} = [];",
             f"const {fetch} = (p) => new Promise((resolve) => setTimeout(() => resolve(Array({size}).fill(p)), 100));",
             f"async function {fn}(tag) {{",
             f"  if ({flag}) {{ console.log(tag, 'skip'); return; }}",
             f"  {flag} = true;",
             f"  const rows = await {fetch}(page + 1);",
             "  page += 1;",
             f"  {arr}.push(...rows);",
             f"  {flag} = false;",
             f"  console.log(tag, 'page', page, '{arr}', {arr}.length);",
             "}",
             f"{fn}('{tags_all[0]}');"]
    if second_via_then:
        lines.append(f"Promise.resolve().then(() => {fn}('{tags_all[1]}'));")
    else:
        lines.append(f"{fn}('{tags_all[1]}');")
    for tag, tm in timer_calls:
        lines.append(f"setTimeout(() => {fn}('{tag}'), {tm});")
    code = "\n".join(lines)
    out = "\n".join(log)
    b_how = (f"из then — микрозадачей, но уже после синхронной части {tags_all[0]}" if second_via_then
             else "синхронно сразу после A")
    tie = any(tm == FETCH_MS for _t, tm in timer_calls)
    tie_txt = (" Таймер вызова на 100 мс создан позже таймера первой загрузки с той же задержкой, поэтому "
               f"срабатывает после него, а продолжение {tags_all[0]} после await (микрозадача) успевает снять флаг — этот вызов "
               "загружает следующую страницу." if tie else "")
    expl = (f"{tags_all[0]} синхронно доходит до await и уже поднял {flag}, поэтому {tags_all[1]} ({b_how}) "
            f"печатает skip. Загрузка "
            f"длится 100 мс; вызов во время загрузки — skip, после её завершения — следующая страница, в каждой "
            f"по {size} элемента(ов).{tie_txt} Итог: " + " / ".join(log) + ".")
    stem = (f"React Native-экран «{ctx.capitalize()}»: FlatList вызывает подгрузку следующей страницы несколько раз "
            f"подряд, функция защищена флагом {flag}. Времена в setTimeout — мс от запуска.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"size": size, "then": second_via_then, "timers": [list(t) for t in timer_calls]},
                          language="javascript")
