"""frontend.state.optimistic_rollback_fix — choose_fix: откат оптимистичного обновления при ошибке запроса.

Порог Middle/Senior. Показанный код перед запросом запоминает весь список и при ошибке возвращает его целиком —
пропадают изменения, подтверждённые за время запроса (переименование того же элемента, новый элемент сверху).
Варианты замены (состав фиксирован, один подтип):
* верный — по id откатить только своё поле к прежнему значению;
* восстановить снимок элемента по id — теряется параллельное переименование того же элемента;
* откат по индексу, запомненному до запроса, — после вставки сверху откатывается чужой элемент;
* откат по id и полю, но поверх списка, запомненного до запроса, — те же потерянные изменения, что и у снимка.
Проверка исполнением (Node): запрос по первому элементу висит, параллельно подтверждаются переименование и вставка,
затем запрос падает; итоговое состояние сверяется. Второй сценарий — успешный запрос.
"""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from assessment_bank.families.common._plus_utils import fix_options_variant

FAMILY_ID = "frontend.state.optimistic_rollback_fix"

# (контекст, коллекция, поле, метод API, функция)
CONTEXTS = [("список задач", "tasks", "done", "setDone", "toggleDone"),
            ("лента сообщений", "messages", "pinned", "setPinned", "togglePin"),
            ("каталог товаров", "products", "favorite", "setFavorite", "toggleFavorite"),
            ("доска карточек", "cards", "archived", "setArchived", "toggleArchive"),
            ("список заметок", "notes", "starred", "setStarred", "toggleStar"),
            ("почтовый ящик", "letters", "read", "setRead", "toggleRead")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, coll, field, method, fn = rng.choice(CONTEXTS)
    st = rng.choice(["state", "store", "model"])
    it = rng.choice(["i", "x", "item"])
    err = rng.choice(["e", "err", "error"])
    cl = rng.choice(["api", "client", "backend"])
    prelude = f"const {st} = {{ {coll}: [] }};"

    def func(prep: list[str], rollback: str) -> str:
        lines = [f"async function {fn}({cl}, id) {{"] + [f"  {p}" for p in prep] + [
            f"  {st}.{coll} = {st}.{coll}.map({it} => {it}.id === id ? {{ ...{it}, {field}: !prev }} : {it});",
            "  try {", f"    await {cl}.{method}(id, !prev);", f"  }} catch ({err}) {{", f"    {rollback}", "  }", "}"]
        return "\n".join(lines) + "\n"

    find_prev = f"const prev = {st}.{coll}.find({it} => {it}.id === id).{field};"
    buggy = prelude + "\n\n" + func([f"const before = {st}.{coll};", find_prev], f"{st}.{coll} = before;")
    correct = func([find_prev], f"{st}.{coll} = {st}.{coll}.map({it} => {it}.id === id ? {{ ...{it}, {field}: prev }} : {it});")
    distractors = [
        func([f"const before = {st}.{coll}.find({it} => {it}.id === id);", f"const prev = before.{field};"],
             f"{st}.{coll} = {st}.{coll}.map({it} => {it}.id === id ? before : {it});"),
        func([f"const idx = {st}.{coll}.findIndex({it} => {it}.id === id);", f"const prev = {st}.{coll}[idx].{field};"],
             f"{st}.{coll} = {st}.{coll}.map(({it}, k) => k === idx ? {{ ...{it}, {field}: prev }} : {it});"),
        func([f"const list = {st}.{coll};", find_prev],
             f"{st}.{coll} = list.map({it} => {it}.id === id ? {{ ...{it}, {field}: prev }} : {it});"),
    ]
    a, b, c = rng.sample(range(10, 99), 3)
    t_old, t_new = rng.choice([("Черновик", "Черновик v2"), ("План", "План на неделю"), ("Отчёт", "Отчёт за квартал"),
                               ("Идея", "Идея (уточнено)")])
    neighbour_on = rng.random() < 0.5
    test = f"""
let rejectFirst;
const api = {{ {method}: (id, v) => id === {a} ? new Promise((_, rej) => {{ rejectFirst = rej; }}) : Promise.resolve(true) }};
{st}.{coll} = [{{ id: {a}, title: {t_old!r}, {field}: false }}, {{ id: {b}, title: 'B', {field}: {str(neighbour_on).lower()} }}];
const pending = {fn}(api, {a});
{st}.{coll} = {st}.{coll}.map(y => y.id === {a} ? {{ ...y, title: {t_new!r} }} : y);
{st}.{coll} = [{{ id: {c}, title: 'C', {field}: false }}, ...{st}.{coll}];
rejectFirst(new Error('503'));
await pending;
const first = {st}.{coll}.find(y => y.id === {a});
const added = {st}.{coll}.find(y => y.id === {c});
__assert({st}.{coll}.length === 3, 'length');
__assert(first.title === {t_new!r}, 'title');
__assert(first.{field} === false, 'rollback');
__assert(added && added.{field} === false, 'added');
await {fn}(api, {b});
__assert({st}.{coll}.find(y => y.id === {b}).{field} === {str(not neighbour_on).lower()}, 'success');
"""
    stem = (f"JavaScript, интерфейс ({ctx}). `{fn}` сразу меняет поле `{field}` в `{st}.{coll}`, а при ошибке "
            f"запроса должна вернуть прежнее значение. Пользователи жалуются: если запрос падает, пропадают "
            f"изменения, которые успели прийти за это время (переименование, новые элементы сверху списка). "
            f"Какая замена функции исправляет откат?")
    why = ("Откатывать нужно только своё изменение: найти элемент по id в текущем (уже изменившемся) списке и вернуть "
           f"полю `{field}` прежнее значение. Возврат снимка всего списка или снимка элемента затирает подтверждённые "
           "параллельные изменения (переименование), откат по индексу после вставки сверху попадает в другой элемент, "
           "а точечный откат поверх списка, запомненного до запроса, — тот же снимок.")
    return fix_options_variant(FAMILY_ID, seed, rng, stem=stem, buggy=buggy, correct=correct,
                               distractors=distractors, test=test, prelude=prelude, runner="node", context=ctx,
                               defect="optimistic_rollback_snapshot", why=why,
                               params={"ids": [a, b, c], "neighbour_on": neighbour_on})
