"""analyst.lead.state_model_bug — find_bug (Lead): текстовая модель состояний заявки нарушает требование повторного одобрения.

Кандидату показана модель жизненного цикла (≈ 22 строки: состояния, начало, конечные, переходы с событиями и
условиями) и четыре требования. Ровно одно требование нарушено ровно одной строкой перехода: переход обходит
обязательное одобрение — либо возврат с доработки ведёт сразу к подписанию (``rework_to_sign``), либо «ускоренное
оформление» ведёт из проверки к подписанию (``review_to_sign``). Тип дефекта один — «переход в обход одобрения»;
место и окружение меняются, порядок строк перемешан. Подозрительные, но верные строки (пересмотр после одобрения,
возврат на доработку после подписания, повторная подача после отказа) остаются.

Ключ проверяется исполнением модели на Python: программа содержит показанную модель дословно, разбирает её и
проверяет все четыре требования (обход графа «состояние × одобрено после последней доработки × подписано после
одобрения»); показанная модель не проходит, исправленная — проходит.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "analyst.lead.state_model_bug"

ROLES = ("DRAFT", "SUBMITTED", "REVIEW", "REWORK", "APPROVED", "SIGNED", "ISSUED", "CLOSED", "REJECTED", "WITHDRAWN")
DOMAINS = [
    ("кредитная заявка", dict(DRAFT="Черновик", SUBMITTED="Подана", REVIEW="Проверка", REWORK="Доработка",
                              APPROVED="Одобрена", SIGNED="Договор подписан", ISSUED="Кредит выдан",
                              CLOSED="Закрыта", REJECTED="Отказ", WITHDRAWN="Отозвана"),
     dict(sign="подписать договор", issue="выдать кредит", approve="одобрить [скоринг пройден]")),
    ("страховой случай", dict(DRAFT="Черновик", SUBMITTED="Заявлен", REVIEW="Экспертиза", REWORK="Запрос документов",
                              APPROVED="Выплата согласована", SIGNED="Акт подписан", ISSUED="Выплачено",
                              CLOSED="Закрыт", REJECTED="Отказ в выплате", WITHDRAWN="Отозван"),
     dict(sign="подписать акт", issue="перечислить выплату", approve="согласовать выплату [экспертиза завершена]")),
    ("закупка", dict(DRAFT="Черновик", SUBMITTED="Заявка подана", REVIEW="Согласование", REWORK="На доработке",
                     APPROVED="Согласована", SIGNED="Договор заключён", ISSUED="Оплачена", CLOSED="Исполнена",
                     REJECTED="Отклонена", WITHDRAWN="Отменена"),
     dict(sign="заключить договор", issue="оплатить", approve="согласовать [бюджет подтверждён]")),
    ("возврат средств", dict(DRAFT="Черновик", SUBMITTED="Запрошен", REVIEW="Проверка", REWORK="Уточнение",
                             APPROVED="Возврат одобрен", SIGNED="Реквизиты подтверждены", ISSUED="Деньги отправлены",
                             CLOSED="Завершён", REJECTED="Отказ", WITHDRAWN="Отозван"),
     dict(sign="подтвердить реквизиты", issue="отправить деньги", approve="одобрить [чек найден]")),
    ("заявка на лимит", dict(DRAFT="Черновик", SUBMITTED="Подана", REVIEW="Анализ риска", REWORK="Доп. сведения",
                             APPROVED="Лимит одобрен", SIGNED="Дополнение подписано", ISSUED="Лимит установлен",
                             CLOSED="Закрыта", REJECTED="Отказ", WITHDRAWN="Отозвана"),
     dict(sign="подписать дополнение", issue="установить лимит", approve="одобрить [риск в пределах]")),
]

WORDS = {  # синонимы событий и условий: варианты различаются видимым текстом модели, а не только порядком строк
    "submit": ["подать [обязательные поля заполнены]", "отправить [анкета заполнена]",
               "направить на рассмотрение [документы приложены]", "подать [согласие на обработку данных получено]"],
    "take": ["взять в работу", "назначить исполнителя", "начать проверку [исполнитель свободен]", "принять к рассмотрению"],
    "reject": ["отказать", "отклонить [основание указано]", "отказать [по результатам проверки]", "вынести отказ"],
    "rework": ["запросить сведения", "вернуть на доработку", "запросить документы [не хватает данных]",
               "направить запрос клиенту"],
    "back": ["сведения получены", "документы предоставлены", "доработка завершена", "ответ клиента получен"],
    "reconsider": ["пересмотр [изменились условия]", "пересмотреть [изменилась сумма]",
                   "вернуть на проверку [новые сведения]", "пересмотр [запрос службы рисков]"],
    "changed": ["клиент изменил данные", "изменение условий по запросу клиента", "клиент запросил другие условия",
                "выявлено расхождение данных"],
    "close": ["закрыть", "завершить", "закрыть [обязательства исполнены]", "перевести в архив"],
    "cancel": ["отозвать", "отменить по запросу клиента", "отозвать [запрос клиента]"],
    "fast": ["ускоренное оформление", "упрощённый порядок", "быстрая обработка", "экспресс-процедура"],
}

PROGRAM = '''MODEL = """
{model}
"""
ROLE = {roles!r}
CANCEL_FROM = ("SUBMITTED", "REVIEW", "REWORK", "APPROVED")
NAME = {{v: k for k, v in ROLE.items()}}


def parse(text):
    states, start, finals, trans = [], None, [], []
    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith("СОСТОЯНИЯ:"):
            states = [s.strip() for s in line.split(":", 1)[1].split(",")]
        elif line.startswith("НАЧАЛО:"):
            start = line.split(":", 1)[1].strip()
        elif line.startswith("КОНЕЧНЫЕ:"):
            finals = [s.strip() for s in line.split(":", 1)[1].split(",")]
        elif "->" in line:
            src, rest = line.split("->", 1)
            dst = rest.split(":", 1)[0]
            trans.append((src.strip(), dst.strip()))
    return states, start, finals, trans


states, start, finals, trans = parse(MODEL)
succ = {{}}
for a, b in trans:
    succ.setdefault(a, []).append(b)
ok = True
# 1) выдача — только после подписания, подписание — только после одобрения; после доработки — снова одобрение
seen, stack = set(), [(start, False, False)]
while stack:
    node, appr, signed = stack.pop()
    if (node, appr, signed) in seen:
        continue
    seen.add((node, appr, signed))
    role = NAME.get(node)
    if role == "ISSUED" and not (appr and signed):
        ok = False
    if role == "SIGNED" and not appr:
        ok = False
    for nxt in succ.get(node, []):
        r = NAME.get(nxt)
        a2, s2 = appr, signed
        if r == "REWORK":
            a2, s2 = False, False
        elif r == "APPROVED":
            a2, s2 = True, False
        elif r == "SIGNED":
            s2 = appr
        stack.append((nxt, a2, s2))
# 2) отзыв из состояний до подписания
for r in CANCEL_FROM:
    if ROLE["WITHDRAWN"] not in succ.get(ROLE[r], []):
        ok = False
# 3) из конечных состояний переходов нет
for f in finals:
    if succ.get(f):
        ok = False
# 4) все состояния достижимы
reach, todo = {{start}}, [start]
while todo:
    for nxt in succ.get(todo.pop(), []):
        if nxt not in reach:
            reach.add(nxt)
            todo.append(nxt)
if set(states) - reach:
    ok = False
print("RESULT: PASS" if ok else "RESULT: FAIL")
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    dom, S, ev = rng.choice(DOMAINS)
    subtype = rng.choice(["rework_to_sign", "review_to_sign"])
    days = rng.choice([14, 30, 60, 90])
    limit = rng.choice([50, 100, 300, 500])
    T = lambda a, b, e: f"{S[a]} -> {S[b]} : {e}"  # noqa: E731
    w = {k: rng.choice(v) for k, v in WORDS.items()}
    cancel = w["cancel"]
    base = [
        T("DRAFT", "SUBMITTED", w["submit"]),
        T("SUBMITTED", "REVIEW", w["take"]),
        T("REVIEW", "APPROVED", ev["approve"]),
        T("REVIEW", "REJECTED", w["reject"]),
        T("REVIEW", "REWORK", w["rework"]),
        T("APPROVED", "SIGNED", ev["sign"]),
        T("APPROVED", "REVIEW", w["reconsider"]),
        T("SIGNED", "REWORK", w["changed"]),
        T("SIGNED", "ISSUED", ev["issue"]),
        T("ISSUED", "CLOSED", w["close"]),
        T("REJECTED", "SUBMITTED", f"повторная подача [не позже {days} дней после отказа]"),
        T("SUBMITTED", "WITHDRAWN", cancel),
        T("REVIEW", "WITHDRAWN", cancel),
        T("REWORK", "WITHDRAWN", cancel),
        T("APPROVED", "WITHDRAWN", cancel),
    ]
    good_rework = T("REWORK", "REVIEW", w["back"])
    if subtype == "rework_to_sign":
        bad, fix = T("REWORK", "SIGNED", w["back"]), good_rework
        lines = base + [bad]
    else:
        bad = T("REVIEW", "SIGNED", f"{w['fast']} [сумма не больше {limit} тыс. ₽]")
        fix = T("REVIEW", "APPROVED", f"{w['fast']}: одобрение [сумма не больше {limit} тыс. ₽]")
        lines = base + [good_rework, bad]
    rng.shuffle(lines)
    header = [f"СОСТОЯНИЯ: {', '.join(S[r] for r in ROLES)}", f"НАЧАЛО: {S['DRAFT']}",
              f"КОНЕЧНЫЕ: {S['CLOSED']}, {S['WITHDRAWN']}", "ПЕРЕХОДЫ:"]
    code = "\n".join(header + lines)
    fixed = code.replace(bad, fix)
    key = header.__len__() + lines.index(bad) + 1
    roles = {r: S[r] for r in ROLES}
    reqs = [f"«{S['ISSUED']}» — только после «{S['SIGNED']}», а «{S['SIGNED']}» — только после «{S['APPROVED']}»; "
            f"после любого возврата в «{S['REWORK']}» заявка снова проходит одобрение",
            f"до подписания (из «{S['SUBMITTED']}», «{S['REVIEW']}», «{S['REWORK']}», «{S['APPROVED']}») клиент "
            f"может отозвать заявку",
            "из конечных состояний переходов нет", "все состояния достижимы из начального"]
    rng.shuffle(reqs)
    stem = (f"Аналитик описал жизненный цикл («{dom}») текстовой моделью: строки «Откуда -> Куда : событие "
            f"[условие]». Требования: " + "; ".join(f"({i}) {r}" for i, r in enumerate(reqs, 1)) +
            ". Модель нарушает одно из требований. В какой строке переход, который нужно исправить?")
    expl = (f"Строка {key}: «{bad}» — путь к «{S['SIGNED']}» и «{S['ISSUED']}» без (повторного) одобрения "
            + ("после доработки: заявка, изменённая клиентом после подписания, снова подписывается без "
               "одобрения" if subtype == "rework_to_sign" else "из проверки: ускоренное оформление пропускает "
               "одобрение") + f". Исправление: «{fix}». Пересмотр «{S['APPROVED']} -> {S['REVIEW']}» и возврат "
            f"«{S['SIGNED']} -> {S['REWORK']}» требований не нарушают: дальше путь снова идёт через одобрение.")
    checks = [Check(name="model_buggy", runner="python", program=PROGRAM.format(model=code, roles=roles),
                    expect="fail"),
              Check(name="model_fixed", runner="python", program=PROGRAM.format(model=fixed, roles=roles),
                    expect="pass", embeds_display_code=False)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code,
                         answer_key=AnswerKey(kind="line", value=key, explanation=expl),
                         context=dom, verification="execution", checks=checks, defect_type="approval_bypass",
                         params={"fixed_code": fixed, "subtype": subtype},
                         display_code_note="Модель на Python разбирает показанную модель дословно и проверяет все "
                                           "четыре требования обходом графа состояний.")
