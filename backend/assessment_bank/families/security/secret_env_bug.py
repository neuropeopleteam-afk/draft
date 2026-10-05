"""Секрет из окружения; только фиктивные значения и отказ при отсутствии настройки."""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from ._support import CONTEXTS, SOURCES, bug_variant

FAMILY_ID = "security.config.secret_env_bug"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    env = rng.choice(["NOTIFY_API_TOKEN", "REPORT_API_TOKEN", "CATALOG_API_TOKEN", "ARCHIVE_API_TOKEN"])
    value = f"DEMO_NOT_A_SECRET_{rng.randint(1000, 99999)}"
    code = f"""import os
TOKEN_ENV = {env!r}

def load_token():
    token = {value!r}
    if not token:
        raise RuntimeError('missing token')
    return token

def auth_headers():
    return {{'Authorization': 'Bearer ' + load_token()}}"""
    fixed = code.replace(f"token = {value!r}", "token = os.environ.get(TOKEN_ENV)")
    test = f"""os.environ[TOKEN_ENV] = 'DEMO_ENV_VALUE_ONLY'
assert load_token() == 'DEMO_ENV_VALUE_ONLY'
assert auth_headers() == {{'Authorization': 'Bearer DEMO_ENV_VALUE_ONLY'}}
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
    stem = (f"{ctx.capitalize()}: по контракту развёртывания адаптер читает `{env}` "
            "из окружения при каждом вызове и отказывается работать без значения. "
            f"В учебном коде оставили фиктивный маркер `{value}` вместо настройки. "
            "Укажите строку дефекта. Не предлагайте резервный секрет в коде или вывод токена в журнал.")
    return bug_variant(
        FAMILY_ID, seed, stem=stem, buggy=code, fixed=fixed, test=test, context=ctx,
        defect="hardcoded_secret",
        params={"why": "Читать os.environ.get(TOKEN_ENV) и сохранить отказ при пустом значении. "
                "Окружение здесь — заданный интерфейс инъекции, не универсальное защищённое "
                "хранилище; доступ к нему и диагностическим дампам необходимо ограничивать.",
                "source_urls": [SOURCES["coding"], SOURCES["crypto"]], "env": env},
    )
