"""Секрет из окружения; только фиктивные значения и отказ при отсутствии настройки.

Версия 2. В версии 1 дефектом была строковая константа вместо чтения окружения, а условие
прямо называло её («оставили фиктивный маркер DEMO_…») — задачу решали малые модели
(калибровка 05.10). Теперь окружение читается, но с резервным значением «для локального
запуска» (`os.environ.get(ENV, DEFAULT)`, `os.getenv(ENV, DEFAULT)` или `... or DEFAULT`):
без настройки сервис молча уходит с этим токеном вместо отказа. Подсказки в условии нет —
дан только симптом. Равноценных исправлений два, принимаются обе строки:
  * строка чтения — убрать резервное значение (`token = os.environ.get(TOKEN_ENV)`);
  * строка константы — сделать резервное значение пустым (`DEFAULT = ''`): проверка
    `if not token` тогда отказывает. Оба варианта проверяются исполнением.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng, py_harness
from assessment_bank.schema import AnswerKey, Check
from ._support import CONTEXTS, SOURCES

FAMILY_ID = "security.config.secret_env_bug"

TEST = """os.environ[TOKEN_ENV] = 'DEMO_ENV_VALUE_ONLY'
assert load_token() == 'DEMO_ENV_VALUE_ONLY'
assert auth_headers() == {'Authorization': 'Bearer DEMO_ENV_VALUE_ONLY'}
os.environ[TOKEN_ENV] = 'DEMO_ROTATED_VALUE_ONLY'
assert load_token() == 'DEMO_ROTATED_VALUE_ONLY'
os.environ.pop(TOKEN_ENV, None)
try:
    load_token()
except RuntimeError:
    pass
else:
    raise AssertionError('must fail closed')
os.environ[TOKEN_ENV] = ''
try:
    load_token()
except RuntimeError:
    pass
else:
    raise AssertionError('empty token accepted')"""


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    env = rng.choice(["NOTIFY_API_TOKEN", "REPORT_API_TOKEN", "CATALOG_API_TOKEN", "ARCHIVE_API_TOKEN"])
    const = rng.choice(["_DEV_TOKEN", "LOCAL_TOKEN", "FALLBACK_TOKEN", "_DEFAULT_TOKEN"])
    value = f"DEMO_LOCAL_ONLY_{rng.randint(1000, 99999)}"
    form = rng.choice(["get", "getenv", "or"])
    read_bad = {"get": f"token = os.environ.get(TOKEN_ENV, {const})",
                "getenv": f"token = os.getenv(TOKEN_ENV, {const})",
                "or": f"token = os.environ.get(TOKEN_ENV) or {const}"}[form]
    read_ok = "token = os.getenv(TOKEN_ENV)" if form == "getenv" else "token = os.environ.get(TOKEN_ENV)"
    note = rng.choice(["  # для локального запуска", "  # чтобы тесты на ноутбуке не падали",
                       "  # временно, до настройки CI", ""])
    extra = rng.sample(["API_URL = 'https://api.example.invalid/v1'", "TIMEOUT_S = 10",
                        "RETRIES = 3"], rng.randint(0, 2))
    pre = "".join(e + "\n" for e in extra)
    code = (f"import os\n\n{pre}TOKEN_ENV = {env!r}\n{const} = {value!r}{note}\n\n\n"
            f"def load_token():\n    {read_bad}\n    if not token:\n"
            f"        raise RuntimeError('missing token')\n    return token\n\n\n"
            f"def auth_headers():\n    return {{'Authorization': 'Bearer ' + load_token()}}")
    fixed = code.replace(f"    {read_bad}", f"    {read_ok}")
    alt_fixed = code.replace(f"{const} = {value!r}{note}", f"{const} = ''{note}")
    key_line = min(changed_lines(code, fixed))
    alt_line = min(changed_lines(code, alt_fixed))
    assert changed_lines(code, fixed) == {key_line} and changed_lines(code, alt_fixed) == {alt_line}
    checks = [
        Check(name="buggy_fails", runner="python", program=py_harness(code, TEST), expect="fail"),
        Check(name="fixed_passes", runner="python", program=py_harness(fixed, TEST),
              expect="pass", embeds_display_code=False),
        Check(name=f"alt_fix:{alt_line}", runner="python", program=py_harness(alt_fixed, TEST),
              expect="pass", embeds_display_code=False),
    ]
    symptom = rng.choice([
        f"на тестовом стенде `{env}` забыли задать, но сервис не упал при старте запроса, а ушёл "
        f"во внешний API с каким-то токеном и получил 401",
        f"после переезда на новый кластер переменная `{env}` не была передана в контейнер, однако "
        f"ошибки конфигурации никто не увидел — запросы шли с чужим токеном",
        f"аудит показал: если `{env}` не задана, адаптер всё равно формирует заголовок "
        f"Authorization"])
    stem = (f"{ctx.capitalize()}: по контракту развёртывания адаптер читает `{env}` из окружения "
            f"при каждом вызове и отказывается работать без значения (пустое значение — тоже "
            f"отказ). Инцидент: {symptom}. Укажите номер строки, исправление которой выполняет "
            f"контракт. Не предлагайте выводить токен в журнал.")
    why = (f"Строка {key_line}: резервное значение `{const}` подставляется, когда `{env}` не "
           f"задана, — отказ не срабатывает (fail open). Исправление — читать окружение без "
           f"резервного значения; равноценно сделать `{const}` пустой строкой (строка {alt_line}): "
           f"тогда сработает `if not token`. Окружение здесь — заданный интерфейс инъекции, не "
           f"защищённое хранилище; доступ к нему и диагностическим дампам ограничивают.")
    return build_variant(
        FAMILY_ID, seed, stem=stem, code=code,
        answer_key=AnswerKey(kind="line", value=key_line, accept=[str(alt_line)], explanation=why),
        context=ctx, verification="execution", checks=checks, defect_type="hardcoded_secret",
        params={"fixed_code": fixed, "alt_fixes": {str(alt_line): alt_fixed}, "form": form,
                "source_urls": [SOURCES["coding"], SOURCES["crypto"]], "env": env})
