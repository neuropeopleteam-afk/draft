"""mobile.push.t21_push_preview_output — predict_output (набор t21, порог Стажёра): превью push-уведомления —
length, slice и конкатенация.

Программа на JavaScript (логика React Native-приложения) укорачивает текст уведомления для превью: если длина
больше MAX, берёт первые MAX − 3 символа и дописывает «...». Ловушки чтения: срез считает символы с нуля и не
включает правую границу (пробел тоже символ), итоговая длина ровно MAX; при длине, равной MAX, условие `>`
ложно и текст не меняется. Ключ — независимый расчёт в генераторе; проверка — исполнение показанного кода в
песочнице Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.push.t21_push_preview_output"

CTX = ["маркетплейс", "доставка еды", "банк", "такси", "медицинская запись", "билетный сервис"]
TEXTS = ["Скидка на самокаты до конца недели", "Ваш заказ передан курьеру", "Новое сообщение от поддержки",
         "Оплата прошла успешно", "Посылка ждёт вас в пункте выдачи", "Напоминание о записи к врачу",
         "Курс валют обновлён", "Билеты на концерт снова в продаже", "Сегодня последний день акции",
         "Ваш отзыв опубликован", "Поездка завершена, оцените водителя", "Новый вход в аккаунт",
         "Бонусы начислены на карту", "Доставка перенесена на завтра", "Кешбэк за октябрь уже на счёте"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    text = rng.choice(TEXTS)
    n = len(text)
    if n <= 22 and rng.random() < 0.35:
        mx = n          # длина ровно MAX — условие > ложно
    else:
        mx = rng.randint(9, min(n - 1, 20))
    var = rng.choice(["text", "title", "body"])
    res = rng.choice(["preview", "short", "line"])
    lim = rng.choice(["MAX", "MAX_LEN", "LIMIT"])
    code = (f"const {var} = '{text}';\n"
            f"const {lim} = {mx};\n"
            f"let {res} = {var};\n"
            f"if ({var}.length > {lim}) {res} = {var}.slice(0, {lim} - 3) + '...';\n"
            f"console.log({res});\n"
            f"console.log({res}.length);")
    if n > mx:
        prev = text[:mx - 3] + "..."
        expl = (f"Длина строки {n} > {mx}, поэтому берётся slice(0, {mx - 3}) — символы с индексами 0…{mx - 4} "
                f"(пробелы тоже считаются): «{text[:mx - 3]}», и к ним дописываются три точки. Итог «{prev}», "
                f"его длина {mx - 3} + 3 = {len(prev)}.")
    else:
        prev = text
        expl = (f"Длина строки ровно {n}, а условие строгое: {n} > {mx} ложно, текст не укорачивается. Вывод — "
                f"исходная строка и её длина {n}.")
    out = f"{prev}\n{len(prev)}"
    stem = (f"Push-уведомление в React Native-приложении ({ctx}): программа готовит короткое превью текста для "
            f"экрана блокировки.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"text": text, "max": mx}, language="javascript")
