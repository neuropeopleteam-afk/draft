"""Выбор библиотечного режима, без реализации шифрования или рабочих нагрузок."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey
from ._support import CONTEXTS, SOURCES

FAMILY_ID = "security.crypto.aead_mcq"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    count, replicas = rng.choice([100, 500, 2000, 10000]), rng.choice([2, 3, 4, 6])
    asset = rng.choice(["содержимое черновиков", "тексты заявок", "вложения отчётов", "заметки редакторов"])
    correct = ("Библиотечный AES-GCM; nonce уникален для ключа; случайность от CSPRNG; "
               "tenant_id в AAD; тег проверяется до выдачи.")
    distractors = [
        ("Библиотечный AES-CBC; IV уникален для ключа; случайность от CSPRNG; "
         "tenant_id в записи; тег отсутствует при выдаче."),
        ("Библиотечный AES-GCM; nonce постоянен для ключа; случайность от CSPRNG; "
         "tenant_id в AAD; тег проверяется до выдачи."),
        ("Библиотечный AES-CTR; nonce уникален для ключа; случайность от CSPRNG; "
         "tenant_id в записи; тег отсутствует при выдаче."),
    ]
    opts, key = make_options(rng, (correct, None), [(d, None) for d in distractors])
    stem = (f"{ctx.capitalize()}: {replicas} экземпляра обрабатывают {count} учебных записей "
            f"в сутки. Нужно защитить {asset}: конфиденциальность, целостность и привязку "
            "к tenant_id, чтобы обнаруживать ошибочную подмену метаданных. Ключ приходит "
            "из защищённого хранилища. Выберите подход из проверенной библиотеки; "
            "уникальность nonce должна обеспечиваться для всех экземпляров с одним ключом, "
            "лимит использования ключа и ротация обязательны. Самодельный шифр не требуется.")
    return build_variant(
        FAMILY_ID, seed, stem=stem, options=opts, context=ctx, verification="reference_table",
        answer_key=AnswerKey(kind="option", value=key, explanation="Нужен аутентифицированный "
                            "режим: GCM даёт шифрование и тег, AAD привязывает метаданные. "
                            "Повтор nonce для одного ключа недопустим. CBC/CTR без отдельной "
                            "аутентификации не выполняют контракт; CSPRNG не заменяет контроль "
                            "коллизий, межэкземплярной уникальности и лимитов ключа."),
        params={"source_urls": [SOURCES["crypto"]],
                "execution_limit": "stdlib Python не содержит AES-GCM; Node vm не предоставляет require",
                "no_custom_crypto": True},
    )
