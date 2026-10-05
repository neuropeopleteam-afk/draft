"""Проверка HMAC и срока: учебная структура, не реализация JWT."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng, ob3_steps, py_harness, rubric_from
from assessment_bank.schema import AnswerKey, Check
from ._support import CONTEXTS, SOURCES

FAMILY_ID = "security.auth.token_validation_ob3"

HEAD = """import hashlib
import hmac
import json

def signed_bytes(claims):
    return json.dumps(claims, sort_keys=True, separators=(',', ':')).encode()

def sign(claims, key):
    return hmac.new(key, signed_bytes(claims), hashlib.sha256).digest()

"""
GOOD = """def valid(claims, signature, key, now, issuer, audience):
    if not hmac.compare_digest(signature, sign(claims, key)):
        return False
    if claims.get('iss') != issuer or claims.get('aud') != audience:
        return False
    expiry = claims.get('exp')
    if type(expiry) is not int:
        return False
    return now < expiry"""
BAD = GOOD.replace("return now < expiry", "return now <= expiry")

CONDITIONS = {
    "revocation": dict(
        text="Нужно немедленно отзывать доступ при увольнении, а токены ещё действуют. "
             "Как добавить отзыв без доверия к непроверенным полям и какие ограничения у решения?",
        criteria=[("authenticated", "Проверяет подпись, срок, issuer/audience до доверия идентификатору", 0.3),
                  ("revocation", "Предлагает версию сессии/учётной записи или реестр отзывов с TTL, короткий срок токена", 0.4),
                  ("tradeoff", "Обсуждает кэш, задержку отзыва, недоступность реестра и тесты", 0.3)],
        strong="Подпись и exp доказывают допустимость токена, но не актуальность прав. "
               "После полной проверки извлекаю subject и версию сессии и сравниваю с доверенным "
               "реестром. При увольнении блокирую учётную запись и увеличиваю версию; новые "
               "обращения старой сессии отклоняются. Альтернатива — список отозванных id с TTL "
               "до exp. Короткий срок access-токена ограничивает окно, но не обеспечивает "
               "немедленный отзыв сам по себе. Фиксирую допустимую задержку кэша; для "
               "чувствительных операций при недоступном реестре доступ закрывается. Тесты "
               "проверяют активную сессию, отзыв, истечение и недоступность реестра.",
        medium="Добавлю реестр отозванных сессий и буду проверять его после подписи. "
               "Токены сделаю короткоживущими. Без реестра немедленный отзыв невозможен.",
        weak="Достаточно удалить токен из браузера сотрудника; exp можно не проверять."),
    "rotation": dict(
        text="Подписывающий ключ планово меняется. Как провести ротацию без остановки, "
             "ограничить выбор ключа и определить поведение при неизвестном идентификаторе ключа?",
        criteria=[("keys", "Новый ключ для выпуска, ограниченное окно приёма старого и доверенный локальный набор", 0.4),
                  ("binding", "Идентификатор выбирает только разрешённый ключ, не алгоритм или произвольный URL", 0.35),
                  ("testing", "Неизвестный ключ отклоняется; тесты старого/нового ключа и сроков", 0.25)],
        strong="Начинаю выпуск новым ключом, а старый принимаю только в заранее ограниченном "
               "окне, не дольше срока соответствующих токенов плюс разрешённое расхождение часов. "
               "Идентификатор ключа выбирает запись доверенного набора; алгоритм закреплён "
               "в настройке верификатора. Нельзя превращать поле токена в путь, URL для загрузки "
               "ключа или произвольный алгоритм. Неизвестный идентификатор даёт отказ и "
               "обезличенное событие мониторинга. Старый ключ после окна удаляется. "
               "При компрометации не жду планового окна и отзываю связанные сессии. "
               "Тестирую оба ключа, истечение окна, неизвестный ключ и неверную подпись.",
        medium="Буду выпускать токены новым ключом, а старый временно оставлю в доверенном "
               "наборе для проверки. Неизвестный идентификатор должен приводить к отказу.",
        weak="При неизвестном ключе нужно принять токен, чтобы ротация не мешала пользователям."),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, now = rng.choice(CONTEXTS), rng.randint(10000, 99999)
    issuer = rng.choice(["demo-auth", "demo-identity", "demo-session"])
    audience = rng.choice(["demo-editor", "demo-archive", "demo-catalog"])
    claims = {"sub": rng.randint(10, 900), "iss": issuer, "aud": audience}
    cases = [
        {**claims, "exp": now},
        {**claims, "exp": now + rng.randint(10, 60)},
        {**claims, "exp": now - rng.randint(10, 60)},
        {**claims, "exp": now + 30, "aud": "another-demo-service"},
    ]
    text = lambda c: f"exp={c['exp']}; iss={c['iss']}; aud={c['aud']}; подпись верна."
    opts1, key1 = make_options(rng, (text(cases[0]), None),
                               [(text(c), None) for c in cases[1:]], step=1)
    by_text = {text(c): c for c in cases}
    fixes = [GOOD, BAD, GOOD.replace("now < expiry", "True"),
             GOOD.replace("if not hmac.compare_digest(signature, sign(claims, key)):", "if not signature:")]
    opts2, key2 = make_options(rng, ("Заменить valid:", fixes[0]),
                               [("Заменить valid:", f) for f in fixes[1:]], step=2)
    code = HEAD + BAD
    checks = []
    for o in opts1:
        c = by_text[o.text]
        expected = (c["iss"] == issuer and c["aud"] == audience and now < c["exp"])
        test = (f"claims = {c!r}\nkey = b'DEMO_TEST_KEY_NOT_FOR_USE'\n"
                f"assert valid(claims, sign(claims, key), key, {now}, {issuer!r}, {audience!r}) is {expected!r}")
        checks.append(Check(name=f"step1:{o.id}", runner="python", program=py_harness(code, test),
                            expect="fail" if o.id == key1 else "pass"))
    valid_claims = {**claims, "exp": now + 60}
    test = f"""key = b'DEMO_TEST_KEY_NOT_FOR_USE'
claims = {valid_claims!r}
sig = sign(claims, key)
assert valid(claims, sig, key, {now}, {issuer!r}, {audience!r}) is True
assert valid(claims, sig, key, {now + 60}, {issuer!r}, {audience!r}) is False
assert valid(claims, sig, key, {now + 61}, {issuer!r}, {audience!r}) is False
assert valid(claims, bytes([sig[0] ^ 1]) + sig[1:], key, {now}, {issuer!r}, {audience!r}) is False
for field, value in [('iss', 'other-demo-issuer'), ('aud', 'other-demo-audience'), ('exp', 'future')]:
    changed = dict(claims)
    changed[field] = value
    assert valid(changed, sign(changed, key), key, {now}, {issuer!r}, {audience!r}) is False"""
    for o in opts2:
        checks.append(Check(name=f"step2:{o.id}", runner="python",
                            program=py_harness(HEAD + o.code, test), embeds_display_code=False,
                            expect="pass" if o.id == key2 else "fail"))
    condition = rng.choice(sorted(CONDITIONS))
    stem = (f"{ctx.capitalize()}: учебный формат подписывает канонический JSON через HMAC-SHA256 "
            f"с доверенным ключом. Это не JWT и не рекомендация создавать свой формат токена. "
            f"Время now={now}, issuer=`{issuer}`, audience=`{audience}`. Контракт: подпись верна, "
            "iss/aud совпадают, exp — целое число; доступ разрешён только при now < exp. "
            "Поля в примерах обычные, никакие запросы не отправляются.")
    return build_variant(
        FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2, context=ctx,
        verification="execution", checks=checks, defect_type="token_expiry_boundary",
        answer_key=AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"},
                            explanation="В момент exp токен уже недействителен. HMAC сравнивается "
                            "через compare_digest, срок и область действия проверяются отдельно."),
        rubric=rubric_from({**CONDITIONS[condition], "notes": "Шаг 3 оценивается по смыслу, "
                           "не по совпадению слов. Критерии: 0/0.5/1, итог — взвешенная сумма. "
                           "Константа ключа существует только в тесте."}),
        steps=ob3_steps("Шаг 1. Какой набор корректно подписанных claims выявляет нарушение контракта?",
                        "Шаг 2. Выберите полную проверку подписи, срока и области действия.",
                        "Шаг 3. " + CONDITIONS[condition]["text"] + " Ответьте в 5–10 предложениях."),
        params={"source_urls": [SOURCES["crypto"], SOURCES["coding"]], "condition": condition},
    )
