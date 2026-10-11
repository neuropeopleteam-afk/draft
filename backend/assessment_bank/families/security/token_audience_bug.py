"""security.auth.token_audience_bug — find_bug: проверка аудитории токена пропускает токен без `aud`.

Порог Middle/Senior. Подписанный токен общего сервера входа проверяется по подписи, сроку и издателю; аудитория
проверяется только если поле есть (`if "aud" in claims and …`), поэтому токен, выпущенный тем же сервером входа для
другого приложения без `aud` (или служебный), принимается. Исправление в той же строке — `aud` обязателен и равен
нашему. Ловушки — `compare_digest`, проверка срока, издатель. Один подтип.
Проверка исполнением: токены без `aud` и с чужим `aud` отклоняются, свой — принимается, истёкший — нет.
"""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from assessment_bank.families.common._plus_utils import line_bug_variant

FAMILY_ID = "security.auth.token_audience_bug"

CONTEXTS = [("API бухгалтерии", "billing-api"), ("API склада", "warehouse-api"), ("API кадров", "hr-api"),
            ("API отчётов", "reports-api"), ("API платежей", "payments-api"), ("API поддержки", "support-api")]
OTHERS = ["mobile-app", "partner-portal", "analytics", "chat-bot"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, aud = rng.choice(CONTEXTS)
    other = rng.choice(OTHERS)
    iss = rng.choice(["https://sso.example.ru", "https://id.corp.example", "https://login.example.org"])
    fn = rng.choice(["verify_token", "decode_token", "check_token"])
    algo = rng.choice(["sha256", "sha384"])
    cl = rng.choice(["claims", "payload", "data"])
    bad = rng.choice([f'    if "aud" in {cl} and {cl}["aud"] != AUDIENCE:',
                      f'    if {cl}.get("aud") not in (None, AUDIENCE):',
                      f'    if {cl}.get("aud", AUDIENCE) != AUDIENCE:'])
    good = f'    if {cl}.get("aud") != AUDIENCE:'
    err = rng.choice(["InvalidToken", "AuthError", "Unauthorized"])
    iss_first = rng.random() < 0.5

    def assemble(line: str) -> str:
        head = ["import base64", "import hashlib", "import hmac", "import json", "", f"ISSUER = {iss!r}",
                f"AUDIENCE = {aud!r}", "", "", f"class {err}(Exception):", "    pass", "", "",
                f"def {fn}(token, key, now):", '    body, sig = token.rsplit(".", 1)',
                f"    expected = hmac.new(key, body.encode(), hashlib.{algo}).hexdigest()",
                "    if not hmac.compare_digest(expected, sig):", f"        raise {err}('signature')",
                f"    {cl} = json.loads(base64.urlsafe_b64decode(body))",
                f'    if {cl}["exp"] <= now:', f"        raise {err}('expired')"]
        iss_chk = [f'    if {cl}.get("iss") != ISSUER:', f"        raise {err}('issuer')"]
        aud_chk = [line, f"        raise {err}('audience')"]
        tail = (iss_chk + aud_chk) if iss_first else (aud_chk + iss_chk)
        return "\n".join(head + tail + [f'    return {cl}["sub"]']) + "\n"

    buggy, fixed = assemble(bad), assemble(good)
    now = 1_900_000_000
    test = f"""
def _tok(c, k=b"idp-shared-key"):
    body = base64.urlsafe_b64encode(json.dumps(c).encode()).decode()
    return body + "." + hmac.new(k, body.encode(), hashlib.{algo}).hexdigest()
K = b"idp-shared-key"
ok = {{"sub": "u1", "iss": ISSUER, "aud": AUDIENCE, "exp": {now + 600}}}
assert {fn}(_tok(ok), K, {now}) == "u1"
for bad in ({{"sub": "u2", "iss": ISSUER, "exp": {now + 600}}},
            {{"sub": "u3", "iss": ISSUER, "aud": {other!r}, "exp": {now + 600}}},
            {{"sub": "u4", "iss": ISSUER, "aud": AUDIENCE, "exp": {now - 1}}},
            {{"sub": "u5", "iss": "https://evil.example", "aud": AUDIENCE, "exp": {now + 600}}}):
    try:
        {fn}(_tok(bad), K, {now})
        raise AssertionError("принят " + bad["sub"])
    except {err}:
        pass
"""
    stem = (f"Безопасность ({ctx}). Токены выпускает общий сервер входа компании одним ключом для всех приложений; "
            f"`{fn}` проверяет токен на стороне `{aud}`. Пентестер вошёл в другое приложение компании "
            f"(`{other}`), взял его токен и с ним получил доступ к `{aud}`. Укажите номер строки с ошибкой.")
    why = ("Аудитория проверяется только если поле есть (или отсутствие считается допустимым), поэтому токен того же "
           "сервера входа, выпущенный без `aud` для другого приложения, принимается. Если один издатель и ключ общие "
           f"для нескольких приложений, `aud` обязателен и должен совпадать: `{good.strip()}`. Подпись "
           "(`compare_digest`), срок и издатель проверяются верно.")
    return line_bug_variant(FAMILY_ID, seed, stem=stem, buggy=buggy, fixed=fixed, test=test, context=ctx,
                            defect="optional_audience_check", why=why,
                            display_note="После показанного кода проверяются токены: свой, без aud, с чужим aud, "
                                         "истёкший, чужого издателя.",
                            params={"other": other, "iss_first": iss_first})
