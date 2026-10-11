"""analyst.process.bottleneck_capacity_output — predict_output: узкое место процесса и его пропускная способность.

Процесс в текстовой записи (шаги по порядку, у каждого — число исполнителей и время на экземпляр), с
разветвлением XOR (часть экземпляров идёт на дополнительный шаг) и/или циклом доработки (после проверки доля
экземпляров уходит на исправление и возвращается на ту же проверку при каждом проходе). Нужно назвать номер
шага — узкого места — и сколько экземпляров в час процесс может принять без роста очереди (целая часть).
Нагрузка шага на один входящий экземпляр: основной путь — 1; ветка XOR — доля p; проверка с возвратом q —
1/(1−q); исправление — q/(1−q). Мощность шага = исполнители · 60 / время / нагрузка; процесс — минимум.
Числа подобраны так, что узкое место единственно и в большинстве вариантов не совпадает с шагом, у которого
наименьшая «голая» мощность (без учёта нагрузки). Ключ проверяется исполнением: Python разбирает показанную
запись процесса и считает точно (Fraction).
"""
from __future__ import annotations

from fractions import Fraction

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import py_literal_block

FAMILY_ID = "analyst.process.bottleneck_capacity_output"

# (процесс, экземпляр, основные шаги, шаг ветки XOR, шаг проверки, шаг исправления)
CTX = [("выдача кредитной карты", "заявка", ["Приём заявки", "Скоринг", "Выпуск карты"], "Ручная проверка",
        "Проверка документов", "Исправление анкеты"),
       ("подключение юрлица к эквайрингу", "заявка", ["Приём заявки", "Проверка компании", "Настройка терминала"],
        "Выезд на точку", "Проверка договора", "Доработка договора"),
       ("обработка возврата товара", "возврат", ["Регистрация возврата", "Приёмка на складе", "Выплата"],
        "Экспертиза качества", "Сверка документов", "Запрос недостающих документов"),
       ("онбординг сотрудника", "сотрудник", ["Оформление документов", "Выдача техники", "Вводный инструктаж"],
        "Оформление допуска", "Проверка оформления", "Исправление ошибок оформления"),
       ("рассмотрение страхового случая", "заявление", ["Приём заявления", "Оценка ущерба", "Выплата"],
        "Выезд эксперта", "Проверка комплекта", "Догрузка документов"),
       ("публикация объявления", "объявление", ["Приём объявления", "Модерация текста", "Публикация"],
        "Проверка фото вручную", "Проверка цены", "Правка объявления"),
       ("обработка обращения в поддержку", "обращение", ["Классификация", "Решение первой линией",
                                                          "Закрытие"], "Решение второй линией",
        "Контроль качества ответа", "Переписывание ответа"),
       ("выдача пропуска подрядчику", "заявка", ["Приём заявки", "Согласование с цехом", "Печать пропуска"],
        "Проверка службой безопасности", "Сверка списка", "Исправление списка")]

CALC = r'''
import re
from fractions import Fraction
steps = []
for l in PROCESS.strip().splitlines():
    m = re.match(r"(\d+)\. (.+?): (\d+) исп\., (\d+) мин(.*)$", l)
    if not m:
        continue
    no, name, w, t, rest = int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4)), m.group(5)
    steps.append(dict(no=no, w=w, t=t, rest=rest))
q_of = {}
for s in steps:
    m = re.search(r"(\d+) % .+ уходят на шаг", s["rest"])
    if m:
        q_of[s["no"]] = Fraction(int(m.group(1)), 100)
best = None
for s in steps:
    load = Fraction(1)
    m = re.search(r"только для (\d+) %", s["rest"])
    if m:
        load = Fraction(int(m.group(1)), 100)
    if s["no"] in q_of:
        load = 1 / (1 - q_of[s["no"]])
    m = re.search(r"только для возвращённых с шага (\d+)", s["rest"])
    if m:
        q = q_of[int(m.group(1))]
        load = q / (1 - q)
    cap = Fraction(s["w"] * 60, s["t"]) / load
    if best is None or cap < best[1]:
        best = (s["no"], cap)
print(best[0], best[1].numerator // best[1].denominator)
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    proc, inst, main, xor_name, check_name, fix_name = rng.choice(CTX)
    has_xor = rng.random() < 0.7
    has_loop = (not has_xor) or rng.random() < 0.6
    for _ in range(3000):
        # порядок: main[0], [main[1]], [XOR-ветка], [проверка, исправление], main[2]
        plan = [("main", main[0])]
        if rng.random() < 0.5 or not has_xor:
            plan.append(("main", main[1]))
        if has_xor:
            plan.append(("xor", xor_name))
        if has_loop:
            plan += [("check", check_name), ("fix", fix_name)]
        plan.append(("main", main[2]))
        p = Fraction(rng.choice([20, 25, 30, 40, 50]), 100)
        q = Fraction(rng.choice([20, 25, 40, 50]), 100)
        rows, caps, naive = [], [], []
        for kind, name in plan:
            w = rng.randint(1, 5)
            t = rng.choice([4, 5, 6, 8, 10, 12, 15, 20, 24, 30, 40])
            load = {"main": Fraction(1), "xor": p, "check": 1 / (1 - q), "fix": q / (1 - q)}[kind]
            rows.append((kind, name, w, t))
            naive.append(Fraction(w * 60, t))
            caps.append(Fraction(w * 60, t) / load)
        m = min(caps)
        if caps.count(m) != 1 or not 3 <= m <= 60:
            continue
        sorted_caps = sorted(caps)
        if sorted_caps[1] < m * Fraction(11, 10):
            continue  # второе место слишком близко — ответ хрупок к округлениям в уме
        bott = caps.index(m)
        if naive.index(min(naive)) == bott and rng.random() < 0.75:
            continue  # чаще всего «голое» узкое место должно вводить в заблуждение
        if naive.count(min(naive)) > 1 and naive.index(min(naive)) != bott and rng.random() < 0.5:
            continue
        break
    else:
        raise RuntimeError("нет процесса")
    nums = {i: i + 1 for i in range(len(rows))}
    check_no = next((nums[i] for i, r in enumerate(rows) if r[0] == "check"), None)
    xor_after = next((nums[i] - 1 for i, r in enumerate(rows) if r[0] == "xor"), None)
    lines = [f"Процесс «{proc}». {inst.capitalize()} проходит шаги по порядку; у шага — число исполнителей "
             f"(исп.) и среднее время одного исполнителя на экземпляр."]
    for i, (kind, name, w, t) in enumerate(rows):
        tail = ""
        if kind == "xor":
            tail = (f" — только для {int(p * 100)} % экземпляров (XOR после шага {xor_after}), остальные идут "
                    f"дальше без него")
        elif kind == "check":
            tail = (f" — после неё {int(q * 100)} % экземпляров уходят на шаг {nums[i] + 1} и возвращаются на шаг "
                    f"{nums[i]} (доля одна и та же при каждом проходе)")
        elif kind == "fix":
            tail = f" — только для возвращённых с шага {check_no}"
        lines.append(f"{nums[i]}. {name}: {w} исп., {t} мин{tail}")
    model = "\n".join(lines)
    out_s = f"{nums[bott]} {m.numerator // m.denominator}"
    prog = py_literal_block("PROCESS", model) + CALC
    checks = [Check(name="capacity", runner="python", program=prog, expect="stdout_equals", expected_stdout=out_s)]
    stem = ("Аналитик моделирует процесс (текстовая запись ниже), исполнители работают без простоев, экземпляры "
            "поступают равномерно. Какой шаг — узкое место и сколько экземпляров в час процесс может принимать "
            "без роста очереди? Ответ — номер шага и целая часть числа экземпляров в час через пробел, например "
            "`2 17`.")
    qd = f"{float(q):g}".replace(".", ",")
    loads = {"main": "1", "xor": f"{float(p):g}".replace(".", ","), "check": f"1/(1 − {qd})",
             "fix": f"{qd}/(1 − {qd})"}
    f1 = lambda x: f"{float(x):.1f}".replace(".", ",")  # noqa: E731
    expl = ("Мощность шага = исполнители · 60 / время / нагрузка на входящий экземпляр (основной путь — 1, ветка "
            "XOR — её доля, проверка с возвратом q — 1/(1 − q), исправление — q/(1 − q)). " +
            "; ".join(f"шаг {nums[i]}: {r[2]}·60/{r[3]} / {loads[r[0]]} = {f1(caps[i])}/ч"
                      for i, r in enumerate(rows)) +
            f". Минимум — шаг {nums[bott]}: {f1(m)} в час → {m.numerator // m.denominator}.")
    ak = AnswerKey(kind="output", value=out_s, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=model, answer_key=ak, context=proc,
                         verification="execution", checks=checks, language="text",
                         params={"xor": has_xor, "loop": has_loop, "rows": [list(r) for r in rows],
                                 "p": str(p), "q": str(q)})
