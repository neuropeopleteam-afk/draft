"""security.session.fixation_bug — find_bug: идентификатор сессии не меняется при входе (фиксация сессии).

Порог Junior/Middle–Middle/Senior. Обработчик входа берёт идентификатор из пришедшей cookie, если она есть, и
привязывает к нему пользователя: злоумышленник, заранее подсунувший жертве свой идентификатор, после её входа
получает её сессию. Один подтип (повторное использование входящего идентификатора); строки-ловушки — флаги cookie,
CSRF-токен, проверка пароля, выход. Порядок функций меняется — строка дефекта не постоянна.
Проверка исполнением: подставленный заранее идентификатор после входа не должен указывать на пользователя.
"""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from assessment_bank.families.common._plus_utils import line_bug_variant

FAMILY_ID = "security.session.fixation_bug"

CONTEXTS = ["личный кабинет клиента", "панель модератора", "кабинет поставщика", "портал сотрудника",
            "кабинет пациента", "кабинет арендатора"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    cookie = rng.choice(["sid", "session", "SESSIONID", "app_sid"])
    store = rng.choice(["SESSIONS", "SESSION_STORE", "ACTIVE"])
    sid = rng.choice(["sid", "session_id", "token"])
    login = rng.choice(["login", "sign_in", "complete_login"])
    same_site = rng.choice(["Lax", "Strict"])
    buggy_line = rng.choice([f'{sid} = request.cookies.get("{cookie}") or new_session_id()',
                             f'{sid} = request.cookies.get("{cookie}", new_session_id())'])
    fixed_line = f"{sid} = new_session_id()"
    csrf = rng.choice(["secrets.token_hex(16)", "secrets.token_urlsafe(16)"])

    blocks = {
        "new": ["def new_session_id():", "    return secrets.token_urlsafe(32)"],
        "current": ["def current_user(request):", f'    data = {store}.get(request.cookies.get("{cookie}"))',
                    '    return data["user"] if data else None'],
        "logout": ["def logout(request):", f'    {store}.pop(request.cookies.get("{cookie}"), None)',
                   f'    request.delete_cookie("{cookie}")'],
    }
    order = ["new", "current", "logout"]
    rng.shuffle(order)
    split = rng.randint(0, 3)

    def assemble(line: str) -> str:
        out = ["import secrets", "", f"{store} = {{}}"]
        login_block = [f"def {login}(request, user_id, password_ok):", "    if not password_ok:",
                       "        return None", f"    {line}",
                       f'    {store}[{sid}] = {{"user": user_id, "csrf": {csrf}}}',
                       f'    request.set_cookie("{cookie}", {sid}, httponly=True, secure=True, samesite="{same_site}")',
                       f"    return {sid}"]
        for i, b in enumerate(order[:split] + ["LOGIN"] + order[split:]):
            out += ["", ""] + (login_block if b == "LOGIN" else blocks[b])
        return "\n".join(out) + "\n"

    buggy, fixed = assemble(buggy_line), assemble(fixed_line)
    planted = "planted-" + "".join(rng.choice("abcdef0123456789") for _ in range(10))
    test = f'''
class _Req:
    def __init__(self, cookies):
        self.cookies = dict(cookies)
        self.out = {{}}
    def set_cookie(self, k, v, **kw):
        self.out[k] = v
    def delete_cookie(self, k):
        self.out[k] = None
r = _Req({{"{cookie}": "{planted}"}})
s = {login}(r, "u42", True)
assert s and {store}[s]["user"] == "u42" and r.out["{cookie}"] == s
assert {store}.get("{planted}", {{}}).get("user") != "u42"
assert current_user(_Req({{"{cookie}": "{planted}"}})) is None
s2 = {login}(_Req({{}}), "u7", True)
assert s2 != s and current_user(_Req({{"{cookie}": s2}})) == "u7"
assert {login}(_Req({{}}), "u1", False) is None
'''
    stem = (f"Безопасность ({ctx}). Пентестер открыл сайт, получил cookie `{cookie}`, подсунул её значение "
            f"в браузер другого пользователя, а после того как тот вошёл, оказался в его сессии. "
            f"Укажите номер строки с ошибкой.")
    why = ("При входе идентификатор сессии берётся из пришедшей cookie, если она есть: идентификатор, известный "
           "злоумышленнику до входа, становится идентификатором сессии жертвы (фиксация сессии). При смене уровня "
           "доверия (вход, повышение прав) нужно выдавать новый идентификатор: `" + fixed_line + "`. Флаги "
           "HttpOnly/Secure/SameSite и CSRF-токен от этой атаки не защищают.")
    return line_bug_variant(FAMILY_ID, seed, stem=stem, buggy=buggy, fixed=fixed, test=test, context=ctx,
                            defect="session_fixation", why=why,
                            display_note="После показанного кода выполняется сценарий: вход с заранее подставленной "
                                         "cookie, вход без cookie, неверный пароль.",
                            params={"order": order, "split": split,
                                    "source_urls": ["https://cheatsheetseries.owasp.org/cheatsheets/"
                                                    "Session_Management_Cheat_Sheet.html"]})
