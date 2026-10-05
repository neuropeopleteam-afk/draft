"""Настройки cookie оцениваются по явно заданному контракту."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check
from ._support import CONTEXTS, SOURCES

FAMILY_ID = "security.web.cookie_policy_mcq"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, age = rng.choice(CONTEXTS), rng.choice([600, 900, 1800, 3600])
    sub = rng.choice(["editor", "archive", "catalog", "desk"])
    configurations = [
        {"secure": True, "http_only": True, "same_site": "Lax", "domain": None, "path": "/", "age": age},
        {"secure": False, "http_only": True, "same_site": "Lax", "domain": None, "path": "/", "age": age},
        {"secure": True, "http_only": False, "same_site": "Lax", "domain": None, "path": "/", "age": age},
        {"secure": True, "http_only": True, "same_site": "Lax", "domain": ".example.invalid", "path": "/", "age": age},
    ]
    def text(c):
        domain = "не задан" if c["domain"] is None else ".example.invalid"
        return (f"Secure={str(c['secure']).lower()}; HttpOnly={str(c['http_only']).lower()}; "
                f"SameSite=Lax; Domain={domain}; Path=/; Max-Age={age}.")
    opts, key = make_options(rng, (text(configurations[0]), None),
                             [(text(c), None) for c in configurations[1:]])
    by_text = {text(c): c for c in configurations}
    policies = {o.id: by_text[o.text] for o in opts}
    oracle = f"""policies = {policies!r}
valid = []
for oid, p in policies.items():
    if p['secure'] and p['http_only'] and p['same_site'] == 'Lax' and p['domain'] is None and p['path'] == '/' and p['age'] == {age}:
        valid.append(oid)
assert len(valid) == 1
print(valid[0])"""
    stem = (f"{ctx.capitalize()}: браузерная сессия только для `{sub}.example.invalid` "
            f"по HTTPS, срок {age} секунд. Соседние поддомены не должны получать cookie; "
            "JavaScript не читает сессионное значение. По утверждённому контракту используются "
            "SameSite=Lax и Path=/, а изменяющие запросы отдельно защищены CSRF-токеном. "
            "Какая конфигурация выполняет все требования?")
    return build_variant(
        FAMILY_ID, seed, stem=stem, options=opts, context=ctx, verification="execution",
        answer_key=AnswerKey(kind="option", value=key, explanation="Secure ограничивает передачу "
            "HTTPS, HttpOnly запрещает чтение через JavaScript, отсутствие Domain делает cookie "
            "host-only. SameSite здесь дополнительная защита, а не замена CSRF-токену."),
        checks=[Check(name="policy_contract", runner="python", program=oracle,
                      expect="stdout_equals", expected_stdout=key)],
        params={"source_urls": [SOURCES["csrf"]], "policies": policies},
    )
