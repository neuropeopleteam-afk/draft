"""security.logging.password_in_log_bug — find_bug: пароль попадает в журнал при входе.

Лёгкое семейство у порога Junior (грейд «Стажёр»): обработчик входа логирует попытку аутентификации,
и в одной строке в сообщение подставляется пароль (или его часть). Остальные записи журнала — логин, IP,
результат, число попыток — допустимы (строки-ловушки). Исправление — убрать пароль из записи в той же
строке. Один подтип. Проверка исполнением: подменный обработчик `logging` собирает записи; дефектный код
оставляет пароль в журнале, исправленный — нет, при этом сам вход работает одинаково.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "security.logging.password_in_log_bug"

CONTEXTS = [("личный кабинет", "login", "users"), ("админ-панель", "admin_login", "admins"),
            ("мобильное API", "authenticate", "accounts"), ("корпоративный портал", "sign_in", "staff"),
            ("интернет-банк", "auth_user", "clients")]

TEST = '''

import logging as _lg

class _Collector(_lg.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))

_h = _Collector()
_root = _lg.getLogger()
_root.handlers[:] = [_h]
_root.setLevel(_lg.DEBUG)
for _name in list(_lg.Logger.manager.loggerDict):
    _l = _lg.getLogger(_name)
    _l.handlers[:] = []
    _l.setLevel(_lg.DEBUG)
    _l.propagate = True

PASSWORD = {password!r}
ok1 = {fn}({user!r}, PASSWORD, {ip!r})
ok2 = {fn}({user!r}, "wrong-" + PASSWORD, {ip!r})
leaked = any(PASSWORD in line for line in _h.lines)
print("RESULT: PASS" if ok1 and not ok2 and not leaked and _h.lines else "RESULT: FAIL")
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, fn, store = rng.choice(CONTEXTS)
    user = rng.choice(["anna", "boris", "vera", "gleb", "daria"])
    password = rng.choice(["Qw3rty!2026", "S3cret#pass", "Riga-2026!", "p@ssw0rd-x", "Tr0ub4dor&3"])
    ip = f"10.0.{rng.randint(0, 9)}.{rng.randint(2, 250)}"
    logger_name = rng.choice(["auth", "security", "app.auth", "login"])
    leak_style = rng.choice([
        'logger.info("login attempt user=%s password=%s ip=%s", username, password, ip)',
        'logger.debug("auth payload: %s", {"user": username, "password": password})',
        'logger.info("checking credentials %s / %s", username, password)',
        'logger.warning("failed login user=%s password=%s", username, password)'])
    fixed_style = {
        'logger.info("login attempt user=%s password=%s ip=%s", username, password, ip)':
            'logger.info("login attempt user=%s ip=%s", username, ip)',
        'logger.debug("auth payload: %s", {"user": username, "password": password})':
            'logger.debug("auth payload: %s", {"user": username})',
        'logger.info("checking credentials %s / %s", username, password)':
            'logger.info("checking credentials for %s", username)',
        'logger.warning("failed login user=%s password=%s", username, password)':
            'logger.warning("failed login user=%s", username)'}[leak_style]
    in_failed_branch = leak_style.startswith("logger.warning")
    with_attempts = rng.random() < 0.5
    hash_fn = "sha256"
    import hashlib as _hl
    digest_lit = _hl.sha256(password.encode()).hexdigest()

    def body(leak_line: str) -> str:
        lines = ["import hashlib", "import logging", "", f'logger = logging.getLogger("{logger_name}")', "",
                 f"{store} = {{{user!r}: {digest_lit!r}}}  # хэши паролей"]
        if with_attempts:
            lines.append("attempts = {}")
        lines += ["", "", f"def {fn}(username, password, ip):"]
        if not in_failed_branch:
            lines.append(f"    {leak_line}")
        lines += [f"    digest = hashlib.{hash_fn}(password.encode()).hexdigest()",
                  f"    if {store}.get(username) == digest:",
                  '        logger.info("login ok user=%s ip=%s", username, ip)',
                  "        return True"]
        if with_attempts:
            lines.append("    attempts[username] = attempts.get(username, 0) + 1")
        if in_failed_branch:
            lines.append(f"    {leak_line}")
        else:
            lines.append('    logger.warning("login failed user=%s ip=%s", username, ip)')
        lines.append("    return False")
        return "\n".join(lines) + "\n"

    buggy, fixed = body(leak_style), body(fixed_style)
    ch = changed_lines(buggy, fixed)
    assert len(ch) == 1
    key = next(iter(ch))
    test = TEST.format(password=password, fn=fn, user=user, ip=ip)
    checks = [Check(name="buggy_fails", runner="python", program=buggy + test, expect="fail"),
              Check(name="fixed_passes", runner="python", program=fixed + test, expect="pass",
                    embeds_display_code=False)]
    stem = (f"Безопасность ({ctx}). Обработчик входа `{fn}` проверяет пароль по хэшу и пишет события в журнал, "
            f"который хранится 90 дней и доступен всей команде поддержки. Укажите номер строки, которую достаточно исправить одной правкой, чтобы ошибка ушла.")
    why = (f"Строка {key}: в сообщение журнала подставляется пароль в открытом виде. Журналы хранятся долго, "
           f"копируются в системы мониторинга и доступны многим людям — пароль там оказывается скомпрометирован, "
           f"даже если в базе хранится только хэш. Логировать можно логин, IP и результат, но не секреты.")
    ak = AnswerKey(kind="line", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="secret_in_log",
                         display_code_note="После показанного кода подключается сборщик записей logging и выполняются "
                                           "два входа: верный и с неверным паролем.",
                         params={"fixed_code": fixed, "style": leak_style[:20]})
