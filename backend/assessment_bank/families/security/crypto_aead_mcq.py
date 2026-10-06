"""security.crypto.aead_mcq — бюджет ключа AES-GCM со случайными 96-битными nonce (расчётная задача).

Версия 2. Версия 1 (выбор «AES-GCM + AAD + проверка тега» среди CBC/CTR/постоянного nonce) по
калибровке 05.10 решалась малыми моделями: верный вариант узнавался по ключевым словам. Теперь
режим задан, а проверяется то, что отличает Senior: ограничение NIST SP 800-38D §8.3 для
случайных IV — не более 2^32 вызовов шифрования на ключ СУММАРНО по всем экземплярам — и его
перевод в период ротации ключа.

Дистракторы — содержательные ошибки (все варианты — числа одной формы, длина не подсказывает):
  * per_instance — лимит 2^32 считается на каждый экземпляр, а не на ключ (период × K);
  * birthday — «у 96-битного nonce коллизии начинаются около 2^48» (период × 2^16);
  * with_decrypt — в бюджет засчитываются и расшифровывания (период меньше верного), т. е. верный
    ответ не всегда самый осторожный из предложенных.
Проверка исполнением: программа на Python по условию (K, R, лимит 2^32) находит среди вариантов
единственный наибольший период, не превышающий лимит, и печатает его букву.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check
from ._support import CONTEXTS, SOURCES

FAMILY_ID = "security.crypto.aead_mcq"
NIST = "https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-38d.pdf"
DAY = 86400
LIMIT = 2 ** 32

PROGRAM = """LIMIT = 2 ** 32
K, R, DAY = {k}, {r}, 86400
options = {opts!r}
per_day = K * R * DAY  # вызовы шифрования одним ключом за сутки (все экземпляры)
ok = [l for l, d in options.items() if per_day * d <= LIMIT < per_day * (d + 1)]
print(ok[0] if len(ok) == 1 else "AMBIGUOUS")
"""


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", "\u202f")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    asset = rng.choice(["содержимое черновиков", "тексты заявок", "вложения отчётов",
                        "заметки редакторов", "записи журнала действий"])
    for _ in range(200):
        k = rng.choice([2, 3, 4, 6, 8])
        r = rng.choice([150, 200, 300, 400, 500, 800, 1000, 1500])
        x = rng.choice([1, 2, 3, 4])               # чтений на одну запись
        per_day = k * r * DAY
        good = LIMIT // per_day
        vals = {"good": good,
                "per_instance": LIMIT // (r * DAY),
                "birthday": (2 ** 48) // per_day,
                "with_decrypt": LIMIT // (per_day * (1 + x))}
        if 2 <= good <= 400 and vals["with_decrypt"] >= 1 and len(set(vals.values())) == 4:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    text = {kk: f"Не реже чем раз в {_fmt(v)} сут" for kk, v in vals.items()}
    chosen = ["per_instance", "birthday", "with_decrypt"]
    opts, key = make_options(rng, (text["good"], None), [(text[d], None) for d in chosen])
    stem = (f"{ctx.capitalize()}: {asset} шифруются AES-GCM (библиотечная реализация) одним ключом "
            f"данных, общим для {k} экземпляров сервиса. Nonce — 96 бит, каждый экземпляр генерирует "
            f"его случайно (CSPRNG) для каждой записи; координации между экземплярами нет. Каждый "
            f"экземпляр шифрует до {_fmt(r)} записей в секунду круглосуточно; каждую запись затем "
            f"читают (расшифровывают) в среднем {x} раз(а). Какой наибольший период ротации ключа "
            f"(целое число суток) соблюдает ограничение NIST SP 800-38D для случайных nonce?")
    opt_days = {o.id: int(o.text.split("раз в ")[1].split(" сут")[0].replace("\u202f", ""))
                for o in opts}
    checks = [Check(name="budget", runner="python", program=PROGRAM.format(k=k, r=r, opts=opt_days),
                    expect="stdout_equals", expected_stdout=key)]
    why = {"per_instance": f"{_fmt(vals['per_instance'])} сут — лимит посчитан на экземпляр, а он "
                           f"действует на ключ по всем экземплярам",
           "birthday": f"{_fmt(vals['birthday'])} сут — граница «дня рождения» 2^48 не является "
                       f"нормой; NIST требует вероятность повтора не выше 2^-32, отсюда 2^32 вызовов",
           "with_decrypt": f"{_fmt(vals['with_decrypt'])} сут — расшифровывание nonce не расходует, "
                           f"лимит считается по вызовам шифрования"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=(f"NIST SP 800-38D §8.3: при случайных IV число вызовов шифрования "
                                f"одним ключом — не более 2^32 = {_fmt(LIMIT)} суммарно по всем "
                                f"экземплярам. В сутки: {k} × {_fmt(r)} × 86{chr(0x202f)}400 = "
                                f"{_fmt(per_day)} вызовов, отсюда ⌊2^32 / {_fmt(per_day)}⌋ = "
                                f"{good} сут. Остальные: " + "; ".join(why[d] for d in chosen) + "."))
    return build_variant(
        FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
        verification="execution", checks=checks, language="text",
        display_code_note="Ответ проверяется программой: по K, R и лимиту 2^32 находится "
                          "единственный наибольший допустимый период среди вариантов.",
        params={"k": k, "r": r, "reads": x, "days": vals, "source_urls": [NIST, SOURCES["crypto"]],
                "no_custom_crypto": True})
