"""mobile.js.cursor_pagination_bug — find_bug: бесконечная лента с курсорной подгрузкой.

Лента в мобильном приложении (новые записи сверху, id по убыванию) подгружается страницами по курсору
`before`: сервер отдаёт записи с id меньше курсора. Курсор следующей страницы берётся с первой записи страницы
(самой новой), а не с последней — следующая страница сдвинута на одну запись: за запрос добавляется одна
запись, запросов в разы больше страниц. Один подтип дефекта; варьируются предметная область, имена, размер страницы,
положение служебной функции. Ключ проверяется исполнением: модель сервера в Node, подгрузка до конца ленты.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, js_harness, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "mobile.js.cursor_pagination_bug"

CTX = [("лента новостей", "feed", "posts"), ("история заказов", "orders", "orders"),
       ("чат поддержки", "messages", "history"), ("уведомления", "notifications", "inbox"),
       ("история операций банка", "operations", "statement"), ("отзывы о товаре", "reviews", "reviews")]
DECOYS = [["function isEmpty(page) {", "  return !page || page.length === 0;", "}"],
          ["const byNewest = (a, b) => b.id - a.id;"],
          ["function lastId(list) {", "  return list.length ? list[list.length - 1].id : null;", "}"],
          ["const formatCount = (n) => (n > 99 ? '99+' : String(n));"]]

PRELUDE = """function makeApi(total, kind) {
  const all = Array.from({ length: total }, (_, i) => ({ id: 1000 + total - i, kind }));
  const api = { calls: 0 };
  api.METHOD = async ({ before, limit }) => {
    api.calls += 1;
    for (let k = 0; k < 2; k++) await null;
    const rest = before == null ? all : all.filter((x) => x.id < before);
    return rest.slice(0, limit);
  };
  return api;
}"""

TEST = """const api = makeApi(TOTAL, 'KIND');
const state = { items: [], seen: new Set(), cursor: null, loading: false, done: false };
for (let i = 0; i < 30 && !state.done; i++) await LOAD(state, api);
__assert(state.done, 'лента не дошла до конца за 30 подгрузок');
__assert(state.items.length === TOTAL, 'записей: ' + state.items.length);
__assert(state.items.every((x, i) => i === 0 || state.items[i - 1].id > x.id), 'порядок нарушен');
__assert(api.calls <= MAXCALLS, 'запросов к серверу: ' + api.calls);"""


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, method, kind = rng.choice(CTX)
    load = rng.choice(["loadMore", "loadNextPage", "fetchOlder", "onEndReached"])
    page_const = rng.choice(["PAGE", "PAGE_SIZE", "LIMIT"])
    size = rng.choice([10, 15, 20, 25])
    total = size * rng.randint(2, 4) + rng.randint(1, size - 1)
    done_first = rng.random() < 0.5
    good_cursor = f"  if (page.length > 0) state.cursor = page[page.length - 1].id;"
    bad_cursor = f"  if (page.length > 0) state.cursor = page[0].id;"
    done_line = f"  if (page.length < {page_const}) state.done = true;"

    def body(cur):
        mid = [done_line, cur] if done_first else [cur, done_line]
        return ([f"const {page_const} = {size};", "", f"async function {load}(state, api) {{",
                 "  if (state.loading || state.done) return;", "  state.loading = true;",
                 f"  const page = await api.{method}({{ before: state.cursor, limit: {page_const} }});",
                 "  for (const item of page) {", "    if (state.seen.has(item.id)) continue;",
                 "    state.seen.add(item.id);", "    state.items.push(item);", "  }"] + mid +
                ["  state.loading = false;", "}"])
    decoy = rng.choice(DECOYS)
    first = rng.random() < 0.5

    def assemble(cur):
        b = body(cur)
        return "\n".join((decoy + [""] + b) if first else (b + [""] + decoy))
    buggy, fixed = assemble(bad_cursor), assemble(good_cursor)
    diff = changed_lines(buggy, fixed)
    assert len(diff) == 1
    key_line = next(iter(diff))
    test = TEST.replace("MAXCALLS", str(-(-total // size) + 1)).replace("TOTAL", str(total)).replace("KIND", kind).replace("LOAD", load)
    pre = PRELUDE.replace("METHOD", method)
    checks = [Check(name="buggy_fails", runner="node", program=js_harness(buggy, test, pre), expect="fail"),
              Check(name="fixed_passes", runner="node", program=js_harness(fixed, test, pre), expect="pass",
                    embeds_display_code=False)]
    stem = (f"Экран «{ctx}» в мобильном приложении показывает записи от новых к старым и при прокрутке до конца "
            f"списка вызывает `{load}`. Сервер `api.{method}({{ before, limit }})` возвращает до `limit` записей "
            f"с id меньше `before` (без `before` — самые новые), упорядоченных по убыванию id. Жалоба: первая "
            f"страница показывается целиком, но дальше при каждой подгрузке в конец списка добавляется лишь "
            f"одна запись, запросов к серверу уходит в разы больше, чем страниц, и батарея садится быстрее. Укажите номер строки, которую достаточно исправить одной правкой, чтобы ошибка ушла.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=(f"Строка {key_line}: курсор следующей страницы берётся с первой (самой новой) "
                                f"записи страницы; запрос `before` с этим id отдаёт почти ту же страницу, сдвинутую на "
                                f"одну запись, повторы отбрасываются проверкой `seen` — за запрос добавляется одна "
                                f"запись. "
                                f"Курсор — id последней (самой старой) записи страницы."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="cursor_from_first",
                         params={"fixed_code": fixed, "page": size, "total": total})
