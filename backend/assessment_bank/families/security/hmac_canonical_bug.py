"""security.crypto.hmac_canonical_bug — find_bug: HMAC от склейки полей без разделителей.

Порог Middle/Senior. Подпись считается от `f"{a}{b}{exp}"`: разные наборы полей дают одну строку
(`"1234" + "5990"` = `"12345" + "990"`), и подпись одного сообщения подходит к другому. Исправление в той же
строке — однозначная (каноническая) кодировка: длина каждого поля перед значением. Строки-ловушки —
`compare_digest`, проверка срока, порядок аргументов `hmac.new(key, msg, …)`. Один подтип.
Проверка исполнением: подпись законного сообщения не принимается для сообщения со сдвинутой границей полей.
"""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from assessment_bank.families.common._plus_utils import line_bug_variant

FAMILY_ID = "security.crypto.hmac_canonical_bug"

# (контекст, поле 1, поле 2, что подписывается)
CONTEXTS = [("уведомление об оплате заказа", "order_id", "amount", "уведомления об оплате"),
            ("ссылка на скачивание файла", "file_id", "user_id", "ссылки на скачивание"),
            ("приглашение в команду", "team_id", "invitee_id", "приглашения"),
            ("подтверждение возврата", "refund_id", "amount", "подтверждения возврата"),
            ("купон на скидку", "campaign_id", "client_id", "купоны"),
            ("выгрузка отчёта", "report_id", "account_id", "ссылки на выгрузку")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, f1, f2, what = rng.choice(CONTEXTS)
    key_name = rng.choice(["SIGNING_KEY", "HMAC_KEY", "SECRET"])
    sign = rng.choice(["sign", "make_signature", "signature"])
    verify = rng.choice(["verify", "check_signature", "is_valid"])
    buggy_line = rng.choice([f'    msg = f"{{{f1}}}{{{f2}}}{{expires}}".encode()',
                             f'    msg = (str({f1}) + str({f2}) + str(expires)).encode()'])
    fixed_line = (f'    msg = "".join(f"{{len(str(v))}}:{{v}}" for v in ({f1}, {f2}, expires)).encode()')
    with_ttl = rng.random() < 0.5
    sign_first = rng.random() < 0.5
    algo = rng.choice(["sha256", "sha384", "sha512"])

    def assemble(line: str) -> str:
        head = ["import hashlib", "import hmac", "import os", "",
                f'{key_name} = os.environ.get("{key_name}", "dev-only").encode()']
        if with_ttl:
            head.append(f"MAX_TTL = {rng_ttl}")
        s = [f"def {sign}({f1}, {f2}, expires):", line,
             f"    return hmac.new({key_name}, msg, hashlib.{algo}).hexdigest()"]
        v = [f"def {verify}({f1}, {f2}, expires, sig, now):", "    if now > expires:", "        return False"]
        if with_ttl:
            v += ["    if expires - now > MAX_TTL:", "        return False"]
        v += [f"    expected = {sign}({f1}, {f2}, expires)", "    return hmac.compare_digest(expected, sig)"]
        blocks = [s, v] if sign_first else [v, s]
        out = head
        for b in blocks:
            out += ["", ""] + b
        return "\n".join(out) + "\n"

    rng_ttl = rng.choice([600, 900, 3600])
    a = str(rng.randint(1000, 9899))
    b = str(rng.randint(10, 99)) + str(rng.randint(100, 999))
    a2, b2 = a + b[0], b[1:]
    buggy, fixed = assemble(buggy_line), assemble(fixed_line)
    now = 1_900_000_000
    exp = now + 300
    test = f'''
sig = {sign}("{a}", "{b}", {exp})
assert {verify}("{a}", "{b}", {exp}, sig, {now})
assert not {verify}("{a2}", "{b2}", {exp}, sig, {now})
assert not {verify}("{a}", "{b}", {exp}, sig, {exp + 1})
assert {sign}("{a}", "{b}", {exp}) != {sign}("{a}", "{b}", {exp + 1})
'''
    stem = (f"Безопасность ({ctx}). Сервер подписывает {what} HMAC и затем проверяет подпись. На аудите "
            f"по одному перехваченному подписанному сообщению собрали другое, с иными значениями `{f1}` и "
            f"`{f2}`, и сервер принял его подпись. Ключ не утёк. Укажите номер строки, которую достаточно исправить одной правкой, чтобы ошибка ушла.")
    why = (f"Подписывается склейка полей без разделителей и длин: `{a}` + `{b}` и `{a2}` + `{b2}` дают одну "
           f"строку, поэтому подпись одного набора полей подходит к другому. Подписывать нужно однозначную "
           f"кодировку — длину каждого поля перед значением (или JSON/протокол с явными границами). "
           f"`compare_digest`, проверка срока и порядок аргументов `hmac.new(key, msg, …)` верны.")
    return line_bug_variant(FAMILY_ID, seed, stem=stem, buggy=buggy, fixed=fixed, test=test, context=ctx,
                            defect="ambiguous_mac_encoding", why=why,
                            display_note="После показанного кода выполняются проверки: законная подпись, подпись "
                                         "со сдвинутой границей полей, истёкший срок.",
                            params={"pair": [a, b, a2, b2], "sign_first": sign_first, "ttl": with_ttl})
