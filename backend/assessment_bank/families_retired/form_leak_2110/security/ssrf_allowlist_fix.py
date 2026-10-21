"""security.web.ssrf_allowlist_fix — choose_fix: список разрешённых хостов для исходящего запроса по URL пользователя.

Порог Middle/Senior. Показанная проверка ищет имя разрешённого хоста подстрокой в netloc — обходится через
userinfo (`https://<разрешённый>@<чужой>/`). Варианты замены (состав фиксирован, один подтип):
* верный — схема https и точное совпадение `hostname` (без userinfo и порта, в нижнем регистре);
* `netloc.split(":")[0]` — обходится userinfo с двоеточием (`https://<разрешённый>:x@<чужой>/`);
* `hostname.endswith(h)` — обходится зарегистрированным доменом с тем же окончанием (`https://evil<разрешённый>/`);
* точный `hostname` и проверка порта, но без проверки схемы — пропускает `http://`.
Проверка исполнением: законные адреса (в т. ч. имя хоста в верхнем регистре) разрешены, атакующие — запрещены.
"""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from assessment_bank.families.common._plus_utils import fix_options_variant

FAMILY_ID = "security.web.ssrf_allowlist_fix"

CONTEXTS = [("предпросмотр ссылок в чате", "fetch_preview"), ("импорт аватара по URL", "import_avatar"),
            ("загрузка прайс-листа партнёра", "load_pricelist"), ("проверка адреса вебхука", "check_webhook"),
            ("импорт документа по ссылке", "import_document"), ("получение карточки товара поставщика", "pull_card")]
HOSTS = ["partner-cdn.ru", "files.supplier.ru", "api.logistics.ru", "media-hub.ru", "docs.vendor.ru",
         "img.marketplace.ru", "feeds.partner.ru", "static-store.ru"]
FUNCS = ["is_allowed", "url_allowed", "may_fetch", "check_target"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, caller = rng.choice(CONTEXTS)
    hosts = rng.sample(HOSTS, rng.randint(2, 3))
    fn = rng.choice(FUNCS)
    var = rng.choice(["parts", "u", "parsed"])
    const = rng.choice(["ALLOWED_HOSTS", "TRUSTED_HOSTS", "ALLOWLIST"])
    host_lit = "{" + ", ".join(repr(h) for h in sorted(hosts)) + "}"
    prelude = f"from urllib.parse import urlsplit\n\n{const} = {host_lit}"

    def func(ret: str) -> str:
        return f"def {fn}(url):\n    {var} = urlsplit(url)\n    return {ret}\n"

    buggy_ret = f'url.startswith("https://") and any(h in {var}.netloc for h in {const})'
    correct = func(f'{var}.scheme == "https" and {var}.hostname in {const}')
    distractors = [
        func(f'url.startswith("https://") and {var}.netloc.split(":")[0] in {const}'),
        func(f'{var}.scheme == "https" and any({var}.hostname.endswith(h) for h in {const})'),
        func(f'{var}.hostname in {const} and {var}.port in (None, 443)'),
    ]
    buggy = prelude + "\n\n\n" + func(buggy_ret)
    h0, h1 = hosts[0], hosts[1]
    path = rng.choice(["/v1/items?id=5", "/img/logo.png", "/export.csv", "/hook", "/files/42"])
    good = [f"https://{h0}{path}", f"https://{h1.upper()}/", f"https://{h1}{path}"]
    bad = [f"https://{h0}@evil.example{path}", f"https://{h0}:x@evil.example/", f"https://evil{h1}/",
           f"http://{h0}{path}", f"https://{h0}.evil.example/"]
    rng.shuffle(bad)
    test = (f"for u in {good!r}:\n    assert {fn}(u), u\n"
            f"for u in {bad!r}:\n    assert not {fn}(u), u\n")
    stem = (f"Безопасность ({ctx}). Сервер сам скачивает файл по адресу, который прислал пользователь, поэтому "
            f"`{fn}` должна пропускать только HTTPS-запросы к хостам из `{const}`. На ревью нашли, что проверку "
            f"можно обойти и заставить сервер обратиться к чужому хосту. Какая замена функции закрывает обход "
            f"и не ломает законные адреса?")
    why = ("Решение о доверии принимается по тому же имени хоста, к которому пойдёт клиент: `urlsplit(url).hostname` "
           "уже без userinfo (`user:pass@`) и порта и в нижнем регистре; его сравнивают точно со списком, схему — "
           "отдельно. Подстрока и `split(\":\")` обходятся адресом `https://<разрешённый>:x@evil.example/`, "
           "`endswith` — доменом `evil<разрешённый>`, без проверки схемы проходит открытый `http://`.")
    return fix_options_variant(
        FAMILY_ID, seed, rng, stem=stem, buggy=buggy, correct=correct, distractors=distractors, test=test,
        prelude=prelude, context=ctx, defect="ssrf_host_substring", why=why,
        params={"hosts": hosts, "caller": caller,
                "source_urls": ["https://cheatsheetseries.owasp.org/cheatsheets/"
                                "Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html"]})
