"""Случайное значение при импорте не означает новое значение для каждой операции."""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from ._support import CONTEXTS, SOURCES, bug_variant

FAMILY_ID = "security.crypto.nonce_lifecycle_bug"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    key_version = rng.choice(["demo-key-v1", "demo-key-v2", "demo-key-v3"])
    object_a, object_b = rng.sample(range(10, 9000), 2)
    code = f"""import secrets
DEFAULT_NONCE = secrets.token_bytes(12)
KEY_VERSION = {key_version!r}

def prepare_metadata(object_id, entropy=secrets.token_bytes):
    nonce = DEFAULT_NONCE
    if len(nonce) != 12:
        raise ValueError('nonce size')
    return {{'object_id': object_id, 'key_version': KEY_VERSION, 'nonce': nonce}}"""
    fixed = code.replace("nonce = DEFAULT_NONCE", "nonce = entropy(12)")
    test = f"""calls = []
def entropy(n):
    calls.append(n)
    return bytes([len(calls)]) * n
first = prepare_metadata({object_a}, entropy)
second = prepare_metadata({object_b}, entropy)
assert calls == [12, 12]
assert first['nonce'] != second['nonce']
assert first['key_version'] == second['key_version'] == KEY_VERSION
assert first['object_id'] == {object_a} and second['object_id'] == {object_b}
assert len(prepare_metadata({object_a})['nonce']) == 12"""
    stem = (f"{ctx.capitalize()}: адаптер готовит метаданные двух разных сообщений "
            f"({object_a} и {object_b}) для библиотечного AES-GCM с ключом `{key_version}`. "
            "Сами сообщения и шифрование здесь отсутствуют. По контракту каждое сообщение "
            "получает отдельный 12-байтовый nonce от поставщика entropy; генератор по умолчанию "
            "криптографический. Для этого задания рассматривается один процесс с ограниченным "
            "числом операций. Укажите строку, которая повторно использует однажды созданный nonce.")
    return bug_variant(
        FAMILY_ID, seed, stem=stem, buggy=code, fixed=fixed, test=test, context=ctx,
        defect="nonce_reuse_at_import",
        params={"why": "Вызывать entropy(12) для каждой операции. Значение, созданное при "
                "импорте, общее для всех вызовов. CSPRNG — необходимая, но не достаточная "
                "мера: в рабочей системе нужны общая область уникальности по ключу, лимиты "
                "сообщений, оценка коллизий и ротация. Тест проверяет жизненный цикл, не стойкость.",
                "source_urls": [SOURCES["crypto"]], "tests_use_injected_entropy": True},
    )
