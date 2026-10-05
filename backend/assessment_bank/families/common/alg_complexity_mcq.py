"""common.alg.complexity_mcq — mcq_concept: асимптотика функции по времени (с «ловушками»).

Ключ проверяется исполнением: показанная функция запускается дословно на входах размера
100 и 400, число исполненных строк считается через sys.settrace, а скрытая стоимость
встроенных операций (list.insert(0, …), list.pop(0), list.index, сортировка) — через
sys.setprofile по модели CPython. Класс сложности определяется по отношению стоимостей.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, dedent, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.alg.complexity_mcq"

CLASSES = ["O(log n)", "O(n)", "O(n log n)", "O(n²)"]

# (имя шаблона, класс, код с {fn}/{arg}, описание n, вход: "list"|"sorted"|"int", пояснение)
TEMPLATES = [
    ("pairs", "O(n²)", """\
        def {fn}({arg}, target):
            count = 0
            for i in range(len({arg})):
                for j in range(i + 1, len({arg})):
                    if {arg}[i] + {arg}[j] == target:
                        count += 1
            return count""", "list",
     "два вложенных цикла по парам i < j — n(n−1)/2 итераций"),
    ("two_pointers", "O(n)", """\
        def {fn}({arg}, target):
            i, j = 0, len({arg}) - 1
            count = 0
            while i < j:
                s = {arg}[i] + {arg}[j]
                if s == target:
                    count += 1
                    i += 1
                elif s < target:
                    i += 1
                else:
                    j -= 1
            return count""", "sorted",
     "каждый шаг цикла сдвигает i или j, всего не больше n шагов"),
    ("set_dedupe", "O(n)", """\
        def {fn}({arg}):
            seen = set()
            result = []
            for x in {arg}:
                if x not in seen:
                    seen.add(x)
                    result.append(x)
            return result""", "list",
     "проверка и добавление в set — в среднем O(1), один проход"),
    ("insert_front", "O(n²)", """\
        def {fn}({arg}):
            result = []
            for x in {arg}:
                if x % 2 == 0:
                    result.insert(0, x)
                else:
                    result.append(x)
            return result""", "list",
     "list.insert(0, x) сдвигает все элементы списка — O(n) на вставку"),
    ("pop_front", "O(n²)", """\
        def {fn}({arg}):
            pending = list({arg})
            total = 0
            while pending:
                x = pending.pop(0)
                total += x
            return total""", "list",
     "list.pop(0) сдвигает оставшиеся элементы — O(n) на извлечение; нужен collections.deque"),
    ("sort_scan", "O(n log n)", """\
        def {fn}({arg}):
            ordered = sorted({arg})
            dups = 0
            for k in range(1, len(ordered)):
                if ordered[k] == ordered[k - 1]:
                    dups += 1
            return dups""", "list",
     "сортировка O(n log n) доминирует над линейным проходом"),
    ("binary_search", "O(log n)", """\
        def {fn}({arg}, x):
            lo, hi = 0, len({arg})
            while lo < hi:
                mid = (lo + hi) // 2
                if {arg}[mid] < x:
                    lo = mid + 1
                else:
                    hi = mid
            return lo""", "sorted",
     "интервал поиска делится пополам на каждой итерации"),
    ("fixed_inner", "O(n)", """\
        def {fn}({arg}):
            counts = []
            for x in {arg}:
                row = 0
                for d in range(7):
                    if (x + d) % 7 == 0:
                        row += 1
                counts.append(row)
            return counts""", "list",
     "внутренний цикл — ровно 7 итераций, константа; итог линейный"),
    ("doubling_inner", "O(n log n)", """\
        def {fn}({arg}):
            total = 0
            for i in range(len({arg})):
                step = 1
                while i + step < len({arg}):
                    total += {arg}[i + step]
                    step *= 2
            return total""", "list",
     "внутренний шаг удваивается — O(log n) итераций на каждый из n элементов"),
    ("index_lookup", "O(n²)", """\
        def {fn}({arg}):
            positions = []
            for x in {arg}:
                positions.append({arg}.index(x))
            return positions""", "list",
     "list.index — линейный поиск внутри цикла по n элементам"),
]

CONTEXTS = [("prices", "цены в корзинах"), ("scores", "оценки за тест"),
            ("durations", "длительности запросов"), ("user_ids", "идентификаторы пользователей"),
            ("timestamps", "метки времени событий"), ("sizes", "размеры файлов")]
FN_NAMES = ["analyze", "process", "collect", "scan", "summarize", "build_report", "compute", "prepare"]

HARNESS = """

import sys as __s


def __bank_cost(call, arg):
    cnt = [0]
    target = call.__code__

    def tr(frame, event, a):
        if frame.f_code is target:
            if event == "line":
                cnt[0] += 1
            return tr
        return None

    def prof(frame, event, a):
        if event != "c_call":
            return
        name = getattr(a, "__name__", "")
        owner = getattr(a, "__self__", None)
        if isinstance(owner, list) and name in ("insert", "pop", "index", "remove"):
            cnt[0] += len(owner)
        elif name in ("sorted", "sort"):
            seq = owner if isinstance(owner, list) else None
            m = len(seq) if seq is not None else len(arg)
            cnt[0] += int(m * max(1.0, __import__("math").log2(max(m, 2))))

    __s.settrace(tr)
    __s.setprofile(prof)
    try:
        call(*__bank_args(arg))
    finally:
        __s.settrace(None)
        __s.setprofile(None)
    return cnt[0]


def __bank_input(n):
    x, out = 12345, []
    for _ in range(n):
        x = (x * 1103515245 + 12345) % 2147483648
        out.append(x % 1000)
    return sorted(out) if __BANK_KIND == "sorted" else out


c1 = __bank_cost({fn}, __bank_input(100))
c2 = __bank_cost({fn}, __bank_input(400))
r = c2 / c1
print("O(log n)" if r < 2.5 else "O(n)" if r < 4.5 else "O(n log n)" if r < 8 else "O(n²)")
"""


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    name, cls, tpl, kind, why = rng.choice(TEMPLATES)
    arg, ctx = rng.choice(CONTEXTS)
    fn = rng.choice(FN_NAMES)
    week = rng.choice([7, 12, 24, 31])
    tpl = tpl.replace("range(7)", f"range({week})").replace("% 7 ==", f"% {week} ==")
    code = dedent(tpl.format(fn=fn, arg=arg))
    extra = {"pairs": "lambda a: (a, 1000)", "two_pointers": "lambda a: (a, 1000)",
             "binary_search": "lambda a: (a, 500)"}.get(name, "lambda a: (a,)")
    program = (code + "\n\n__BANK_KIND = " + repr(kind) + "\n__bank_args = " + extra
               + HARNESS.replace("{fn}", fn))
    distr = [c for c in CLASSES if c != cls]
    opts, key = make_options(rng, (cls, None), [(d, None) for d in distr])
    sorted_note = " Список на входе уже отсортирован по возрастанию." if kind == "sorted" else ""
    stem = (f"Функция обрабатывает список `{arg}` ({ctx}); n = len({arg}).{sorted_note} "
            f"Какова её временная сложность в худшем случае (CPython, элементы — целые числа)?")
    ak = AnswerKey(kind="option", value=key, explanation=f"{cls}: {why}.")
    checks = [Check(name="complexity", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=cls)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         params={"template": name, "class": cls})
