"""common.text.utf8_truncate_fix — choose_fix: обрезка строки по лимиту в байтах UTF-8.

Дефект: лимит в байтах, а функция режет по символам. Верно — закодировать, обрезать байты и
декодировать с errors='ignore' (отбрасывается только неполный последний символ). С версии 2
состав дистракторов фиксирован: strict (decode без errors падает на разрезанном символе),
replace (U+FFFD — лишний символ и возможное превышение лимита), chars_loop (считает, что каждый
символ занимает 2 байта); latin-1 и «limit // 2» исключены. Панель 06.10: при выборке 3 из 5
семейство было неизоморфно и чрезмерно трудным (p ≈ 0,2 при 4 вариантах) — часть трудности
давал случайный состав. Условие явно перечисляет три требования к результату (лимит, корректность,
самый длинный префикс), по которым исключаются replace и strict.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.text.utf8_truncate_fix"

CTX = [("имя файла на ext4", 255, "файловая система отклоняет имя: «File name too long»"),
       ("заголовок push-уведомления", 100, "сервис уведомлений отвечает «payload too large»"),
       ("поле subject в API партнёра", 64, "API партнёра отвечает 400: «subject exceeds 64 bytes»"),
       ("метка в системе мониторинга", 128, "агент мониторинга отбрасывает метрики с ошибкой "
                                            "«label value too long»"),
       ("ключ кэша в Memcached", 250, "клиент Memcached падает с «key length exceeds 250 bytes»")]
FN = ["fit_bytes", "truncate_utf8", "clip_to_bytes", "limit_bytes"]
ARG = ["text", "value", "s"]


def _code(kind, fn, a, lim="limit", doc=None):
    body = {
        "buggy": [f"    if len({a}) <= limit:", f"        return {a}", f"    return {a}[:limit]"],
        "good": [f"    data = {a}.encode('utf-8')", "    return data[:limit].decode('utf-8', errors='ignore')"],
        "replace": [f"    data = {a}.encode('utf-8')", "    return data[:limit].decode('utf-8', errors='replace')"],
        "strict": [f"    data = {a}.encode('utf-8')", "    return data[:limit].decode('utf-8')"],
        "latin": [f"    data = {a}.encode('utf-8')", "    return data[:limit].decode('latin-1')"],
        "half": [f"    data = {a}.encode('utf-8')", f"    return {a} if len(data) <= limit else {a}[:limit // 2]"],
        "chars_loop": [f"    while len({a}) * 2 > limit:", f"        {a} = {a}[:-1]",
                       f"    return {a}"],
    }[kind]
    head = [f"def {fn}({a}: str, {lim}: int) -> str:"] if lim != "limit" else [f"def {fn}({a}, limit):"]
    if doc:
        head.append(f'    """{doc}"""')
    body = [b.replace("limit", lim) if lim != "limit" else b for b in body]
    return "\n".join(head + body)


def _expected(t, limit):
    out = ""
    for ch in t:
        if len((out + ch).encode("utf-8")) > limit:
            break
        out += ch
    return out


WHY = {"replace": "errors='replace' добавляет символ U+FFFD (3 байта) — результат может "
                  "превысить лимит и содержит мусорный символ",
       "strict": "decode без errors падает с UnicodeDecodeError, если граница разрезала "
                 "многобайтовый символ",
       "latin": "latin-1 превращает каждый байт в отдельный символ — получается «кракозябра», "
                "которая в UTF-8 занимает больше лимита",
       "half": "limit // 2 символов не гарантирует лимит (эмодзи — 4 байта) и обрезает лишнее у "
               "ASCII-текста",
       "chars_loop": "len * 2 предполагает, что каждый символ занимает ровно 2 байта: эмодзи "
                     "и иероглифы превышают лимит, а ASCII-строки обрезаются вдвое сильнее"}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    where, limit, symptom = rng.choice(CTX)
    fn, a = rng.choice(FN), rng.choice(ARG)
    lim = rng.choice(["limit", "limit", "max_bytes", "byte_limit"])
    doc = rng.choice([None, None, "Обрезать строку под лимит хранилища.", "Укоротить значение, если оно не влезает."])
    word = rng.choice(["Привет", "Отчёт", "Заказ", "Ёжик", "Вакансия", "Счёт"])
    cases_in = ["a" * (limit - 1) + "ж", "ж" * limit, "😀" * (limit // 2), word * limit,
                "x" * (limit - 2) + "€€", "日本" * limit, "ok", "a" * limit,
                "b" * (limit - 3) + "😀z"]
    cases = [(t, limit, _expected(t, limit)) for t in cases_in]
    chosen = ["strict", "replace", "chars_loop"]  # версия 2: фиксированный состав
    rng.shuffle(chosen)
    opts, key = make_options(rng, ("Заменить функцию на:", _code("good", fn, a, lim, doc)),
                             [("Заменить функцию на:", _code(k, fn, a, lim, doc)) for k in chosen])
    test = ("cases = " + repr(cases) + "\n"
            "for t, lim, exp in cases:\n"
            f"    got = {fn}(t, lim)\n"
            "    assert len(got.encode('utf-8')) <= lim, (t[:10], len(got.encode('utf-8')))\n"
            "    assert got == exp, (t[:10], got[-5:])\n")
    code = _code("buggy", fn, a, lim, doc)
    checks = [Check(name=f"option:{o.id}", runner="python", embeds_display_code=False,
                    program=py_harness(o.code, test), expect="pass" if o.id == key else "fail")
              for o in opts]
    checks.append(Check(name="buggy_fails", runner="python", program=py_harness(code, test),
                        expect="fail"))
    stem = (f"Функция `{fn}` готовит {where}: результат в кодировке UTF-8 должен занимать не "
            f"больше {limit} байт, быть корректной строкой и быть самым длинным таким префиксом "
            f"исходной строки (по символам Unicode). Для английских строк всё работает, но для "
            f"строк на русском и с эмодзи {symptom}. Какое исправление верно?")
    ak = AnswerKey(kind="option", value=key,
                   explanation="len(str) считает символы, а лимит задан в байтах: кириллица в UTF-8 "
                               "занимает 2 байта, € — 3, эмодзи — 4. Верно: закодировать, обрезать "
                               "байты и декодировать с errors='ignore' — отбрасывается только "
                               "неполный последний символ. Дистракторы: "
                               + "; ".join(WHY[k] for k in chosen) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=where, verification="execution", checks=checks,
                         defect_type="chars_vs_bytes",
                         params={"distractors": chosen, "limit": limit})
