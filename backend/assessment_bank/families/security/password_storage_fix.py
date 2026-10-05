"""Медленный KDF, уникальная соль и compare_digest; тестовые двойники отделены от KDF."""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from assessment_bank.schema import Check
from ._support import CONTEXTS, SOURCES, fix_variant

FAMILY_ID = "security.auth.password_storage_fix"

HEAD = """import hashlib
import hmac
import secrets

def _derive(password, salt):
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=16384,
                          r=8, p=5, dklen=32, maxmem=67108864)

"""
GOOD = """def store(password, entropy=secrets.token_bytes):
    salt = entropy(16)
    digest = _derive(password, salt)
    return salt, digest

def verify(password, record):
    salt, digest = record
    return hmac.compare_digest(_derive(password, salt), digest)"""


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    uid, batch = rng.randint(10, 900), rng.randint(2, 20)
    buggy_body = GOOD.replace("_derive(password, salt)", "hashlib.sha256(password.encode()).digest()")
    correct = HEAD + GOOD
    distractors = [
        HEAD + buggy_body,
        HEAD + GOOD.replace("salt = entropy(16)", "salt = bytes(16)"),
        HEAD + GOOD.replace("hmac.compare_digest(_derive(password, salt), digest)",
                            "(_derive(password, salt) == digest)"),
    ]
    test = """global _derive
real_derive = _derive
_derive = lambda password, salt: hashlib.sha256(salt + password.encode()).digest()
calls = []
def entropy(n):
    calls.append(n)
    return bytes([len(calls)]) * n
first = store('Учебный пароль', entropy)
second = store('Учебный пароль', entropy)
assert calls == [16, 16]
assert first[0] != second[0] and first[1] != second[1]
assert first[1] == _derive('Учебный пароль', first[0])
comparisons = []
real_compare = hmac.compare_digest
def compare(a, b):
    comparisons.append((type(a), type(b)))
    return real_compare(a, b)
hmac.compare_digest = compare
try:
    assert verify('Учебный пароль', first) is True
    assert verify('Другой пароль', first) is False
    assert comparisons == [(bytes, bytes), (bytes, bytes)]
finally:
    hmac.compare_digest = real_compare
    _derive = real_derive"""
    # Этот вектор вычислен один раз реальной stdlib scrypt с заданными параметрами.
    # Никакие параметры KDF не понижаются для тестирования.
    vector_program = HEAD + "\nassert _derive('demo-safe-kdf', bytes([1]) * 16).hex() == '7d8ea5dc9e1697a34d3eae7ae243027e868495f84adf4e4a1c76668903f8bca8'\nprint('RESULT: PASS')"
    stem = (f"{ctx.capitalize()}: миграция {batch} учебных учётных записей, пример user_id={uid}. "
            "Argon2id недоступен в заданном окружении; утверждён scrypt с N=16384, r=8, p=5, "
            "солью 16 байт и результатом 32 байта. `record` хранит соль и хеш, параметры "
            "профиля фиксированы отдельно; входной размер ограничен выше по стеку. "
            "Выберите исправление: новая случайная соль на каждую запись, медленный KDF и "
            "сравнение через API постоянного времени. Все фрагменты выполняют одну и ту же задачу.")
    return fix_variant(
        FAMILY_ID, seed, rng, stem=stem, buggy=HEAD + buggy_body, correct=correct,
        distractors=distractors, test=test, context=ctx, defect="fast_password_hash",
        why="Быстрый SHA256 не подходит для хранения паролей. Соль генерируется отдельно для "
            "каждой записи, scrypt использует утверждённый профиль, сравнение — compare_digest. "
            "В рабочем формате сохраняются также версия алгоритма и параметры для миграции.",
        extra_checks=[Check(name="real_scrypt_vector", runner="python", program=vector_program,
                            expect="pass", embeds_display_code=False)],
        params={"source_urls": [SOURCES["password"]], "functional_test_uses_kdf_double": True,
                "kdf_vector_is_real": True, "timing_benchmark": False},
    )
