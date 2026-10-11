"""analyst.bpmn.join_mismatch_bug — find_bug: тип шлюза-слияния не соответствует разветвлению.

Текстовая модель BPMN из 2–4 блоков: параллельные (AND-разветвление → ветви → AND-слияние) и
исключающие (XOR-разветвление по условию → ветви → XOR-слияние). В одном блоке тип слияния перепутан:
AND-разветвление со слиянием XOR — задачи после слияния выполняются дважды; XOR-разветвление со слиянием AND
— экземпляр зависает (слияние ждёт фишку из невыбранной ветви). Симптом в условии не дан: нужно проверить
модель на корректность самому. Один подтип дефекта — несоответствие слияния разветвлению. Ключ проверяется
исполнением: игра фишек на Python по показанной модели для всех значений условий.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import py_literal_block

FAMILY_ID = "analyst.bpmn.join_mismatch_bug"

SIM = r'''
import itertools, re
flow, conds = {}, {}
incoming = {}
for l in MODEL.strip().splitlines():
    s = l.strip()
    if "->" not in s or s.startswith("задачи"):
        continue
    m = re.match(r"(\S+) \(XOR-разветвление\): (\S+) = (\S+) -> (\S+); иначе -> (\S+)$", s)
    if m:
        g, var, val, a, b = m.groups()
        flow[g] = ("xor_split", var, val, a, b)
        conds[var] = None
        targets = [a, b]
    else:
        m = re.match(r"(\S+)(?: \((AND-разветвление|AND-слияние|XOR-слияние)\))? -> (.+)$", s)
        g, kind, rest = m.groups()
        targets = [t.strip() for t in rest.split(",")]
        flow[g] = ({"AND-разветвление": "and_split", "AND-слияние": "and_join",
                    "XOR-слияние": "xor_join", None: "seq"}[kind], targets)
    for t in targets:
        incoming[t] = incoming.get(t, 0) + 1

def run(data):
    tokens = [("СТАРТ", None)]
    waiting = {}
    done = []
    ends = 0
    steps = 0
    while tokens and steps < 500:
        steps += 1
        node, _ = tokens.pop(0)
        if node == "КОНЕЦ":
            ends += 1
            continue
        if node.startswith("T"):
            done.append(node)
        f = flow[node]
        if f[0] == "xor_split":
            tokens.append((f[3] if data[f[1]] == f[2] else f[4], node))
        elif f[0] == "and_join":
            waiting[node] = waiting.get(node, 0) + 1
            if waiting[node] == incoming[node]:
                waiting[node] = 0
                tokens.extend((t, node) for t in f[1])
        else:
            tokens.extend((t, node) for t in f[1])
    stuck = sum(waiting.values())
    return ends == 1 and stuck == 0 and len(done) == len(set(done)), done, ends, stuck

ok = True
for vals in itertools.product(["да", "нет"], repeat=len(conds)):
    data = dict(zip(sorted(conds), vals))
    good, done, ends, stuck = run(data)
    ok = ok and good
print("RESULT: PASS" if ok else "RESULT: FAIL")
'''

CTX = {
    "выполнение заказа": [
        ("and", [["Собрать заказ на складе"], ["Выставить счёт", "Отправить счёт клиенту"]]),
        ("xor", "оплата_онлайн", ["Проверить поступление оплаты"], ["Отметить оплату при получении"]),
        ("and", [["Упаковать заказ"], ["Распечатать накладную"]]),
        ("xor", "доставка_курьером", ["Вызвать курьера"], ["Передать в пункт выдачи"])],
    "приём сотрудника": [
        ("and", [["Подготовить рабочее место"], ["Оформить пропуск"], ["Создать учётную запись"]]),
        ("xor", "удалённая_работа", ["Отправить ноутбук курьером"], ["Выдать ноутбук в офисе"]),
        ("and", [["Провести вводный инструктаж"], ["Назначить наставника"]]),
        ("xor", "испытательный_срок", ["Составить план испытательного срока"], ["Согласовать план развития"])],
    "страховой случай": [
        ("xor", "нужен_осмотр", ["Назначить осмотр эксперта", "Получить акт осмотра"], ["Принять фото от клиента"]),
        ("and", [["Проверить полис"], ["Запросить справку из ГИБДД"]]),
        ("xor", "сумма_крупная", ["Согласовать выплату с андеррайтером"], ["Утвердить выплату автоматически"]),
        ("and", [["Перечислить выплату"], ["Уведомить клиента"]])],
    "открытие счёта юрлицу": [
        ("and", [["Проверить учредительные документы"], ["Проверить руководителя по спискам"]]),
        ("xor", "нерезидент", ["Запросить валютный контроль"], ["Пропустить валютный контроль"]),
        ("and", [["Открыть счёт в АБС"], ["Подключить интернет-банк"]]),
        ("xor", "нужна_карта", ["Выпустить корпоративную карту"], ["Отправить реквизиты счёта"])],
    "возврат товара": [
        ("xor", "товар_с_браком", ["Провести экспертизу качества", "Оформить акт брака"], ["Проверить товарный вид"]),
        ("and", [["Принять товар на склад"], ["Сформировать заявку на возврат денег"]]),
        ("xor", "оплата_картой", ["Вернуть деньги на карту"], ["Выдать наличные в кассе"]),
        ("and", [["Списать товар или вернуть в продажу"], ["Отправить клиенту чек возврата"]])],
    "проведение мероприятия": [
        ("and", [["Забронировать площадку"], ["Пригласить спикеров"], ["Запустить регистрацию"]]),
        ("xor", "участников_больше_100", ["Заказать охрану"], ["Назначить дежурного администратора"]),
        ("and", [["Подготовить раздаточные материалы"], ["Настроить трансляцию"]]),
        ("xor", "платное_участие", ["Сверить оплаты участников"], ["Разослать напоминания"])],
}
FIRST = {"выполнение заказа": "Принять заказ", "приём сотрудника": "Подписать трудовой договор",
         "страховой случай": "Зарегистрировать обращение", "открытие счёта юрлицу": "Принять заявку",
         "возврат товара": "Принять заявление на возврат", "проведение мероприятия": "Утвердить смету"}
LAST = {"выполнение заказа": "Закрыть заказ", "приём сотрудника": "Закрыть заявку на приём",
        "страховой случай": "Закрыть страховое дело", "открытие счёта юрлицу": "Сообщить клиенту об открытии",
        "возврат товара": "Закрыть заявление", "проведение мероприятия": "Собрать обратную связь"}


def _build(ctx, blocks, bad_idx, flip, opts):
    tasks, lines, code_of = [], [], {}

    def t(name):
        if name not in code_of:
            code_of[name] = f"T{len(code_of) + 1}"
            tasks.append(f"  {code_of[name]}  {name}")
        return code_of[name]
    g = 0
    prev = t(FIRST[ctx])
    lines.append(f"СТАРТ -> {prev}")
    for bi, b in enumerate(blocks):
        g += 1
        split = f"G{g}"
        g += 1
        join = f"G{g}"
        if opts["extra"].get(bi):
            e = t(opts["extra"][bi])
            lines.append(f"{prev} -> {e}")
            prev = e
        lines.append(f"{prev} -> {split}")
        if b[0] == "and":
            branches = [b[1][i] for i in opts["perm"][bi][:len(b[1])]] if len(b[1]) == len(opts["perm"][bi]) \
                else b[1]
            heads = [t(br[0]) for br in branches]
            lines.append(f"{split} (AND-разветвление) -> {', '.join(heads)}")
        else:
            neg = opts["neg"][bi]
            branches = [b[3], b[2]] if neg else [b[2], b[3]]
            heads = [t(br[0]) for br in branches]
            lines.append(f"{split} (XOR-разветвление): {b[1]} = {'нет' if neg else 'да'} -> {heads[0]}; "
                         f"иначе -> {heads[1]}")
        for br in branches:
            codes = [t(n) for n in br]
            for x, y in zip(codes, codes[1:]):
                lines.append(f"{x} -> {y}")
            lines.append(f"{codes[-1]} -> {join}")
        jt = "AND" if b[0] == "and" else "XOR"
        if bi == bad_idx and flip:
            jt = "XOR" if jt == "AND" else "AND"
        nxt = None
        lines.append(f"{join} ({jt}-слияние) -> @NEXT@")
        prev = join
    last = t(LAST[ctx])
    lines = [l.replace("@NEXT@", "@") for l in lines]
    # подставить «следующий» после каждого слияния: следующий блок начинается со «X -> Gk», где X — слияние
    out, pending = [], None
    for l in lines:
        if l.endswith("-> @"):
            pending = l[:-1]
            continue
        if pending is not None and l.split(" -> ")[0] == pending.split(" (")[0]:
            out.append(pending + l.split(" -> ")[1])
            pending = None
            continue
        out.append(l)
    if pending is not None:
        out.append(pending + last)
    out.append(f"{last} -> КОНЕЦ")
    del nxt
    return "задачи:\n" + "\n".join(tasks) + "\nпоток:\n" + "\n".join(f"  {l}" for l in out)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(sorted(CTX))
    allb = CTX[ctx]
    for _ in range(100):
        idx = sorted(rng.sample(range(len(allb)), rng.choice([2, 3, 4])))
        blocks = [allb[i] for i in idx]
        if {b[0] for b in blocks} == {"and", "xor"}:
            break
    bad_idx = rng.randrange(len(blocks))
    perm = []
    for b in blocks:
        n = len(b[1]) if b[0] == "and" else 2
        p = list(range(n))
        rng.shuffle(p)
        perm.append(p)
    extras = {"выполнение заказа": "Зарезервировать товар", "приём сотрудника": "Внести данные в кадровую систему",
              "страховой случай": "Проверить срок действия полиса", "открытие счёта юрлицу": "Сверить анкету",
              "возврат товара": "Проверить срок возврата", "проведение мероприятия": "Согласовать программу"}
    ex = {}
    if rng.random() < 0.6:
        ex[rng.randrange(len(blocks))] = extras[ctx]
    opts = {"perm": perm, "neg": [rng.random() < 0.4 for _ in blocks], "extra": ex}
    buggy = _build(ctx, blocks, bad_idx, True, opts)
    fixed = _build(ctx, blocks, bad_idx, False, opts)
    diff = changed_lines(buggy, fixed)
    assert len(diff) == 1, diff
    key_line = next(iter(diff))
    checks = [Check(name="buggy_fails", runner="python", program=py_literal_block("MODEL", buggy) + SIM, expect="fail"),
              Check(name="fixed_passes", runner="python", program=py_literal_block("MODEL", fixed) + SIM,
                    expect="pass", embeds_display_code=False)]
    kind = blocks[bad_idx][0]
    stem = (f"Аналитик описал процесс «{ctx}» текстовой моделью BPMN. Обозначения: AND-разветвление запускает все "
            f"ветви; AND-слияние ждёт фишки из всех входящих ветвей и пропускает одну; XOR-разветвление выбирает "
            f"одну ветвь по условию; XOR-слияние пропускает каждую пришедшую фишку сразу. Требование к модели: "
            f"при любых значениях условий экземпляр завершается ровно один раз, ни одна задача не выполняется "
            f"дважды. В модели одна ошибка. Укажите номер строки с ней.")
    if kind == "and":
        why = ("после AND-разветвления все ветви выполняются параллельно, а XOR-слияние пропускает фишку каждой "
               "ветви — задачи после слияния выполнятся несколько раз. Нужно AND-слияние")
    else:
        why = ("после XOR-разветвления приходит фишка только из выбранной ветви, а AND-слияние ждёт все ветви — "
               "экземпляр зависнет. Нужно XOR-слияние")
    ak = AnswerKey(kind="line", value=key_line, explanation=f"Строка {key_line}: {why}.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="join_mismatch", language="text",
                         params={"fixed_code": fixed, "blocks": [b[0] for b in blocks], "bad_block": bad_idx})
