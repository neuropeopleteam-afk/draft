"""devops.net.nginx_location_mcq — mcq_concept: какой блок location nginx обработает запрос.

Порядок выбора (документация nginx, директива location): точное совпадение `=` — сразу; иначе ищется
самый длинный совпавший префикс; если у него модификатор `^~` — он, регулярные выражения не проверяются;
иначе регулярные выражения (`~` с учётом регистра, `~*` без) проверяются в порядке записи, первое
совпадение побеждает; если ни одно не совпало — самый длинный префикс. Подтип один: ловушка порядка —
регулярное выражение важнее более длинного префикса, `^~` блокирует регулярные, `=` только для точного
URI, `~` чувствителен к регистру. Ключ — исполнение модели выбора в песочнице Python (re) над показанной
конфигурацией.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._yaml_model import program

FAMILY_ID = "devops.net.nginx_location_mcq"

SITES = [("интернет-магазин", "api", "static", "png|jpg|css|js"), ("личный кабинет", "rest", "assets", "css|js|svg"),
         ("портал документов", "v2", "media", "pdf|png|jpg"), ("сайт кинотеатра", "backend", "public", "jpg|webp|css"),
         ("онлайн-школа", "graphql", "static", "mp4|png|css"), ("сервис бронирования", "booking", "files", "pdf|ics|png"),
         ("городской портал", "gateway", "cdn", "svg|png|woff2")]
DOMAINS = ["shop.example.ru", "lk.example.ru", "docs.example.ru", "kino.example.ru", "school.example.ru",
           "book.example.ru", "city.example.ru"]
TRAPS = ["regex_over_prefix", "caret_blocks_regex", "exact_only", "longest_prefix", "case_sensitive"]

MODEL = '''
import re

locs = []
for line in CONF.splitlines():
    s = line.strip()
    if s.startswith("location "):
        head = s.split("{")[0].strip()
        parts = head[len("location "):].split()
        mod, pat = (parts[0], parts[1]) if len(parts) == 2 else ("", parts[0])
        locs.append((mod, pat, head))

def choose(uri):
    for mod, pat, head in locs:
        if mod == "=" and uri == pat:
            return head
    best = None
    for mod, pat, head in locs:
        if mod in ("", "^~") and uri.startswith(pat) and (best is None or len(pat) > len(best[1])):
            best = (mod, pat, head)
    if best and best[0] == "^~":
        return best[2]
    for mod, pat, head in locs:
        if mod in ("~", "~*") and re.search(pat, uri, re.I if mod == "~*" else 0):
            return head
    return best[2]

print(choose(URI))
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, api, static, exts = rng.choice(SITES)
    trap = rng.choice(TRAPS)
    rmod = "~" if trap == "case_sensitive" else rng.choice(["~", "~*"])
    regex = rf"\.({exts})$"
    heads = {"exact": f"location = /{api}", "caret": f"location ^~ /{static}/", "regex": f"location {rmod} {regex}",
             "prefix": f"location /{api}/", "root": "location /"}
    bodies = {"exact": rng.choice(["return 204;", "return 301 /{a}/;".format(a=api)]),
              "caret": rng.choice(["root /var/www;", "alias /srv/static/;"]),
              "regex": rng.choice(["expires 30d;", "add_header Cache-Control public;"]),
              "prefix": rng.choice(["proxy_pass http://app:8080;", "proxy_pass http://upstream_api;"]),
              "root": rng.choice(["try_files $uri /index.html;", "root /var/www/spa;"])}
    order = ["exact", "prefix", "caret", "regex", "root"]
    if rng.random() < 0.5:
        order = ["exact", "regex", "caret", "prefix", "root"]
    ext = rng.choice(exts.split("|"))
    name = rng.choice(["logo", "app", "report", "banner", "main"])
    uri, key_loc = {
        "regex_over_prefix": (f"/{api}/files/{name}.{ext}", "regex"),
        "caret_blocks_regex": (f"/{static}/{name}.{ext}", "caret"),
        "exact_only": (rng.choice([f"/{api}/", f"/{api}"]), None),
        "longest_prefix": (f"/{api}/v{rng.randint(1, 3)}/orders", "prefix"),
        "case_sensitive": (f"/{api}/files/{name.upper()}.{ext.upper()}", "prefix"),
    }[trap]
    if trap == "exact_only":
        key_loc = "exact" if uri == f"/{api}" else "prefix"
    conf_lines = ["server {", f"    listen {rng.choice(['80', '443 ssl', '8080'])};",
                  f"    server_name {rng.choice(DOMAINS)};"]
    for k in order:
        conf_lines.append(f"    {heads[k]} {{ {bodies[k]} }}")
    conf_lines.append("}")
    code = "\n".join(conf_lines)
    others = [k for k in ("prefix", "regex", "caret", "exact", "root") if k != key_loc][:3]
    opts, key = make_options(rng, (heads[key_loc], None), [(heads[k], None) for k in others])
    stem = (f"Сайт «{ctx}» обслуживает nginx с конфигурацией ниже. Какой блок location обработает запрос "
            f"`GET {uri}`?")
    why = {"regex_over_prefix": "у самого длинного префикса нет ^~, поэтому проверяются регулярные выражения, и "
                                "совпавшее регулярное выражение важнее префикса",
           "caret_blocks_regex": "самый длинный префикс помечен ^~ — регулярные выражения не проверяются",
           "exact_only": "= срабатывает только при точном совпадении URI",
           "longest_prefix": "регулярные выражения не совпали, используется самый длинный префикс",
           "case_sensitive": "модификатор ~ учитывает регистр, регулярное выражение не совпало — остаётся "
                             "самый длинный префикс"}[trap]
    expl = f"Выбран `{heads[key_loc]}`: {why}."
    prog = program(MODEL, CONF=code, URI=uri)
    checks = [Check(name="nginx_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=heads[key_loc])]
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Исполняется модель выбора location над показанной конфигурацией",
                         params={"trap": trap, "uri": uri})
