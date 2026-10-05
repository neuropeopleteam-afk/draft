"""CORS не заменяет серверную защиту изменяющих cookie-запросов."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check
from ._support import CONTEXTS, SOURCES

FAMILY_ID = "security.web.cors_csrf_mcq"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    sub = rng.choice(["editor", "archive", "catalog", "support"])
    origin = f"https://{sub}.example.invalid"
    resource = rng.choice(["documents", "requests", "drafts", "bookings"])
    policies = [
        {"allow": [origin], "credentials": True, "csrf": True, "origin_check": True},
        {"allow": [origin], "credentials": True, "csrf": False, "origin_check": True},
        {"allow": ["*"], "credentials": True, "csrf": True, "origin_check": True},
        {"allow": ["reflect_any"], "credentials": True, "csrf": True, "origin_check": True},
    ]
    texts = [
        "CORS: один доверенный origin; credentials: да; CSRF: проверять; Origin: проверять.",
        "CORS: один доверенный origin; credentials: да; CSRF: пропускать; Origin: проверять.",
        "CORS: общий шаблон «звёздочка»; credentials: да; CSRF: проверять; Origin: проверять.",
        "CORS: любой отражённый origin; credentials: да; CSRF: проверять; Origin: проверять.",
    ]
    opts, key = make_options(rng, (texts[0], None), [(t, None) for t in texts[1:]])
    by_text = dict(zip(texts, policies))
    candidates = {o.id: by_text[o.text] for o in opts}
    oracle = f"""candidates = {candidates!r}
trusted = {origin!r}
accepted = []
for oid, p in candidates.items():
    if p['allow'] == [trusted] and p['credentials'] and p['csrf'] and p['origin_check']:
        accepted.append(oid)
assert len(accepted) == 1
print(accepted[0])"""
    stem = (f"{ctx.capitalize()}: cookie-сессия обслуживает `POST /api/{resource}`. "
            f"Разрешён единственный UI-origin `{origin}`, cookie-флаги уже настроены. "
            "Тело может приходить обычной HTML-формой: одной CORS-политики недостаточно. "
            "Утверждённый контракт требует сессионный CSRF-токен и проверку Origin "
            "для всех изменяющих запросов; отсутствующий или неверный токен даёт отказ. "
            "Какая политика выполняет контракт, не расширяя список доверенных origins?")
    return build_variant(
        FAMILY_ID, seed, stem=stem, options=opts, context=ctx, verification="execution",
        answer_key=AnswerKey(kind="option", value=key, explanation="CORS управляет доступом "
                            "браузера к ответу и не заменяет авторизацию или проверку CSRF. "
                            "Для credentials нужен явный доверенный origin, не * и не отражение любого Origin."),
        checks=[Check(name="policy_contract", runner="python", program=oracle,
                      expect="stdout_equals", expected_stdout=key)],
        params={"source_urls": [SOURCES["csrf"]], "contract_not_browser_emulation": True},
    )
