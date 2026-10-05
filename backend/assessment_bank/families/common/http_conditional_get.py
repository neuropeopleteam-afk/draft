"""common.http.conditional_get — predict_output: ETag, If-None-Match, If-Match в обработчике."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.http.conditional_get"

RESOURCES = [
    ("/profiles/{n}", '{{"name": "{v}"}}', ["Анна", "Аня", "А. Петрова"], "профиль"),
    ("/documents/{n}", '{{"title": "{v}"}}', ["Договор", "Договор v2", "Акт"], "документы"),
    ("/settings/{n}", '{{"theme": "{v}"}}', ["light", "dark", "auto"], "настройки"),
    ("/carts/{n}", '{{"items": {v}}}', ["1", "2", "3"], "корзина"),
]


def _handler(has_delete: bool) -> list[str]:
    lines = [
        "def handle(method, path, headers, body=None):",
        "    if path not in store:",
        "        return 404",
        "    tag = etag(store[path])",
        '    if method == "GET":',
        '        if headers.get("If-None-Match") == tag:',
        "            return 304",
        "        return 200",
        '    if method == "PUT":',
        '        if "If-Match" in headers and headers["If-Match"] != tag:',
        "            return 412",
        "        store[path] = body",
        "        return 204",
    ]
    if has_delete:
        lines += ['    if method == "DELETE":',
                  '        if "If-Match" in headers and headers["If-Match"] != tag:',
                  "            return 412",
                  "        del store[path]",
                  "        return 204"]
    lines.append("    return 405")
    return lines


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    tmpl, body_tmpl, values, ctx = rng.choice(RESOURCES)
    path = tmpl.format(n=rng.randint(2, 99))
    other = tmpl.format(n=rng.randint(100, 199))
    has_delete = rng.random() < 0.5
    bodies = [body_tmpl.format(v=v) for v in values]
    store = {path: bodies[0]}
    tags = {"v1": bodies[0]}
    lines = ["import hashlib", "", f"store = {{{path!r}: {bodies[0]!r}}}", "", "",
             "def etag(body):", "    return '\"' + hashlib.sha256(body.encode()).hexdigest()[:8] + '\"'",
             "", ""] + _handler(has_delete) + ["", "", f'v1 = etag(store["{path}"])', "codes = []"]
    out: list[int] = []
    n_req = rng.randint(5, 7)
    v2_defined = False
    kinds: list[str] = []
    for i in range(n_req):
        known = [t for t in tags if t != "v2" or v2_defined]
        kind = rng.choices(["get_plain", "get_inm", "put_im", "put_plain", "delete", "post", "missing"],
                           weights=[1, 3, 3, 1, 2 if has_delete else 1, 1, 1])[0]
        if i == 0:
            kind = "get_inm"
        elif len(kinds) >= 2 and kinds[-1] == kinds[-2] == kind:
            kind = "get_inm" if kind != "get_inm" else "put_im"
        kinds.append(kind)
        tag = rng.choice(known)
        cur = store.get(path)
        if kind == "get_plain":
            lines.append(f'codes.append(handle("GET", "{path}", {{}}))')
            out.append(200 if cur is not None else 404)
        elif kind == "get_inm":
            lines.append(f'codes.append(handle("GET", "{path}", {{"If-None-Match": {tag}}}))')
            out.append(404 if cur is None else (304 if tags[tag] == cur else 200))
        elif kind in ("put_im", "put_plain"):
            new = rng.choice(bodies)
            hdr = f'{{"If-Match": {tag}}}' if kind == "put_im" else "{}"
            lines.append(f'codes.append(handle("PUT", "{path}", {hdr}, {new!r}))')
            if cur is None:
                out.append(404)
            elif kind == "put_im" and tags[tag] != cur:
                out.append(412)
            else:
                store[path] = new
                out.append(204)
                if not v2_defined and rng.random() < 0.7:
                    lines.append(f'v2 = etag(store["{path}"])')
                    tags["v2"] = new
                    v2_defined = True
        elif kind == "delete":
            lines.append(f'codes.append(handle("DELETE", "{path}", {{"If-Match": {tag}}}))')
            if cur is None:
                out.append(404)
            elif not has_delete:
                out.append(405)
            elif tags[tag] != cur:
                out.append(412)
            else:
                del store[path]
                out.append(204)
        elif kind == "post":
            lines.append(f'codes.append(handle("POST", "{path}", {{}}))')
            out.append(405 if cur is not None else 404)
        else:
            lines.append(f'codes.append(handle("GET", "{other}", {{}}))')
            out.append(404)
    lines.append("print(*codes)")
    code = "\n".join(lines)
    expected = " ".join(map(str, out))
    stem = ("Упрощённый обработчик HTTP реализует условные запросы: сильный ETag, If-None-Match "
            "для GET и If-Match для изменения ресурса. Что напечатает программа? Запишите коды "
            "через пробел.")
    ak = AnswerKey(kind="output", value=expected,
                   explanation="ETag зависит только от содержимого: после PUT с тем же телом тег не "
                               "меняется; If-None-Match с текущим тегом даёт 304, If-Match с "
                               "устаревшим — 412; удалённый ресурс — 404.")
    checks = [Check(name="stdout", runner="python", program=code, expect="stdout_equals",
                    expected_stdout=expected)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         params={"has_delete": has_delete, "n_requests": n_req})
