"""frontend.ui.t21_toast_default_output — predict_output (набор t21, порог Стажёра): простая функция
с параметром по умолчанию.

Функция собирает текст всплывающего уведомления с длительностью показа; у длительности есть значение по
умолчанию. Программа вызывает функцию трижды: без второго аргумента, с явным числом и с явным `undefined`
или нулём. Ловушки: значение по умолчанию подставляется только для отсутствующего аргумента или `undefined`,
а 0 передаётся как есть. Ключ — независимая модель в генераторе; проверка — исполнение показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.ui.t21_toast_default_output"

CTX = [("редактор документов", "toast", ["Сохранено", "Скопировано", "Ссылка создана", "Файл загружен",
                                         "Изменения отменены"]),
       ("интернет-банк", "notify", ["Платёж отправлен", "Карта привязана", "Лимит изменён", "Шаблон сохранён",
                                    "Код отправлен"]),
       ("админ-панель", "flash", ["Пользователь добавлен", "Роль изменена", "Отчёт готов", "Доступ закрыт",
                                  "Кэш очищен"]),
       ("интернет-магазин", "showHint", ["Товар в корзине", "Промокод принят", "Адрес сохранён",
                                         "Отзыв опубликован", "Заказ оформлен"])]
PARAMS = [("seconds", "с"), ("sec", "с"), ("delay", "с")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, fn, texts = rng.choice(CTX)
    par, unit = rng.choice(PARAMS)
    default = rng.choice([2, 3, 4, 5])
    explicit = rng.choice([x for x in range(1, 11) if x != default])
    t1, t2, t3 = rng.sample(texts, 3)
    third = rng.choice(["undefined", "zero"])
    calls = [("none", f"{fn}(\"{t1}\")", f"{t1} ({default} {unit})",
              f"{fn}(\"{t1}\") — второго аргумента нет, берётся значение по умолчанию {default}"),
             ("explicit", f"{fn}(\"{t2}\", {explicit})", f"{t2} ({explicit} {unit})",
              f"{fn}(\"{t2}\", {explicit}) — передано {explicit}")]
    if third == "undefined":
        calls.append(("undefined", f"{fn}(\"{t3}\", undefined)", f"{t3} ({default} {unit})",
                      f"{fn}(\"{t3}\", undefined) — явный undefined тоже заменяется значением по умолчанию "
                      f"{default}"))
    else:
        calls.append(("zero", f"{fn}(\"{t3}\", 0)", f"{t3} (0 {unit})",
                      f"{fn}(\"{t3}\", 0) — 0 не undefined, значение по умолчанию не подставляется"))
    rng.shuffle(calls)
    code = "\n".join([f"function {fn}(text, {par} = {default}) {{",
                      f"  return text + \" (\" + {par} + \" {unit})\";", "}"] +
                     [f"console.log({c[1]});" for c in calls])
    out = "\n".join(c[2] for c in calls)
    expl = ("Значение параметра по умолчанию подставляется, только если аргумент не передан или равен undefined. "
            + "; ".join(c[3] for c in calls) + ".")
    stem = f"Интерфейс ({ctx}): функция собирает текст всплывающего уведомления с длительностью показа."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"default": default, "explicit": explicit, "third": third,
                                  "order": [c[0] for c in calls]}, language="javascript")
