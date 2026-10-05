"""frontend.forms.int_validation_fix — choose_fix: валидация целого числа из поля формы."""
from __future__ import annotations

import json
import re

from assessment_bank.gen_utils import build_variant, js_harness, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.forms.int_validation_fix"

FIELDS = [("validateQty", "«Количество»", "карточка товара", [1], [20, 50, 99]),
          ("validateGuests", "«Число гостей»", "бронирование столика", [1, 2], [8, 12]),
          ("validateSeats", "«Число мест»", "покупка билетов", [1], [6, 10]),
          ("validateExperience", "«Опыт работы, лет»", "анкета кандидата", [0], [50, 60]),
          ("validateTeamSize", "«Размер команды»", "профиль компании", [1, 2], [100, 500])]
MSG = "Введите целое число"


def _code(kind, fn):
    head = f"function {fn}(raw, min, max) {{"
    tail = ["  if (n < min) return `Минимум ${min}`;", "  if (n > max) return `Не больше ${max}`;",
            "  return null;", "}"]
    body = {
        "buggy": ["  const n = parseInt(raw);", f"  if (!n) return '{MSG}';"],
        "good": ["  const s = raw.trim();", f"  if (!/^\\d+$/.test(s)) return '{MSG}';",
                 "  const n = Number(s);"],
        "number": ["  const s = raw.trim();", "  const n = Number(s);",
                   f"  if (!Number.isInteger(n)) return '{MSG}';"],
        "parse_float": ["  const s = raw.trim();", "  const n = parseFloat(s);",
                        f"  if (!Number.isInteger(n)) return '{MSG}';"],
        "no_anchor": ["  const s = raw.trim();", f"  if (!/\\d+/.test(s)) return '{MSG}';",
                      "  const n = Number(s);"],
        "is_nan": ["  const s = raw.trim();", f"  if (isNaN(s)) return '{MSG}';",
                   "  const n = Number(s);"],
        "parse_int": ["  const s = raw.trim();", "  const n = parseInt(s, 10);",
                      f"  if (Number.isNaN(n)) return '{MSG}';"],
    }[kind]
    return "\n".join([head] + body + tail)


def _spec(raw, mn, mx):
    s = raw.strip()
    if not re.fullmatch(r"[0-9]+", s):
        return MSG
    n = int(s)
    if n < mn:
        return f"Минимум {mn}"
    if n > mx:
        return f"Не больше {mx}"
    return None


WHY = {"number": "Number('') и Number('  ') дают 0, а '1e2' — 100: пустое поле и запись с "
                 "экспонентой не считаются ошибкой ввода",
       "parse_float": "parseFloat('12abc') = 12 — мусор после числа пропускается",
       "no_anchor": "регулярное выражение без ^ и $ находит цифры внутри '12abc', а Number даёт "
                    "NaN, и все сравнения с NaN ложны — значение проходит",
       "is_nan": "isNaN('') ложно (пустая строка приводится к 0), а дробные '2.5' проходят",
       "parse_int": "parseInt('12abc', 10) = 12 и parseInt('2.5', 10) = 2 — недопустимый ввод "
                    "принимается"}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    fn, label, ctx, mins, maxs = rng.choice(FIELDS)
    mn, mx = rng.choice(mins), rng.choice(maxs)
    inputs = ["", "   ", f"{rng.randint(mn + 1, min(9, mx))}abc", f"{rng.randint(mn + 1, mn + 4)}.5", "1e2", "-3",
              f" {mn + 1} ", str(mn), str(mx), str(mx + 1), "0" + str(mn + 1)]
    if mn > 0:
        inputs.append(str(mn - 1))
    cases = [[x, _spec(x, mn, mx)] for x in inputs]
    chosen = rng.sample(sorted(WHY), 3)
    opts, key = make_options(rng, ("Заменить функцию на:", _code("good", fn)),
                             [("Заменить функцию на:", _code(k, fn)) for k in chosen])
    test = (f"const cases = {json.dumps(cases, ensure_ascii=False)};\n"
            f"for (const [raw, exp] of cases) {{\n  const got = {fn}(raw, {mn}, {mx});\n"
            f"  __assert(got === exp, JSON.stringify(raw) + ' → ' + got);\n}}")
    code = _code("buggy", fn)
    checks = [Check(name=f"option:{o.id}", runner="node", embeds_display_code=False,
                    program=js_harness(o.code, test), expect="pass" if o.id == key else "fail")
              for o in opts]
    checks.append(Check(name="buggy_fails", runner="node", program=js_harness(code, test),
                        expect="fail"))
    def buggy_accepts(x):  # parseInt: ведущие цифры; !n отсекает 0 и NaN
        m = re.match(r"\s*([0-9]+)", x)
        n = int(m.group(1)) if m else 0
        return bool(n) and mn <= n <= mx
    cand = [x for x in (inputs[2], inputs[3], "1e2") if buggy_accepts(x)]
    assert len(cand) >= 2
    bad_inputs = [f"«{x}»" for x in rng.sample(cand, 2)]
    stem = (f"Поле {label} ({ctx}) — обычный `<input type=\"text\">`, значение приходит строкой. "
            f"Правило: после обрезки пробелов по краям допустимы только цифры, иначе ошибка "
            f"«{MSG}»; число меньше min — «Минимум min», больше max — «Не больше max»; "
            f"корректное значение — null. Вызов: `{fn}(value, {mn}, {mx})`. Сейчас форма "
            f"принимает {bad_inputs[0]} и {bad_inputs[1]}"
            + (f", а для «0» пишет «{MSG}» вместо «Минимум {mn}»" if mn > 0 else
               f", а «0» отклоняет, хотя минимум — {mn}") + ". Какое исправление верно?")
    ak = AnswerKey(kind="option", value=key,
                   explanation="Верно: сначала проверить строку целиком (^\\d+$ после trim), потом "
                               "переводить в число и сравнивать с границами. parseInt отбрасывает "
                               "хвост, а !n считает 0 пустым значением. Дистракторы: "
                               + "; ".join(WHY[k] for k in chosen) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="loose_number_parsing",
                         params={"distractors": chosen, "min": mn, "max": mx})
