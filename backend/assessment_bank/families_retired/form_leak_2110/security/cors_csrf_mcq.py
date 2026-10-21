"""CORS не заменяет серверную защиту изменяющих cookie-запросов (версия 3: цели вместо контракта в условии, длины вариантов выровнены)."""
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
    # Версия 2 (калибровка 05.10: решалась малыми моделями — условие перечисляло контракт
    # «CSRF-токен и проверка Origin», и верный вариант совпадал с ним дословно). Теперь условие
    # задаёт только цели, а дистракторы отличаются от верного одним атрибутом и формулируют
    # типичное заблуждение («CORS не пропустит чужой запрос», «токен только для JSON»).
    P = {"good": {"allow": [origin], "credentials": True, "csrf": "all", "origin_check": True},
         "no_csrf": {"allow": [origin], "credentials": True, "csrf": "none", "origin_check": True},
         "json_only": {"allow": [origin], "credentials": True, "csrf": "json", "origin_check": True},
         "star": {"allow": ["*"], "credentials": True, "csrf": "all", "origin_check": True},
         "reflect": {"allow": ["reflect_any"], "credentials": True, "csrf": "all", "origin_check": True}}
    # Версия 3 (08.10): длины формулировок выровнены (верный вариант раньше был на 4–9 знаков короче всех).
    T = {"good": "CORS: только UI-origin; credentials: да; CSRF-токен: для всех изменяющих запросов API; Origin: проверять.",
         "no_csrf": "CORS: только UI-origin; credentials: да; CSRF-токен: не нужен, CORS отсечёт чужой origin; Origin: проверять.",
         "json_only": "CORS: только UI-origin; credentials: да; CSRF-токен: только для запросов с JSON-телом; Origin: проверять.",
         "star": "CORS: «*» для всех origins; credentials: да; CSRF-токен: для всех изменяющих запросов; Origin: проверять.",
         "reflect": "CORS: отражать любой Origin; credentials: да; CSRF-токен: для всех изменяющих запросов; Origin: проверять."}
    chosen = ["no_csrf", "json_only", rng.choice(["star", "reflect"])]
    texts = [T["good"]] + [T[d] for d in chosen]
    policies = [P["good"]] + [P[d] for d in chosen]
    opts, key = make_options(rng, (texts[0], None), [(t, None) for t in texts[1:]])
    by_text = dict(zip(texts, policies))
    candidates = {o.id: by_text[o.text] for o in opts}
    oracle = f"""candidates = {candidates!r}
trusted = {origin!r}
accepted = []
for oid, p in candidates.items():
    if p['allow'] == [trusted] and p['credentials'] and p['csrf'] == 'all' and p['origin_check']:
        accepted.append(oid)
assert len(accepted) == 1
print(accepted[0])"""
    method = rng.choice(["POST", "PUT", "PATCH", "DELETE"])
    lead = rng.choice([
        f"{ctx.capitalize()}: вход по cookie-сессии, API `{method} /api/{resource}` меняет данные; "
        f"интерфейс размещён на `{origin}` и читает ответы API с cookie (credentials).",
        f"{ctx.capitalize()}. Фронтенд с адреса `{origin}` вызывает `{method} /api/{resource}` с "
        f"credentials; пользователь аутентифицирован сессионной cookie.",
        f"В проекте «{ctx}» запросы `{method} /api/{resource}` изменяют записи пользователя; "
        f"сессия хранится в cookie, единственный легитимный клиент — SPA на `{origin}`."])
    channel = rng.choice([
        "Изменяющий запрос может прийти и обычной HTML-формой, и через fetch с JSON-телом.",
        "Сервер принимает и тело формы (application/x-www-form-urlencoded), и JSON.",
        "Старые страницы отправляют формы, новые — fetch с JSON; сервер принимает оба вида тела."])
    goal = rng.choice([
        "Чужой сайт не должен ни выполнить изменение от имени вошедшего пользователя, ни прочитать ответы API.",
        "Требование безопасности: сторонняя страница не может ни менять данные в чужой сессии, ни читать ответы.",
        "Нужно исключить и подделку изменяющих запросов со сторонних страниц, и чтение ответов API ими."])
    stem = (f"{lead} {channel} {goal} Какая конфигурация этого добивается, не расширяя круг "
            f"доверенных origins?")
    return build_variant(
        FAMILY_ID, seed, stem=stem, options=opts, context=ctx, verification="execution",
        answer_key=AnswerKey(kind="option", value=key, explanation="CORS управляет доступом "
                            "браузера к ответу и не заменяет проверку CSRF: форма отправляется "
                            "без предварительного запроса, и cookie уходит. Поэтому токен нужен для "
                            "всех изменяющих запросов, включая формы (не только JSON). Для credentials "
                            "нужен явный доверенный origin: «*» с credentials браузер не примет, а "
                            "отражение любого Origin даёт любому сайту читать ответы."),
        checks=[Check(name="policy_contract", runner="python", program=oracle,
                      expect="stdout_equals", expected_stdout=key)],
        params={"source_urls": [SOURCES["csrf"]], "contract_not_browser_emulation": True,
                "distractors": chosen},
    )
