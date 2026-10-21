"""Настройки cookie оцениваются по явно заданному контракту."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check
from ._support import CONTEXTS, SOURCES

FAMILY_ID = "security.web.cookie_policy_mcq"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, age = rng.choice(CONTEXTS), rng.choice([300, 600, 900, 1200, 1800, 2400, 3600, 7200])
    sub = rng.choice(["editor", "archive", "catalog", "desk", "billing", "portal", "reports", "support"])
    factor = rng.choice([12, 24, 48])             # «срок длиннее нужного» — во столько раз
    base = {"secure": True, "http_only": True, "same_site": "Lax", "domain": None, "path": "/", "age": age}

    def with_deviations(*devs):
        c = dict(base)
        for d in devs:
            if d in ("secure", "http_only"):
                c[d] = False
            elif d == "domain":
                c["domain"] = ".example.invalid"
            elif d == "age_missing":
                c["age"] = None          # сессионная cookie: срока жизни нет
            else:
                c["age"] = age * factor
        return c

    # Версия 3 (08.10): состав дистракторов фиксирован — один одиночный дефект (Secure=false) и два двойных с общим
    # признаком (Domain задан + Max-Age в 12–48 раз больше / Max-Age нет). Верный вариант не «центр» (две пары
    # близких вариантов: верный + первый дистрактор, второй + третий) и не выделяется длиной: Secure=false длиннее
    # на 1 знак, Domain задан — на 8, отсутствие Max-Age — короче на 14. Версия 2 выбирала признаки случайно, и
    # панель ext4 показала неизоморфность (σ 1,12: при одиночном Domain p 0,24, при остальных ≈ 0,6).
    configurations = [base, with_deviations("secure"), with_deviations("domain", "age_long"),
                      with_deviations("domain", "age_missing")]

    def text(c):
        domain = "не задан" if c["domain"] is None else ".example.invalid"
        max_age = "" if c["age"] is None else f"; Max-Age={c['age']}"
        return (f"Secure={str(c['secure']).lower()}; HttpOnly={str(c['http_only']).lower()}; "
                f"SameSite=Lax; Domain={domain}; Path=/{max_age}.")
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
            "host-only, Max-Age задаёт требуемый срок. SameSite здесь дополнительная защита, а не замена CSRF-токену."),
        checks=[Check(name="policy_contract", runner="python", program=oracle,
                      expect="stdout_equals", expected_stdout=key)],
        params={"source_urls": [SOURCES["csrf"]], "policies": policies},
    )
