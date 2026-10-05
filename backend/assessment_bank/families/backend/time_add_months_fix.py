"""backend.time.add_months_fix — choose_fix: прибавить n месяцев к дате с «прижатием» к концу месяца.

`d.replace(month=d.month + n)` падает при переходе через декабрь и на 29–31 числах.
Варианты исправления одинаковой формы (четыре строки тела): верный перенос года и месяца
с ограничением дня; ошибка переноса (месяц 0 для декабря); «безопасное» 28-е число;
сдвиг на 30·n дней; перенос без ограничения дня. Тестовые даты подбираются так, чтобы
каждый показанный дистрактор ошибался хотя бы на одной; эталон — независимая модель.
"""
from __future__ import annotations

from datetime import date

from assessment_bank.gen_utils import (build_variant, dedent, indent, make_options, make_rng,
                                       py_harness)
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.time.add_months_fix"

CONTEXTS = [("next_charge_date", "start", "months", "дату следующего списания по подписке",
             "подписочный сервис"),
            ("installment_due", "issued", "months", "дату очередного платежа по рассрочке",
             "рассрочка"),
            ("license_until", "start", "months", "дату окончания лицензии", "продажа лицензий"),
            ("membership_end", "since", "months", "дату окончания абонемента", "фитнес-клуб"),
            ("report_deadline", "base", "months", "срок сдачи периодического отчёта",
             "бухгалтерия")]

HEADER = "import calendar\nfrom datetime import date, timedelta\n\n\ndef {fn}({a}: date, {m}: int) -> date:\n"
BODIES = {
    "good": """\
        total = {a}.month - 1 + {m}
        year, month = {a}.year + total // 12, total % 12 + 1
        last = calendar.monthrange(year, month)[1]
        return {a}.replace(year=year, month=month, day=min({a}.day, last))""",
    "wrap": """\
        total = {a}.month + {m}
        year, month = {a}.year + total // 12, total % 12
        last = calendar.monthrange(year, month)[1]
        return {a}.replace(year=year, month=month, day=min({a}.day, last))""",
    "fixed28": """\
        total = {a}.month - 1 + {m}
        year, month = {a}.year + total // 12, total % 12 + 1
        last = min(calendar.monthrange(year, month)[1], 28)
        return {a}.replace(year=year, month=month, day=min({a}.day, last))""",
    "days30": """\
        target = {a} + timedelta(days=30 * {m})
        year, month = target.year, target.month
        last = calendar.monthrange(year, month)[1]
        return {a}.replace(year=year, month=month, day=min({a}.day, last))""",
    "no_clamp": """\
        total = {a}.month - 1 + {m}
        year, month = {a}.year + total // 12, total % 12 + 1
        day = {a}.day
        return {a}.replace(year=year, month=month, day=day)""",
}
BUGGY = '''\
from datetime import date


def {fn}({a}: date, {m}: int) -> date:
    """Дата через {m} месяцев ({m} >= 1); если такого числа нет — последний день месяца."""
    return {a}.replace(month={a}.month + {m})'''

DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _ref(d: date, n: int) -> date | None:
    """Независимая модель: шагаем по месяцам, длину месяца берём из таблицы."""
    y, m = d.year, d.month
    for _ in range(n):
        m += 1
        if m == 13:
            y, m = y + 1, 1
    leap = y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
    last = 29 if (m == 2 and leap) else DAYS[m - 1]
    return date(y, m, min(d.day, last))


def _sim(kind: str, d: date, n: int) -> date | None:
    """Поведение каждого варианта (для подбора тестовых дат); None — исключение."""
    import calendar
    from datetime import timedelta
    try:
        if kind == "buggy":
            return d.replace(month=d.month + n)
        if kind == "days30":
            t = d + timedelta(days=30 * n)
            y, mo = t.year, t.month
            return d.replace(year=y, month=mo, day=min(d.day, calendar.monthrange(y, mo)[1]))
        if kind == "wrap":
            total = d.month + n
            y, mo = d.year + total // 12, total % 12
            return d.replace(year=y, month=mo, day=min(d.day, calendar.monthrange(y, mo)[1]))
        total = d.month - 1 + n
        y, mo = d.year + total // 12, total % 12 + 1
        last = calendar.monthrange(y, mo)[1]
        if kind == "fixed28":
            return d.replace(year=y, month=mo, day=min(d.day, min(last, 28)))
        if kind == "no_clamp":
            return d.replace(year=y, month=mo, day=d.day)
        return d.replace(year=y, month=mo, day=min(d.day, last))
    except ValueError:
        return None


def _rand_date(rng) -> date:
    y = rng.choice([2025, 2026, 2027, 2028])
    m = rng.randint(1, 12)
    leap = y % 4 == 0
    last = 29 if (m == 2 and leap) else DAYS[m - 1]
    day = rng.choice([1, 5, 10, 15, 28, 29, 30, 31, rng.randint(1, 31)])
    return date(y, m, min(day, last))


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    fn, a, m, what, ctx = rng.choice(CONTEXTS)
    chosen = rng.sample(["wrap", "fixed28", "days30", "no_clamp"], 3)
    cases: list[tuple[date, int]] = []
    need = set(chosen) | {"buggy"}
    for _ in range(5000):
        d, n = _rand_date(rng), rng.choice([1, 1, 2, 3, 6, 11, 12, 13])
        good = _ref(d, n)
        assert _sim("good", d, n) == good
        fails = {k for k in set(chosen) | {"buggy"} if _sim(k, d, n) != good}
        if fails and (fails & need or len(cases) < 3) and (d, n) not in cases:
            cases.append((d, n))
            need -= fails
        if not need and len(cases) >= 3:
            break
    else:
        raise RuntimeError("не нашлись тестовые даты")
    while len(cases) < 5:
        d, n = date(rng.choice([2026, 2027]), rng.randint(1, 6), rng.randint(1, 28)), rng.randint(1, 5)
        if (d, n) not in cases:
            cases.append((d, n))
    rng.shuffle(cases)
    fmt = dict(fn=fn, a=a, m=m)
    code = dedent(BUGGY.format(**fmt))
    lit = lambda d: f"date({d.year}, {d.month}, {d.day})"
    tests = "\n".join(f"assert {fn}({lit(d)}, {n}) == {lit(_ref(d, n))}" for d, n in cases)
    opt = lambda k: HEADER.format(**fmt) + indent(dedent(BODIES[k].format(**fmt)))
    opts, key = make_options(rng, ("Заменить функцию на:", opt("good")),
                             [("Заменить функцию на:", opt(k)) for k in chosen])
    checks = [Check(name=f"option:{o.id}", runner="python", program=py_harness(o.code, tests),
                    expect="pass" if o.id == key else "fail", embeds_display_code=False)
              for o in opts]
    checks.append(Check(name="buggy_fails", runner="python", program=py_harness(code, tests),
                        expect="fail"))
    ex = next((d, n) for d, n in cases if _sim("buggy", d, n) is None)
    stem = (f"Сервис ({ctx}) вычисляет {what}: дату через `{m}` месяцев после `{a}`. Если в "
            f"целевом месяце нет такого числа, берётся последний день месяца (31 января + 1 месяц "
            f"→ 28 или 29 февраля). Сейчас вызов `{fn}({lit(ex[0])}, {ex[1]})` падает с "
            f"`ValueError`, хотя должен вернуть `{lit(_ref(*ex))}`. Какое исправление верно для "
            f"любой даты и любого `{m}` ≥ 1?")
    why = {"wrap": "`total % 12` без сдвига на единицу даёт месяц 0 для декабря",
           "fixed28": "ограничение 28-м числом портит даты, у которых 29–31 число существует",
           "days30": "30·n дней — не n месяцев: дата уезжает в соседний месяц",
           "no_clamp": "без ограничения дня 31-е число падает в коротком месяце"}
    ak = AnswerKey(kind="option", value=key,
                   explanation="Верно: перенос через (month − 1 + n) // 12 и % 12 + 1 и "
                               "ограничение дня длиной целевого месяца. Дистракторы: "
                               + "; ".join(why[k] for k in chosen) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="month_arithmetic",
                         params={"distractors": chosen, "cases": [(str(d), n) for d, n in cases]})
