"""Опубликованная канарейка: минимизация данных в журнале."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check
from ._support import CONTEXTS

FAMILY_ID = "security.logging.canary_redaction"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, uid = rng.choice(CONTEXTS), rng.randint(10, 999)
    allowed = rng.choice([("event", "user_id"), ("event", "request_id"), ("event", "status")])
    event = rng.choice(["login_ok", "profile_saved", "document_read", "logout_ok"])
    record = {"event": event, "user_id": uid, "request_id": f"req-{rng.randint(10, 9999)}",
              "status": rng.choice([200, 201, 204]), "token": "DEMO_TOKEN_ONLY",
              "password": "DEMO_PASSWORD_ONLY"}
    order = list(record)
    rng.shuffle(order)
    record = {k: record[k] for k in order}
    code = f"""ALLOWED = {allowed!r}

def safe_log(record):
    return ' '.join(str(record[k]) for k in ALLOWED)

record = {record!r}
print(safe_log(record))"""
    out = " ".join(str(record[k]) for k in allowed)
    stem = (f"{ctx.capitalize()}: в журнал допускается только список `ALLOWED` в указанном "
            "порядке. Все значения учебные. Какую строку выведет код? Порядок ключей словаря "
            "не задаёт порядок вывода, токен и пароль в журнал попасть не должны.")
    return build_variant(
        FAMILY_ID, seed, stem=stem, code=code, context=ctx, verification="execution",
        answer_key=AnswerKey(kind="output", value=out,
                            explanation="Вывод идёт по ALLOWED, остальные поля не читаются."),
        checks=[Check(name="stdout", runner="python", program=code,
                      expect="stdout_equals", expected_stdout=out)],
        params={"published_canary": True, "allowed": list(allowed)},
    )
