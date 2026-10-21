"""security.web.t21_cookie_attrs_output — predict_output (t21, порог Middle): разбор Set-Cookie, регистр
имён атрибутов, наличие флагов и зависимость SameSite=None от Secure.

Код делит заголовки по «;», убирает пробелы на краях, приводит имена и значения атрибутов к нижнему регистру
и собирает словарь. Затем перечисляет отсутствующие secure / httponly / samesite в заданном порядке; отдельно
добавляет none-without-secure, если SameSite=None стоит без Secure. Пустое значение флага Secure не означает
его отсутствия: важен ключ в словаре. Ключ считает модель по выбранным свойствам cookie, без разбора заголовка;
проверка исполняет показанный код в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.web.t21_cookie_attrs_output"
CTX = ["портал единого входа", "кабинет клиента", "панель оператора", "шлюз партнёров", "сервис заказов",
       "внутренний биллинг", "платформа поддержки", "каталог документов"]
COOKIE_NAMES = ["sid", "session", "auth", "prefs", "csrf", "device", "portal", "refresh", "visit", "login"]
CASES = {"secure": ["Secure", "SECURE", "secure", "sEcUrE"],
         "httponly": ["HttpOnly", "HTTPONLY", "httponly", "hTtPoNlY"],
         "samesite": ["SameSite", "SAMESITE", "samesite", "sameSITE"]}
NAMES = [("headers", "header", "parts", "attrs", "missing"),
         ("cookies", "line", "items", "flags", "issues"),
         ("values", "value", "chunks", "attrs", "absent")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    hv, iv, pv, av, mv = rng.choice(NAMES)
    patterns = [(True, True, rng.choice(["lax", "strict", "none"])),
                (False, rng.choice([True, False]), "none"),
                (rng.choice([True, False]), rng.choice([True, False]), rng.choice([None, None, "lax", "strict"]))]
    rng.shuffle(patterns)
    rows = []
    headers = []
    for name, (secure, httponly, same) in zip(rng.sample(COOKIE_NAMES, 3), patterns):
        attrs = []
        if secure:
            attrs.append(rng.choice(CASES["secure"]))
        if httponly:
            attrs.append(rng.choice(CASES["httponly"]))
        if same is not None:
            val = rng.choice([same, same.capitalize(), same.upper()])
            attrs.append(rng.choice(CASES["samesite"]) + "=" + val)
        if rng.random() < 0.6:
            attrs.append(rng.choice(["Path=/", "path=/api", "Max-Age=600"]))
        rng.shuffle(attrs)
        token = "".join(rng.choice("abcdef0123456789") for _ in range(rng.randint(2, 4)))
        header = name + "=" + token
        for attr in attrs:
            header += rng.choice(["; ", ";  ", " ; "]) + attr
        rows.append((name, secure, httponly, same))
        headers.append(header)
    header_lines = [f"{hv} = ["] + [f"    {h!r}," for h in headers[:-1]] + [f"    {headers[-1]!r}]"]
    code = "\n".join(header_lines + [
        f"for {iv} in {hv}:",
        f'    {pv} = [p.strip() for p in {iv}.split(";")]',
        f"    {av} = {{}}",
        f"    for item in {pv}[1:]:",
        '        k, _, v = item.partition("=")',
        f"        {av}[k.lower()] = v.lower()",
        f'    {mv} = [k for k in ("secure", "httponly", "samesite") if k not in {av}]',
        f'    if {av}.get("samesite") == "none" and "secure" not in {av}:',
        f'        {mv}.append("none-without-secure")',
        f'    print({pv}[0].split("=", 1)[0], ",".join({mv}) or "ok")',
    ])
    lines = []
    trace = []
    for name, secure, httponly, same in rows:
        issues = []
        if not secure:
            issues.append("secure")
        if not httponly:
            issues.append("httponly")
        if same is None:
            issues.append("samesite")
        if same == "none" and not secure:
            issues.append("none-without-secure")
        result = ",".join(issues) or "ok"
        lines.append(f"{name} {result}")
        have = (f"Secure {'есть' if secure else 'нет'}, HttpOnly {'есть' if httponly else 'нет'}, "
                f"SameSite={same if same is not None else 'отсутствует'}")
        trace.append(f"{name}: {have} → «{result}»")
    out = "\n".join(lines)
    explanation = ("strip() удаляет пробелы вокруг атрибута, lower() выравнивает регистр имён и значений. "
                   "Флаг с пустым значением всё равно есть в словаре. Пропуски идут в порядке secure, httponly, "
                   "samesite; SameSite=None без Secure добавляет отдельное нарушение. " + "; ".join(trace) + ".")
    stem = (f"Аудит cookie ({ctx}): программа разбирает заголовки Set-Cookie и выводит замечания к атрибутам "
            "каждой cookie.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=explanation, context=ctx,
                          params={"headers": headers}, language="python")
